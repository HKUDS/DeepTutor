"""M2 regression — admin-assigned skills must load admin SKILL.md, not empty."""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from deeptutor.multi_user import grants as grants_mod
from deeptutor.multi_user.skill_access import (
    assert_skill_allowed,
    assigned_skill_detail,
    assigned_skill_ids,
    assigned_skill_infos,
)
from deeptutor.services.skill.service import SkillService


def _write_skill(workspace_dir, name: str, body: str) -> None:
    skill_dir = workspace_dir / name
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: test skill\n---\n\n{body}\n"
    )


def _grant_skills(uid: str, names: list[str]) -> None:
    grant = grants_mod.empty_grant(uid)
    grant["skills"] = [{"skill_id": n, "access": "use", "source": "admin"} for n in names]
    grants_mod.grant_path(uid).parent.mkdir(parents=True, exist_ok=True)
    grants_mod.grant_path(uid).write_text(__import__("json").dumps(grant))


def test_assigned_skill_loads_admin_skill_body(mu_isolated_root, as_user):
    admin_skills_root = (
        mu_isolated_root / "data" / "user" / "workspace" / "skills"
    ).resolve()
    _write_skill(admin_skills_root, "research-mode", "Use citations rigorously.")

    _grant_skills("u_alice", ["research-mode"])

    with as_user("u_alice", role="user"):
        # Pre-fix this set was {} because the skill_access path read the user
        # workspace; assigned_skill_ids reads grants directly so it was already
        # right — but the SkillService wasn't routed to admin.
        assert "research-mode" in assigned_skill_ids("u_alice")
        infos = assigned_skill_infos("u_alice")
        assert any(i["name"] == "research-mode" for i in infos)

        detail = assigned_skill_detail("research-mode")
        assert detail is not None
        assert "Use citations rigorously." in detail["content"]
        assert detail["assigned"] is True

        # And the admin scope SkillService renders the body in the prompt.
        admin_service = SkillService(root=admin_skills_root)
        rendered = admin_service.load_for_context(["research-mode"])
        assert "Use citations rigorously." in rendered


def test_unassigned_skill_rejected(mu_isolated_root, as_user):
    with as_user("u_bob", role="user"):
        with pytest.raises(HTTPException) as exc:
            assert_skill_allowed("forbidden-skill")
        assert exc.value.status_code == 403


def test_admin_skip_grant_check(mu_isolated_root, as_user):
    with as_user("u_root", role="admin"):
        # Admin doesn't go through grant filtering at all.
        assert_skill_allowed("anything")
