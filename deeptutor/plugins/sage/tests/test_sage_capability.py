"""
Tests for the SAGE memory companion plugin.

Mocks the ``sage_sdk`` package via ``sys.modules`` so the suite runs
without the real SDK installed and without a live SAGE node. Exercises:

* The plugin loader discovers ``sage`` and the manifest parses cleanly.
* The capability is a strict no-op when ``SAGE_ENABLED`` is unset.
* When enabled, recall is called pre-run for ``deep_solve`` /
  ``deep_research`` and the memory_context is enriched.
* When enabled, ``CAPABILITY_COMPLETE`` triggers a remember() call.
* The status ``run()`` method emits a result without exploding when SAGE
  is unreachable.
"""

from __future__ import annotations

import asyncio
import sys
import types
from unittest.mock import MagicMock, patch

import pytest

from deeptutor.core.context import UnifiedContext
from deeptutor.core.stream import StreamEvent, StreamEventType
from deeptutor.core.stream_bus import StreamBus

# ---------------------------------------------------------------------------
# Fake sage_sdk — installed once, used by every test that needs SAGE enabled.
# ---------------------------------------------------------------------------


class _FakeMemory:
    def __init__(self, content: str, confidence: float = 0.9, domain: str = "deeptutor-pedagogy"):
        self.content = content
        self.confidence_score = confidence
        self.domain_tag = domain
        self.memory_id = "fake-id"


class _FakeListResult:
    def __init__(self, memories):
        self.memories = memories


class _FakeProposeResult:
    def __init__(self, memory_id="m-1", tx_hash="t-1"):
        self.memory_id = memory_id
        self.tx_hash = tx_hash


class _FakeSdkClient:
    """Mimics the surface of ``sage_sdk.SageClient`` we actually call."""

    def __init__(self, *_args, **_kwargs):
        self.proposed: list[dict] = []
        self.listed: list[dict] = []

    def health(self):
        return {"sage": "running"}

    def register_agent(self, **_kwargs):
        return None

    def list_memories(self, *, domain, status="committed", limit=20):
        self.listed.append({"domain": domain, "status": status, "limit": limit})
        return _FakeListResult(
            memories=[
                _FakeMemory(
                    content="Students often confuse dx with delta x in early calculus",
                    domain=domain,
                ),
                _FakeMemory(
                    content="Visual derivations of integrals improve retention",
                    domain=domain,
                ),
            ]
        )

    def propose(self, *, content, memory_type, domain_tag, confidence):
        self.proposed.append(
            {
                "content": content,
                "memory_type": memory_type,
                "domain_tag": domain_tag,
                "confidence": confidence,
            }
        )
        return _FakeProposeResult()


class _FakeAgentIdentity:
    @classmethod
    def from_file(cls, _path):
        return cls()

    @classmethod
    def generate(cls):
        return cls()

    def to_file(self, _path):  # pragma: no cover - exercised indirectly
        return None


@pytest.fixture
def fake_sdk(monkeypatch):
    """Install a fake ``sage_sdk`` package in ``sys.modules``."""
    module = types.ModuleType("sage_sdk")
    module.SageClient = _FakeSdkClient
    module.AgentIdentity = _FakeAgentIdentity
    monkeypatch.setitem(sys.modules, "sage_sdk", module)
    yield module


@pytest.fixture(autouse=True)
def _reset_singleton_and_hooks(monkeypatch):
    """Reset the singleton + hook-installed flag between tests."""
    from deeptutor.plugins.sage import capability as sage_cap
    from deeptutor.plugins.sage.client import SageClient

    SageClient.reset_instance()
    monkeypatch.setattr(sage_cap, "_HOOKS_INSTALLED", False, raising=False)
    yield
    SageClient.reset_instance()
    monkeypatch.setattr(sage_cap, "_HOOKS_INSTALLED", False, raising=False)
    # Best-effort cleanup of EventBus listener.
    try:
        sage_cap.uninstall_hooks()
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Loader / manifest
# ---------------------------------------------------------------------------


def test_loader_discovers_sage_plugin():
    from deeptutor.plugins.loader import discover_plugins

    manifests = {m.name: m for m in discover_plugins()}
    assert "sage" in manifests
    sage = manifests["sage"]
    assert "capability.py" in sage.entry
    assert sage.type == "companion"
    assert "recall" in sage.stages
    assert "remember" in sage.stages


def test_loader_loads_capability_class():
    from deeptutor.plugins.loader import discover_plugins, load_plugin_capability

    sage_manifest = next(m for m in discover_plugins() if m.name == "sage")
    cap = load_plugin_capability(sage_manifest)
    assert cap is not None
    assert cap.manifest.name == "sage_memory"


# ---------------------------------------------------------------------------
# Disabled-by-default behaviour
# ---------------------------------------------------------------------------


def test_disabled_by_default(monkeypatch):
    """Without SAGE_ENABLED the plugin is a strict no-op."""
    monkeypatch.delenv("SAGE_ENABLED", raising=False)

    from deeptutor.plugins.sage.capability import install_hooks
    from deeptutor.plugins.sage.client import get_sage_client

    assert install_hooks() is False
    client = get_sage_client()
    assert client.enabled is False
    # recall + remember return empty / {} without ever touching the SDK.
    assert client.recall("anything", domain="deeptutor-pedagogy") == []
    assert client.remember("anything", domain="deeptutor-pedagogy") == {}


def test_status_run_when_disabled(monkeypatch):
    monkeypatch.delenv("SAGE_ENABLED", raising=False)
    from deeptutor.plugins.sage.capability import SageMemoryCompanion

    cap = SageMemoryCompanion()
    bus = StreamBus()
    ctx = UnifiedContext(user_message="status?")

    async def _run():
        await cap.run(ctx, bus)
        await bus.close()
        return [event async for event in bus.subscribe()]

    events = asyncio.run(_run())
    results = [e for e in events if e.type == StreamEventType.RESULT]
    assert results, "capability should always emit a RESULT event"
    assert results[-1].metadata.get("enabled") is False


# ---------------------------------------------------------------------------
# Enabled behaviour
# ---------------------------------------------------------------------------


def test_recall_called_for_target_capability(monkeypatch, fake_sdk):
    monkeypatch.setenv("SAGE_ENABLED", "true")

    # Simulate a registered ``deep_solve`` capability the registry would
    # have already loaded by the time the plugin __init__ runs.
    from deeptutor.core.capability_protocol import BaseCapability, CapabilityManifest
    from deeptutor.plugins.sage import capability as sage_cap
    from deeptutor.plugins.sage.client import SageClient

    SageClient.reset_instance()

    class FakeDeepSolve(BaseCapability):
        manifest = CapabilityManifest(
            name="deep_solve",
            description="fake",
            stages=["planning", "reasoning"],
        )

        def __init__(self):
            self.seen_memory_context = ""

        async def run(self, context, stream):
            self.seen_memory_context = context.memory_context

    fake_solve = FakeDeepSolve()

    fake_registry = MagicMock()
    fake_registry.get.side_effect = lambda name: fake_solve if name == "deep_solve" else None

    with patch(
        "deeptutor.runtime.registry.capability_registry.get_capability_registry",
        return_value=fake_registry,
    ):
        installed = sage_cap.install_hooks(force=True)
    assert installed is True

    bus = StreamBus()
    ctx = UnifiedContext(
        user_message="how do I integrate sin(x) by parts?",
        knowledge_bases=["calculus-101"],
        metadata={"learner_id": "u-42"},
    )

    asyncio.run(fake_solve.run(ctx, bus))

    # The wrapped run should have appended a SAGE block with recalled
    # memories from at least the pedagogy domain.
    assert "SAGE — Cross-Session Memory" in fake_solve.seen_memory_context
    assert (
        "dx" in fake_solve.seen_memory_context.lower()
        or "integrals" in fake_solve.seen_memory_context.lower()
    )


def test_capability_complete_triggers_remember(monkeypatch, fake_sdk):
    monkeypatch.setenv("SAGE_ENABLED", "true")

    import deeptutor.events.event_bus as eb_mod
    from deeptutor.events.event_bus import Event, EventBus, EventType, get_event_bus
    from deeptutor.plugins.sage import capability as sage_cap
    from deeptutor.plugins.sage.client import SageClient

    # Reset both the class-level and module-level EventBus caches so the
    # listener we install + the bus we publish on are the SAME instance.
    EventBus.reset()
    eb_mod._event_bus = None  # noqa: SLF001 - test reset
    SageClient.reset_instance()

    fake_registry = MagicMock()
    fake_registry.get.return_value = None  # no built-ins to wrap in this test

    with patch(
        "deeptutor.runtime.registry.capability_registry.get_capability_registry",
        return_value=fake_registry,
    ):
        sage_cap.install_hooks(force=True)

    # Force the SDK client to be ours so we can assert calls.
    client = SageClient.get_instance()
    sdk = client._ensure_sdk()
    assert sdk is not None, "SDK should be initialised when SAGE_ENABLED is true"

    async def _exercise():
        bus = get_event_bus()
        await bus.start()
        try:
            await bus.publish(
                Event(
                    type=EventType.CAPABILITY_COMPLETE,
                    task_id="t-1",
                    user_input="walk me through integration by parts",
                    agent_output="ignored",
                    tools_used=["rag", "reason"],
                    metadata={
                        "capability": "deep_solve",
                        "session_id": "s-1",
                        "subject": "calculus",
                        "learner_id": "u-42",
                    },
                )
            )
            # Drain the queue.
            await bus.flush(timeout=5.0)
        finally:
            await bus.stop()
            EventBus.reset()
            eb_mod._event_bus = None  # noqa: SLF001 - test reset

    asyncio.run(_exercise())

    # At least one propose() per domain (pedagogy + subject + tutor-{learner}).
    assert len(sdk.proposed) >= 1
    domains = {entry["domain_tag"] for entry in sdk.proposed}
    assert "deeptutor-pedagogy" in domains
    assert any(d.startswith("deeptutor-tutor-") for d in domains)
    # Content is compact: no agent_output should leak in.
    for entry in sdk.proposed:
        assert "ignored" not in entry["content"]
        assert "deep_solve" in entry["content"]


def test_status_run_when_enabled(monkeypatch, fake_sdk):
    monkeypatch.setenv("SAGE_ENABLED", "true")

    from deeptutor.plugins.sage.capability import SageMemoryCompanion

    cap = SageMemoryCompanion()
    bus = StreamBus()
    ctx = UnifiedContext(user_message="status?")

    async def _run():
        await cap.run(ctx, bus)
        await bus.close()
        return [event async for event in bus.subscribe()]

    events = asyncio.run(_run())
    results = [e for e in events if e.type == StreamEventType.RESULT]
    assert results, "capability should emit RESULT"
    assert results[-1].metadata.get("enabled") is True
