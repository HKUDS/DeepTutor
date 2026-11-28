"""The default model an account's picker shows must match the one the turn path uses.

An account is often granted a model that is not the deployment's active model.
The option list used to leave every entry unflagged in that case, so the chat
composer fell back to "Select model" while the turn path already pinned the
first granted model — the user had to pick a model the server had chosen
anyway (#2438).
"""

from deeptutor.multi_user import model_access
from deeptutor.multi_user.context import reset_current_user, set_current_user
from deeptutor.multi_user.models import CurrentUser, UserScope

SHARED_PROFILE = "llm-profile-shared"
LOCAL_PROFILE = "llm-profile-local"


def make_user(tmp_path):
    return CurrentUser(
        id="u_alice",
        username="alice",
        role="user",
        scope=UserScope(kind="user", user_id="u_alice", root=tmp_path / "u_alice"),
    )


def _profile(profile_id: str, model_ids: list[str]) -> dict:
    return {
        "id": profile_id,
        "name": profile_id,
        "binding": "openai",
        "models": [
            {"id": model_id, "name": model_id, "model": f"model-{model_id}"}
            for model_id in model_ids
        ],
    }


def _catalog(*, active: tuple[str, str], profiles: list[dict]) -> dict:
    return {
        "services": {
            "llm": {
                "active_profile_id": active[0],
                "active_model_id": active[1],
                "profiles": profiles,
            }
        }
    }


def _grant(*pairs: tuple[str, list[str]]):
    return lambda _user_id=None: {
        "models": {
            "llm": [
                {"profile_id": profile_id, "model_ids": list(model_ids)}
                for profile_id, model_ids in pairs
            ]
        }
    }


def _run(tmp_path, monkeypatch, catalog, grant):
    monkeypatch.setattr(model_access, "admin_catalog", lambda: catalog)
    monkeypatch.setattr(model_access, "load_grant", grant)
    token = set_current_user(make_user(tmp_path))
    try:
        return model_access.allowed_llm_options()
    finally:
        reset_current_user(token)


def test_granted_model_becomes_the_default_when_the_active_one_is_not_granted(
    tmp_path, monkeypatch
):
    """The picker defaults to the model the turn path pins, not to nothing."""
    allowed = _run(
        tmp_path,
        monkeypatch,
        _catalog(
            active=(SHARED_PROFILE, "m-other"),
            profiles=[_profile(SHARED_PROFILE, ["m-other"]), _profile(LOCAL_PROFILE, ["m-one"])],
        ),
        _grant((LOCAL_PROFILE, ["m-one"])),
    )

    assert [(option["model_id"], option["is_active_default"]) for option in allowed["options"]] == [
        ("m-one", True)
    ]
    assert allowed["active"] == {"profile_id": LOCAL_PROFILE, "model_id": "m-one"}


def test_the_active_model_still_wins_when_the_account_holds_it(tmp_path, monkeypatch):
    """A granted active model keeps the default; the fallback must not reorder it."""
    allowed = _run(
        tmp_path,
        monkeypatch,
        _catalog(
            active=(SHARED_PROFILE, "m-second"),
            profiles=[_profile(SHARED_PROFILE, ["m-first", "m-second"])],
        ),
        _grant((SHARED_PROFILE, ["m-first", "m-second"])),
    )

    assert [(option["model_id"], option["is_active_default"]) for option in allowed["options"]] == [
        ("m-first", False),
        ("m-second", True),
    ]
    assert allowed["active"] == {"profile_id": SHARED_PROFILE, "model_id": "m-second"}


def test_an_account_without_usable_models_keeps_no_default(tmp_path, monkeypatch):
    """The fallback only picks among usable options, so the lock still shows nothing."""
    allowed = _run(
        tmp_path,
        monkeypatch,
        _catalog(
            active=(SHARED_PROFILE, "m-other"),
            profiles=[_profile(SHARED_PROFILE, ["m-other"]), _profile(LOCAL_PROFILE, ["m-gone"])],
        ),
        _grant((LOCAL_PROFILE, ["m-missing"])),
    )

    assert allowed["options"] == []
    assert allowed["active"] is None


def test_non_admin_allowed_llm_options_includes_reasoning_control(tmp_path, monkeypatch):
    """Non-admin /api/settings/llm-options options must carry backend reasoning_control too."""
    catalog = _catalog(
        active=(SHARED_PROFILE, "m-ds"),
        profiles=[
            {
                "id": SHARED_PROFILE,
                "name": "DeepSeek",
                "binding": "deepseek",
                "models": [
                    {"id": "m-ds", "name": "DeepSeek Reasoner", "model": "deepseek-reasoner"},
                    {
                        "id": "m-chat",
                        "name": "DeepSeek Chat",
                        "model": "deepseek-chat",
                        "reasoning_effort": "high",
                    },
                    {
                        "id": "m-codex",
                        "name": "Custom Levels",
                        "model": "gpt-5.3-codex",
                        "codex_supported_reasoning_levels": ["low", "high"],
                    },
                ],
            }
        ],
    )
    allowed = _run(
        tmp_path,
        monkeypatch,
        catalog,
        _grant((SHARED_PROFILE, ["m-ds", "m-chat", "m-codex"])),
    )
    by_id = {opt["model_id"]: opt for opt in allowed["options"]}
    assert by_id["m-ds"]["supported_reasoning_efforts"] is None
    assert by_id["m-ds"]["reasoning_control"] == {
        "mode": "toggle",
        "off_value": "minimal",
        "on_value": "high",
        "default_on": True,
    }
    assert by_id["m-chat"]["reasoning_control"] == {
        "mode": "toggle",
        "off_value": "minimal",
        "on_value": "high",
        "default_on": True,
    }
    assert by_id["m-codex"]["reasoning_control"] == {
        "mode": "levels",
        "levels": ["low", "high"],
    }
