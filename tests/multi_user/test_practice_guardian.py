"""Guardian/admin read-only access to a learner's practice data (#1988).

``GET /api/question-notebook/practice/{summary,queue,analytics,questions/{id}}``
accept ``?learner=<id>``: admins keep their access, guardians need the
``view_reports`` permission, and every access lands in the supervisor audit
log. Write actions (check, review, import) never accept a learner scope.
Analytics additionally merges the learner's effective reading minutes.
"""

from __future__ import annotations

import asyncio
import json

from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
import pytest

pytest.importorskip("fastapi")

PREFIX = "/api/question-notebook/practice"


def _auth(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture
def guardian_client(mu_isolated_root, monkeypatch):
    from deeptutor.api.routers import auth as auth_router
    from deeptutor.api.routers import multi_user as multi_user_router
    from deeptutor.api.routers import practice as practice_router
    from deeptutor.api.routers.auth import require_auth
    from deeptutor.multi_user.identity import save_user
    from deeptutor.services.auth import TokenPayload, hash_password

    users = {
        "root": save_user("root", hash_password("root-password"), role="admin"),
        "guardian": save_user("guardian", hash_password("guardian-password")),
        "stranger": save_user("stranger", hash_password("stranger-password")),
        "learner": save_user("learner", hash_password("learner-password"), preset="learner"),
        "other_learner": save_user(
            "other-learner", hash_password("other-password"), preset="learner"
        ),
    }
    tokens = {
        "root-token": TokenPayload(username="root", role="admin", user_id=users["root"]["id"]),
        "guardian-token": TokenPayload(
            username="guardian", role="user", user_id=users["guardian"]["id"]
        ),
        "stranger-token": TokenPayload(
            username="stranger", role="user", user_id=users["stranger"]["id"]
        ),
        "learner-token": TokenPayload(
            username="learner", role="user", user_id=users["learner"]["id"]
        ),
    }
    monkeypatch.setattr(auth_router, "AUTH_ENABLED", True)
    monkeypatch.setattr(auth_router, "decode_token", lambda token: tokens.get(token))
    monkeypatch.setattr(multi_user_router, "POCKETBASE_ENABLED", False)

    app = FastAPI()
    app.include_router(multi_user_router.router, prefix="/api/multi-user")
    app.include_router(practice_router.router, prefix=PREFIX, dependencies=[Depends(require_auth)])
    with TestClient(app) as client:
        created = client.post(
            "/api/multi-user/guardians",
            headers=_auth("root-token"),
            json={
                "guardian_user_id": users["guardian"]["id"],
                "learner_user_id": users["learner"]["id"],
                "permissions": ["view_reports"],
            },
        )
        assert created.status_code == 201
        yield client, users


def _seed_user_data(username: str, user_id: str, question_id: str, reading_seconds: int):
    """Write practice + reading-time rows as the given user."""
    from deeptutor.api.routers.auth import _install_current_user
    from deeptutor.learning.storage import LearningStore
    from deeptutor.multi_user.context import reset_current_user
    from deeptutor.services.auth import TokenPayload
    from deeptutor.services.session import get_sqlite_session_store

    token = _install_current_user(TokenPayload(username=username, role="user", user_id=user_id))
    try:
        store = get_sqlite_session_store()

        async def seed() -> dict:
            await store.ensure_notebook_session("lesson", "Lesson")
            await store.upsert_notebook_entries(
                "lesson",
                [
                    {
                        "question_id": question_id,
                        "question": f"{question_id}: 2 + 2?",
                        "question_type": "single_choice",
                        "options": {"A": "3", "B": "4"},
                        "correct_answer": "B",
                        "user_answer": "A",
                        "is_correct": False,
                        "source": "immersive_reading",
                    }
                ],
            )
            return await store.find_notebook_entry("lesson", question_id)

        entry = asyncio.run(seed())
        learning = LearningStore()
        if reading_seconds:
            learning.record_reading_time(
                "rm_learner_book", active_seconds=reading_seconds, timezone="UTC"
            )
        return entry
    finally:
        reset_current_user(token)


def test_guardian_reads_learner_practice_and_reading_minutes(guardian_client):
    client, users = guardian_client
    entry = _seed_user_data("learner", users["learner"]["id"], "lq1", reading_seconds=120)
    # The guardian's own practice stays separate and must not leak into the view.
    _seed_user_data("guardian", users["guardian"]["id"], "gq1", reading_seconds=0)

    summary = client.get(
        f"{PREFIX}/summary?timezone=UTC&learner={users['learner']['id']}",
        headers=_auth("guardian-token"),
    )
    assert summary.status_code == 200
    assert summary.json()["total"] == 1

    analytics = client.get(
        f"{PREFIX}/analytics?timezone=UTC&days=7&learner={users['learner']['id']}",
        headers=_auth("guardian-token"),
    )
    assert analytics.status_code == 200
    body = analytics.json()
    assert body["totals"]["questions"] == 1
    assert body["totals"]["reading_seconds"] == 120
    assert body["materials"] == [{"material_id": "rm_learner_book", "reading_seconds": 120}]
    assert body["daily"][-1]["reading_seconds"] == 120

    question = client.get(
        f"{PREFIX}/questions/{entry['id']}?learner={users['learner']['id']}",
        headers=_auth("guardian-token"),
    )
    assert question.status_code == 200
    assert question.json()["entry"]["question_id"] == "lq1"

    queue = client.get(
        f"{PREFIX}/queue?timezone=UTC&learner={users['learner']['id']}",
        headers=_auth("guardian-token"),
    )
    assert queue.status_code == 200
    assert isinstance(queue.json(), list)


def test_admin_keeps_read_access_and_is_audited_as_admin(guardian_client, mu_isolated_root):
    client, users = guardian_client
    _seed_user_data("learner", users["learner"]["id"], "lq2", reading_seconds=30)
    response = client.get(
        f"{PREFIX}/analytics?timezone=UTC&days=7&learner={users['learner']['id']}",
        headers=_auth("root-token"),
    )
    assert response.status_code == 200
    assert response.json()["totals"]["reading_seconds"] == 30

    events = _audit_events(mu_isolated_root)
    practice_views = [e for e in events if e.get("action") == "guardian_practice_view"]
    assert practice_views, "guardian practice views must be audited"
    assert any(
        event.get("actor_role") == "admin" and event.get("target_user_id") == users["learner"]["id"]
        for event in practice_views
    )


def _audit_events(root) -> list[dict]:
    from deeptutor.multi_user import audit

    path = audit.SYSTEM_ROOT / "audit" / "usage.jsonl"
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def test_unauthorized_callers_get_403(guardian_client):
    client, users = guardian_client
    learner_id = users["learner"]["id"]
    for token in ("stranger-token", "learner-token"):
        response = client.get(
            f"{PREFIX}/summary?timezone=UTC&learner={learner_id}",
            headers=_auth(token),
        )
        assert response.status_code == 403, token
    unknown = client.get(
        f"{PREFIX}/summary?timezone=UTC&learner=missing-user-id",
        headers=_auth("guardian-token"),
    )
    assert unknown.status_code == 404


def test_write_actions_reject_a_learner_scope(guardian_client):
    client, users = guardian_client
    entry = _seed_user_data("learner", users["learner"]["id"], "lq3", reading_seconds=0)
    learner_id = users["learner"]["id"]
    check = client.post(
        f"{PREFIX}/questions/{entry['id']}/check?learner={learner_id}",
        headers=_auth("guardian-token"),
        json={"answer": "B"},
    )
    review = client.post(
        f"{PREFIX}/questions/{entry['id']}/review?learner={learner_id}",
        headers=_auth("guardian-token"),
        json={
            "request_id": "submission_00000001",
            "version": 0,
            "rating": "again",
            "answer": "A",
        },
    )
    commit = client.post(
        f"{PREFIX}/import/commit?learner={learner_id}",
        headers=_auth("guardian-token"),
        json={"token": "0" * 32},
    )
    assert check.status_code == 403
    assert review.status_code == 403
    assert commit.status_code == 403


def test_guardian_access_is_audited(guardian_client, mu_isolated_root):
    client, users = guardian_client
    _seed_user_data("learner", users["learner"]["id"], "lq4", reading_seconds=0)
    _resp = client.get(
        f"{PREFIX}/summary?timezone=UTC&learner={users['learner']['id']}",
        headers=_auth("guardian-token"),
    )
    assert _resp.status_code == 200
    events = _audit_events(mu_isolated_root)
    practice_views = [e for e in events if e.get("action") == "guardian_practice_view"]
    assert practice_views
    assert any(users["guardian"]["id"] in json.dumps(e) for e in practice_views)
