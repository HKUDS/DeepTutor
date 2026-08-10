"""Resident-memory snapshot of the running DeepTutor process tree.

The counterpart to :mod:`deeptutor.runtime.memory_reclaim`: that module *acts*
on memory (cycle collection, ``malloc_trim``), this one *observes* it so the
settings status strip can show what the app actually costs.

Two things make "how much memory does DeepTutor use" more than one ``getrusage``
call:

* The backend is only one of the processes. ``deeptutor.runtime.launcher``
  spawns the Next.js frontend as a *sibling* (see ``_spawn``), and capabilities
  spawn sandboxes and subagent CLIs below it. Answering honestly means walking
  the supervisor's process tree, which is why the launcher stamps its own pid
  into :data:`SUPERVISOR_PID_ENV` — without that anchor a bare
  ``uvicorn deeptutor.api.main:app`` run would climb into the developer's shell
  and count unrelated jobs.
* Inside a container the host's total RAM is the wrong denominator. cgroup's
  own accounting is what the OOM killer reads, so it wins when present.

Summing per-process RSS double-counts pages shared through ``fork``, so the
total is an upper bound. The cheaper, exact-enough alternative (USS) costs a
page-table walk per process, which is too much for a strip that polls.
"""

from __future__ import annotations

from dataclasses import dataclass
import os
from pathlib import Path
import sys
from typing import Any

# Stamped by the launcher onto every child's environment so the backend can
# find the root of the DeepTutor process tree it belongs to.
SUPERVISOR_PID_ENV = "DEEPTUTOR_SUPERVISOR_PID"

_CGROUP_V2_CURRENT = Path("/sys/fs/cgroup/memory.current")
_CGROUP_V2_MAX = Path("/sys/fs/cgroup/memory.max")
_CGROUP_V1_USAGE = Path("/sys/fs/cgroup/memory/memory.usage_in_bytes")
_CGROUP_V1_LIMIT = Path("/sys/fs/cgroup/memory/memory.limit_in_bytes")

# cgroup v1 spells "no limit" as a sentinel near the top of the address space
# rather than as a word, and the exact value varies with page size.
_CGROUP_V1_UNLIMITED = 1 << 62

# Enough detail to explain a large total without turning the tooltip into a
# process list; the rest is folded into one "other" row by the router.
MAX_REPORTED_PROCESSES = 12


@dataclass(frozen=True, slots=True)
class ProcessMemory:
    """One process in the DeepTutor tree."""

    pid: int
    label: str
    rss_bytes: int


@dataclass(frozen=True, slots=True)
class MemorySnapshot:
    """What the app costs right now, and what it is allowed to cost."""

    processes: tuple[ProcessMemory, ...]
    total_rss_bytes: int
    limit_bytes: int | None
    available_bytes: int | None
    # "cgroup" when a container limit is in force, "host" for physical RAM,
    # "unknown" when neither could be read.
    limit_source: str
    # True when only this process could be measured, so the total understates
    # the tree. The UI labels the number differently rather than hiding it.
    partial: bool

    @property
    def usage_ratio(self) -> float | None:
        if not self.limit_bytes:
            return None
        return self.total_rss_bytes / self.limit_bytes


def _load_psutil() -> Any | None:
    """Import psutil lazily; it is a soft dependency (see ``_scan_proc``)."""
    try:
        import psutil
    except ImportError:
        return None
    return psutil


def _read_int(path: Path) -> int | None:
    try:
        return int(path.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return None


def _supervisor_pid(pid_exists: Any) -> int | None:
    """Resolve the launcher's pid from the environment, if it is still alive."""
    raw = os.environ.get(SUPERVISOR_PID_ENV, "").strip()
    if not raw.isdigit():
        return None
    pid = int(raw)
    if pid <= 0 or not pid_exists(pid):
        return None
    return pid


def _classify(pid: int, name: str, cmdline: str, root_pid: int | None = None) -> str:
    """Name a process by the role it plays, never by its full command line.

    Command lines can carry credentials passed as flags, and this snapshot is
    served over HTTP — so classification reads the command line but only ever
    emits one of these fixed role labels or a bare executable name.

    The two roles we know as *facts* (this process, and the tree's root) are
    decided by pid. Guessing them from the command line was wrong in practice:
    the supervisor runs as a bare ``deeptutor`` console script with nothing in
    its argv to match on.
    """
    if pid == os.getpid():
        return "backend"
    if root_pid is not None and pid == root_pid:
        return "supervisor"
    lowered = f"{name} {cmdline}".lower()
    if "next" in lowered or "node" in lowered:
        return "web"
    if "uvicorn" in lowered or "deeptutor.api" in lowered:
        return "backend"
    if "pocketbase" in lowered:
        return "pocketbase"
    if "sandbox" in lowered:
        return "sandbox"
    return (name or "process").split(os.sep)[-1][:32] or "process"


def _scan_psutil(psutil: Any) -> tuple[list[ProcessMemory], bool]:
    """Walk the supervisor's tree with psutil (the cross-platform path)."""
    root_pid = _supervisor_pid(psutil.pid_exists)
    partial = root_pid is None
    try:
        root = psutil.Process(root_pid if root_pid is not None else os.getpid())
        candidates = [root, *root.children(recursive=True)]
    except psutil.Error:
        return [], True

    found: list[ProcessMemory] = []
    for proc in candidates:
        try:
            with proc.oneshot():
                rss = int(proc.memory_info().rss)
                name = proc.name() or ""
                try:
                    cmdline = " ".join(proc.cmdline()[:3])
                except (psutil.AccessDenied, psutil.Error):
                    cmdline = ""
            found.append(
                ProcessMemory(
                    pid=proc.pid,
                    label=_classify(proc.pid, name, cmdline, root_pid),
                    rss_bytes=rss,
                )
            )
        except psutil.Error:
            # The tree is live; a child exiting mid-walk is expected, not an error.
            continue
    if not any(p.pid == os.getpid() for p in found):
        # We were not under the anchor after all (stale env var, re-parented
        # process). Reporting a tree that excludes the backend would be wrong.
        return _scan_psutil_self(psutil)
    return found, partial


def _scan_psutil_self(psutil: Any) -> tuple[list[ProcessMemory], bool]:
    try:
        proc = psutil.Process()
        return [
            ProcessMemory(pid=proc.pid, label="backend", rss_bytes=int(proc.memory_info().rss))
        ], True
    except psutil.Error:
        return [], True


def _proc_entry(pid: int) -> tuple[int, str, str] | None:
    """Read ``(ppid, comm, cmdline_head)`` for one pid from /proc."""
    try:
        stat = Path(f"/proc/{pid}/stat").read_text(encoding="utf-8", errors="replace")
    except OSError:
        return None
    # comm is parenthesised and may itself contain spaces/parens, so split on
    # the LAST ')' rather than tokenising the whole line.
    open_paren = stat.find("(")
    close_paren = stat.rfind(")")
    if open_paren < 0 or close_paren < open_paren:
        return None
    comm = stat[open_paren + 1 : close_paren]
    rest = stat[close_paren + 2 :].split()
    if len(rest) < 2:
        return None
    try:
        ppid = int(rest[1])
    except ValueError:
        return None
    try:
        cmdline = (
            Path(f"/proc/{pid}/cmdline")
            .read_bytes()
            .replace(b"\0", b" ")
            .decode("utf-8", errors="replace")
        )
    except OSError:
        cmdline = ""
    return ppid, comm, cmdline[:200]


def _proc_rss(pid: int) -> int | None:
    try:
        fields = Path(f"/proc/{pid}/statm").read_text(encoding="utf-8").split()
    except OSError:
        return None
    if len(fields) < 2:
        return None
    try:
        return int(fields[1]) * os.sysconf("SC_PAGE_SIZE")
    except (ValueError, OSError):
        return None


def _scan_proc() -> tuple[list[ProcessMemory], bool]:
    """psutil-free fallback for Linux — the platform DeepTutor ships in Docker on."""
    children: dict[int, list[int]] = {}
    meta: dict[int, tuple[str, str]] = {}
    for entry in Path("/proc").iterdir():
        if not entry.name.isdigit():
            continue
        parsed = _proc_entry(int(entry.name))
        if parsed is None:
            continue
        ppid, comm, cmdline = parsed
        children.setdefault(ppid, []).append(int(entry.name))
        meta[int(entry.name)] = (comm, cmdline)

    root_pid = _supervisor_pid(lambda pid: pid in meta)
    partial = root_pid is None
    if root_pid is None:
        root_pid = os.getpid()

    found: list[ProcessMemory] = []
    seen: set[int] = set()
    queue = [root_pid]
    while queue:
        pid = queue.pop()
        if pid in seen:
            continue
        seen.add(pid)
        rss = _proc_rss(pid)
        if rss is not None:
            comm, cmdline = meta.get(pid, ("", ""))
            found.append(
                ProcessMemory(pid=pid, label=_classify(pid, comm, cmdline, root_pid), rss_bytes=rss)
            )
        queue.extend(children.get(pid, ()))
    return found, partial


def _meminfo_kb(key: str) -> int | None:
    try:
        for line in Path("/proc/meminfo").read_text(encoding="utf-8").splitlines():
            if line.startswith(key):
                return int(line.split()[1]) * 1024
    except (OSError, ValueError, IndexError):
        return None
    return None


def _cgroup_limit() -> tuple[int, int] | None:
    """Return ``(limit_bytes, current_bytes)`` when a container cap is in force."""
    limit = _read_int(_CGROUP_V2_MAX)
    current = _read_int(_CGROUP_V2_CURRENT)
    if limit is None:
        v1_limit = _read_int(_CGROUP_V1_LIMIT)
        if v1_limit is not None and v1_limit < _CGROUP_V1_UNLIMITED:
            limit = v1_limit
            current = _read_int(_CGROUP_V1_USAGE)
    if limit is None or limit <= 0 or limit >= _CGROUP_V1_UNLIMITED:
        return None
    return limit, current if current is not None else 0


def _host_memory(psutil: Any | None) -> tuple[int | None, int | None]:
    if psutil is not None:
        try:
            vm = psutil.virtual_memory()
            return int(vm.total), int(vm.available)
        except Exception:  # noqa: BLE001 - psutil raises platform-specific errors
            pass
    if sys.platform.startswith("linux"):
        return _meminfo_kb("MemTotal:"), _meminfo_kb("MemAvailable:")
    return None, None


def capture() -> MemorySnapshot:
    """Snapshot the tree's resident memory and the ceiling it runs against."""
    psutil = _load_psutil()
    if psutil is not None:
        processes, partial = _scan_psutil(psutil)
    elif sys.platform.startswith("linux"):
        processes, partial = _scan_proc()
    else:
        processes, partial = [], True

    processes.sort(key=lambda p: p.rss_bytes, reverse=True)
    total = sum(p.rss_bytes for p in processes)

    cgroup = _cgroup_limit()
    host_total, host_available = _host_memory(psutil)
    if cgroup is not None and (host_total is None or cgroup[0] < host_total):
        limit, current = cgroup
        return MemorySnapshot(
            processes=tuple(processes),
            total_rss_bytes=total,
            limit_bytes=limit,
            available_bytes=max(limit - current, 0),
            limit_source="cgroup",
            partial=partial,
        )
    return MemorySnapshot(
        processes=tuple(processes),
        total_rss_bytes=total,
        limit_bytes=host_total,
        available_bytes=host_available,
        limit_source="host" if host_total is not None else "unknown",
        partial=partial,
    )


__all__ = [
    "MAX_REPORTED_PROCESSES",
    "SUPERVISOR_PID_ENV",
    "MemorySnapshot",
    "ProcessMemory",
    "capture",
]
