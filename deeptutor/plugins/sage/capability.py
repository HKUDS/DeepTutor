"""
SAGE Memory Companion Capability
================================

A small "companion" capability that ships two hooks:

1. **Pre-capability-run** — wraps ``deep_solve`` and ``deep_research`` so
   their ``UnifiedContext.memory_context`` is enriched with cross-session
   pedagogy / subject-domain memories pulled from a SAGE node *before* the
   underlying agent pipeline runs. The existing per-learner SUMMARY.md /
   PROFILE.md is left intact — SAGE is appended, never replaced.

2. **Post-capability-run** — subscribes to the global EventBus and stores
   one observation per ``CAPABILITY_COMPLETE`` event under domain tags
   ``deeptutor-pedagogy``, ``deeptutor-{subject}``, and
   ``deeptutor-tutor-{learner_id}``. The observation captures only the
   user prompt + capability name + tools used — never the full agent
   output, to keep the audit trail compact.

The capability also registers itself in the registry (``BUILTIN_CAPABILITY_CLASSES``
adjacent) so it shows up in ``deeptutor plugin list``. Its own ``run``
method is a thin "status" handler that confirms the integration is live —
it is NOT meant to be invoked from end-user prompts.

Everything is opt-in via ``SAGE_ENABLED=true``. When SAGE is disabled or
unreachable the plugin is a strict no-op: no hooks fire, the host
framework behaves byte-for-byte as before.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
from typing import Any

from deeptutor.core.capability_protocol import BaseCapability, CapabilityManifest
from deeptutor.core.context import UnifiedContext
from deeptutor.core.stream_bus import StreamBus
from deeptutor.events.event_bus import Event, EventType, get_event_bus
from deeptutor.plugins.sage.client import SageClient, get_sage_client

logger = logging.getLogger(__name__)


# Capabilities whose prompts we enrich pre-run. Kept tight on purpose —
# expanding the surface should be a deliberate decision, not a default.
PRE_RUN_TARGETS: tuple[str, ...] = ("deep_solve", "deep_research")


# Module-level guard to ensure we never install hooks twice (e.g. if the
# loader is imported a second time during tests).
_HOOKS_INSTALLED = False


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _truthy(value: str | None) -> bool:
    if not value:
        return False
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _domain_prefix() -> str:
    return os.environ.get("SAGE_DEEPTUTOR_DOMAIN_PREFIX", "deeptutor")


def _slugify(text: str) -> str:
    """Best-effort lower-snake-case slug used for domain tags."""
    if not text:
        return ""
    cleaned = re.sub(r"[^a-zA-Z0-9]+", "-", text.strip().lower())
    return cleaned.strip("-")[:48]


def _infer_subject(context: UnifiedContext) -> str:
    """Infer a subject tag from the unified context — best-effort."""
    meta = context.metadata or {}
    subject = (
        meta.get("subject")
        or meta.get("domain")
        or (context.knowledge_bases[0] if context.knowledge_bases else "")
    )
    return _slugify(str(subject))


def _infer_learner(context: UnifiedContext) -> str:
    meta = context.metadata or {}
    learner = meta.get("learner_id") or meta.get("user_id") or context.session_id or ""
    return _slugify(str(learner))[:32]


def _format_recall_block(memories: list[dict[str, Any]]) -> str:
    """Render recalled SAGE memories into a markdown block.

    The block is appended to ``UnifiedContext.memory_context`` so the host
    capability sees it through the existing prompt-stitching logic. It
    deliberately uses a distinctive header so it never gets confused with
    DeepTutor's own SUMMARY/PROFILE content.
    """
    if not memories:
        return ""
    lines = ["", "### SAGE — Cross-Session Memory (institutional)"]
    for idx, mem in enumerate(memories, start=1):
        content = (mem.get("content") or "").strip()
        if not content:
            continue
        confidence = mem.get("confidence") or 0.0
        domain = mem.get("domain") or ""
        # Keep each memory on a single line — capability prompts already
        # paginate at higher levels and we don't want to blow up token
        # budgets.
        snippet = content.replace("\n", " ")
        if len(snippet) > 320:
            snippet = snippet[:317] + "..."
        lines.append(f"- [{idx}] ({domain}, conf={confidence:.2f}) {snippet}")
    if len(lines) == 2:
        return ""
    return "\n".join(lines)


def _append_memory_context(context: UnifiedContext, block: str) -> None:
    if not block:
        return
    existing = context.memory_context or ""
    if block in existing:
        return
    context.memory_context = (existing + "\n\n" + block).strip() if existing else block


# ---------------------------------------------------------------------------
# Hook installation
# ---------------------------------------------------------------------------


def _wrap_capability_run(capability: BaseCapability) -> None:
    """Decorate ``capability.run`` with a pre-run SAGE recall step."""
    original_run = capability.run

    if getattr(original_run, "__sage_wrapped__", False):
        return

    async def wrapped(context: UnifiedContext, stream: StreamBus) -> None:
        try:
            client = get_sage_client()
            if client.enabled:
                subject = _infer_subject(context)
                domains = [f"{_domain_prefix()}-pedagogy"]
                if subject:
                    domains.append(f"{_domain_prefix()}-{subject}")

                merged: list[dict[str, Any]] = []
                for domain in domains:
                    memories = client.recall(
                        query=context.user_message or capability.name,
                        domain=domain,
                        top_k=3,
                    )
                    merged.extend(memories)

                block = _format_recall_block(merged)
                if block:
                    _append_memory_context(context, block)
                    logger.debug(
                        "SAGE recall injected %d memories into %s (domains=%s)",
                        len(merged),
                        capability.name,
                        domains,
                    )
        except Exception:
            # Recall is strictly best-effort — never let it break a turn.
            logger.debug("SAGE recall hook failed; continuing", exc_info=True)

        await original_run(context, stream)

    wrapped.__sage_wrapped__ = True  # type: ignore[attr-defined]
    capability.run = wrapped  # type: ignore[method-assign]


def _install_pre_run_hooks() -> int:
    """Wrap every PRE_RUN_TARGETS capability already in the registry.

    Called once during ``SageMemoryCompanion.__init__``. Capabilities that
    aren't loaded yet (because of an unusual registration order) are
    silently skipped — they'll either get wrapped on the next registry
    refresh or run unwrapped, which is still correct (just no recall).
    """
    try:
        from deeptutor.runtime.registry.capability_registry import get_capability_registry
    except Exception:
        logger.debug(
            "Capability registry import failed; skipping pre-run hook install", exc_info=True
        )
        return 0

    registry = get_capability_registry()
    wrapped = 0
    for name in PRE_RUN_TARGETS:
        cap = registry.get(name)
        if cap is None:
            continue
        _wrap_capability_run(cap)
        wrapped += 1
    return wrapped


async def _on_capability_complete(event: Event) -> None:
    """EventBus listener — store a SAGE observation after each turn."""
    try:
        client = get_sage_client()
        if not client.enabled:
            return

        meta = event.metadata or {}
        capability = str(meta.get("capability") or "unknown")
        session_id = str(meta.get("session_id") or "")
        subject_meta = meta.get("subject") or meta.get("domain") or ""
        subject = _slugify(str(subject_meta))
        learner = _slugify(str(meta.get("learner_id") or meta.get("user_id") or session_id))[:32]

        prefix = _domain_prefix()
        domains = [f"{prefix}-pedagogy"]
        if subject:
            domains.append(f"{prefix}-{subject}")
        if learner:
            domains.append(f"{prefix}-tutor-{learner}")

        # Compact observation — never include the full agent output, only
        # the user prompt, capability name, and tools used. That keeps the
        # audit trail useful for cross-session pedagogy without leaking
        # entire conversations into consensus storage.
        prompt = (event.user_input or "").strip().replace("\n", " ")
        if len(prompt) > 400:
            prompt = prompt[:397] + "..."
        tools = ", ".join(event.tools_used or []) or "none"
        success = "ok" if event.success else "failed"

        content = (
            f"[deeptutor:{capability}] success={success} tools={tools} prompt={prompt or '(empty)'}"
        )

        for domain in domains:
            client.remember(
                content=content,
                domain=domain,
                memory_type="observation",
                confidence=0.80,
                tags=["deeptutor", capability],
            )
    except Exception:
        logger.debug("SAGE post-run hook failed; continuing", exc_info=True)


def _install_event_listener() -> None:
    bus = get_event_bus()
    bus.subscribe(EventType.CAPABILITY_COMPLETE, _on_capability_complete)


def install_hooks(force: bool = False) -> bool:
    """Install pre/post hooks if SAGE is enabled. Idempotent."""
    global _HOOKS_INSTALLED
    if _HOOKS_INSTALLED and not force:
        return True
    if not _truthy(os.environ.get("SAGE_ENABLED")):
        logger.debug("SAGE_ENABLED is not truthy — leaving hooks uninstalled")
        return False

    try:
        wrapped = _install_pre_run_hooks()
        _install_event_listener()
        _HOOKS_INSTALLED = True
        logger.info(
            "SAGE plugin hooks installed (pre-run wrapped=%d, event=CAPABILITY_COMPLETE)",
            wrapped,
        )
        return True
    except Exception:
        logger.warning("SAGE plugin failed to install hooks", exc_info=True)
        return False


def uninstall_hooks() -> None:
    """Remove the EventBus subscription. Pre-run wrappers stay in place
    (unwrapping safely is messy and not worth the complexity for tests —
    use ``SageClient.reset_instance`` + a fresh registry instead)."""
    global _HOOKS_INSTALLED
    try:
        bus = get_event_bus()
        bus.unsubscribe(EventType.CAPABILITY_COMPLETE, _on_capability_complete)
    except Exception:
        pass
    _HOOKS_INSTALLED = False


# ---------------------------------------------------------------------------
# Capability stub — surfaces in `deeptutor plugin list`.
# ---------------------------------------------------------------------------


class SageMemoryCompanion(BaseCapability):
    """SAGE memory companion — installs recall + remember hooks on import."""

    manifest = CapabilityManifest(
        name="sage_memory",
        description=(
            "External SAGE-backed long-term memory: recalls cross-session "
            "pedagogy + subject memories before deep_solve / deep_research, "
            "and stores observations after every capability run. "
            "Opt-in via SAGE_ENABLED=true; no-op otherwise."
        ),
        stages=["recall", "remember"],
        cli_aliases=["sage"],
        config_defaults={
            "enabled_env": "SAGE_ENABLED",
            "url_env": "SAGE_URL",
            "identity_env": "SAGE_AGENT_KEY",
            "domain_prefix": "deeptutor",
        },
    )

    def __init__(self) -> None:
        # Hooks self-install on first instantiation. Safe to call repeatedly.
        try:
            install_hooks()
        except Exception:
            logger.debug("SAGE hook install raised during __init__", exc_info=True)

    async def run(self, context: UnifiedContext, stream: StreamBus) -> None:
        """Status / health probe — emits the SAGE node status to the stream."""
        client = get_sage_client()
        async with stream.stage("recall", source=self.name):
            await stream.thinking(
                f"SAGE plugin status: enabled={client.enabled}",
                source=self.name,
                stage="recall",
            )

        if not client.enabled:
            await stream.result(
                {
                    "response": (
                        "SAGE companion is **disabled**. Set `SAGE_ENABLED=true` "
                        "and ensure a SAGE node is reachable at `SAGE_URL` to "
                        "activate cross-session memory."
                    ),
                    "enabled": False,
                },
                source=self.name,
            )
            return

        # Run health check off the event loop — sage_sdk is sync.
        healthy = await asyncio.to_thread(client.health_check)
        await stream.result(
            {
                "response": (
                    f"SAGE companion is **enabled** and "
                    f"{'reachable' if healthy else 'configured but currently unreachable'}."
                ),
                "enabled": True,
                "healthy": healthy,
            },
            source=self.name,
        )


# Last-resort safety net: if some entry point bypasses ``__init__``
# (e.g. the manifest API listing), the hooks still install when the module
# is first imported and SAGE is enabled.
try:
    install_hooks()
except Exception:  # pragma: no cover - defensive
    logger.debug("SAGE module-level install_hooks failed", exc_info=True)


__all__ = [
    "PRE_RUN_TARGETS",
    "SageClient",
    "SageMemoryCompanion",
    "install_hooks",
    "uninstall_hooks",
]
