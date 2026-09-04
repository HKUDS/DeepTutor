"""Backend registry — the single place that knows which subagents exist.

Add a new subagent by writing a :class:`SubagentBackend` and listing it here;
the capability, API and UI all discover it through these helpers. Local-CLI
backends (Claude Code, Codex, Antigravity CLI, Kimi CLI, opencode,
MiMo Code, Hermes Agent, OpenClaw, DeepSeek Harness), configured remote
backends, and the in-process partner backend live in the same registry.
``local_cli`` and ``detectable`` control which backends participate in
connection discovery.
"""

from __future__ import annotations

import asyncio

from deeptutor.services.subagent.antigravity import AntigravityBackend
from deeptutor.services.subagent.base import SubagentBackend
from deeptutor.services.subagent.claude_code import ClaudeCodeBackend
from deeptutor.services.subagent.codex import CodexBackend
from deeptutor.services.subagent.deepseek_harness import DeepSeekHarnessBackend
from deeptutor.services.subagent.hermes import HermesBackend
from deeptutor.services.subagent.hermes_remote import HermesRemoteBackend
from deeptutor.services.subagent.kimi import KimiBackend
from deeptutor.services.subagent.openclaw import OpenClawBackend
from deeptutor.services.subagent.opencode_family import MimoBackend, OpencodeBackend
from deeptutor.services.subagent.partner import PartnerBackend
from deeptutor.services.subagent.types import DetectResult

_BACKENDS: dict[str, SubagentBackend] = {
    backend.kind: backend
    for backend in (
        ClaudeCodeBackend(),
        CodexBackend(),
        AntigravityBackend(),
        KimiBackend(),
        OpencodeBackend(),
        MimoBackend(),
        HermesBackend(),
        HermesRemoteBackend(),
        OpenClawBackend(),
        DeepSeekHarnessBackend(),
        PartnerBackend(),
    )
}


def list_backend_kinds() -> list[str]:
    """Return every connectable local, remote, and Partner backend kind."""
    return list(_BACKENDS.keys())


def get_backend(kind: str) -> SubagentBackend | None:
    return _BACKENDS.get(str(kind or "").strip())


def _detectable_backends() -> list[SubagentBackend]:
    return [
        backend
        for backend in _BACKENDS.values()
        if getattr(backend, "local_cli", True) or getattr(backend, "detectable", False)
    ]


async def detect_all() -> list[DetectResult]:
    """Probe local CLIs and configured remote backends."""
    backends = _detectable_backends()
    results = await asyncio.gather(
        *(backend.detect() for backend in backends),
        return_exceptions=True,
    )
    detections: list[DetectResult] = []
    for backend, result in zip(backends, results, strict=True):
        if isinstance(result, DetectResult):
            detections.append(result)
        else:
            detections.append(
                DetectResult(
                    kind=backend.kind,
                    display_name=backend.display_name,
                    available=False,
                    detail=str(result),
                )
            )
    return detections


__all__ = ["list_backend_kinds", "get_backend", "detect_all"]
