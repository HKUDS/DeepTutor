"""Tests for the browser-OAuth loopback login helper (skill login)."""

from __future__ import annotations

import threading
import time
import urllib.error
import urllib.parse
import urllib.request

from deeptutor_cli.skill_login import (
    hub_origin_from_base,
    oauth_start_url,
    run_login,
)


def test_hub_origin_from_base() -> None:
    assert (
        hub_origin_from_base("https://eduhub.deeptutor.info/api/v1")
        == "https://eduhub.deeptutor.info"
    )
    assert hub_origin_from_base("https://x.test/api/") == "https://x.test"
    assert hub_origin_from_base("https://x.test") == "https://x.test"


def test_oauth_start_url_carries_port_and_state() -> None:
    url = oauth_start_url("https://h/", "github", port=5173, state="nonce")
    assert url.startswith("https://h/api/auth/oauth/github?")
    q = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
    assert q["cli_port"] == ["5173"]
    assert q["cli_state"] == ["nonce"]


def _await_url(box: dict[str, str], key: str = "url", tries: int = 200) -> str:
    for _ in range(tries):
        if key in box:
            return box[key]
        time.sleep(0.02)
    raise AssertionError("run_login never produced an authorize URL")


def test_run_login_captures_token_and_rejects_bad_state() -> None:
    seen: dict[str, str] = {}
    result: dict[str, object] = {}

    def worker() -> None:
        result["r"] = run_login(
            "https://hub.test",
            "github",
            on_url=lambda u: seen.update(url=u),
            open_browser=False,
            timeout=10,
        )

    thread = threading.Thread(target=worker)
    thread.start()

    url = _await_url(seen)
    q = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
    port = int(q["cli_port"][0])
    state = q["cli_state"][0]
    base = f"http://127.0.0.1:{port}/callback"

    # Wrong state → rejected (400), login not completed.
    bad = base + "?" + urllib.parse.urlencode({"state": "wrong", "token": "eduhub_x"})
    try:
        urllib.request.urlopen(bad, timeout=5)
        raise AssertionError("expected HTTP 400 for mismatched state")
    except urllib.error.HTTPError as exc:
        assert exc.code == 400
    assert thread.is_alive()  # still waiting for a valid callback

    # Correct state → token captured.
    good = (
        base
        + "?"
        + urllib.parse.urlencode({"state": state, "token": "eduhub_abc", "login": "alice"})
    )
    with urllib.request.urlopen(good, timeout=5) as resp:
        assert resp.status == 200

    thread.join(timeout=10)
    res = result["r"]
    assert res.token == "eduhub_abc"  # type: ignore[union-attr]
    assert res.login == "alice"  # type: ignore[union-attr]
    assert not res.error  # type: ignore[union-attr]


def test_run_login_times_out() -> None:
    res = run_login("https://hub.test", "github", open_browser=False, timeout=0.2)
    assert res.token is None
    assert res.error and "超时" in res.error
