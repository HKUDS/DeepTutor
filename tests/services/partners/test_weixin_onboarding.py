"""Web-driven personal-WeChat QR login (#951).

The reporter's problem, in the WeChat case: the channel already knew how to log
in by QR, but drew the code on the server's stdout — a supervisord log on any
container deployment, so nobody configuring a partner could ever scan it.

These cover the two things that decides: reading WeChat's status payload
correctly, and never letting the bot token out of the server.
"""

from __future__ import annotations

from typing import Any

import httpx
import pytest

from deeptutor.partners.channels.weixin_qr import (
    QrCode,
    QrOutcome,
    interpret_status,
    is_retryable_poll_error,
    normalize_host,
)
from deeptutor.services.partners import weixin_onboarding


@pytest.fixture(autouse=True)
def _clean_attempts():
    weixin_onboarding._attempts.clear()
    yield
    weixin_onboarding._attempts.clear()


@pytest.fixture
def stub_partner(monkeypatch) -> dict[str, Any]:
    """A partner whose channel config we can read back after a login."""
    saved: dict[str, Any] = {"channels": {"weixin": {}}}

    class _Config:
        channels = saved["channels"]

    class _Manager:
        def load_config(self, partner_id: str):  # noqa: ARG002
            return _Config()

        def merge_config(self, partner_id: str, overrides):  # noqa: ARG002
            saved["channels"] = overrides["channels"]
            return _Config()

        def save_config(self, partner_id: str, config, **kwargs):  # noqa: ARG002
            saved["written"] = True

    monkeypatch.setattr(
        "deeptutor.services.partners.manager.get_partner_manager", lambda: _Manager()
    )
    return saved


def _stub_exchange(monkeypatch, *, code: str = "qr-1", outcomes: list[QrOutcome] | None = None):
    calls = {"fetched": 0}

    async def _fetch(client, base_url, **kwargs):  # noqa: ARG001
        calls["fetched"] += 1
        # A re-issued code is a different code: distinct payload each time.
        return QrCode(
            qrcode_id=f"{code}-{calls['fetched']}",
            scan_payload=f"scan-{code}-{calls['fetched']}",
        )

    queue = list(outcomes or [])

    async def _poll(client, base_url, qrcode_id, **kwargs):  # noqa: ARG001
        return queue.pop(0) if queue else QrOutcome(status="waiting")

    monkeypatch.setattr(weixin_onboarding, "fetch_qr_code", _fetch)
    monkeypatch.setattr(weixin_onboarding, "poll_qr_code", _poll)
    return calls


# ---- reading WeChat's answers ------------------------------------------------


def test_confirmed_without_a_token_is_a_failure_not_a_success() -> None:
    """Storing an empty token would fail later, far from the cause."""
    assert interpret_status({"status": "confirmed"}).status == "error"


def test_an_unrecognised_status_means_keep_waiting() -> None:
    """A future WeChat status string must not end a login that is still live."""
    assert interpret_status({"status": "something_new"}).status == "unknown"
    assert interpret_status("not a dict").status == "unknown"


def test_redirect_is_a_scan_in_progress_carrying_a_new_host() -> None:
    outcome = interpret_status(
        {"status": "scaned_but_redirect", "redirect_host": "other.weixin.qq.com"}
    )

    assert outcome.status == "scanned"
    assert outcome.poll_base_url == "https://other.weixin.qq.com"


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("host.qq.com", "https://host.qq.com"),
        ("https://host.qq.com", "https://host.qq.com"),
        ("http://host.qq.com", "http://host.qq.com"),
        ("", ""),
    ],
)
def test_redirect_hosts_are_normalised(raw: str, expected: str) -> None:
    assert normalize_host(raw) == expected


def test_only_transient_failures_are_worth_another_poll() -> None:
    assert is_retryable_poll_error(httpx.ConnectTimeout("x")) is True
    assert (
        is_retryable_poll_error(
            httpx.HTTPStatusError(
                "x", request=httpx.Request("GET", "https://x"), response=httpx.Response(503)
            )
        )
        is True
    )
    assert (
        is_retryable_poll_error(
            httpx.HTTPStatusError(
                "x", request=httpx.Request("GET", "https://x"), response=httpx.Response(403)
            )
        )
        is False
    )


# ---- the web-driven attempt --------------------------------------------------


@pytest.mark.asyncio
async def test_start_returns_something_the_browser_can_draw(monkeypatch, stub_partner) -> None:
    _stub_exchange(monkeypatch)

    started = await weixin_onboarding.start_login("p1")

    assert started["scan_payload"] == "scan-qr-1-1"
    assert started["status"] == "waiting"
    assert started["session_id"]


@pytest.mark.asyncio
async def test_a_confirmed_scan_writes_the_token_into_the_channel_config(
    monkeypatch, stub_partner
) -> None:
    _stub_exchange(
        monkeypatch,
        outcomes=[QrOutcome(status="confirmed", token="bot-token", base_url="https://edge")],
    )
    started = await weixin_onboarding.start_login("p1")

    status = await weixin_onboarding.poll_login("p1", started["session_id"])

    assert status["status"] == "confirmed"
    assert stub_partner["channels"]["weixin"]["token"] == "bot-token"
    assert stub_partner["channels"]["weixin"]["base_url"] == "https://edge"
    assert stub_partner["written"] is True


@pytest.mark.asyncio
async def test_the_token_never_appears_in_a_response(monkeypatch, stub_partner) -> None:
    """A status reply says whether it worked, never what it produced."""
    _stub_exchange(monkeypatch, outcomes=[QrOutcome(status="confirmed", token="s3cret")])
    started = await weixin_onboarding.start_login("p1")

    status = await weixin_onboarding.poll_login("p1", started["session_id"])

    assert "s3cret" not in str(started)
    assert "s3cret" not in str(status)
    assert "token" not in status


@pytest.mark.asyncio
async def test_a_redirect_moves_where_the_attempt_polls_next(monkeypatch, stub_partner) -> None:
    _stub_exchange(
        monkeypatch,
        outcomes=[QrOutcome(status="scanned", poll_base_url="https://edge-2")],
    )
    started = await weixin_onboarding.start_login("p1")

    status = await weixin_onboarding.poll_login("p1", started["session_id"])

    assert status["status"] == "scanned"
    assert weixin_onboarding._attempts[started["session_id"]].poll_base_url == "https://edge-2"


@pytest.mark.asyncio
async def test_an_expired_code_is_reissued_so_a_slow_scan_is_not_a_dead_end(
    monkeypatch, stub_partner
) -> None:
    calls = _stub_exchange(monkeypatch, outcomes=[QrOutcome(status="expired")])
    started = await weixin_onboarding.start_login("p1")

    status = await weixin_onboarding.poll_login("p1", started["session_id"])

    assert status["status"] == "waiting"
    assert calls["fetched"] == 2  # the original, plus the replacement


@pytest.mark.asyncio
async def test_repeated_expiry_eventually_ends_the_attempt(monkeypatch, stub_partner) -> None:
    _stub_exchange(monkeypatch, outcomes=[QrOutcome(status="expired")] * 6)
    started = await weixin_onboarding.start_login("p1")

    for _ in range(5):
        status = await weixin_onboarding.poll_login("p1", started["session_id"])

    assert status["status"] == "expired"


@pytest.mark.asyncio
async def test_an_unknown_status_keeps_the_attempt_alive(monkeypatch, stub_partner) -> None:
    _stub_exchange(monkeypatch, outcomes=[QrOutcome(status="unknown")])
    started = await weixin_onboarding.start_login("p1")

    status = await weixin_onboarding.poll_login("p1", started["session_id"])

    assert status["status"] == "waiting"


@pytest.mark.asyncio
async def test_confirmed_without_token_is_reported_as_an_error(monkeypatch, stub_partner) -> None:
    _stub_exchange(monkeypatch, outcomes=[QrOutcome(status="error")])
    started = await weixin_onboarding.start_login("p1")

    status = await weixin_onboarding.poll_login("p1", started["session_id"])

    assert status["status"] == "error"
    assert status["error"]
    assert "token" not in stub_partner["channels"]["weixin"]


@pytest.mark.asyncio
async def test_a_transient_poll_failure_is_not_a_verdict(monkeypatch, stub_partner) -> None:
    _stub_exchange(monkeypatch)
    started = await weixin_onboarding.start_login("p1")

    async def _boom(*args, **kwargs):
        raise httpx.ConnectTimeout("network blip")

    monkeypatch.setattr(weixin_onboarding, "poll_qr_code", _boom)
    status = await weixin_onboarding.poll_login("p1", started["session_id"])

    assert status["status"] == "waiting"


@pytest.mark.asyncio
async def test_a_session_belonging_to_another_partner_is_not_readable(
    monkeypatch, stub_partner
) -> None:
    _stub_exchange(monkeypatch)
    started = await weixin_onboarding.start_login("p1")

    status = await weixin_onboarding.poll_login("p2", started["session_id"])

    assert status["status"] == "expired"


@pytest.mark.asyncio
async def test_a_settled_attempt_stops_re_running_the_exchange(monkeypatch, stub_partner) -> None:
    _stub_exchange(monkeypatch, outcomes=[QrOutcome(status="confirmed", token="t")])
    started = await weixin_onboarding.start_login("p1")
    await weixin_onboarding.poll_login("p1", started["session_id"])

    async def _boom(*args, **kwargs):
        raise AssertionError("a confirmed attempt must not poll again")

    monkeypatch.setattr(weixin_onboarding, "poll_qr_code", _boom)
    status = await weixin_onboarding.poll_login("p1", started["session_id"])

    assert status["status"] == "confirmed"


@pytest.mark.asyncio
async def test_start_renders_the_code_server_side(monkeypatch, stub_partner) -> None:
    """The web bundle carries no QR library, so the SVG is drawn here."""
    _stub_exchange(monkeypatch)

    started = await weixin_onboarding.start_login("p1")

    assert started["qr_svg"].lstrip().startswith("<?xml")
    assert "<svg" in started["qr_svg"]


@pytest.mark.asyncio
async def test_a_reissued_code_ships_a_fresh_image_to_redraw(monkeypatch, stub_partner) -> None:
    """Expiry silently swaps the code; polling is the browser's only notice."""
    _stub_exchange(monkeypatch, outcomes=[QrOutcome(status="expired")])
    started = await weixin_onboarding.start_login("p1")

    status = await weixin_onboarding.poll_login("p1", started["session_id"])

    assert status["status"] == "waiting"
    assert "<svg" in status["qr_svg"]


@pytest.mark.asyncio
async def test_an_unchanged_code_does_not_resend_the_image(monkeypatch, stub_partner) -> None:
    _stub_exchange(monkeypatch, outcomes=[QrOutcome(status="waiting")])
    started = await weixin_onboarding.start_login("p1")

    status = await weixin_onboarding.poll_login("p1", started["session_id"])

    assert "qr_svg" not in status


def test_a_deployment_without_the_qrcode_library_still_gets_a_page(monkeypatch) -> None:
    """`qrcode` rides on the partners extra; missing it must degrade, not fail."""
    import builtins

    real_import = builtins.__import__

    def _no_qrcode(name, *args, **kwargs):
        if name.startswith("qrcode"):
            raise ImportError("no qrcode here")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _no_qrcode)

    assert weixin_onboarding.render_qr_svg("payload") == ""
