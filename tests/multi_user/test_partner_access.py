"""Partner assignment / visibility for non-admin users."""

from __future__ import annotations

from fastapi import HTTPException
import pytest

from deeptutor.multi_user import partner_access
from deeptutor.multi_user.grants import empty_grant, normalize_grant


class _FakeManager:
    def __init__(self, partners: list[dict]) -> None:
        self._partners = partners

    def list_partners(self) -> list[dict]:
        return self._partners


def _patch_manager(monkeypatch, partners: list[dict]) -> None:
    import deeptutor.services.partners as pkg

    monkeypatch.setattr(pkg, "get_partner_manager", lambda: _FakeManager(partners))


# ── Grant shape ───────────────────────────────────────────────


def test_empty_grant_has_partners_list():
    assert empty_grant("u")["partners"] == []


def test_normalize_grant_round_trips_partners():
    grant = normalize_grant(
        "u_alice",
        {"partners": [{"partner_id": "p1"}, {"id": "p2"}, "not-a-dict", {}]},
    )
    # Non-dict entries are dropped; dict entries (even empty) survive.
    assert grant["partners"] == [{"partner_id": "p1"}, {"id": "p2"}, {}]


def test_normalize_grant_missing_partners_defaults_empty():
    assert normalize_grant("u_alice", {"skills": []})["partners"] == []


# ── assigned_partner_ids ──────────────────────────────────────


def test_assigned_partner_ids_reads_grant(as_user, monkeypatch):
    monkeypatch.setattr(
        partner_access,
        "load_grant",
        lambda uid: {"partners": [{"partner_id": "p1"}, {"id": "p2"}, {"partner_id": "  "}]},
    )
    with as_user("u_alice", role="user"):
        assert partner_access.assigned_partner_ids() == {"p1", "p2"}


# ── assert_partner_allowed ────────────────────────────────────


def test_admin_may_use_any_partner(as_user, monkeypatch):
    # Admin short-circuits before any grant lookup.
    monkeypatch.setattr(
        partner_access,
        "load_grant",
        lambda uid: (_ for _ in ()).throw(AssertionError("admin must not read grants")),
    )
    with as_user("u_admin", role="admin"):
        partner_access.assert_partner_allowed("anything")  # no raise


def test_non_admin_allowed_only_for_assigned(as_user, monkeypatch):
    monkeypatch.setattr(
        partner_access, "load_grant", lambda uid: {"partners": [{"partner_id": "p1"}]}
    )
    with as_user("u_alice", role="user"):
        partner_access.assert_partner_allowed("p1")  # assigned → ok
        with pytest.raises(HTTPException) as exc:
            partner_access.assert_partner_allowed("p2")
        assert exc.value.status_code == 403


# ── visible_partner_cards ─────────────────────────────────────


def test_admin_sees_all_partners_identity_only(as_user, monkeypatch):
    _patch_manager(
        monkeypatch,
        [
            {"partner_id": "p1", "name": "P1", "emoji": "🤖", "channels": ["telegram"]},
            {"partner_id": "p2", "name": "P2", "channels": [], "llm_selection": {"x": "y"}},
        ],
    )
    with as_user("u_admin", role="admin"):
        cards = partner_access.visible_partner_cards()
    assert {c["partner_id"] for c in cards} == {"p1", "p2"}
    # Identity only — channel wiring / model selection must not leak to a card.
    assert all("channels" not in c and "llm_selection" not in c for c in cards)


def test_non_admin_sees_only_assigned_partners(as_user, monkeypatch):
    _patch_manager(
        monkeypatch,
        [{"partner_id": "p1", "name": "P1"}, {"partner_id": "p2", "name": "P2"}],
    )
    monkeypatch.setattr(
        partner_access, "load_grant", lambda uid: {"partners": [{"partner_id": "p2"}]}
    )
    with as_user("u_alice", role="user"):
        cards = partner_access.visible_partner_cards()
    assert [c["partner_id"] for c in cards] == ["p2"]


def test_non_admin_with_no_grant_sees_nothing(as_user, monkeypatch):
    _patch_manager(monkeypatch, [{"partner_id": "p1", "name": "P1"}])
    monkeypatch.setattr(partner_access, "load_grant", lambda uid: empty_grant(uid))
    with as_user("u_alice", role="user"):
        assert partner_access.visible_partner_cards() == []


# ── assignable pool (admin side) ──────────────────────────────


def test_admin_partner_summary_is_identity_only(monkeypatch):
    from deeptutor.multi_user import router

    _patch_manager(
        monkeypatch,
        [
            {
                "partner_id": "p1",
                "name": "Tutor",
                "description": "math",
                "emoji": "🤖",
                "channels": ["telegram"],
                "llm_selection": {"x": "y"},
            }
        ],
    )
    summary = router._admin_partner_summary()
    assert summary == [{"partner_id": "p1", "name": "Tutor", "description": "math", "emoji": "🤖"}]
