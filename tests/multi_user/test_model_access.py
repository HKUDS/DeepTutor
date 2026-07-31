"""Regression coverage for redacted model and BYOK source selection."""

from __future__ import annotations

from types import SimpleNamespace

from deeptutor.multi_user import execution_source, model_access
from deeptutor.multi_user.execution_source import ExecutionSource


def test_allowed_llm_options_separates_platform_and_byok_and_reads_access_once(
    as_user, monkeypatch
):
    calls: list[str] = []

    def access(user_id: str):
        calls.append(user_id)
        return {
            "llm": [
                {
                    "source": "admin",
                    "profile_id": "platform-profile",
                    "model_id": "platform-model",
                    "name": "Platform model",
                    "model": "platform-model",
                    "available": True,
                },
                {
                    "source": "byok",
                    "profile_id": "byok-profile",
                    "generation": 2,
                    "name": "Personal model",
                    "model": "gpt-test",
                    "provider": "openai",
                    "available": True,
                },
            ]
        }

    monkeypatch.setattr(model_access, "redacted_model_access", access)
    with as_user("u_alice"):
        options = model_access.allowed_llm_options()["options"]

    assert calls == ["u_alice"]
    assert [(item["source"], item["profile_id"]) for item in options] == [
        ("admin", "platform-profile"),
        ("byok", "byok-profile"),
    ]


def test_redacted_byok_access_uses_target_users_grant(as_user, monkeypatch):
    monkeypatch.setattr(
        model_access,
        "load_grant",
        lambda _user_id: {"models": {"llm": []}, "byok": {"llm": {"enabled": False}}},
    )
    monkeypatch.setattr(model_access, "admin_catalog", lambda: {"services": {"llm": {}}})
    monkeypatch.setattr(model_access, "load_policy", lambda: {})
    monkeypatch.setattr(model_access, "byok_runtime_enabled", lambda *_args: True)
    monkeypatch.setattr(model_access, "allowed_binding", lambda *_args: True)
    monkeypatch.setattr(
        model_access,
        "get_user_byok_vault",
        lambda: SimpleNamespace(
            list_profiles=lambda _user_id, service: [
                {
                    "id": "byok-profile",
                    "service": service,
                    "provider": "openai",
                    "configured": True,
                    "generation": 1,
                }
            ]
        ),
    )

    with as_user("u_admin", role="admin"):
        items = model_access.redacted_model_access("u_alice")["llm"]

    assert items[0]["source"] == "byok"
    assert items[0]["available"] is False


def test_default_byok_selection_only_passes_binding_allowed_profiles(as_user, monkeypatch):
    profiles = [
        {"id": "blocked", "provider": "blocked-provider", "configured": True},
        {"id": "allowed", "provider": "openai", "configured": True, "generation": 3},
    ]
    captured: list[dict[str, object]] = []
    monkeypatch.setattr(
        model_access,
        "get_user_byok_vault",
        lambda: SimpleNamespace(
            list_profiles=lambda _user_id, service: profiles,
            get_preferences=lambda _user_id: {"llm": {"source": "byok"}},
        ),
    )
    monkeypatch.setattr(model_access, "load_policy", lambda: {})
    monkeypatch.setattr(
        model_access,
        "allowed_binding",
        lambda _service, provider, _policy: provider == "openai",
    )

    def resolve_source(_service: str, **kwargs):
        captured.extend(kwargs["byok_profiles"])
        return ExecutionSource(
            source="byok",
            service="llm",
            user_id="u_alice",
            profile_id="allowed",
            profile_generation=3,
            usage_origin="byok",
        )

    monkeypatch.setattr(execution_source, "resolve_execution_source", resolve_source)
    with as_user("u_alice"):
        selection = model_access.default_llm_selection()

    assert captured == [profiles[1]]
    assert selection == {"source": "byok", "profile_id": "allowed", "generation": 3}
