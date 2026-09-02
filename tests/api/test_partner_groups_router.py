from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

try:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
except Exception:  # pragma: no cover
    FastAPI = None
    TestClient = None

from deeptutor.services.partners.manager import PartnerConfig, PartnerManager

pytestmark = pytest.mark.skipif(
    FastAPI is None or TestClient is None, reason="fastapi not installed"
)


@pytest.fixture
def client(tmp_path: Path, monkeypatch) -> TestClient:
    from deeptutor.api.routers import auth as auth_module
    from deeptutor.api.routers import partner_groups as router_module
    from deeptutor.multi_user import paths
    import deeptutor.services.partner_groups.manager as manager_module
    from deeptutor.services.partner_groups.manager import PartnerGroupManager

    admin_root = (tmp_path / "data").resolve()
    monkeypatch.setattr(paths, "PROJECT_ROOT", tmp_path)
    monkeypatch.setattr(paths, "ADMIN_WORKSPACE_ROOT", admin_root)
    monkeypatch.setattr(paths, "USERS_ROOT", admin_root / "users")
    monkeypatch.setattr(paths, "SYSTEM_ROOT", admin_root / "system")
    monkeypatch.setattr(paths, "_path_services", {})
    admin_root.mkdir(parents=True, exist_ok=True)
    from deeptutor.multi_user.context import reset_current_user, set_current_user
    from deeptutor.multi_user.models import CurrentUser, UserScope

    token = set_current_user(
        CurrentUser(
            id="local-admin",
            username="local",
            role="admin",
            scope=UserScope(kind="admin", user_id="local-admin", root=admin_root),
        )
    )

    partners = PartnerManager()
    partners.save_config("ada", PartnerConfig(name="Ada"))
    partners.save_config("bob", PartnerConfig(name="Bob"))
    monkeypatch.setattr(manager_module, "get_partner_manager", lambda: partners)
    groups = PartnerGroupManager()
    monkeypatch.setattr(router_module, "get_partner_group_manager", lambda: groups)
    monkeypatch.setattr(auth_module, "AUTH_ENABLED", False)

    app = FastAPI()
    app.state.partner_groups = groups
    app.state.partners = partners
    app.include_router(router_module.router, prefix="/api/partner-groups")
    app.include_router(router_module.ws_router, prefix="/ws/partner-groups")
    try:
        yield TestClient(app)
    finally:
        reset_current_user(token)


def test_group_crud_and_extension_catalogs(client: TestClient) -> None:
    created = client.post(
        "/api/partner-groups",
        json={
            "name": "Study panel",
            "member_ids": ["ada", "bob"],
            "discussion_mode": "panel_parallel",
            "shared_memory": "whiteboard",
        },
    )
    assert created.status_code == 200
    group_id = created.json()["group_id"]
    assert [member["name"] for member in created.json()["members"]] == ["Ada", "Bob"]

    listed = client.get("/api/partner-groups")
    assert listed.status_code == 200
    assert [group["group_id"] for group in listed.json()] == [group_id]

    patched = client.patch(
        f"/api/partner-groups/{group_id}",
        json={"name": "Renamed panel", "description": "A learning group"},
    )
    assert patched.status_code == 200
    assert patched.json()["name"] == "Renamed panel"

    assert client.get("/api/partner-groups/discussion-modes").json() == [
        {
            "name": "panel_parallel",
            "label": "Parallel panel",
            "description": (
                "Selected Partners answer concurrently from shared public context; "
                "their private intermediate work is not shared."
            ),
        },
        {
            "name": "sequential",
            "label": "Sequential Build",
            "description": (
                "Selected Partners respond in Group member order, each building on messages "
                "already produced this round without repeating them."
            ),
        },
        {
            "name": "debate",
            "label": "Cross Debate",
            "description": (
                "Selected Partners debate in two parallel rounds: clear opening positions, "
                "then substantive clashes informed by every opening statement."
            ),
        },
    ]
    assert client.get("/api/partner-groups/shared-memory-types").json()[0]["name"] == ("whiteboard")

    assert client.delete(f"/api/partner-groups/{group_id}").status_code == 200
    assert client.get(f"/api/partner-groups/{group_id}").status_code == 404


def test_group_requires_two_visible_partners(client: TestClient) -> None:
    response = client.post(
        "/api/partner-groups",
        json={"name": "Too small", "member_ids": ["ada", "missing"]},
    )
    assert response.status_code == 422


def test_unknown_mentions_are_nonfatal_turn_metadata(
    client: TestClient,
    monkeypatch,
) -> None:
    partners = client.app.state.partners
    monkeypatch.setattr(
        partners,
        "get_partner",
        lambda partner_id: SimpleNamespace(running=True, partner_id=partner_id),
    )

    async def send_group_message(partner_id, content, **kwargs):
        _ = (content, kwargs)
        return f"{partner_id} answer"

    monkeypatch.setattr(partners, "send_group_message", send_group_message)
    group_id = client.post(
        "/api/partner-groups",
        json={"name": "Mention panel", "member_ids": ["ada", "bob"]},
    ).json()["group_id"]

    response = client.post(
        f"/api/partner-groups/{group_id}/messages",
        json={
            "content": "@ada @typo compare this",
            "session_key": "mention-session",
            "mentions": ["ada", "typo"],
        },
    )

    assert response.status_code == 200
    assert response.json()["targets"] == ["ada"]
    assert response.json()["unknown_mentions"] == ["@typo"]


def test_session_and_whiteboard_resource_contracts(
    client: TestClient,
    monkeypatch,
) -> None:
    partners = client.app.state.partners
    monkeypatch.setattr(
        partners,
        "get_partner",
        lambda partner_id: SimpleNamespace(running=True, partner_id=partner_id),
    )

    async def send_group_message(partner_id, content, **kwargs):
        _ = (content, kwargs)
        return f"{partner_id} curated answer"

    monkeypatch.setattr(partners, "send_group_message", send_group_message)
    group_id = client.post(
        "/api/partner-groups",
        json={"name": "Resource panel", "member_ids": ["ada", "bob"]},
    ).json()["group_id"]
    turn = client.post(
        f"/api/partner-groups/{group_id}/messages",
        json={"content": "A first server-owned thread", "session_key": "thread-a"},
    ).json()

    sessions = client.get(f"/api/partner-groups/{group_id}/sessions")
    assert sessions.status_code == 200
    assert sessions.json() == [
        {
            "session_key": "thread-a",
            "title": "A first server-owned thread",
            "message_count": 3,
            "updated_at": sessions.json()[0]["updated_at"],
            "created_at": turn["user_message"]["created_at"],
        }
    ]

    created_session = client.post(f"/api/partner-groups/{group_id}/sessions")
    assert created_session.status_code == 201
    assert created_session.json()["session_key"].startswith("pg-")
    assert created_session.json()["message_count"] == 0
    assert created_session.json()["created_at"]
    assert created_session.json()["updated_at"] == created_session.json()["created_at"]

    event_id = turn["replies"][0]["event_id"]
    pinned = client.post(
        f"/api/partner-groups/{group_id}/whiteboard/pins",
        json={"event_id": event_id},
    )
    assert pinned.status_code == 200
    assert pinned.json()["created"] is True
    assert pinned.json()["entry"]["event_id"] == event_id
    assert pinned.json()["entry"]["author_name"] == "Ada"
    assert pinned.json()["entry"]["content"] == "ada curated answer"
    assert pinned.json()["entry"]["pinned_at"]
    assert client.get(f"/api/partner-groups/{group_id}/whiteboard").json() == [
        pinned.json()["entry"]
    ]

    unpinned = client.delete(f"/api/partner-groups/{group_id}/whiteboard/pins/{event_id}")
    assert unpinned.json() == {"deleted": True, "event_id": event_id}
    assert client.get(f"/api/partner-groups/{group_id}/whiteboard").json() == []

    session_key = created_session.json()["session_key"]
    deleted = client.delete(f"/api/partner-groups/{group_id}/sessions/{session_key}")
    assert deleted.json() == {"deleted": True, "session_key": session_key}
    assert (
        client.delete(f"/api/partner-groups/{group_id}/sessions/{session_key}").status_code == 404
    )


def test_user_can_create_and_reject_partner_invocation(client: TestClient) -> None:
    group_id = client.post(
        "/api/partner-groups",
        json={"name": "Invocation panel", "member_ids": ["ada", "bob"]},
    ).json()["group_id"]

    created = client.post(
        f"/api/partner-groups/{group_id}/invocations",
        json={
            "session_key": "user-originated",
            "requester_partner_id": "ada",
            "target_partner_id": "bob",
            "question": "  Challenge Ada's conclusion.  ",
        },
    )

    assert created.status_code == 200
    invocation = created.json()
    assert invocation == {
        "invocation_id": invocation["invocation_id"],
        "group_id": group_id,
        "session_key": "user-originated",
        "parent_turn_id": "",
        "requester_partner_id": "ada",
        "requester_partner_name": "Ada",
        "target_partner_id": "bob",
        "target_partner_name": "Bob",
        "question": "Challenge Ada's conclusion.",
        "status": "pending",
        "created_at": invocation["created_at"],
        "updated_at": invocation["created_at"],
        "question_event_id": "",
        "reply_event_id": "",
        "error": "",
    }
    assert client.get(
        f"/api/partner-groups/{group_id}/invocations",
        params={"session_key": "user-originated"},
    ).json() == [invocation]

    rejected = client.post(
        f"/api/partner-groups/{group_id}/invocations/{invocation['invocation_id']}/reject",
        json={"session_key": "user-originated"},
    )
    assert rejected.status_code == 200
    assert rejected.json()["status"] == "rejected"


@pytest.mark.parametrize(
    "payload",
    [
        {
            "session_key": "invalid",
            "requester_partner_id": "missing",
            "target_partner_id": "bob",
            "question": "Question",
        },
        {
            "session_key": "invalid",
            "requester_partner_id": "ada",
            "target_partner_id": "missing",
            "question": "Question",
        },
        {
            "session_key": "invalid",
            "requester_partner_id": "ada",
            "target_partner_id": "ada",
            "question": "Question",
        },
        {
            "session_key": "invalid",
            "requester_partner_id": "ada",
            "target_partner_id": "bob",
            "question": "   ",
        },
        {
            "session_key": "invalid",
            "requester_partner_id": "ada",
            "target_partner_id": "bob",
            "question": "x" * 2_001,
        },
    ],
)
def test_user_created_invocation_validation_returns_422(
    client: TestClient,
    payload: dict,
) -> None:
    group_id = client.post(
        "/api/partner-groups",
        json={"name": "Validation panel", "member_ids": ["ada", "bob"]},
    ).json()["group_id"]

    response = client.post(
        f"/api/partner-groups/{group_id}/invocations",
        json=payload,
    )

    assert response.status_code == 422


def test_new_group_resources_preserve_owner_isolation(client: TestClient) -> None:
    group_id = client.post(
        "/api/partner-groups",
        json={"name": "Private panel", "member_ids": ["ada", "bob"]},
    ).json()["group_id"]
    config_path = client.app.state.partner_groups.store.group_dir(group_id) / "config.json"
    config = json.loads(config_path.read_text(encoding="utf-8"))
    config["owner_id"] = "another-owner"
    config_path.write_text(json.dumps(config), encoding="utf-8")

    assert client.get(f"/api/partner-groups/{group_id}/sessions").status_code == 404
    assert client.delete(f"/api/partner-groups/{group_id}/sessions/hidden").status_code == 404
    response = client.post(
        f"/api/partner-groups/{group_id}/invocations",
        json={
            "session_key": "hidden",
            "requester_partner_id": "ada",
            "target_partner_id": "bob",
            "question": "Can anyone else see this?",
        },
    )
    assert response.status_code == 404


def test_retry_failed_partner_seat_returns_to_the_original_turn(
    client: TestClient,
    monkeypatch,
) -> None:
    partners = client.app.state.partners
    monkeypatch.setattr(
        partners,
        "get_partner",
        lambda partner_id: SimpleNamespace(running=True, partner_id=partner_id),
    )

    async def first_attempt(partner_id, content, **kwargs):
        _ = (content, kwargs)
        if partner_id == "ada":
            raise RuntimeError("temporary failure")
        return "bob answer"

    monkeypatch.setattr(partners, "send_group_message", first_attempt)
    group_id = client.post(
        "/api/partner-groups",
        json={"name": "Retry panel", "member_ids": ["ada", "bob"]},
    ).json()["group_id"]
    turn = client.post(
        f"/api/partner-groups/{group_id}/messages",
        json={"content": "Compare", "session_key": "retry-thread"},
    ).json()
    failed = next(reply for reply in turn["replies"] if reply["author_id"] == "ada")
    assert failed["error"] is True

    async def recovered(partner_id, content, **kwargs):
        _ = (content, kwargs)
        assert partner_id == "ada"
        return "ada recovered"

    monkeypatch.setattr(partners, "send_group_message", recovered)
    retried = client.post(
        (f"/api/partner-groups/{group_id}/turns/{turn['turn_id']}/partners/ada/retry"),
        json={"session_key": "retry-thread"},
    )
    assert retried.status_code == 200
    assert retried.json()["operation"] == "retry_partner"
    assert retried.json()["turn_id"] == turn["turn_id"]
    assert retried.json()["partner_id"] == "ada"
    assert retried.json()["message"]["event_id"] == failed["event_id"]
    assert retried.json()["message"]["content"] == "ada recovered"
    assert retried.json()["message"]["error"] is False

    history = client.get(
        f"/api/partner-groups/{group_id}/history",
        params={"session_key": "retry-thread"},
    ).json()
    assert len(history) == 3
    assert next(row for row in history if row["author_id"] == "ada")["content"] == ("ada recovered")
    repeated = client.post(
        (f"/api/partner-groups/{group_id}/turns/{turn['turn_id']}/partners/ada/retry"),
        json={"session_key": "retry-thread"},
    )
    assert repeated.status_code == 409


def test_round_summary_rest_contract_and_membership_validation(
    client: TestClient,
    monkeypatch,
) -> None:
    partners = client.app.state.partners
    monkeypatch.setattr(
        partners,
        "get_partner",
        lambda partner_id: SimpleNamespace(running=True, partner_id=partner_id),
    )
    summary_contexts: list[str] = []

    async def send_group_message(partner_id, content, **kwargs):
        if content.startswith("Summarize this completed"):
            summary_contexts.append(kwargs["public_context"])
            assert partner_id == "ada"
            assert kwargs["allow_invoke_other"] is False
            return "Consensus / disagreements / recommendation"
        return f"{partner_id} original answer"

    monkeypatch.setattr(partners, "send_group_message", send_group_message)
    group_id = client.post(
        "/api/partner-groups",
        json={"name": "Summary panel", "member_ids": ["ada", "bob"]},
    ).json()["group_id"]
    turn = client.post(
        f"/api/partner-groups/{group_id}/messages",
        json={"content": "Compare both approaches", "session_key": "rest-summary"},
    ).json()

    response = client.post(
        f"/api/partner-groups/{group_id}/rounds/{turn['turn_id']}/summary",
        json={"session_key": "rest-summary", "partner_id": "ada"},
    )

    assert response.status_code == 200
    result = response.json()
    message = result["message"]
    assert result == {
        "operation": "summarize_round",
        "turn_id": turn["turn_id"],
        "partner_id": "ada",
        "message": message,
    }
    assert message == {
        "event_id": message["event_id"],
        "turn_id": turn["turn_id"],
        "session_key": "rest-summary",
        "role": "partner",
        "content": "Consensus / disagreements / recommendation",
        "author_id": "ada",
        "author_name": "Ada",
        "created_at": message["created_at"],
        "mentions": [],
        "error": False,
        "kind": "round_summary",
        "events": [],
        "invocation_id": "",
        "invocation": None,
    }
    assert "local: Compare both approaches" in summary_contexts[0]
    assert "Ada: ada original answer" in summary_contexts[0]
    assert "Bob: bob original answer" in summary_contexts[0]
    assert (
        client.post(
            f"/api/partner-groups/{group_id}/rounds/{turn['turn_id']}/summary",
            json={"session_key": "rest-summary", "partner_id": "missing"},
        ).status_code
        == 422
    )
    assert (
        client.post(
            f"/api/partner-groups/{group_id}/rounds/missing/summary",
            json={"session_key": "rest-summary", "partner_id": "ada"},
        ).status_code
        == 404
    )


def test_round_summary_websocket_uses_standard_stream_frames(
    client: TestClient,
    monkeypatch,
) -> None:
    from deeptutor.core.stream import StreamEvent, StreamEventType

    partners = client.app.state.partners
    monkeypatch.setattr(
        partners,
        "get_partner",
        lambda partner_id: SimpleNamespace(running=True, partner_id=partner_id),
    )

    async def original_answers(partner_id, content, **kwargs):
        _ = (content, kwargs)
        return f"{partner_id} original"

    monkeypatch.setattr(partners, "send_group_message", original_answers)
    group_id = client.post(
        "/api/partner-groups",
        json={"name": "Socket summary", "member_ids": ["ada", "bob"]},
    ).json()["group_id"]
    turn = client.post(
        f"/api/partner-groups/{group_id}/messages",
        json={"content": "Synthesize later", "session_key": "ws-summary"},
    ).json()

    async def streamed_summary(partner_id, content, **kwargs):
        _ = content
        assert partner_id == "bob"
        await kwargs["on_event"](StreamEvent(type=StreamEventType.CONTENT, content="summary trace"))
        return "Bob's round summary"

    monkeypatch.setattr(partners, "send_group_message", streamed_summary)
    with client.websocket_connect(f"/ws/partner-groups/{group_id}") as ws:
        ws.send_json(
            {
                "action": "summarize_round",
                "session_key": "ws-summary",
                "turn_id": turn["turn_id"],
                "partner_id": "bob",
            }
        )
        frames = [ws.receive_json() for _ in range(4)]

    assert frames[0] == {
        "type": "partner_started",
        "turn_id": turn["turn_id"],
        "partner_id": "bob",
    }
    assert frames[1]["type"] == "partner_trace"
    assert frames[1]["turn_id"] == turn["turn_id"]
    assert frames[1]["partner_id"] == "bob"
    assert frames[1]["partner_name"] == "Bob"
    assert frames[1]["event"]["content"] == "summary trace"
    assert frames[2]["type"] == "partner_message"
    assert frames[2]["message"]["kind"] == "round_summary"
    assert frames[2]["message"]["content"] == "Bob's round summary"
    assert frames[3] == {
        "type": "done",
        "result": {
            "operation": "summarize_round",
            "turn_id": turn["turn_id"],
            "partner_id": "bob",
            "message": frames[2]["message"],
        },
    }


def test_websocket_receives_commands_while_turn_is_streaming(
    client: TestClient,
    monkeypatch,
) -> None:
    groups = client.app.state.partner_groups
    group_id = client.post(
        "/api/partner-groups",
        json={"name": "Live panel", "member_ids": ["ada", "bob"]},
    ).json()["group_id"]

    async def hanging_send(group_id, *, emit, **kwargs):
        _ = (group_id, kwargs)
        await emit({"type": "user_message", "message": {"event_id": "user-1"}})
        await asyncio.Event().wait()

    rejected = SimpleNamespace(to_dict=lambda: {"invocation_id": "inv-1", "status": "rejected"})
    monkeypatch.setattr(groups, "send_message", hanging_send)
    monkeypatch.setattr(groups, "reject_invocation", lambda *args, **kwargs: rejected)

    with client.websocket_connect(f"/ws/partner-groups/{group_id}") as ws:
        ws.send_json({"content": "first", "session_key": "live"})
        assert ws.receive_json()["type"] == "user_message"

        ws.send_json({"content": "second", "session_key": "live"})
        assert "already in progress" in ws.receive_json()["content"]

        ws.send_json(
            {
                "action": "reject_invocation",
                "invocation_id": "inv-1",
                "session_key": "live",
            }
        )
        assert ws.receive_json() == {
            "type": "invocation_updated",
            "invocation": {"invocation_id": "inv-1", "status": "rejected"},
        }

        ws.send_json({"action": "cancel", "session_key": "live"})
        terminal_types = {ws.receive_json()["type"], ws.receive_json()["type"]}
        assert terminal_types == {"cancel_requested", "cancelled"}


def test_websocket_create_invocation_emits_immediate_update(client: TestClient) -> None:
    group_id = client.post(
        "/api/partner-groups",
        json={"name": "Socket panel", "member_ids": ["ada", "bob"]},
    ).json()["group_id"]

    with client.websocket_connect(f"/ws/partner-groups/{group_id}") as ws:
        ws.send_json(
            {
                "action": "create_invocation",
                "session_key": "socket-session",
                "requester_partner_id": "ada",
                "target_partner_id": "bob",
                "question": "Please critique this answer.",
            }
        )
        frame = ws.receive_json()
        assert frame["type"] == "invocation_updated"
        assert frame["invocation"]["status"] == "pending"
        assert frame["invocation"]["parent_turn_id"] == ""
        assert frame["invocation"]["question"] == "Please critique this answer."

        ws.send_json(
            {
                "action": "create_invocation",
                "session_key": "socket-session",
                "requester_partner_id": "ada",
                "target_partner_id": "ada",
                "question": "Invalid target",
            }
        )
        assert ws.receive_json() == {
            "type": "error",
            "content": "Requester and target Partners must differ.",
        }
