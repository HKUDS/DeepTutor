"""The supported-reasoning-efforts field must never reach accounts as null.

A granted model that publishes no Codex reasoning levels used to serialise
as ``"supported_reasoning_efforts": null`` for ordinary accounts, while the
admin option builder omitted the key entirely. The chat composer builds the
reasoning selector straight from this field and crashed on ``null.map()``,
so the whole user-role chat page died behind the error boundary. The option
API must publish a list or nothing at all — never null — for granted and
personal models alike.
"""

from deeptutor.multi_user import model_access, personal_models
from deeptutor.multi_user.context import reset_current_user, set_current_user
from deeptutor.multi_user.models import CurrentUser, UserScope

PROFILE = "llm-profile-shared"


def make_user(tmp_path):
    return CurrentUser(
        id="u_alice",
        username="alice",
        role="user",
        scope=UserScope(kind="user", user_id="u_alice", root=tmp_path / "u_alice"),
    )


def _catalog(levels: object) -> dict:
    model = {"id": "m-one", "name": "m-one", "model": "model-m-one"}
    if levels is not None:
        model["codex_supported_reasoning_levels"] = levels
    return {
        "services": {
            "llm": {
                "active_profile_id": PROFILE,
                "active_model_id": "m-one",
                "profiles": [
                    {
                        "id": PROFILE,
                        "name": PROFILE,
                        "binding": "openai",
                        "models": [model],
                    }
                ],
            }
        }
    }


def _run(tmp_path, monkeypatch, catalog):
    monkeypatch.setattr(model_access, "admin_catalog", lambda: catalog)
    monkeypatch.setattr(
        model_access,
        "load_grant",
        lambda _user_id=None: {
            "models": {"llm": [{"profile_id": PROFILE, "model_ids": ["m-one"]}]}
        },
    )
    token = set_current_user(make_user(tmp_path))
    try:
        return model_access.allowed_llm_options()
    finally:
        reset_current_user(token)


def test_a_model_without_levels_omits_the_field_rather_than_sending_null(tmp_path, monkeypatch):
    """Admins never saw the key for such models; users must not see null."""
    option = _run(tmp_path, monkeypatch, _catalog(None))["options"][0]
    assert "supported_reasoning_efforts" not in option


def test_declared_levels_still_reach_the_account_as_a_list(tmp_path, monkeypatch):
    option = _run(tmp_path, monkeypatch, _catalog(["minimal", "low"]))["options"][0]
    assert option["supported_reasoning_efforts"] == ["minimal", "low"]


def test_personal_rows_share_the_same_shape(monkeypatch):
    monkeypatch.setattr(
        personal_models,
        "_personal_catalog_profiles",
        lambda: [
            {
                "id": "llm-personal",
                "binding": "openai",
                "models": [{"id": "m-p", "model": "personal-model"}],
            }
        ],
    )
    row = personal_models.personal_llm_rows()[0]
    assert "supported_reasoning_efforts" not in row
