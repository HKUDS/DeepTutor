"""
Root conftest — shared fixtures for the entire test suite.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from deeptutor.core.capability_protocol import BaseCapability, CapabilityManifest
from deeptutor.core.context import Attachment, UnifiedContext
from deeptutor.core.stream_bus import StreamBus

# ---------------------------------------------------------------------------
# Multi-user legacy migration guard
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def _guard_legacy_multi_user_migration(monkeypatch):
    """Tests must never migrate the developer's real ``multi-user/`` tree.

    ``migrate_legacy_multi_user_tree`` runs on the auth/grants/workspace read
    paths, so any test that exercises those without full path isolation would
    otherwise move a real sibling ``multi-user/`` into ``data/``. Point the
    legacy root at a path that cannot exist and reset the once-flag;
    migration tests opt back in by patching the constants themselves.
    """
    from deeptutor.multi_user import paths

    monkeypatch.setattr(
        paths, "LEGACY_MULTI_USER_ROOT", Path("/nonexistent/deeptutor-legacy-multi-user")
    )
    monkeypatch.setattr(paths, "_legacy_migration_done", False)
    yield


# ---------------------------------------------------------------------------
# StreamBus
# ---------------------------------------------------------------------------


@pytest.fixture
def stream_bus() -> StreamBus:
    """Fresh StreamBus for one test."""
    return StreamBus()


# ---------------------------------------------------------------------------
# UnifiedContext
# ---------------------------------------------------------------------------


@pytest.fixture
def minimal_context() -> UnifiedContext:
    """Context with just a user message."""
    return UnifiedContext(
        session_id="test-session",
        user_message="Hello",
        language="en",
    )


@pytest.fixture
def rich_context() -> UnifiedContext:
    """Context with attachments, tools, KB, and metadata."""
    return UnifiedContext(
        session_id="test-session",
        user_message="Explain RAG",
        conversation_history=[
            {"role": "user", "content": "What is AI?"},
            {"role": "assistant", "content": "AI is..."},
        ],
        enabled_tools=["rag", "web_search"],
        active_capability="deep_solve",
        knowledge_bases=["my-kb"],
        attachments=[Attachment(type="image", url="https://img.png")],
        config_overrides={"temperature": 0.7},
        language="en",
        metadata={"turn_id": "t-1"},
    )


# ---------------------------------------------------------------------------
# SQLiteSessionStore (in-memory / tmp)
# ---------------------------------------------------------------------------


@pytest.fixture
def tmp_db_path(tmp_path: Path) -> Path:
    """Temporary database file path."""
    return tmp_path / "test_chat.db"


@pytest.fixture
def sqlite_store(tmp_db_path: Path):
    """SQLiteSessionStore backed by a temp file."""
    from deeptutor.services.session.sqlite_store import SQLiteSessionStore

    return SQLiteSessionStore(db_path=tmp_db_path)


# ---------------------------------------------------------------------------
# Fake / stub capability
# ---------------------------------------------------------------------------


class _StubCapability(BaseCapability):
    """Capability that emits one content event and returns."""

    manifest = CapabilityManifest(
        name="stub",
        description="Stub for testing.",
        stages=["responding"],
    )

    async def run(self, context: UnifiedContext, stream: StreamBus) -> None:
        await stream.content("stub response", source=self.name)


@pytest.fixture
def stub_capability() -> _StubCapability:
    return _StubCapability()


# ---------------------------------------------------------------------------
# Fake LLM helpers
# ---------------------------------------------------------------------------


@pytest.fixture
def fake_llm_config() -> MagicMock:
    """MagicMock mimicking LLMConfig with common defaults."""
    cfg = MagicMock()
    cfg.model = "gpt-4o-mini"
    cfg.max_tokens = 4096
    cfg.temperature = 0.7
    cfg.api_key = "sk-test"
    cfg.api_base = "https://api.openai.com/v1"
    return cfg
