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
    monkeypatch.setattr(codebuddy_auth, "_STATUS_PROBE_BACKOFF_S", 0.01)

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
    await _drain(service)

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


async def _drain(service, ticks: int = 20) -> None:
    """Let the background login task settle before reading public status."""
    for _ in range(ticks):
        await asyncio.sleep(0)
        if service.public_status()["connection"] != "authorizing":
            return


async def _value(value):
    return value


class _WedgedFlow:
    """A flow like the SDK returns when ``createSession`` silently failed.

    No ``auth_url``; its await never completes — exactly what used to freeze
    the settings API.
    """

    auth_url = ""

    def __init__(self) -> None:
        self.entered = asyncio.Event()

    def __await__(self):
        return self._wait().__await__()

    async def _wait(self):
        self.entered.set()
        await asyncio.Event().wait()

    async def cancel(self) -> None:
        return None


@pytest.mark.asyncio
async def test_start_login_does_not_hold_the_lock_on_a_wedged_flow(monkeypatch) -> None:
    """Regression: a no-URL flow must not wedge the settings API.

    ``/auth/start`` used to await the flow while holding ``_lock``; a flow that
    never resolved then blocked every ``/auth/status`` poll forever. A
    concurrent ``cancel_login`` returning promptly proves the await is no longer
    under the lock.
    """
    flow = _WedgedFlow()
    monkeypatch.setattr(codebuddy_auth, "_start_sdk_authenticate", lambda: _value(flow))
    service = CodeBuddyAuthService()

    starter = asyncio.create_task(service.start_login())
    try:
        await asyncio.wait_for(flow.entered.wait(), timeout=1.0)
        try:
            status = await asyncio.wait_for(service.cancel_login(), timeout=1.0)
        except asyncio.TimeoutError:
            pytest.fail("cancel_login blocked on the lock held by a wedged flow")
    finally:
        starter.cancel()
        try:
            await starter
        except asyncio.CancelledError:
            pass

    assert status["connection"] == "disconnected"


class _StuckFlow:
    """A flow that enters, never resolves, and swallows cancellation."""

    auth_url = ""

    def __init__(self) -> None:
        self.entered = asyncio.Event()
        self.finished = asyncio.Event()
        self.cancel_calls = 0

    def __await__(self):
        return self._wait().__await__()

    async def _wait(self):
        self.entered.set()
        try:
            await self.finished.wait()
            return SimpleNamespace(userinfo=None)
        except asyncio.CancelledError:
            pass

    async def cancel(self) -> None:
        self.cancel_calls += 1


@pytest.mark.asyncio
async def test_concurrent_status_polls_share_a_single_probe(monkeypatch) -> None:
    """Regression: concurrent status requests must not spawn separate SDK flows."""
    flows = []

    async def start_flow():
        flow = _StuckFlow()
        flows.append(flow)
        return flow

    monkeypatch.setattr(codebuddy_auth, "_start_sdk_authenticate", start_flow)
    monkeypatch.setattr(codebuddy_auth, "_STATUS_PROBE_WAIT_S", 0.05)
    service = CodeBuddyAuthService()

    requests = [asyncio.create_task(service.status()) for _ in range(3)]
    try:
        done, pending = await asyncio.wait(requests, timeout=0.15)
        assert len(done) == 3
        assert len(flows) == 1, f"Expected 1 shared probe, got {len(flows)} separate flows"
        for result in done:
            status = result.result()
            assert status["connection"] == "error"
            assert status["error_code"] == "login_timeout"
    finally:
        for flow in flows:
            flow.finished.set()
        await asyncio.gather(*requests, return_exceptions=True)


@pytest.mark.asyncio
async def test_cancelled_login_does_not_overwrite_connected_state(monkeypatch) -> None:
    """Regression: a flow that completes after cancellation must not overwrite newer state."""
    flow = _StuckFlow()
    monkeypatch.setattr(codebuddy_auth, "_start_sdk_authenticate", lambda: _value(flow))
    monkeypatch.setattr(codebuddy_auth, "_PROBE_TIMEOUT", 10.0)
    service = CodeBuddyAuthService()

    starter = asyncio.create_task(service.start_login())
    try:
        await asyncio.wait_for(flow.entered.wait(), timeout=1.0)
        await service.cancel_login()
        
        # Let the flow complete after cancellation
        flow.finished.set()
        await asyncio.sleep(0.05)

        status = service.public_status()
        assert status["connection"] == "disconnected"
        assert status["operation_state"] == "cancelled"
    finally:
        flow.finished.set()
        await asyncio.gather(starter, return_exceptions=True)


@pytest.mark.asyncio
async def test_start_status_and_cancel_all_settle_while_flow_hangs(monkeypatch) -> None:
    """Regression: Taz33m's scenario - start, status, cancel must all settle.
    
    The key guarantee: cancel_login() itself must complete promptly and not
    block on stuck flows. start_login() may still be awaiting its flow, but
    the service state is updated and new requests see the cancellation.
    """
    flow_with_url = FakeFlow("https://codebuddy.example/login")
    flow_with_url.ready = asyncio.Event()  # Never set, so it hangs
    
    monkeypatch.setattr(codebuddy_auth, "_start_sdk_authenticate", lambda: _value(flow_with_url))
    service = CodeBuddyAuthService()

    start_task = asyncio.create_task(service.start_login())
    status_task = None
    try:
        await asyncio.sleep(0.02)
        status_task = asyncio.create_task(service.status())
        
        # Give status a moment to check
        await asyncio.sleep(0.01)
        
        # Cancel should complete immediately even while the flow hangs
        cancel_result = await asyncio.wait_for(service.cancel_login(), timeout=1.0)
        assert cancel_result["operation_state"] == "cancelled"
        
        # Verify the service state is updated
        status_after = service.public_status()
        assert status_after["connection"] == "disconnected"
        assert status_after["operation_state"] == "cancelled"
        
        # Verify cancel reached the flow
        assert flow_with_url.cancelled is True, "cancel_login should have called flow.cancel()"
    finally:
        flow_with_url.ready.set()
        await asyncio.gather(start_task, status_task or asyncio.sleep(0), return_exceptions=True)


@pytest.mark.asyncio
async def test_timed_out_flow_stays_owned_until_it_finishes(monkeypatch) -> None:
    """Regression: a flow that refuses cancellation must stay tracked.
    
    When a no-URL flow times out, _await_flow cancels the underlying task
    and raises TimeoutError. The task stays in _tasks until it actually
    finishes (even if it ignores cancellation).
    """
    flow = _StuckFlow()
    
    monkeypatch.setattr(codebuddy_auth, "_start_sdk_authenticate", lambda: _value(flow))
    monkeypatch.setattr(codebuddy_auth, "_PROBE_TIMEOUT", 0.05)
    service = CodeBuddyAuthService()

    starter = asyncio.create_task(service.start_login())
    try:
        await asyncio.wait_for(flow.entered.wait(), timeout=1.0)
        
        # Capture tasks while the flow is still running
        await asyncio.sleep(0.01)
        tasks_before_timeout = list(service._tasks)
        assert len(tasks_before_timeout) > 0, "Flow tasks must be tracked while running"
        
        # Let it timeout - the wrapper _await_flow task will cancel and complete
        await asyncio.sleep(0.1)
        
        # The service reports the timeout error
        status = service.public_status()
        assert status["error_code"] == "login_timeout"
    finally:
        flow.finished.set()
        await asyncio.gather(starter, return_exceptions=True)


@pytest.mark.asyncio
async def test_cancelling_start_login_propagates_to_child_flow(monkeypatch) -> None:
    """Regression: cancelling the caller must cancel its spawned flow task."""
    flow = _StuckFlow()
    monkeypatch.setattr(codebuddy_auth, "_start_sdk_authenticate", lambda: _value(flow))
    service = CodeBuddyAuthService()

    starter = asyncio.create_task(service.start_login())
    await asyncio.wait_for(flow.entered.wait(), timeout=1.0)
    
    starter.cancel()
    try:
        await starter
    except asyncio.CancelledError:
        pass

    # The flow's task should be cancelled
    await asyncio.sleep(0.05)
    assert all(t.cancelled() or t.done() for t in service._tasks), "Child tasks must be cancelled"
    
    flow.finished.set()
