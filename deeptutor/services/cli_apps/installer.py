"""Install and remove CLI apps. Administrator only.

This module is the one place in the feature that executes code **outside** the
sandbox: ``pip install`` runs the package's own ``setup.py`` in the application
container, as the application user. No amount of care makes that a self-service
action, which is why installing is admin-gated and why the catalog labels every
entry's provenance (see :class:`~deeptutor.services.cli_apps.models.AppTrust`).

What this module does *not* do:

* **Run the registry's install command.** It runs an argv assembled from an
  :class:`~deeptutor.services.cli_apps.models.InstallPlan`. See ``models``.
* **Let npm packages run their install scripts.** ``npm_config_ignore_scripts``
  is forced on: a postinstall hook is arbitrary third-party code with no
  relationship to the package's actual contents. Some packages genuinely need
  one (a browser download, a native build) and will not work here — that is the
  intended trade, and the failure is visible in the install log rather than
  silent.
* **Replace a working install with a broken one.** An update moves the existing
  environment aside, builds fresh, and moves it back if the build fails. A venv's
  console scripts hard-code the absolute path of the interpreter that created
  them, so the build has to happen *at* the final path — which is exactly why the
  rollback restores that same path rather than promoting a staging directory.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import logging
import os
import shutil
import subprocess
import sys

from deeptutor.services.cli_apps.models import (
    AppRuntime,
    CliAppEntry,
    InstallKind,
)
from deeptutor.services.cli_apps.paths import (
    abi_stamp,
    app_dir,
    ensure_root,
    executable_path,
    install_log_path,
    runtime_dir,
)
from deeptutor.services.cli_apps.state import (
    InstalledApp,
    forget_install,
    load_installed,
    now_stamp,
    record_install,
)

logger = logging.getLogger(__name__)

#: A pip install that compiles a wheel can legitimately take minutes.
INSTALL_TIMEOUT_S = int(os.environ.get("DEEPTUTOR_CLI_APP_INSTALL_TIMEOUT_S", "900"))

#: Tail of the install output kept for the admin to read back.
_LOG_TAIL_CHARS = 20_000

#: One in-flight install per app, per process. A multi-process deployment can
#: still race two installs of the same app; the loser's build lands in a
#: directory the winner is rewriting, and the outcome is an install failure
#: rather than a corrupt state file (the state write itself is atomic).
_locks: dict[str, asyncio.Lock] = {}


@dataclass(frozen=True, slots=True)
class InstallOutcome:
    """What happened, in the terms the admin UI reports."""

    ok: bool
    app_id: str
    #: Machine-readable reason on failure (``cli.install_failed`` and friends).
    code: str = ""
    message: str = ""
    #: Tail of the install output. Present on success too — a warning-riddled
    #: successful install is worth reading.
    log: str = ""
    app: InstalledApp | None = None


async def install_app(entry: CliAppEntry) -> InstallOutcome:
    """Install *entry* for the deployment."""
    if not entry.install.installable:
        return InstallOutcome(
            ok=False,
            app_id=entry.id,
            code="cli.not_installable",
            message=entry.install.reason,
        )
    lock = _locks.setdefault(entry.id, asyncio.Lock())
    if lock.locked():
        return InstallOutcome(
            ok=False,
            app_id=entry.id,
            code="cli.install_in_progress",
            message=f"{entry.display_name} is already being installed.",
        )
    async with lock:
        return await asyncio.to_thread(_install_blocking, entry)


async def uninstall_app(app_id: str) -> InstallOutcome:
    """Remove *app_id*'s environment and forget it.

    Tolerant of a partially-installed app: the directory is removed if present
    and the state entry dropped either way, so a failed install cannot leave a
    row an admin is unable to clear.
    """
    lock = _locks.setdefault(app_id, asyncio.Lock())
    async with lock:
        return await asyncio.to_thread(_uninstall_blocking, app_id)


def _install_blocking(entry: CliAppEntry) -> InstallOutcome:
    ensure_root()
    target_dir = app_dir(entry.id)
    target_dir.mkdir(parents=True, exist_ok=True)
    runtime = entry.install.runtime
    env_dir = runtime_dir(entry.id, runtime)
    backup = env_dir.with_name(f"{env_dir.name}.old")

    shutil.rmtree(backup, ignore_errors=True)
    had_previous = env_dir.exists()
    if had_previous:
        os.replace(env_dir, backup)

    chunks: list[str] = []
    try:
        for argv, env in _steps(entry, env_dir):
            code, output = _run(argv, env=env)
            chunks.append(f"$ {' '.join(argv)}\n{output}")
            if code != 0:
                raise _StepFailed(f"`{argv[0]}` exited {code}")
        executable = executable_path(entry.id, runtime, entry.entry_point)
        if not executable.exists():
            raise _StepFailed(
                f"install finished but {entry.entry_point!r} is not in the app's bin "
                "directory — the package may publish a different command name"
            )
    except (_StepFailed, OSError) as exc:
        log = _write_log(entry.id, chunks + [f"\nFAILED: {exc}"])
        shutil.rmtree(env_dir, ignore_errors=True)
        if had_previous:
            # Put the working install back at exactly the path its console
            # scripts' shebangs name.
            os.replace(backup, env_dir)
        return InstallOutcome(
            ok=False,
            app_id=entry.id,
            code="cli.install_failed",
            message=str(exc),
            log=log,
        )

    shutil.rmtree(backup, ignore_errors=True)
    app = InstalledApp(
        id=entry.id,
        entry_point=entry.entry_point,
        runtime=runtime,
        kind=entry.install.kind,
        target=entry.install.target,
        pin=_pin_of(entry),
        abi=abi_stamp(),
        installed_at=now_stamp(),
        version=entry.version,
    )
    record_install(app)
    return InstallOutcome(
        ok=True,
        app_id=entry.id,
        log=_write_log(entry.id, chunks),
        app=app,
    )


def _uninstall_blocking(app_id: str) -> InstallOutcome:
    directory = app_dir(app_id)
    known = app_id in load_installed()
    try:
        shutil.rmtree(directory, ignore_errors=True)
    finally:
        forget_install(app_id)
    if not known and not directory.exists():
        return InstallOutcome(
            ok=True, app_id=app_id, message="Nothing was installed under that id."
        )
    return InstallOutcome(ok=True, app_id=app_id)


class _StepFailed(RuntimeError):
    """An install step returned non-zero, or produced nothing usable."""


def _steps(entry: CliAppEntry, env_dir) -> list[tuple[list[str], dict[str, str]]]:
    """The argv sequence that installs *entry*, and each step's environment."""
    plan = entry.install
    if plan.runtime is AppRuntime.PYTHON:
        base = _clean_env()
        return [
            ([sys.executable, "-m", "venv", str(env_dir)], base),
            (
                [
                    str(env_dir / "bin" / "python"),
                    "-m",
                    "pip",
                    "install",
                    "--no-input",
                    "--disable-pip-version-check",
                    plan.target,
                ],
                base,
            ),
        ]
    if plan.runtime is AppRuntime.NODE:
        env = _clean_env()
        # Refuse install scripts: a postinstall hook is arbitrary code shipped
        # alongside — but not described by — the package being installed.
        env["npm_config_ignore_scripts"] = "1"
        env["npm_config_fund"] = "false"
        env["npm_config_audit"] = "false"
        env["npm_config_update_notifier"] = "false"
        return [
            (
                ["npm", "install", "-g", "--prefix", str(env_dir), plan.target],
                env,
            )
        ]
    raise _StepFailed(f"no install steps for runtime {plan.runtime.value!r}")


def _clean_env() -> dict[str, str]:
    """A minimal environment for an install step.

    Passing the app's whole environment would hand a third-party ``setup.py``
    every provider API key the process holds.
    """
    keep = ("PATH", "HOME", "LANG", "LC_ALL", "TMPDIR", "SSL_CERT_FILE", "SSL_CERT_DIR")
    env = {key: os.environ[key] for key in keep if key in os.environ}
    env.setdefault("PATH", "/usr/local/bin:/usr/bin:/bin")
    # Proxy settings are deployment infrastructure, not app state: an install
    # behind a corporate proxy needs them or it cannot reach the index at all.
    for key in ("HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY", "http_proxy", "https_proxy"):
        if key in os.environ:
            env[key] = os.environ[key]
    env["PIP_DISABLE_PIP_VERSION_CHECK"] = "1"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return env


def _run(argv: list[str], *, env: dict[str, str]) -> tuple[int, str]:
    """Run one install step, returning ``(exit code, combined output)``."""
    try:
        completed = subprocess.run(  # noqa: S603 - argv is built by this module
            argv,
            env=env,
            capture_output=True,
            text=True,
            timeout=INSTALL_TIMEOUT_S,
            check=False,
        )
    except FileNotFoundError:
        return 127, f"{argv[0]}: not found in this image"
    except subprocess.TimeoutExpired:
        return 124, f"timed out after {INSTALL_TIMEOUT_S}s"
    return completed.returncode, (completed.stdout or "") + (completed.stderr or "")


def _write_log(app_id: str, chunks: list[str]) -> str:
    """Persist the install output and return the tail that the API reports."""
    text = "\n\n".join(chunks)
    tail = text[-_LOG_TAIL_CHARS:] if len(text) > _LOG_TAIL_CHARS else text
    try:
        path = install_log_path(app_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    except OSError:
        logger.warning("could not write the install log for %s", app_id, exc_info=True)
    return tail


def _pin_of(entry: CliAppEntry) -> str:
    """What this install is pinned to, or "" when it floats."""
    if entry.install.kind is InstallKind.PINNED_HARNESS:
        from deeptutor.services.cli_apps.catalog import catalog_pin

        return catalog_pin()
    return entry.install.target if entry.install.pinned else ""


__all__ = ["INSTALL_TIMEOUT_S", "InstallOutcome", "install_app", "uninstall_app"]
