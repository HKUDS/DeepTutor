"""
Sandbox configuration and backend selection.

The active backend is chosen from environment so it tracks the deployment
shape without per-user config:

* ``DEEPTUTOR_SANDBOX_RUNNER_URL`` set ⇒ runner sidecar (Docker deployment);
* else on Linux with a functional ``bwrap`` ⇒ bwrap (bare-metal);
* else, only when ``DEEPTUTOR_SANDBOX_ALLOW_SUBPROCESS=1`` ⇒ restricted
  subprocess (admin-opt-in local dev — APPLICATION isolation only);
* else ⇒ no sandbox (exec disabled).

``exec`` is offered to ordinary users only when the active backend reaches
SYSTEM isolation; APPLICATION isolation is admin-opt-in (see
:mod:`deeptutor.tools.exec_tool`). Per-user quotas live in
:mod:`deeptutor.services.sandbox.quota`.
"""

from __future__ import annotations

from dataclasses import dataclass
import os

from deeptutor.services.sandbox.backends import (
    BwrapBackend,
    RestrictedSubprocessBackend,
    RunnerSidecarBackend,
    SandboxBackend,
)
from deeptutor.services.sandbox.spec import ResourceLimits

RUNNER_URL_ENV = "DEEPTUTOR_SANDBOX_RUNNER_URL"
ALLOW_SUBPROCESS_ENV = "DEEPTUTOR_SANDBOX_ALLOW_SUBPROCESS"

# Per-user execution quotas (see quota.py). Conservative defaults; override
# via the matching env vars.
MAX_CONCURRENT_ENV = "DEEPTUTOR_SANDBOX_MAX_CONCURRENT"
MAX_PER_MINUTE_ENV = "DEEPTUTOR_SANDBOX_MAX_PER_MINUTE"


@dataclass(frozen=True)
class SandboxSettings:
    runner_url: str = ""
    allow_subprocess: bool = False
    default_limits: ResourceLimits = ResourceLimits()
    max_concurrent_per_user: int = 2
    max_runs_per_minute_per_user: int = 20

    @classmethod
    def from_env(cls) -> "SandboxSettings":
        def _int(name: str, default: int) -> int:
            try:
                return int(os.environ.get(name, "") or default)
            except ValueError:
                return default

        return cls(
            runner_url=os.environ.get(RUNNER_URL_ENV, "").strip(),
            allow_subprocess=os.environ.get(ALLOW_SUBPROCESS_ENV, "").strip()
            in {"1", "true", "yes"},
            max_concurrent_per_user=_int(MAX_CONCURRENT_ENV, 2),
            max_runs_per_minute_per_user=_int(MAX_PER_MINUTE_ENV, 20),
        )


def build_backend(settings: SandboxSettings) -> SandboxBackend | None:
    """Pick the backend implied by *settings*; ``None`` when none is usable.

    Note: returns the candidate by configuration shape. Liveness (e.g. can
    bwrap actually create namespaces here) is confirmed lazily via the
    backend's ``health()`` — see :mod:`deeptutor.services.sandbox.service`.
    """
    import sys

    if settings.runner_url:
        return RunnerSidecarBackend(settings.runner_url)
    if sys.platform.startswith("linux"):
        import shutil

        if shutil.which("bwrap"):
            return BwrapBackend()
    if settings.allow_subprocess:
        return RestrictedSubprocessBackend()
    return None


__all__ = [
    "ALLOW_SUBPROCESS_ENV",
    "RUNNER_URL_ENV",
    "SandboxSettings",
    "build_backend",
]
