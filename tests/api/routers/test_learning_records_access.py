"""Regression tests for the account-scoped learning-records read API.

``GET /api/mastery-paths/reading/records`` (the merged #1109/#1130 surface)
is read-only and account-scoped. Nothing here may ever leak across
accounts, the activity tail must stay bounded to the most recent entries,
and the auth/workspace guards must answer bad input with 4xx instead of
crashing or falling back to another workspace.

These tests drive the real router through ``require_learning_surface`` (the
same dependency stack ``main.py`` mounts) with ``AUTH_ENABLED=true`` so the
request → ``require_auth`` → user ContextVar → ``LearningStore`` chain is
exercised end to end, mirroring how the web client calls the endpoint.
"""

from __future__ import annotations

from pathlib import Path
import types

from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
import pytest

from deeptutor.services.auth import TokenPayload

#: Bearer token → (username, user_id). Unknown tokens must decode to None so
#: ``require_auth`` answers 401 instead of raising or admitting the request.
_TOKENS: dict[str, tuple[str, str]] = {
    "token-alice": ("alice", "u_alice"),
    "token-bob": ("bob", "u_bob"),
}

RECORDS_URL = "/api/mastery-paths/reading/records"


def _token_for(user_id: str) -> str:
    for token, (_, owner) in _TOKENS.items():
        if owner == user_id:
            return token
    raise KeyError(user_id)  # pragma: no cover - test-local lookup


@pytest.fixture
def records_client(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    """The mastery-path router behind the production auth dependency stack.

    Isolates every persisted root under ``tmp_path`` the same way
    ``tests/api/test_book_permission_api.py`` does, then mounts
    ``mastery_path.router`` with ``require_learning_surface`` — the exact
    dependencies ``main.py`` puts in front of ``/api/mastery-paths``.
    """
    from deeptutor.api.routers import auth as auth_router
    from deeptutor.api.routers import mastery_path
    from deeptutor.api.routers.auth import require_learning_surface
    from deeptutor.multi_user import grants, identity
    from deeptutor.multi_user import paths as mu_paths

    admin_root = (tmp_path / "data").resolve()
    system_root = admin_root / "system"

    monkeypatch.setattr(auth_router, "AUTH_ENABLED", True)

    def _decode(token: str) -> TokenPayload | None:
        pair = _TOKENS.get(token)
        if pair is None:
            return None
        username, user_id = pair
        return TokenPayload(username=username, role="user", user_id=user_id)

    monkeypatch.setattr(auth_router, "decode_token", _decode)

    monkeypatch.setattr(mu_paths, "USERS_ROOT", admin_root / "users")
    monkeypatch.setattr(mu_paths, "_path_services", {})
    monkeypatch.setattr(identity, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(identity, "SYSTEM_ROOT", system_root)
    monkeypatch.setattr(identity, "AUTH_DIR", system_root / "auth")
    monkeypatch.setattr(identity, "USERS_FILE", system_root / "auth" / "users.json")
    monkeypatch.setattr(identity, "LEGACY_USERS_FILE", tmp_path / "missing-users.json")
    monkeypatch.setattr(identity, "LEGACY_SECRET_FILE", tmp_path / "missing-secret")
    monkeypatch.setattr(grants, "GRANTS_DIR", system_root / "grants")

    app = FastAPI()
    app.include_router(
        mastery_path.router,
        prefix="/api/mastery-paths",
        dependencies=[Depends(require_learning_surface)],
    )
    with TestClient(app) as client:
        yield client


def _acting_user(user_id: str) -> TokenPayload:
    username = next(name for name, owner in _TOKENS.values() if owner == user_id)
    return TokenPayload(username=username, role="user", user_id=user_id)


@pytest.fixture
def deterministic_clock(monkeypatch: pytest.MonkeyPatch) -> None:
    """Give ``LearningStore`` a strictly increasing clock.

    Activity ordering is ``created_at DESC``; wall-clock ties would make the
    tie-break (random activity ids) non-deterministic, so the boundary test
    pins a monotonic fake clock on the storage module only.
    """
    import deeptutor.learning.storage as storage_module

    state = {"now": 1_000_000.0}

    def _fake_time() -> float:
        state["now"] += 1.0
        return state["now"]

    monkeypatch.setattr(storage_module, "time", types.SimpleNamespace(time=_fake_time))


def test_records_stay_within_each_account(records_client: TestClient) -> None:
    """Cross-account invisibility: alice and bob each only ever see their own
    progress rows and activity tail, physically stored in separate databases."""
    from deeptutor.api.routers.auth import _install_current_user
    from deeptutor.learning.storage import LearningStore
    from deeptutor.multi_user.context import reset_current_user

    def seed(user_id: str, material_id: str, *, locator: int, percentage: float) -> Path:
        token = _install_current_user(_acting_user(user_id))
        try:
            store = LearningStore()
            store.record_reading_position(material_id, locator=locator, percentage=percentage)
            store.record_reading_activity(
                material_id,
                extension_id="sample-ext",
                action="open",
                locator=1,
                result_type="card",
            )
            return store.db_path
        finally:
            reset_current_user(token)

    alice_db = seed("u_alice", "rm_alice_book", locator=7, percentage=0.7)
    bob_db = seed("u_bob", "rm_bob_book", locator=3, percentage=0.3)

    assert alice_db != bob_db, "accounts must not share one learning database"

    seen = {}
    for user_id in ("u_alice", "u_bob"):
        response = records_client.get(
            RECORDS_URL, headers={"Authorization": f"Bearer {_token_for(user_id)}"}
        )
        assert response.status_code == 200
        seen[user_id] = response.json()

    alice_body, bob_body = seen["u_alice"], seen["u_bob"]

    assert [row["material_id"] for row in alice_body["progress"]] == ["rm_alice_book"]
    assert alice_body["progress"][0]["furthest_locator"] == 7
    assert {row["material_id"] for row in alice_body["activities"]} == {"rm_alice_book"}
    assert "rm_bob_book" not in str(alice_body)

    assert [row["material_id"] for row in bob_body["progress"]] == ["rm_bob_book"]
    assert bob_body["progress"][0]["furthest_locator"] == 3
    assert {row["material_id"] for row in bob_body["activities"]} == {"rm_bob_book"}
    assert "rm_alice_book" not in str(bob_body)


def test_records_activity_tail_is_bounded_and_most_recent_first(
    records_client: TestClient, deterministic_clock: None
) -> None:
    """Pagination boundary: the endpoint hands out the 200 most recent
    activities (not the whole table), newest first, while progress stays
    uncapped and nothing from another account ever appears."""
    from deeptutor.api.routers.auth import _install_current_user
    from deeptutor.learning.storage import LearningStore
    from deeptutor.multi_user.context import reset_current_user

    total = 205  # five entries beyond the API's default activity_limit=200

    token = _install_current_user(_acting_user("u_alice"))
    try:
        store = LearningStore()
        for index in range(1, 4):
            store.record_reading_position(
                f"rm_material_{index}", locator=index, percentage=index / 10
            )
        seeded_ids = [
            store.record_reading_activity(
                "rm_material_1",
                extension_id="sample-ext",
                action="open",
                locator=index + 1,
                result_type="card",
            ).activity_id
            for index in range(total)
        ]
    finally:
        reset_current_user(token)

    bob_token = _install_current_user(_acting_user("u_bob"))
    try:
        LearningStore().record_reading_activity(
            "rm_bob_book",
            extension_id="sample-ext",
            action="open",
            locator=1,
            result_type="card",
        )
    finally:
        reset_current_user(bob_token)

    response = records_client.get(RECORDS_URL, headers={"Authorization": "Bearer token-alice"})
    assert response.status_code == 200
    body = response.json()

    activities = body["activities"]
    assert len(activities) == 200, "the read API must cap the activity tail at 200"
    assert [row["activity_id"] for row in activities] == list(reversed(seeded_ids[-200:])), (
        "the tail must be the 200 most recent activities, newest first"
    )
    created = [row["created_at"] for row in activities]
    assert created == sorted(created, reverse=True), "activities must arrive newest first"

    # Progress is a per-material summary, not part of the paginated tail.
    assert len(body["progress"]) == 3
    assert {row["material_id"] for row in body["progress"]} == {
        "rm_material_1",
        "rm_material_2",
        "rm_material_3",
    }

    bob_ids = {
        row["activity_id"]
        for row in records_client.get(
            RECORDS_URL, headers={"Authorization": "Bearer token-bob"}
        ).json()["activities"]
    }
    assert bob_ids.isdisjoint(seeded_ids)


def test_records_for_fresh_account_are_empty(records_client: TestClient) -> None:
    """Empty branch: an account with no reading history gets a 200 with empty
    collections — never an error and never another account's data."""
    response = records_client.get(RECORDS_URL, headers={"Authorization": "Bearer token-bob"})
    assert response.status_code == 200
    assert response.json() == {"progress": [], "activities": []}


def test_records_reject_missing_and_invalid_tokens(records_client: TestClient) -> None:
    """401 branches: no bearer token and an unrecognisable token must both be
    rejected before any store is opened."""
    missing = records_client.get(RECORDS_URL)
    assert missing.status_code == 401
    assert missing.headers["WWW-Authenticate"] == "Bearer"

    invalid = records_client.get(RECORDS_URL, headers={"Authorization": "Bearer not-a-real-token"})
    assert invalid.status_code == 401
    assert invalid.headers["WWW-Authenticate"] == "Bearer"


def test_records_reject_wrong_method_and_conflicting_workspace(
    records_client: TestClient,
) -> None:
    """Invalid input 4xx branches on the records route: the read-only endpoint
    refuses writes with 405, and a request that claims two different
    workspace scopes is refused with 400 instead of silently picking one."""
    posted = records_client.post(RECORDS_URL, json={"material_id": "rm_alice_book", "locator": 9})
    assert posted.status_code == 405

    conflicted = records_client.get(
        RECORDS_URL,
        headers={
            "Authorization": "Bearer token-alice",
            "x-deeptutor-workspace": "ws-one",
        },
        params={"dt_workspace": "ws-two"},
    )
    assert conflicted.status_code == 400
    assert "Conflicting workspace scopes" in conflicted.json()["detail"]
