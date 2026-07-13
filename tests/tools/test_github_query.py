"""Unit tests for the ``github_query`` tool's pure logic.

We never spawn ``gh`` for real — every test injects its own
``command_runner`` so we can pin returncode / stdout / stderr.
"""

from __future__ import annotations

import asyncio
from typing import Any

import pytest

from deeptutor.tools.github_query import (
    MAX_OUTPUT_CHARS,
    GithubOutcome,
    run_github_query,
)


def _runner(
    *,
    returncode: int = 0,
    stdout: str = "",
    stderr: str = "",
    record: list[list[str]] | None = None,
):
    async def _run(argv, timeout_s):
        if record is not None:
            record.append(list(argv))
        return returncode, stdout, stderr

    return _run


# ---------------------------------------------------------------------------
# Argument validation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_rejects_missing_query_type() -> None:
    outcome = await run_github_query(
        query_type="",
        target="owner/repo",
        gh_available=lambda: True,
        command_runner=_runner(),
    )
    assert outcome.ok is False
    assert "query_type" in outcome.error


@pytest.mark.asyncio
async def test_rejects_missing_target() -> None:
    outcome = await run_github_query(
        query_type="pr",
        target="",
        gh_available=lambda: True,
        command_runner=_runner(),
    )
    assert outcome.ok is False
    assert "target" in outcome.error


@pytest.mark.asyncio
async def test_rejects_unsupported_query_type() -> None:
    outcome = await run_github_query(
        query_type="merge",  # explicitly write-flavoured, not in the whitelist
        target="owner/repo#1",
        gh_available=lambda: True,
        command_runner=_runner(),
    )
    assert outcome.ok is False
    assert "Unsupported query_type" in outcome.error


# ---------------------------------------------------------------------------
# gh CLI availability
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_reports_gh_missing_gracefully() -> None:
    outcome = await run_github_query(
        query_type="pr",
        target="owner/repo#1",
        gh_available=lambda: False,
        command_runner=_runner(),  # should never be invoked
    )
    assert outcome.ok is False
    assert "`gh`" in outcome.error or "gh" in outcome.error.lower()


# ---------------------------------------------------------------------------
# argv shape — confirms each query_type stays read-only
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pr_argv_is_view_only() -> None:
    record: list[list[str]] = []
    await run_github_query(
        query_type="pr",
        target="owner/repo#42",
        gh_available=lambda: True,
        command_runner=_runner(stdout='{"title":"x"}', record=record),
    )
    assert record == [
        [
            "gh",
            "pr",
            "view",
            "owner/repo#42",
            "--json",
            "title,state,statusCheckRollup,reviews,url,author,createdAt,body",
        ]
    ]


@pytest.mark.asyncio
async def test_issue_argv_is_view_only() -> None:
    record: list[list[str]] = []
    await run_github_query(
        query_type="issue",
        target="owner/repo#7",
        gh_available=lambda: True,
        command_runner=_runner(stdout='{"title":"x"}', record=record),
    )
    assert record[0][:4] == ["gh", "issue", "view", "owner/repo#7"]


@pytest.mark.asyncio
async def test_run_argv_uses_list_subcommand() -> None:
    record: list[list[str]] = []
    await run_github_query(
        query_type="run",
        target="owner/repo",
        gh_available=lambda: True,
        command_runner=_runner(stdout="[]", record=record),
    )
    assert record[0][:5] == ["gh", "run", "list", "--repo", "owner/repo"]


@pytest.mark.asyncio
async def test_api_argv_does_not_set_method() -> None:
    """`gh api` defaults to GET; we never pass --method so the tool
    can't be coerced into a mutating call by creative ``target``s."""
    record: list[list[str]] = []
    await run_github_query(
        query_type="api",
        target="repos/owner/repo/issues",
        gh_available=lambda: True,
        command_runner=_runner(stdout="[]", record=record),
    )
    assert "--method" not in record[0]
    assert "-X" not in record[0]
    assert record[0][0:2] == ["gh", "api"]


# ---------------------------------------------------------------------------
# Output handling
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_truncates_oversized_output() -> None:
    huge = "y" * (MAX_OUTPUT_CHARS + 500)
    outcome = await run_github_query(
        query_type="pr",
        target="o/r#1",
        gh_available=lambda: True,
        command_runner=_runner(stdout=huge),
    )
    assert outcome.ok is True
    assert outcome.output.endswith("[truncated]")


@pytest.mark.asyncio
async def test_surfaces_nonzero_exit_as_failure() -> None:
    outcome = await run_github_query(
        query_type="pr",
        target="o/r#1",
        gh_available=lambda: True,
        command_runner=_runner(returncode=1, stderr="not found"),
    )
    assert outcome.ok is False
    assert "not found" in outcome.error
