"""Partner-only memory + history tools.

Covers the split-memory model: ``partner_memorize`` writes ONLY the partner's
own memory (never the owner's), ``partner_read`` folds the owner's shared L3 on
top of the partner's own, and ``partner_search`` greps the partner's sessions.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from deeptutor.multi_user.paths import get_admin_path_service, user_context
from deeptutor.partners.config.paths import get_partner_sessions_dir, get_partner_workspace
from deeptutor.services.partners.scope import partner_user
from deeptutor.services.partners.sessions import PartnerSessionStore
from deeptutor.tools.partner_memory import (
    PartnerMemorizeTool,
    PartnerReadTool,
    PartnerSearchTool,
)

PID = "alice"


def _run(coro):
    return asyncio.run(coro)


@pytest.fixture(autouse=True)
def _fresh_memory_singleton(monkeypatch):
    """Each test gets a fresh MemoryStore so its write locks don't leak."""
    from deeptutor.services.memory import store

    monkeypatch.setattr(store, "_singleton", None)


def _write_owner_preference(text: str) -> None:
    """Seed the owner's (admin) L3 preferences directly on disk."""
    admin_mem = get_admin_path_service().get_memory_dir()
    pref = admin_mem / "L3" / "preferences.md"
    pref.parent.mkdir(parents=True, exist_ok=True)
    pref.write_text(f"# Preferences\n\n## Preferences\n- {text}\n", encoding="utf-8")


def test_memorize_writes_own_not_owner(partners_root: Path) -> None:
    with user_context(partner_user(PID, name="Alice")):
        result = _run(PartnerMemorizeTool().execute(op="add", text="prefers terse answers"))
    assert result.success, result.content

    own_pref = get_partner_workspace(PID) / "memory" / "L3" / "preferences.md"
    assert own_pref.exists()
    assert "prefers terse answers" in own_pref.read_text(encoding="utf-8")

    # The owner's memory must be untouched.
    admin_pref = get_admin_path_service().get_memory_dir() / "L3" / "preferences.md"
    assert not admin_pref.exists()


def test_read_concats_owner_and_own(partners_root: Path) -> None:
    _write_owner_preference("owner wants formal tone")
    with user_context(partner_user(PID, name="Alice")):
        _run(PartnerMemorizeTool().execute(op="add", text="alice likes calculus examples"))
        result = _run(PartnerReadTool().execute())

    assert "Shared memory" in result.content
    assert "Your own memory" in result.content
    assert "owner wants formal tone" in result.content
    assert "alice likes calculus examples" in result.content
    assert result.metadata["has_shared"] is True
    assert result.metadata["has_own"] is True


def test_read_labels_empty_layers(partners_root: Path) -> None:
    with user_context(partner_user(PID, name="Alice")):
        result = _run(PartnerReadTool().execute())
    assert "(none yet" in result.content
    assert result.metadata["has_shared"] is False
    assert result.metadata["has_own"] is False


def test_read_own_does_not_leak_into_owner(partners_root: Path) -> None:
    """A partner's own note must not appear under the shared (owner) section."""
    with user_context(partner_user(PID, name="Alice")):
        _run(PartnerMemorizeTool().execute(op="add", text="secret partner note"))
        result = _run(PartnerReadTool().execute())
    shared_part, _, own_part = result.content.partition("## Your own memory")
    assert "secret partner note" not in shared_part
    assert "secret partner note" in own_part


def test_search_matches_history(partners_root: Path) -> None:
    store = PartnerSessionStore(get_partner_sessions_dir(PID))
    store.append("s1", "user", "Can you explain calculus limits to me?")
    store.append("s1", "assistant", "Sure — a limit describes the value a function approaches.")
    store.append("s2", "user", "Let's talk about linear algebra instead.")

    with user_context(partner_user(PID, name="Alice")):
        result = _run(PartnerSearchTool().execute(query="calculus"))

    assert result.success
    assert result.metadata["count"] == 1
    assert "calculus limits" in result.content


def test_search_skips_tool_messages(partners_root: Path) -> None:
    store = PartnerSessionStore(get_partner_sessions_dir(PID))
    store.append("s1", "tool", "calculus tool payload noise")
    store.append("s1", "user", "real question about calculus")

    with user_context(partner_user(PID, name="Alice")):
        result = _run(PartnerSearchTool().execute(query="calculus"))
    assert result.metadata["count"] == 1
    assert "real question" in result.content


def test_search_no_match(partners_root: Path) -> None:
    store = PartnerSessionStore(get_partner_sessions_dir(PID))
    store.append("s1", "user", "hello there")

    with user_context(partner_user(PID, name="Alice")):
        result = _run(PartnerSearchTool().execute(query="nonexistent-term"))
    assert result.metadata["count"] == 0
    assert "No past messages matched" in result.content


def test_search_requires_partner_scope(partners_root: Path) -> None:
    # No partner user_context → the admin/local scope is active.
    result = _run(PartnerSearchTool().execute(query="anything"))
    assert not result.success
    assert "only available inside a partner" in result.content


def test_memorize_rejects_bad_op(partners_root: Path) -> None:
    with user_context(partner_user(PID, name="Alice")):
        result = _run(PartnerMemorizeTool().execute(op="delete", text="x"))
    assert not result.success
    assert "op must be" in result.content
