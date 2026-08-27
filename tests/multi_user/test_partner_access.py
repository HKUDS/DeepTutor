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

    def owner_id(self, partner_id: str) -> str:
        for partner in self._partners:
            if partner.get("partner_id") == partner_id:
                return str(partner.get("owner_id") or "")
        return ""


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


# ── ownership ─────────────────────────────────────────────────


def test_owner_may_manage_and_use_their_own_partner(as_user, monkeypatch):
    _patch_manager(monkeypatch, [{"partner_id": "p1", "name": "P1", "owner_id": "u_alice"}])
    monkeypatch.setattr(partner_access, "load_grant", lambda uid: empty_grant(uid))
    with as_user("u_alice", role="user"):
        assert partner_access.can_manage_partner("p1")
        assert partner_access.can_use_partner("p1")
        partner_access.assert_partner_manageable("p1")  # no raise
        partner_access.assert_partner_allowed("p1")  # no raise


def test_a_partner_someone_else_owns_is_not_manageable(as_user, monkeypatch):
    _patch_manager(monkeypatch, [{"partner_id": "p1", "name": "P1", "owner_id": "u_bob"}])
    monkeypatch.setattr(partner_access, "load_grant", lambda uid: empty_grant(uid))
    with as_user("u_alice", role="user"):
        assert not partner_access.can_manage_partner("p1")
        with pytest.raises(HTTPException) as exc:
            partner_access.assert_partner_manageable("p1")
        assert exc.value.status_code == 403


def test_assigned_partner_is_usable_but_not_manageable(as_user, monkeypatch):
    _patch_manager(monkeypatch, [{"partner_id": "p1", "name": "P1", "owner_id": "u_bob"}])
    monkeypatch.setattr(
        partner_access, "load_grant", lambda uid: {"partners": [{"partner_id": "p1"}]}
    )
    with as_user("u_alice", role="user"):
        assert partner_access.can_use_partner("p1")
        assert not partner_access.can_manage_partner("p1")


def test_ownerless_partners_stay_admin_managed(as_user, monkeypatch):
    # Partners that predate ownership carry no owner_id; nobody inherits them
    # just by having an empty id themselves.
    _patch_manager(monkeypatch, [{"partner_id": "legacy", "name": "Legacy", "owner_id": ""}])
    monkeypatch.setattr(partner_access, "load_grant", lambda uid: empty_grant(uid))
    with as_user("", role="user"):
        assert not partner_access.can_manage_partner("legacy")
    with as_user("u_admin", role="admin"):
        assert partner_access.can_manage_partner("legacy")


def test_visible_partners_projects_by_what_the_caller_may_do(as_user, monkeypatch):
    _patch_manager(
        monkeypatch,
        [
            {"partner_id": "mine", "name": "Mine", "owner_id": "u_alice", "channels": ["qq"]},
            {"partner_id": "lent", "name": "Lent", "owner_id": "u_bob", "channels": ["telegram"]},
            {"partner_id": "hidden", "name": "Hidden", "owner_id": "u_bob"},
        ],
    )
    monkeypatch.setattr(
        partner_access, "load_grant", lambda uid: {"partners": [{"partner_id": "lent"}]}
    )
    with as_user("u_alice", role="user"):
        visible = {p["partner_id"]: p for p in partner_access.visible_partners()}

    assert set(visible) == {"mine", "lent"}
    # Their own partner comes through whole, with its wiring and a manage flag.
    assert visible["mine"]["can_manage"] is True
    assert visible["mine"]["channels"] == ["qq"]
    # A partner merely lent to them is reduced to a face.
    assert visible["lent"]["can_manage"] is False
    assert "channels" not in visible["lent"]


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
