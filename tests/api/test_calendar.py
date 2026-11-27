"""HTTP calendar export: content type, disposition, filtering and isolation."""

from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
import pytest

from deeptutor.api.routers import auth, calendar, task_board
from deeptutor.services.auth import TokenPayload
from deeptutor.services.workspace.activity import WorkspaceActivityMiddleware
from tests.multi_user.conftest import mu_isolated_root as mu_isolated_root


@pytest.fixture
def client(mu_isolated_root, monkeypatch):
    monkeypatch.setattr(auth, "AUTH_ENABLED", True)
    monkeypatch.setattr(
        auth,
        "decode_token",
        lambda token: (
            TokenPayload(username=token, role="user", user_id=token)
            if token in {"alice", "bob"}
            else None
        ),
    )
    app = FastAPI()
    app.add_middleware(WorkspaceActivityMiddleware)
    for router, prefix in [
        (calendar.router, "/api/calendar"),
        (task_board.router, "/api/task-board"),
    ]:
        app.include_router(
            router, prefix=prefix, dependencies=[Depends(auth.require_learning_surface)]
        )
    with TestClient(app) as item:
        yield item


def h(user="alice"):
    return {"Authorization": f"Bearer {user}"}


def event(**extra):
    return {
        "title": "Private",
        "start": "2026-10-17T01:00:00Z",
        "end": "2026-10-17T02:00:00Z",
        **extra,
    }


def test_export_requires_auth(client):
    assert client.get("/api/calendar/export.ics").status_code == 401


def test_export_content_type_and_disposition(client):
    client.post("/api/calendar/events", headers=h(), json=event(title="Algebra"))
    response = client.get("/api/calendar/export.ics", headers=h())
    assert response.status_code == 200, response.text
    content_type = response.headers["content-type"].lower()
    assert "text/calendar" in content_type
    assert "charset=utf-8" in content_type
    disposition = response.headers["content-disposition"]
    assert disposition.startswith("attachment;")
    assert 'filename="deeptutor.ics"' in disposition
    assert "filename*=UTF-8''" in disposition
    assert response.content.startswith(b"BEGIN:VCALENDAR\r\n")
    assert b"SUMMARY:Algebra" in response.content


def test_export_calendar_id_filter_and_unknown_404(client):
    client.post("/api/calendar/events", headers=h(), json=event(title="Default class"))
    created = client.post(
        "/api/calendar/calendars", headers=h(), json={"name": "School", "color": "#112233"}
    )
    assert created.status_code == 201, created.text
    school_id = created.json()["calendar"]["id"]
    client.post(
        "/api/calendar/events",
        headers=h(),
        json=event(title="School class", calendar_id=school_id),
    )
    school = client.get("/api/calendar/export.ics", headers=h(), params={"calendar_id": school_id})
    assert school.status_code == 200, school.text
    assert b"SUMMARY:School class" in school.content
    assert b"SUMMARY:Default class" not in school.content
    assert "filename=" in school.headers["content-disposition"]
    missing = client.get("/api/calendar/export.ics", headers=h(), params={"calendar_id": "missing"})
    assert missing.status_code == 404


def test_export_does_not_include_another_users_events(client):
    client.post("/api/calendar/events", headers=h(), json=event(title="Alice only"))
    client.post("/api/calendar/events", headers=h("bob"), json=event(title="Bob only"))
    alice = client.get("/api/calendar/export.ics", headers=h())
    bob = client.get("/api/calendar/export.ics", headers=h("bob"))
    assert alice.status_code == bob.status_code == 200
    assert b"SUMMARY:Alice only" in alice.content
    assert b"SUMMARY:Bob only" not in alice.content
    assert b"SUMMARY:Bob only" in bob.content
    assert b"SUMMARY:Alice only" not in bob.content
