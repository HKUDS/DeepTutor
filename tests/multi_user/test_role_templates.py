"""Role default grant templates: assigning a role opens the account.

The production walkthrough (2026-09-09) found new teacher/student/parent
accounts fully locked because every grant was hand-crafted per account. These
tests pin the contract: a role change seeds the role's default grant when the
account carries nothing, never overwrites an existing grant, and degrades
quietly when the deployment has no usable active LLM default.
"""

from __future__ import annotations

import pytest

from deeptutor.multi_user.grants import empty_grant, load_grant, save_grant

TEACHER_KB = "教材-v2-数学"
OTHER_KB = "research-notes"


@pytest.fixture
def llm_catalog(monkeypatch):
    """A deployment with one usable active LLM profile."""
    from deeptutor.multi_user import model_access

    catalog = {
        "services": {
            "llm": {
                "active_profile_id": "prof-main",
                "active_model_id": "m-main",
                "profiles": [
                    {
                        "id": "prof-main",
                        "name": "Main LLM",
                        "models": [{"id": "m-main", "name": "Main", "model": "main-v1"}],
                    }
                ],
            }
        }
    }
    monkeypatch.setattr(model_access, "admin_catalog", lambda: catalog)
    return catalog


@pytest.fixture
def admin_kbs(mu_isolated_root):
    """Seed the admin KB registry with a subject KB and an unrelated one."""
    from pathlib import Path

    from deeptutor.multi_user.knowledge_access import admin_kb_base_dir, admin_kb_manager

    for name in (TEACHER_KB, OTHER_KB):
        kb_dir = Path(admin_kb_base_dir()) / name / "raw"
        kb_dir.mkdir(parents=True, exist_ok=True)
        (kb_dir / "chapter-1.pdf").write_bytes(b"x" * 512)
        admin_kb_manager().register_knowledge_base(name, description=f"kb {name}")


def _allow_grant_save(monkeypatch, user_id: str, role: str = "teacher") -> None:
    """Resolve ``save_grant``'s user lookup without first-user admin promotion."""
    import deeptutor.multi_user.grants as grants

    monkeypatch.setattr(
        grants,
        "get_user_by_id",
        lambda uid: (f"owner-{user_id}", {"role": role}) if uid == user_id else None,
    )


def test_teacher_template_grants_active_llm_and_subject_kbs(
    mu_isolated_root, llm_catalog, admin_kbs, seed_user, monkeypatch
):
    from deeptutor.multi_user.role_templates import apply_role_template, build_role_template

    user_id = seed_user("teacher1", role="teacher")["id"]
    _allow_grant_save(monkeypatch, user_id)

    template = build_role_template(user_id, "teacher")
    assert template is not None
    assert template["models"]["llm"] == [{"profile_id": "prof-main", "model_ids": ["m-main"]}]
    assert template["knowledge_bases"] == [
        {"resource_id": f"admin:kb:{TEACHER_KB}", "name": TEACHER_KB}
    ]

    grant = apply_role_template(user_id, "teacher")
    assert grant is not None
    assert load_grant(user_id)["knowledge_bases"][0]["name"] == TEACHER_KB


def test_apply_role_template_persists_llm_and_kb(
    mu_isolated_root, llm_catalog, admin_kbs, seed_user, monkeypatch
):
    from deeptutor.multi_user.role_templates import apply_role_template

    user_id = seed_user("student1", role="student")["id"]
    _allow_grant_save(monkeypatch, user_id, role="student")
    grant = apply_role_template(user_id, "student")
    assert grant is not None
    saved = load_grant(user_id)
    assert saved["models"]["llm"][0]["profile_id"] == "prof-main"
    assert saved["knowledge_bases"][0]["resource_id"] == f"admin:kb:{TEACHER_KB}"


def test_existing_grants_are_never_overwritten(
    mu_isolated_root, llm_catalog, admin_kbs, seed_user, monkeypatch
):
    from deeptutor.multi_user.role_templates import apply_role_template

    user_id = seed_user("teacher2", role="teacher")["id"]
    _allow_grant_save(monkeypatch, user_id)
    save_grant(
        user_id,
        {
            "models": {"llm": [{"profile_id": "prof-main", "model_ids": ["m-main"]}]},
            "knowledge_bases": [{"resource_id": f"admin:kb:{OTHER_KB}", "name": OTHER_KB}],
        },
    )

    assert apply_role_template(user_id, "teacher") is None

    grant = load_grant(user_id)
    assert [item["name"] for item in grant["knowledge_bases"]] == [OTHER_KB]


def test_non_template_roles_apply_nothing(mu_isolated_root, llm_catalog, admin_kbs, seed_user):
    from deeptutor.multi_user.role_templates import apply_role_template

    for role in ("admin", "user"):
        user_id = seed_user(f"plain-{role}", role=role)["id"]
        assert apply_role_template(user_id, role) is None
        assert load_grant(user_id) == empty_grant(user_id)


def test_missing_active_llm_yields_no_model_slot(mu_isolated_root, seed_user, monkeypatch):
    """A deployment without a usable LLM default must not block role changes."""
    from deeptutor.multi_user import model_access
    from deeptutor.multi_user.role_templates import apply_role_template, build_role_template

    monkeypatch.setattr(model_access, "admin_catalog", lambda: {"services": {"llm": {}}})
    user_id = seed_user("parent1", role="parent")["id"]

    assert build_role_template(user_id, "teacher") is not None
    assert build_role_template(user_id, "teacher")["models"]["llm"] == []
    assert apply_role_template(user_id, "parent") is None
    assert load_grant(user_id) == empty_grant(user_id)


def test_owner_bound_active_profile_is_not_lent(
    mu_isolated_root, seed_user, admin_kbs, monkeypatch
):
    from deeptutor.multi_user import model_access
    from deeptutor.multi_user.role_templates import apply_role_template

    catalog = {
        "services": {
            "llm": {
                "active_profile_id": "prof-codex",
                "active_model_id": "m-sol",
                "profiles": [
                    {
                        "id": "prof-codex",
                        "owner_bound": True,
                        "models": [{"id": "m-sol", "name": "Sol", "model": "sol"}],
                    }
                ],
            }
        }
    }
    monkeypatch.setattr(model_access, "admin_catalog", lambda: catalog)
    user_id = seed_user("parent2", role="parent")["id"]

    assert apply_role_template(user_id, "parent") is None
    assert load_grant(user_id) == empty_grant(user_id)


def test_role_change_endpoint_applies_the_template(
    mu_isolated_root, llm_catalog, admin_kbs, seed_user, monkeypatch
):
    """PUT /users/{username}/role seeds the grant (admin-visible contract)."""
    import asyncio
    from types import SimpleNamespace

    from deeptutor.api.routers.auth import SetRoleRequest, update_user_role

    seed_user("bootstrap-admin", role="admin")  # first account promotion
    user_id = seed_user("teacher9", role="user")["id"]
    _allow_grant_save(monkeypatch, user_id)

    result = asyncio.run(
        update_user_role(
            "teacher9",
            SetRoleRequest(role="teacher"),
            SimpleNamespace(username="bootstrap-admin"),
        )
    )
    assert result["grant_template_applied"] is True
    grant = load_grant(user_id)
    assert grant["models"]["llm"][0]["profile_id"] == "prof-main"
    assert grant["knowledge_bases"][0]["name"] == TEACHER_KB
