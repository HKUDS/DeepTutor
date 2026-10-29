"""Offline module changes: dependency planning, environment leases and pip.

Official wheels share the host interpreter. Mutations require exclusive
ownership of that environment; serving processes and turns hold read leases.
Removing code never removes user data or uninstalls transitive packages.
"""

from __future__ import annotations

from contextlib import ExitStack, contextmanager
import hashlib
from importlib import metadata
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile

from .catalog import (
    dependency_order,
    dependents,
    installed,
    manifests,
    selection,
    source_checkout,
    state_path,
)


class ModuleLifecycleError(ValueError):
    pass


@contextmanager
def environment_lease(*, exclusive: bool = False):
    # Deployments may share a home across interpreters. Lock both package files
    # and module selection so another environment cannot disable a live feature.
    identities = (str(Path(sys.prefix).resolve()), str(state_path().resolve()))
    with ExitStack() as stack:
        for identity in identities:
            stack.enter_context(_file_lease(identity, exclusive=exclusive))
        yield


@contextmanager
def _file_lease(identity: str, *, exclusive: bool):
    identity = hashlib.sha256(identity.encode()).hexdigest()[:24]
    path = Path(tempfile.gettempdir()) / f"deeptutor-environment-{identity}.lock"
    with path.open("a+b") as handle:
        if sys.platform == "win32":
            import ctypes
            from ctypes import wintypes
            import msvcrt

            class Overlapped(ctypes.Structure):
                _fields_ = [
                    ("Internal", ctypes.c_size_t),
                    ("InternalHigh", ctypes.c_size_t),
                    ("Offset", wintypes.DWORD),
                    ("OffsetHigh", wintypes.DWORD),
                    ("hEvent", wintypes.HANDLE),
                ]

            kernel = ctypes.WinDLL("kernel32", use_last_error=True)
            overlapped = Overlapped()
            native = wintypes.HANDLE(msvcrt.get_osfhandle(handle.fileno()))
            if not kernel.LockFileEx(
                native, 1 | (2 if exclusive else 0), 0, 1, 0, ctypes.byref(overlapped)
            ):
                raise ModuleLifecycleError(
                    "Environment is in use. Stop DeepTutor before changing modules."
                )
            try:
                yield
            finally:
                kernel.UnlockFileEx(native, 0, 1, 0, ctypes.byref(overlapped))
        else:
            import fcntl

            try:
                fcntl.flock(handle, (fcntl.LOCK_EX if exclusive else fcntl.LOCK_SH) | fcntl.LOCK_NB)
            except BlockingIOError as exc:
                raise ModuleLifecycleError(
                    "Environment is in use. Stop DeepTutor before changing modules."
                ) from exc
            try:
                yield
            finally:
                fcntl.flock(handle, fcntl.LOCK_UN)


def plan(action: str, name: str) -> dict:
    if name not in manifests():
        raise ModuleLifecycleError(f"Unknown module: {name}")
    if name == "core" and action in {"disable", "uninstall"}:
        raise ModuleLifecycleError("The core module cannot be removed or disabled.")
    if action not in {"install", "uninstall", "enable", "disable"}:
        raise ModuleLifecycleError(f"Unknown action: {action}")
    affected = dependency_order([name]) if action in {"install", "enable"} else [name]
    blockers = (
        dependents(name, enabled_only=action == "disable")
        if action in {"disable", "uninstall"}
        else []
    )
    if action == "uninstall" and not source_checkout():
        from packaging.requirements import Requirement

        target = _canonical(manifests()[name]["distribution"])
        for distribution in metadata.distributions():
            headers = distribution.metadata
            package = headers["Name"] if "Name" in headers else ""
            if _canonical(package) == target:
                continue
            for raw in distribution.requires or ():
                requirement = Requirement(raw)
                if (requirement.marker is None or requirement.marker.evaluate()) and _canonical(
                    requirement.name
                ) == target:
                    # Include dependents outside the official catalog as well.
                    if package not in {
                        manifests()[key]["distribution"] if key in manifests() else key
                        for key in blockers
                    }:
                        blockers.append(package)
                    break
    return {
        "action": action,
        "module": name,
        "affected": affected,
        "blocked_by": blockers,
        "preserves_data": True,
        "requires_stopped_environment": True,
    }


def _save_selection(enabled: dict[str, bool]) -> None:
    path = state_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=".modules-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as stream:
            json.dump({"schema_version": 1, "enabled": enabled}, stream, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def change(action: str, name: str, *, wheelhouse: Path | None = None) -> dict:
    from deeptutor.__version__ import __version__

    with environment_lease(exclusive=True):
        # Refuse malformed state before any package mutation, including uninstall.
        enabled = selection()
        result = plan(action, name)
        if result["blocked_by"]:
            raise ModuleLifecycleError("Required by: " + ", ".join(result["blocked_by"]))
        if action in {"enable", "disable"}:
            for module in result["affected"]:
                if action == "enable" and not installed(module):
                    raise ModuleLifecycleError(f"Install {module} before enabling it.")
                if action == "enable" and not source_checkout() and module != "core":
                    version = metadata.version(manifests()[module]["distribution"])
                    if version != __version__:
                        raise ModuleLifecycleError(
                            f"Module {module} version {version} must match core {__version__}."
                        )
                enabled[module] = action == "enable"
            _save_selection(enabled)
            return result
        if source_checkout():
            raise ModuleLifecycleError(
                "This is a source checkout. Use enable/disable here; install/uninstall "
                "operates on wheel installations in a separate virtual environment."
            )
        base = [sys.executable, "-m", "pip", "--disable-pip-version-check"]
        if action == "install":
            targets = [
                f"{manifests()[module]['distribution']}=={__version__}"
                for module in result["affected"]
                if module != "core"
            ]
            targets.append(f"deeptutor=={__version__}")
            before = {
                _canonical(dist.metadata["Name"]): dist.version
                for dist in metadata.distributions()
                if dist.metadata["Name"]
            }
            with tempfile.TemporaryDirectory(prefix="deeptutor-install-") as directory:
                stage = Path(directory)
                report = stage / "plan.json"
                source = ["--find-links", str(wheelhouse.resolve())] if wheelhouse else []
                _pip([*base, "install", "--dry-run", "--report", str(report), *source, *targets])
                resolved = json.loads(report.read_text())["install"]
                replacements = [
                    row["metadata"]["name"]
                    for row in resolved
                    if _canonical(row["metadata"]["name"]) in before
                    and before[_canonical(row["metadata"]["name"])] != row["metadata"]["version"]
                ]
                if replacements:
                    raise ModuleLifecycleError(
                        "Installation would replace existing dependencies: "
                        + ", ".join(replacements)
                        + ". Use a fresh virtual environment or update the whole environment explicitly."
                    )
                # Build precisely the dry-run solution. Resolving again could select
                # different versions, or rebuild dependencies already installed.
                artifacts = []
                for row in resolved:
                    info = row["download_info"]
                    url = info["url"]
                    digest = info.get("archive_info", {}).get("hashes", {}).get("sha256")
                    if digest and "#" not in url:
                        url += "#sha256=" + digest
                    artifacts.append(url)
                if artifacts:
                    _pip([*base, "wheel", "--no-deps", "--wheel-dir", str(stage), *artifacts])
                try:
                    wheels = sorted(str(path) for path in stage.glob("*.whl"))
                    log = (
                        _pip([*base, "install", "--no-deps", "--no-index", *wheels])
                        if wheels
                        else "Requested modules are already installed."
                    )
                    for module in result["affected"]:
                        enabled[module] = True
                    _save_selection(enabled)
                except BaseException:
                    added = sorted(
                        {
                            _canonical(dist.metadata["Name"])
                            for dist in metadata.distributions()
                            if dist.metadata["Name"]
                        }
                        - before.keys()
                    )
                    if added:
                        _pip([*base, "uninstall", "-y", *added])
                    raise
            return {**result, "log": log}
        else:
            log = _pip([*base, "uninstall", "-y", manifests()[name]["distribution"]])
        # Selection changes only after pip succeeds. Dependencies are never
        # auto-removed: other applications may also own them in this interpreter.
        enabled.pop(name, None)
        _save_selection(enabled)
        return {**result, "log": log}


def _canonical(name: str) -> str:
    from packaging.utils import canonicalize_name

    return canonicalize_name(name)


def _pip(argv: list[str]) -> str:
    """Do not release the environment lease while pip/build children still run."""
    try:
        process = subprocess.Popen(
            argv,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            start_new_session=os.name != "nt",
        )
        try:
            stdout, stderr = process.communicate(timeout=900)
        except BaseException:
            from deeptutor.runtime.process import kill_process_tree

            kill_process_tree(process.pid)
            process.communicate()
            raise
    except OSError as exc:
        raise ModuleLifecycleError(str(exc)) from exc
    if process.returncode:
        raise ModuleLifecycleError((stderr or stdout)[-6000:])
    return stdout
