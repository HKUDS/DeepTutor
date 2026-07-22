"""Unit tests for channel-secret handling in the partner manager layer.

These guard the contract that secret-looking fields (token, password, api_key,
…) are NEVER serialised into responses unless the caller explicitly opts into
``include_secrets=True``. A regression here would re-introduce the token-leak
fixed alongside PR #338.
"""

from __future__ import annotations

import pytest

from deeptutor.services.partners.manager import (
    PartnerConfig,
    PartnerInstance,
    mask_channel_secrets,
)

# ---------------------------------------------------------------------------
# mask_channel_secrets
# ---------------------------------------------------------------------------


class TestMaskChannelSecrets:
    def test_masks_top_level_token(self):
        out = mask_channel_secrets({"telegram": {"token": "123:abc"}})
        assert out["telegram"]["token"] == "***"

    def test_masks_nested_password_in_email_section(self):
        out = mask_channel_secrets(
            {
                "email": {
                    "imap_username": "me",
                    "imap_password": "supersecret",
                    "smtp_password": "another",
                }
            }
        )
        assert out["email"]["imap_username"] == "me"
        assert out["email"]["imap_password"] == "***"
        assert out["email"]["smtp_password"] == "***"

    def test_masks_diverse_secret_keys(self):
        out = mask_channel_secrets(
            {
                "slack": {"bot_token": "xoxb-…", "app_token": "xapp-…"},
                "matrix": {"access_token": "syt_…"},
                "feishu": {
                    "app_id": "cli_…",
                    "app_secret": "shh",
                    "encrypt_key": "k",
                    "verification_token": "vt",
                },
                "wecom": {"secret": "s"},
            }
        )
        assert out["slack"]["bot_token"] == "***"
        assert out["slack"]["app_token"] == "***"
        assert out["matrix"]["access_token"] == "***"
        assert out["feishu"]["app_id"] == "cli_…"  # not a secret hint
        assert out["feishu"]["app_secret"] == "***"
        assert out["feishu"]["encrypt_key"] == "***"
        assert out["feishu"]["verification_token"] == "***"
        assert out["wecom"]["secret"] == "***"

    def test_preserves_non_string_values(self):
        out = mask_channel_secrets(
            {"telegram": {"token": "", "enabled": True, "allow_from": ["1", "2"]}}
        )
        # Empty string is left as-is (nothing to hide; helps the UI distinguish
        # "unset" from "redacted").
        assert out["telegram"]["token"] == ""
        assert out["telegram"]["enabled"] is True
        assert out["telegram"]["allow_from"] == ["1", "2"]

    def test_does_not_mutate_input(self):
        original = {"telegram": {"token": "abc"}}
        out = mask_channel_secrets(original)
        assert original["telegram"]["token"] == "abc"
        assert out is not original


# ---------------------------------------------------------------------------
# PartnerInstance.to_dict contract
# ---------------------------------------------------------------------------


def _make_instance() -> PartnerInstance:
    return PartnerInstance(
        partner_id="p",
        config=PartnerConfig(
            name="partner",
            channels={
                "telegram": {
                    "enabled": True,
                    "token": "123:ABC",
                    "send_progress": False,
                },
                # Legacy top-level delivery flags should not be exposed.
                "send_progress": True,
            },
        ),
    )


class TestToDictDefaultsAreSafe:
    def test_default_returns_keys_only(self):
        inst = _make_instance()
        d = inst.to_dict()
        assert set(d["channels"]) == {"telegram"}
        # last_reload_error is always present for the UI to consume
        assert "last_reload_error" in d
        assert d["last_reload_error"] is None

    def test_mask_secrets_returns_full_dict_with_token_masked(self):
        inst = _make_instance()
        d = inst.to_dict(mask_secrets=True)
        assert d["channels"]["telegram"]["enabled"] is True
        assert d["channels"]["telegram"]["token"] == "***"
        assert d["channels"]["telegram"]["send_progress"] is False
        assert "send_progress" not in d["channels"]

    def test_include_secrets_returns_raw_token(self):
        inst = _make_instance()
        d = inst.to_dict(include_secrets=True)
        assert d["channels"]["telegram"]["token"] == "123:ABC"
        assert "send_progress" not in d["channels"]

    def test_include_secrets_takes_precedence_over_mask(self):
        inst = _make_instance()
        d = inst.to_dict(include_secrets=True, mask_secrets=True)
        assert d["channels"]["telegram"]["token"] == "123:ABC"


# ---------------------------------------------------------------------------
# reload_lock + last_reload_error wiring
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_reload_lock_serialises_concurrent_calls(monkeypatch):
    """Two concurrent reload_channels calls must not run their bodies in parallel."""
    import asyncio

    from deeptutor.services.partners.manager import PartnerManager

    mgr = PartnerManager()
    inst = _make_instance()

    class _FakeRunner:
        bus = object()

    inst.runner = _FakeRunner()
    # Mark the instance as running by giving it a not-done sentinel task.
    sentinel = asyncio.create_task(asyncio.sleep(60))
    inst.tasks = [sentinel]
    mgr._partners["p"] = inst

    overlap_count = 0
    max_overlap = 0
    in_flight = 0

    async def fake_teardown(instance, partner_id):
        nonlocal in_flight, overlap_count, max_overlap
        in_flight += 1
        max_overlap = max(max_overlap, in_flight)
        overlap_count += 1
        await asyncio.sleep(0.05)
        in_flight -= 1

    monkeypatch.setattr(mgr, "_teardown_channel_listeners", fake_teardown)
    monkeypatch.setattr(mgr, "_build_channel_manager", lambda config, bus, *, partner_id: None)

    try:
        await asyncio.gather(mgr.reload_channels("p"), mgr.reload_channels("p"))
        assert overlap_count == 2
        assert max_overlap == 1, "reload_channels must be serialised per partner"
    finally:
        sentinel.cancel()
        try:
            await sentinel
        except asyncio.CancelledError:
            pass


@pytest.mark.asyncio
async def test_reload_failure_records_last_reload_error(monkeypatch):
    import asyncio

    from deeptutor.services.partners.manager import PartnerManager

    mgr = PartnerManager()
    inst = _make_instance()

    class _FakeRunner:
        bus = object()

    inst.runner = _FakeRunner()
    sentinel = asyncio.create_task(asyncio.sleep(60))
    inst.tasks = [sentinel]
    mgr._partners["p"] = inst

    async def fake_teardown(instance, partner_id):
        return None

    def boom(*args, **kwargs):
        raise ValueError("invalid telegram token format")

    monkeypatch.setattr(mgr, "_teardown_channel_listeners", fake_teardown)
    monkeypatch.setattr(mgr, "_build_channel_manager", boom)

    try:
        with pytest.raises(ValueError):
            await mgr.reload_channels("p")
        assert inst.last_reload_error is not None
        assert "invalid telegram token format" in inst.last_reload_error
        assert inst.channel_manager is None
    finally:
        sentinel.cancel()
        try:
            await sentinel
        except asyncio.CancelledError:
            pass
