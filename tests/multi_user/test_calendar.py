"""HTTP calendar authentication, account isolation and workspace projections."""

from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
import pytest

from deeptutor.api.routers import auth, calendar, task_board
from deeptutor.services.auth import TokenPayload
from deeptutor.services.workspace import get_content_workspace_service
from deeptutor.services.workspace.activity import WorkspaceActivityMiddleware


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
    with TestClient(app) as c:
        yield c


def h(user="alice"):
    return {"Authorization": f"Bearer {user}"}


def event(**extra):
    return {
        "title": "Private",
        "start": "2026-10-17T01:00:00Z",
        "end": "2026-10-17T02:00:00Z",
        **extra,
    }


def test_requires_auth_and_isolates_accounts(client):
    assert client.get("/api/calendar/calendars").status_code == 401
    created = client.post("/api/calendar/events", headers=h(), json=event())
    assert created.status_code == 201, created.text
    id = created.json()["event"]["id"]
    assert (
        client.get("/api/calendar/search", params={"q": "Private"}, headers=h("bob")).json()[
            "events"
        ]
        == []
    )
    assert (
        client.patch(
            f"/api/calendar/events/{id}", headers=h("bob"), json={"changes": {"title": "No"}}
        ).status_code
        == 404
    )
    assert client.delete(f"/api/calendar/events/{id}", headers=h("bob")).status_code == 404


def test_events_account_wide_but_task_links_workspace_scoped(client, as_user):
    with as_user("alice"):
        first = get_content_workspace_service().create_workspace("One")["workspace_id"]
        second = get_content_workspace_service().create_workspace("Two")["workspace_id"]
    card = client.post(
        "/api/task-board/cards", headers=h(), params={"dt_workspace": first}, json={"title": "Task"}
    ).json()["cards"][0]
    assert (
        client.post(
            "/api/calendar/events",
            headers=h(),
            params={"dt_workspace": second},
            json=event(task_id=card["id"], task_workspace_id=first),
        ).status_code
        == 404
    )
    response = client.post(
        "/api/calendar/events",
        headers=h(),
        params={"dt_workspace": first},
        json=event(task_id=card["id"]),
    )
    assert response.status_code == 201, response.text
    assert (
        len(
            client.get(
                "/api/calendar/events",
                headers=h(),
                params={
                    "dt_workspace": second,
                    "start": "2026-10-17T00:00:00Z",
                    "end": "2026-10-18T00:00:00Z",
                },
            ).json()["occurrences"]
        )
        == 1
    )


def test_layer_reads_empty_workspace(client):
    response = client.get(
        "/api/calendar/layers",
        headers=h(),
        params={
            "start": "2026-10-17T00:00:00Z",
            "end": "2026-10-18T00:00:00Z",
            "tz": "Asia/Shanghai",
        },
    )
    assert response.status_code == 200, response.text
    assert response.json() == {
        "workspace_id": "",
        "reviews": [],
        "automations": [],
        "footprints": [],
    }


@pytest.mark.parametrize(
    "params",
    [
        {"tz": "Not/AZone"},
        {"start": "yesterday"},
        {"end": "2026-01-01T00:00:00Z"},
        {"end": "2030-01-01T00:00:00Z"},
    ],
)
def test_bad_ranges_rejected(client, params):
    response = client.get(
        "/api/calendar/events",
        headers=h(),
        params={"start": "2026-10-17T00:00:00Z", "end": "2026-10-18T00:00:00Z", **params},
    )
    assert response.status_code == 400


def test_forecast_and_footprints_do_not_leak_between_workspaces(client, as_user):
    import sqlite3

    from deeptutor.services.calendar.recurrence import parse_instant
    from deeptutor.services.session import get_sqlite_session_store
    from deeptutor.services.workspace.context import workspace_context

    stamp = parse_instant("2026-10-16T17:00:00Z").timestamp()
    with as_user("alice"):
        first = get_content_workspace_service().create_workspace("Learning")["workspace_id"]
        second = get_content_workspace_service().create_workspace("Private")["workspace_id"]
        with workspace_context(first):
            store = get_sqlite_session_store()
            with sqlite3.connect(store.db_path) as db:
                db.execute(
                    "INSERT INTO sessions(id,title,created_at,updated_at) VALUES(?,?,?,?)",
                    ("s", "Calculus", stamp, stamp),
                )
                db.execute(
                    "INSERT INTO messages(session_id,role,content,created_at) VALUES(?,?,?,?)",
                    ("s", "user", "Study", stamp),
                )
                db.execute(
                    "INSERT INTO notebook_entries(origin_ref,question_id,question,created_at,updated_at,is_correct) VALUES('import','q','Question',?,?,0)",
                    (stamp - 86400, stamp - 86400),
                )
    params = {"start": "2026-10-16T16:00:00Z", "end": "2026-10-17T16:00:00Z", "tz": "Asia/Shanghai"}
    data = client.get(
        "/api/calendar/layers", headers=h(), params={**params, "dt_workspace": first}
    ).json()
    assert data["reviews"][0]["date"] == "2026-10-17"
    assert data["reviews"][0]["practice"] == 1
    assert data["footprints"][0]["sessions"] == [{"id": "s", "title": "Calculus"}]
    other = client.get(
        "/api/calendar/layers", headers=h(), params={**params, "dt_workspace": second}
    ).json()
    assert other["reviews"] == other["footprints"] == []


def test_automation_projection_and_cancellation_enforce_owner_and_workspace(
    client, as_user, monkeypatch
):
    from datetime import datetime, timedelta, timezone

    from deeptutor.services.calendar.recurrence import parse_instant
    from deeptutor.services.cron import service as cron

    due = datetime.now(timezone.utc) + timedelta(hours=2)
    with as_user("alice"):
        first = get_content_workspace_service().create_workspace("First")["workspace_id"]
        second = get_content_workspace_service().create_workspace("Second")["workspace_id"]
        service = cron.get_cron_service()
        job = service.add_job(
            name="Review",
            message="Study",
            schedule=cron.CronSchedule(kind="at", at_ms=int(due.timestamp() * 1000)),
            owner=cron.CronOwner(kind="chat", user_id="alice", workspace_id=first),
        )
    monkeypatch.setattr(cron, "get_cron_service", lambda: service)
    params = {
        "start": (due - timedelta(hours=1)).isoformat(),
        "end": (due + timedelta(hours=1)).isoformat(),
        "dt_workspace": first,
    }
    data = client.get("/api/calendar/layers", headers=h(), params=params).json()
    assert [r["job_id"] for r in data["automations"]] == [job.id]
    url = f"/api/calendar/automations/{job.id}"
    assert client.delete(url, headers=h("bob")).status_code == 404
    assert client.delete(url, headers=h(), params={"dt_workspace": second}).status_code == 404
    assert client.delete(url, headers=h(), params={"dt_workspace": first}).json() == {"ok": True}


def test_calendar_learning_policy_gate(client, monkeypatch):
    from deeptutor.multi_user.grants import learner_grant, save_grant
    from deeptutor.multi_user.identity import save_user

    save_user("admin", "placeholder", role="admin")
    learner = save_user("alice", "placeholder", preset="learner")
    monkeypatch.setattr(
        auth,
        "decode_token",
        lambda token: TokenPayload(username="alice", role="user", user_id=learner["id"]),
    )
    grant = learner_grant(learner["id"])
    save_grant(learner["id"], grant)
    assert client.get("/api/calendar/calendars", headers=h()).status_code == 200
    grant["learning_policy"]["allowed_surfaces"] = ["reading"]
    save_grant(learner["id"], grant)
    assert client.get("/api/calendar/calendars", headers=h()).status_code == 403
