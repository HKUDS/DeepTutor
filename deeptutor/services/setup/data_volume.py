"""Probe whether the runtime data volume is writable by the app user.

The container image bakes a ``deeptutor`` user at UID/GID 1000 and drops
supervisord children to that user. Bind mounts on Unraid / NAS hosts are often
owned by a different host UID (``PUID``/``PGID``). A silent ``chown || true``
then leaves the volume unwritable, and later KB indexing is reported as
"Knowledge base not initialized" instead of a permission error.

This helper is the fail-fast seam used by the container entrypoint,
:class:`~deeptutor.knowledge.initializer.KnowledgeBaseInitializer`, and
:class:`~deeptutor.knowledge.add_documents.DocumentAdder`.
"""

from __future__ import annotations

import os
from pathlib import Path
import stat
from typing import Final

DEFAULT_RUNTIME_UID: Final[int] = 1000
DEFAULT_RUNTIME_GID: Final[int] = 1000
_PROBE_PREFIX: Final[str] = ".deeptutor-write-probe"


class DataVolumePermissionError(PermissionError):
    """The data volume cannot be written by the process that will run the app."""


def parse_id(value: str | None, *, default: int, name: str) -> int:
    """Parse a PUID/PGID-style identifier, rejecting root and non-integers."""
    raw = (value or "").strip() or str(default)
    try:
        parsed = int(raw)
    except ValueError as exc:
        raise ValueError(f"{name} must be a non-root integer, got {value!r}") from exc
    if parsed <= 0:
        raise ValueError(f"{name} must be a non-root integer, got {parsed}")
    return parsed


def resolve_runtime_ids(
    *,
    puid: str | None = None,
    pgid: str | None = None,
    euid: int | None = None,
    egid: int | None = None,
) -> tuple[int, int]:
    """Return the UID/GID the app processes should run as.

    Rootless (non-zero euid) keeps the current process identity so we do not
    try to ``setuid`` without ``CAP_SETUID``. Rootful Docker remaps to
    ``PUID``/``PGID`` (default 1000/1000).
    """
    current_uid = os.geteuid() if euid is None else euid
    current_gid = os.getegid() if egid is None else egid
    if current_uid != 0:
        return current_uid, current_gid
    return (
        parse_id(puid, default=DEFAULT_RUNTIME_UID, name="PUID"),
        parse_id(pgid, default=DEFAULT_RUNTIME_GID, name="PGID"),
    )


def describe_path_ownership(path: Path) -> str:
    """Human-readable owner/mode for *path*, or ``unreadable``."""
    try:
        info = path.stat()
    except OSError:
        return "unreadable"
    mode = stat.S_IMODE(info.st_mode)
    return f"uid={info.st_uid} gid={info.st_gid} mode={mode:04o}"


def format_data_volume_permission_error(
    path: Path,
    *,
    uid: int,
    gid: int,
    cause: BaseException | None = None,
) -> str:
    """Explain a UID mismatch in terms operators can act on (PUID/PGID)."""
    owner = describe_path_ownership(path)
    cause_txt = f" ({cause})" if cause else ""
    return (
        f"Data directory is not writable by the running process "
        f"(euid={uid}, egid={gid}): {path} is {owner}.{cause_txt} "
        "On Unraid/NAS bind mounts, set PUID and PGID to the host owner of the "
        "volume instead of chowning the mount. The app stays a non-root user; "
        "the container remaps `deeptutor` to those ids."
    )


def ensure_data_volume_writable(
    path: Path | str,
    *,
    uid: int | None = None,
    gid: int | None = None,
) -> None:
    """Create *path* if needed and fail if the runtime user cannot write it.

    When this process is root and *uid*/*gid* differ from the current euid,
    the probe forks and drops to that identity so a root-only write does not
    mask an Unraid bind-mount that UID 1000 cannot use. Non-root callers
    (the FastAPI backend) probe as themselves.
    """
    target = Path(path)
    probe_uid = os.geteuid() if uid is None else uid
    probe_gid = os.getegid() if gid is None else gid
    drop_privs = (
        os.geteuid() == 0
        and probe_uid != 0
        and (probe_uid != os.geteuid() or probe_gid != os.getegid())
        and hasattr(os, "fork")
        and hasattr(os, "setuid")
    )
    if drop_privs:
        _ensure_writable_as(target, probe_uid, probe_gid)
        return
    _try_write_or_raise(target, probe_uid, probe_gid)


def check_container_data_volume(data_root: Path | str | None = None) -> None:
    """Entrypoint fail-fast: ``/app/data`` and ``knowledge_bases`` must be writable."""
    root = Path(data_root or "/app/data")
    uid, gid = resolve_runtime_ids(
        puid=os.environ.get("PUID") or os.environ.get("DEEPTUTOR_PUID"),
        pgid=os.environ.get("PGID") or os.environ.get("DEEPTUTOR_PGID"),
    )
    for target in (root, root / "knowledge_bases"):
        ensure_data_volume_writable(target, uid=uid, gid=gid)


def _try_write_or_raise(path: Path, uid: int, gid: int) -> None:
    probe = path / f"{_PROBE_PREFIX}-{os.getpid()}"
    try:
        # Create as the process that will write the data. A root parent can
        # receive EACCES on a root-squashed NAS mount even when PUID can write.
        path.mkdir(parents=True, exist_ok=True)
        probe.write_text("ok", encoding="utf-8")
        probe.unlink(missing_ok=True)
    except OSError as exc:
        try:
            probe.unlink(missing_ok=True)
        except OSError:
            pass
        raise DataVolumePermissionError(
            format_data_volume_permission_error(path, uid=uid, gid=gid, cause=exc)
        ) from exc


def _ensure_writable_as(path: Path, uid: int, gid: int) -> None:
    """Fork, drop to *uid*/*gid*, and probe. Parent raises on child failure."""
    pid = os.fork()
    if pid == 0:  # pragma: no cover - child process
        try:
            os.setgid(gid)
            os.setuid(uid)
            _try_write_or_raise(path, uid, gid)
            os._exit(0)
        except OSError:
            os._exit(1)
    _, status = os.waitpid(pid, 0)
    if not os.WIFEXITED(status) or os.WEXITSTATUS(status) != 0:
        raise DataVolumePermissionError(format_data_volume_permission_error(path, uid=uid, gid=gid))
