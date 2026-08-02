"""Execute one installed CLI app, through the sandbox.

Arguments come from the model, so they are passed as an **argument vector** and
never as a shell string: :meth:`ExecRequest.of_argv` derives the shell form for
older runner images, and every backend that understands ``argv`` execs it
directly. That is the whole reason ``argv`` exists — an app invocation is the one
exec path in DeepTutor whose arguments are model-authored *and* whose program is
fixed, so there is nothing to gain from a shell and a lot to lose.

The app's own ``bin`` directory goes on ``PATH`` and nothing else does: a Python
harness shells out to its own interpreter and its own console scripts, and it
must find those rather than whatever the sandbox image happens to ship.
"""

from __future__ import annotations

from collections.abc import Sequence
import logging
import os

from deeptutor.core.i18n import t
from deeptutor.services.cli_apps.paths import abi_stamp, bin_dir, executable_path, runtime_dir
from deeptutor.services.cli_apps.state import InstalledApp
from deeptutor.services.sandbox.spec import ExecRequest, ExecResult, Mount, ResourceLimits

logger = logging.getLogger(__name__)

#: Default wall-clock ceiling for one app invocation. Higher than the exec
#: tool's, because a CLI app's job is often a real conversion or render.
DEFAULT_TIMEOUT_S = 120
MAX_TIMEOUT_S = 600

#: How much of the app's output reaches the model.
MAX_OUTPUT_CHARS = 20_000


async def run_app(
    app: InstalledApp,
    args: Sequence[str],
    *,
    user_id: str,
    workdir: str = "",
    mounts: tuple[Mount, ...] = (),
    timeout_s: int | None = None,
) -> ExecResult:
    """Invoke *app* with *args*, returning the sandbox's result.

    Never raises: a broken install, a missing sandbox and a non-zero exit all
    come back as an :class:`ExecResult`, because the caller is a tool whose job
    is to report what happened rather than to fail a turn.
    """
    if app.abi and app.abi != abi_stamp():
        # The venv's console scripts hard-code the interpreter that built them.
        # After a base-image bump they point at a path that no longer exists, and
        # the failure would otherwise surface as a bare ENOENT mid-turn.
        return ExecResult(
            error=t(
                "cli_apps.abi_mismatch",
                app=app.id,
                installed=app.abi,
                current=abi_stamp(),
            )
        )
    try:
        executable = executable_path(app.id, app.runtime, app.entry_point)
    except ValueError as exc:
        return ExecResult(error=str(exc))
    if not executable.exists():
        return ExecResult(error=t("cli_apps.not_installed", app=app.id))
    app_root = runtime_dir(app.id, app.runtime)

    limits = ResourceLimits(
        timeout_s=_bounded_timeout(timeout_s),
        max_output_chars=MAX_OUTPUT_CHARS,
    )
    request = ExecRequest.of_argv(
        [str(executable), *(str(arg) for arg in args)],
        workdir=workdir,
        # The app's own tree, read-only. A backend that mounts per command needs
        # it or the executable is not there at all; the sidecar already has it
        # from the compose layout and ignores the duplicate.
        mounts=(*mounts, Mount(host_path=str(app_root), sandbox_path=str(app_root))),
        env=_env_for(app),
        limits=limits,
    )
    from deeptutor.services.sandbox import get_sandbox_service

    return await get_sandbox_service().run(request, user_id=user_id)


def _bounded_timeout(requested: int | None) -> int:
    if not requested:
        return DEFAULT_TIMEOUT_S
    try:
        value = int(requested)
    except (TypeError, ValueError):
        return DEFAULT_TIMEOUT_S
    return max(1, min(value, MAX_TIMEOUT_S))


def _env_for(app: InstalledApp) -> dict[str, str]:
    """The app's environment: its own bin directory, and the bare minimum else.

    Deliberately **not** the process environment. An installed app is third-party
    code, and the application's own environment holds every provider API key the
    deployment is configured with. ``PATH`` is the one exception, because it is
    not a secret and because getting it wrong is fatal rather than degrading:
    ``PATH`` set here *replaces* whatever the backend would have used, and an
    npm-installed CLI's console script starts ``#!/usr/bin/env node``. A
    hardcoded list of standard directories therefore breaks every node app on any
    host that keeps its interpreter elsewhere — a Homebrew macOS deployment, for
    one, where the failure is a bare ``env: node: No such file or directory``.
    """
    return {
        "PATH": _path_for(app),
        "HOME": "/tmp",  # noqa: S108  # nosec B108 - tmpfs inside the sandbox, not a host path
        "LANG": "C.UTF-8",
        "PYTHONUNBUFFERED": "1",
        "PYTHONDONTWRITEBYTECODE": "1",
    }


def _path_for(app: InstalledApp) -> str:
    """The app's own ``bin`` first, then the search path this host actually uses.

    The inherited value comes from the *application* process, which for the
    sidecar backend is a different container than the one that will run the
    command. That is harmless in both directions: a directory that does not exist
    there is skipped, and the standard locations are appended so the result is a
    superset rather than a substitution.
    """
    parts = [str(bin_dir(app.id, app.runtime))]
    for candidate in (
        *os.environ.get("PATH", "").split(os.pathsep),
        "/usr/local/bin",
        "/usr/bin",
        "/bin",
    ):
        if candidate and candidate not in parts:
            parts.append(candidate)
    return os.pathsep.join(parts)


__all__ = ["DEFAULT_TIMEOUT_S", "MAX_OUTPUT_CHARS", "MAX_TIMEOUT_S", "run_app"]
