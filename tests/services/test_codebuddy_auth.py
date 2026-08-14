from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from deeptutor.services import codebuddy_auth
from deeptutor.services.codebuddy_auth import CodeBuddyAuthService


class FakeFlow:
    def __init__(self, auth_url: str, result=None) -> None:
        self.auth_url = auth_url
        self.result = result
        self.cancelled = False
        self.ready = asyncio.Event()
        if result is not None:
            self.ready.set()

    def __await__(self):
        return self.wait().__await__()

    async def wait(self):
        await self.ready.wait()
        return self.result

    async def cancel(self) -> None:
        self.cancelled = True


def auth_result(label: str = "Karsa"):
    return SimpleNamespace(
        userinfo=SimpleNamespace(user_nickname=label, user_name="", user_id="user-1")
    )


@pytest.mark.asyncio
async def test_status_reports_existing_local_login(monkeypatch) -> None:
    flow = FakeFlow("", auth_result())
    monkeypatch.setattr(codebuddy_auth, "_start_sdk_authenticate", lambda: _value(flow))

    status = await CodeBuddyAuthService().status()

    assert status == {
        "connection": "connected",
        "operation_state": "completed",
        "authorize_url": None,
        "user_label": "Karsa",
        "error_code": None,
    }


@pytest.mark.asyncio
async def test_status_cancels_probe_when_login_is_required(monkeypatch) -> None:
    flow = FakeFlow("https://codebuddy.example/login")
    monkeypatch.setattr(codebuddy_auth, "_start_sdk_authenticate", lambda: _value(flow))

    status = await CodeBuddyAuthService().status()

    assert status["connection"] == "disconnected"
    assert status["authorize_url"] is None
    assert flow.cancelled is True


@pytest.mark.asyncio
async def test_start_login_exposes_url_then_records_completion(monkeypatch) -> None:
    flow = FakeFlow("https://codebuddy.example/login")
    monkeypatch.setattr(codebuddy_auth, "_start_sdk_authenticate", lambda: _value(flow))
    service = CodeBuddyAuthService()

    started = await service.start_login()

    assert started["connection"] == "authorizing"
    assert started["operation_state"] == "waiting"
    assert started["authorize_url"] == "https://codebuddy.example/login"

    flow.result = auth_result("CodeBuddy User")
    flow.ready.set()
    await asyncio.sleep(0)
    await asyncio.sleep(0)

    completed = service.public_status()
    assert completed["connection"] == "connected"
    assert completed["user_label"] == "CodeBuddy User"
    assert completed["authorize_url"] is None


@pytest.mark.asyncio
async def test_start_login_reports_missing_sdk(monkeypatch) -> None:
    async def missing():
        raise ImportError("codebuddy-agent-sdk is not installed")

    monkeypatch.setattr(codebuddy_auth, "_start_sdk_authenticate", missing)

    status = await CodeBuddyAuthService().start_login()

    assert status["connection"] == "error"
    assert status["error_code"] == "sdk_missing"


@pytest.mark.asyncio
async def test_logout_disconnects_when_no_session_remains(monkeypatch) -> None:
    """With no login on the host there is nothing to report but disconnection."""
    service = CodeBuddyAuthService()
    service._connection = "connected"
    service._operation_state = "completed"
    service._user_label = "Old Account"

    status = await service.logout()

    assert status == {
        "connection": "disconnected",
        "operation_state": None,
        "authorize_url": None,
        "user_label": None,
        "error_code": None,
    }


@pytest.mark.asyncio
async def test_status_accepts_ide_session_without_the_sdk(tmp_path, monkeypatch) -> None:
    _write_ide_session(tmp_path, monkeypatch)

    async def unused_sdk():
        raise AssertionError("the SDK must not be probed when a session file exists")

    monkeypatch.setattr(codebuddy_auth, "_start_sdk_authenticate", unused_sdk)
    monkeypatch.setattr("deeptutor.services.codebuddy_credentials.probe_account", _account_label)

    status = await CodeBuddyAuthService().status()

    assert status["connection"] == "connected"
    assert status["user_label"] == "tester"
    assert status["error_code"] is None


@pytest.mark.asyncio
async def test_logout_explains_that_an_ide_session_ends_in_the_ide(tmp_path, monkeypatch) -> None:
    """DeepTutor never ends a session it does not own.

    The auth file is shared with the IDE plugin and the CLI on this host —
    signing it out from a web endpoint would sign the operator out of their
    editor, and on a shared host out of whoever else is on that login.
    """
    _write_ide_session(tmp_path, monkeypatch)

    status = await CodeBuddyAuthService().logout()

    assert status["connection"] == "connected"
    assert status["error_code"] == "logout_external"


def _write_ide_session(tmp_path, monkeypatch) -> None:
    import json

    path = tmp_path / "Tencent-Cloud.coding-copilot.info"
    path.write_text(
        json.dumps(
            {
                "account": {"uid": "uid-1", "nickname": "tester"},
                "auth": {"accessToken": "access-token", "domain": "www.codebuddy.cn"},
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("DEEPTUTOR_CODEBUDDY_AUTH_FILE", str(path))


async def _account_label(credentials):
    return credentials.user_label


async def _value(value):
    return value
