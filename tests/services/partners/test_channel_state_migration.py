"""The one-shot rehoming of channel state that used to be shared by all partners."""

from __future__ import annotations

import json

import pytest

from deeptutor.partners.config import paths as partner_paths
from deeptutor.partners.helpers import ensure_dir
from deeptutor.services.partners.channel_state_migration import rehome_shared_channel_state


@pytest.fixture
def partners_root(tmp_path, monkeypatch):
    root = ensure_dir(tmp_path / "partners")
    monkeypatch.setattr(partner_paths, "_base_dir", lambda: root)
    return root


def _legacy_weixin(partners_root, token: str, cursor: str = "cursor-1"):
    legacy = ensure_dir(partners_root / "weixin")
    (legacy / "account.json").write_text(
        json.dumps({"token": token, "get_updates_buf": cursor}), encoding="utf-8"
    )
    return legacy


def _adopted(partners_root, partner_id: str, channel: str = "weixin"):
    return partners_root / partner_id / "channels" / channel / "account.json"


class TestRehomeSharedChannelState:
    def test_sole_partner_on_the_channel_keeps_working(self, partners_root):
        _legacy_weixin(partners_root, "token-a")

        rehome_shared_channel_state({"alice": {"weixin": {"enabled": True}}})

        saved = json.loads(_adopted(partners_root, "alice").read_text())
        assert saved["token"] == "token-a"
        assert saved["get_updates_buf"] == "cursor-1"

    def test_token_match_decides_between_two_partners(self, partners_root):
        """The reported case: a second partner was added, so both are candidates."""
        _legacy_weixin(partners_root, "token-b")

        rehome_shared_channel_state(
            {
                "alice": {"weixin": {"enabled": True, "token": "token-a"}},
                "bob": {"weixin": {"enabled": True, "token": "token-b"}},
            }
        )

        assert _adopted(partners_root, "bob").exists()
        assert not _adopted(partners_root, "alice").exists()

    def test_ambiguous_owner_is_left_alone(self, partners_root):
        """Two candidates and no proof: guessing would repeat the bug."""
        _legacy_weixin(partners_root, "token-unknown")

        rehome_shared_channel_state(
            {
                "alice": {"weixin": {"enabled": True}},
                "bob": {"weixin": {"enabled": True}},
            }
        )

        assert not _adopted(partners_root, "alice").exists()
        assert not _adopted(partners_root, "bob").exists()
        assert (partners_root / "weixin" / "account.json").exists()

    def test_disabled_partners_are_not_candidates(self, partners_root):
        _legacy_weixin(partners_root, "token-a")

        rehome_shared_channel_state(
            {
                "alice": {"weixin": {"enabled": True}},
                "bob": {"weixin": {"enabled": False}},
            }
        )

        assert _adopted(partners_root, "alice").exists()
        assert not _adopted(partners_root, "bob").exists()

    def test_existing_state_is_never_overwritten(self, partners_root):
        _legacy_weixin(partners_root, "token-legacy")
        own = ensure_dir(partners_root / "alice" / "channels" / "weixin") / "account.json"
        own.write_text(json.dumps({"token": "token-own"}), encoding="utf-8")

        rehome_shared_channel_state({"alice": {"weixin": {"enabled": True}}})

        assert json.loads(own.read_text())["token"] == "token-own"

    def test_is_idempotent_and_non_destructive(self, partners_root):
        legacy = _legacy_weixin(partners_root, "token-a")

        rehome_shared_channel_state({"alice": {"weixin": {"enabled": True}}})
        rehome_shared_channel_state({"alice": {"weixin": {"enabled": True}}})

        assert (legacy / "account.json").exists()
        assert json.loads(_adopted(partners_root, "alice").read_text())["token"] == "token-a"

    def test_partner_named_after_a_channel_is_not_treated_as_state(self, partners_root):
        impostor = ensure_dir(partners_root / "weixin")
        (impostor / "config.yaml").write_text("name: weixin\n", encoding="utf-8")

        rehome_shared_channel_state({"alice": {"weixin": {"enabled": True}}})

        assert not _adopted(partners_root, "alice").exists()

    def test_other_channels_rehome_by_their_legacy_dir_name(self, partners_root):
        store = ensure_dir(partners_root / "matrix-store")
        (store / "nio.db").write_text("device-keys", encoding="utf-8")

        rehome_shared_channel_state({"alice": {"matrix": {"enabled": True}}})

        assert (
            partners_root / "alice" / "channels" / "matrix" / "nio.db"
        ).read_text() == "device-keys"
