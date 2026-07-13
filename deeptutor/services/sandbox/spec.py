"""
Sandbox value types: isolation levels, exec requests, and exec results.

Kept dependency-free so both the backends and the skill/exec layers can
import them without pulling in the backend implementations.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class IsolationLevel(str, Enum):
    """How strongly a backend isolates an execution from the host.

    Mirrors nanobot's WorkspaceSandboxStatus vocabulary. The policy gate
    keys off this: shell exec is offered to ordinary users only at
    ``SYSTEM`` (OS-enforced) isolation; ``APPLICATION`` (path checks only)
    is admin-opt-in; ``OFF`` never runs untrusted code.
    """

    SYSTEM = "system"  # OS-enforced (container / bubblewrap namespaces)
    APPLICATION = "application"  # in-process guards only (path + deny rules)
    OFF = "off"  # no sandbox available

    def rank(self) -> int:
        return {"off": 0, "application": 1, "system": 2}[self.value]


@dataclass(frozen=True)
class ResourceLimits:
    """Per-execution resource ceilings. Enforcement is best-effort per backend."""

    timeout_s: int = 30
    memory_mb: int = 512
    max_output_chars: int = 10_000
    cpu_seconds: int = 30


@dataclass(frozen=True)
class Mount:
    """A directory exposed inside the sandbox."""

    host_path: str
    sandbox_path: str
    read_only: bool = True


@dataclass(frozen=True)
class ExecRequest:
    """A shell command to run inside the sandbox."""

    command: str
    workdir: str = ""
    mounts: tuple[Mount, ...] = ()
    env: dict[str, str] = field(default_factory=dict)
    limits: ResourceLimits = field(default_factory=ResourceLimits)


@dataclass(frozen=True)
class ExecResult:
    """Outcome of a sandboxed execution."""

    stdout: str = ""
    stderr: str = ""
    exit_code: int = 0
    timed_out: bool = False
    error: str = ""  # set when the sandbox itself failed (not the command)

    @property
    def ok(self) -> bool:
        return not self.error and not self.timed_out

    def render(self, max_chars: int) -> str:
        """Combine streams into a single model-facing string (head+tail capped)."""
        if self.error:
            return f"Error: {self.error}"
        parts: list[str] = []
        if self.stdout.strip():
            parts.append(self.stdout)
        if self.stderr.strip():
            parts.append(f"STDERR:\n{self.stderr}")
        if self.timed_out:
            parts.append("\n(command timed out)")
        parts.append(f"\nExit code: {self.exit_code}")
        text = "\n".join(parts) if parts else "(no output)"
        if len(text) > max_chars:
            half = max_chars // 2
            text = (
                text[:half]
                + f"\n\n... ({len(text) - max_chars:,} chars truncated) ...\n\n"
                + text[-half:]
            )
        return text


__all__ = [
    "ExecRequest",
    "ExecResult",
    "IsolationLevel",
    "Mount",
    "ResourceLimits",
]
