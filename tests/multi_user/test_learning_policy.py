"""Server-side policy resolution for learning accounts."""

from __future__ import annotations

import pytest

from deeptutor.multi_user.grants import normalize_grant, save_grant, validate_grant
from deeptutor.multi_user.identity import set_preset
from deeptutor.multi_user.learning_access import (
    allowed_reading_extensions,
    apply_learning_policy,
    assert_learning_material,
    assert_learning_surface,
    learning_policy_for_user,
)


def _policy_grant(material_ids: list[str] | None = None, extensions: list[str] | None = None):
    return {
        "enabled_tools": [],
        "mcp_tools": [],
        "cli_apps": [],
        "exec_enabled": False,
        "learning_policy": {
            "age_band": "9-12",
            "locked_persona": "teacher",
            "allowed_capabilities": ["chat", "immersive_reading"],
            "default_capability": "immersive_reading",
            "allowed_surfaces": ["chat", "reading"],
            "reading": {
                "allow_upload": False,
                "material_ids": material_ids or [],
                "extensions": extensions or [],
            },
        },
    }


def _seed_learner(seed_user, name: str):
    seed_user("admin", role="admin")
    return seed_user(name)


def test_legacy_grants_remain_unrestricted(mu_isolated_root):
    grant = normalize_grant("u_legacy", {"version": 1})
    assert grant["learning_policy"] is None
    validate_grant(grant)


def test_learning_policy_validation_rejects_unsafe_values(mu_isolated_root):
    grant = normalize_grant(
        "u_student",
        _policy_grant(extensions=["not valid"]),
    )
    grant["learning_policy"]["allowed_capabilities"] = ["deep_research"]

    with pytest.raises(ValueError, match="unsupported values"):
        validate_grant(grant)


def test_apply_policy_keeps_allowed_modes_and_strips_the_turn_surface(
    mu_isolated_root, seed_user, as_user
):
    learner = _seed_learner(seed_user, "student")
    save_grant(learner["id"], _policy_grant())

    with as_user(learner["id"], username="student"):
        result = apply_learning_policy(
            {
                "capability": "immersive_reading",
                "persona": "friend",
                "tools": [{"name": "web_search"}],
                "enabled_tools": ["web_search"],
                "knowledge_bases": ["admin:kb:private"],
                "kb_name": "private",
                "enable_rag": True,
                "enable_web_search": True,
                "partner_id": "partner",
                "bot_id": "bot",
            }
        )

    assert result["persona"] == "teacher"
    assert result["tools"] == []
    assert result["enabled_tools"] == []
    assert result["knowledge_bases"] == []
    assert result["kb_name"] == ""
    assert result["enable_rag"] is False
    assert result["enable_web_search"] is False
    assert result["partner_id"] is None
    assert result["bot_id"] is None


def test_apply_policy_rejects_unallowed_capabilities(mu_isolated_root, seed_user, as_user):
    learner = _seed_learner(seed_user, "student")
    save_grant(learner["id"], _policy_grant())

    with as_user(learner["id"], username="student"):
        with pytest.raises(PermissionError, match="cannot use this mode"):
            apply_learning_policy({"capability": "deep_research"})


def test_surface_material_upload_and_extension_guards(mu_isolated_root, seed_user, as_user):
    learner = _seed_learner(seed_user, "student")
    grant = save_grant(
        learner["id"],
        _policy_grant(
            material_ids=["rm_allowed"],
            extensions=["read_aloud"],
        ),
    )

    with as_user(learner["id"], username="student"):
        assert_learning_surface("chat")
        assert_learning_surface("reading")
        with pytest.raises(PermissionError, match="knowledge surface"):
            assert_learning_surface("knowledge")

        assert_learning_material("rm_allowed")
        with pytest.raises(PermissionError, match="not assigned"):
            assert_learning_material("rm_private")
        with pytest.raises(PermissionError, match="cannot upload"):
            assert_learning_material("", upload=True)

        assert allowed_reading_extensions() == {"read_aloud"}


def test_policy_without_explicit_reading_keeps_legacy_access(mu_isolated_root, seed_user, as_user):
    learner = _seed_learner(seed_user, "legacy-learner")
    grant = save_grant(
        learner["id"],
        {
            "learning_policy": {
                "age_band": "9-12",
                "locked_persona": "teacher",
                "allowed_capabilities": ["chat", "immersive_reading"],
                "default_capability": "immersive_reading",
            }
        },
    )

    assert grant["learning_policy"]["reading"] == {
        "allow_upload": True,
        "material_ids": ["*"],
        "extensions": [
            "read_aloud",
            "guided_learning",
            "vocabulary",
            "quiz",
            "translation",
        ],
    }
    with as_user(learner["id"], username="legacy-learner"):
        assert_learning_material("rm_anything")
        assert_learning_material("", upload=True)
        assert_learning_surface("reading")
        assert allowed_reading_extensions() == {
            "read_aloud",
            "guided_learning",
            "vocabulary",
            "quiz",
            "translation",
        }


def test_learner_preset_falls_back_to_the_conservative_policy(mu_isolated_root, seed_user):
    learner = _seed_learner(seed_user, "student")
    assert set_preset("student", "learner")

    policy = learning_policy_for_user(learner["id"], is_admin=False)

    assert policy is not None
    assert policy["default_capability"] == "immersive_reading"
    assert policy["reading"] == {
        "allow_upload": False,
        "material_ids": [],
        "extensions": [],
    }
