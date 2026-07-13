"""Read-only GitHub queries via the ``gh`` CLI.

Pure-function shape on top of an injectable ``run_command`` callback so
tests don't need to mock ``asyncio.subprocess``. The tool exposes a
restricted set of operations:

* ``pr``    — view a pull request (title, state, checks, reviews)
* ``issue`` — view an issue (title, state, body, comments)
* ``run``   — list recent workflow runs for a repo
* ``repo``  — show repo metadata
* ``api``   — generic ``gh api`` GET (read-only fallback for things not
              covered by the four shortcuts above)

**Read-only by construction**: the command vocabulary below contains
*only* ``view`` / ``list`` and the ``api`` action is always invoked as a
GET. The tool does not expose mutation verbs (``close``, ``merge``,
``comment``, ``edit`` …) — the model can't get them through this
interface even by trying to be creative with ``target``.

If ``gh`` is not installed (which is the common case on most deploys)
:py:func:`run_github_query` returns a friendly ``ok=False`` outcome
instead of raising, so the LLM gets a clear "tool unavailable on this
system" message that it can relay to the user.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import logging
import shutil
from typing import Awaitable, Callable

logger = logging.getLogger(__name__)

DEFAULT_TIMEOUT_S = 20.0
MAX_OUTPUT_CHARS = 16_000

QueryType = str  # "pr" | "issue" | "run" | "repo" | "api"

# Mapping from (query_type, target) → argv. Each is a strict *read-only*
# template — no mutation verbs.
_PR_FIELDS = "title,state,statusCheckRollup,reviews,url,author,createdAt,body"
_ISSUE_FIELDS = "title,state,body,comments,url,author,createdAt,labels"
_REPO_FIELDS = "description,defaultBranchRef,stargazerCount,forkCount,visibility,url"
_RUN_FIELDS = "name,status,conclusion,workflowName,event,createdAt,url"


@dataclass(frozen=True)
class GithubOutcome:
    """Result of one ``gh`` invocation."""

    ok: bool
    output: str = ""
    error: str = ""
    query_type: str = ""
    target: str = ""


# A "command runner" — given an argv list and a timeout, returns
# (returncode, stdout, stderr). Injectable so the tool stays unit-
# testable without spawning real subprocesses.
CommandRunner = Callable[[list[str], float], Awaitable[tuple[int, str, str]]]


async def run_github_query(
    *,
    query_type: str,
    target: str,
    timeout_s: float = DEFAULT_TIMEOUT_S,
    command_runner: CommandRunner | None = None,
    gh_available: Callable[[], bool] | None = None,
) -> GithubOutcome:
    """Run one read-only ``gh`` command and return its output.

    Arguments
    ---------
    query_type : "pr" | "issue" | "run" | "repo" | "api"
        Determines which read-only template to use.
    target : str
        ``owner/repo[#number]`` or full URL for ``pr`` / ``issue``;
        ``owner/repo`` for ``run`` and ``repo``; raw ``gh api`` path
        (e.g. ``users/octocat``) for ``api``.
    """
    q = (query_type or "").strip().lower()
    t = (target or "").strip()
    if not q:
        return GithubOutcome(ok=False, error="query_type is required.")
    if not t:
        return GithubOutcome(ok=False, query_type=q, error="target is required.")

    is_available = gh_available or _default_gh_available
    if not is_available():
        return GithubOutcome(
            ok=False,
            query_type=q,
            target=t,
            error=(
                "The `gh` CLI is not installed on this server, so GitHub "
                "queries can't run here. Tell the user; they may need to "
                "ask their admin to install it."
            ),
        )

    argv = _build_argv(q, t)
    if argv is None:
        return GithubOutcome(
            ok=False,
            query_type=q,
            target=t,
            error=(f"Unsupported query_type {q!r}. Choose one of: pr, issue, run, repo, api."),
        )

    runner = command_runner or _default_command_runner
    try:
        rc, stdout, stderr = await runner(argv, timeout_s)
    except asyncio.TimeoutError:
        return GithubOutcome(
            ok=False,
            query_type=q,
            target=t,
            error=f"`gh` timed out after {timeout_s:g}s.",
        )
    except Exception as exc:  # pragma: no cover — defensive
        return GithubOutcome(
            ok=False,
            query_type=q,
            target=t,
            error=f"`gh` invocation failed: {exc}",
        )

    if rc != 0:
        err_line = (stderr or stdout).strip().splitlines()[:3]
        return GithubOutcome(
            ok=False,
            query_type=q,
            target=t,
            error=" / ".join(err_line) or f"gh exited with code {rc}.",
        )

    out = stdout.strip()
    if len(out) > MAX_OUTPUT_CHARS:
        out = out[:MAX_OUTPUT_CHARS].rstrip() + "\n…[truncated]"
    return GithubOutcome(ok=True, output=out, query_type=q, target=t)


# ---------------------------------------------------------------------------
# Internals
# ---------------------------------------------------------------------------


def _build_argv(query_type: str, target: str) -> list[str] | None:
    if query_type == "pr":
        return [
            "gh",
            "pr",
            "view",
            target,
            "--json",
            _PR_FIELDS,
        ]
    if query_type == "issue":
        return [
            "gh",
            "issue",
            "view",
            target,
            "--json",
            _ISSUE_FIELDS,
        ]
    if query_type == "run":
        return [
            "gh",
            "run",
            "list",
            "--repo",
            target,
            "--limit",
            "10",
            "--json",
            _RUN_FIELDS,
        ]
    if query_type == "repo":
        return [
            "gh",
            "repo",
            "view",
            target,
            "--json",
            _REPO_FIELDS,
        ]
    if query_type == "api":
        # ``gh api`` defaults to GET; we never pass ``--method`` so even
        # a creative ``target`` like ``-X POST repos/...`` can't sneak
        # through because the shell isn't invoked.
        return ["gh", "api", "-H", "Accept: application/vnd.github+json", target]
    return None


def _default_gh_available() -> bool:
    return shutil.which("gh") is not None


async def _default_command_runner(argv: list[str], timeout_s: float) -> tuple[int, str, str]:
    """Run ``argv`` as a subprocess, time-bounded, capturing stdout+stderr."""
    proc = await asyncio.create_subprocess_exec(
        *argv,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    try:
        stdout_b, stderr_b = await asyncio.wait_for(proc.communicate(), timeout=timeout_s)
    except asyncio.TimeoutError:
        proc.kill()
        await proc.wait()
        raise
    return (
        proc.returncode if proc.returncode is not None else -1,
        stdout_b.decode("utf-8", errors="replace") if stdout_b else "",
        stderr_b.decode("utf-8", errors="replace") if stderr_b else "",
    )


__all__ = [
    "DEFAULT_TIMEOUT_S",
    "GithubOutcome",
    "QueryType",
    "run_github_query",
]
