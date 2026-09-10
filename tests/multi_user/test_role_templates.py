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
    """A deployment without a usable LLM default must not block role changes.

    Learner templates still apply (learning_policy is mandatory for learner
    usability), they just ship without a model slot for the admin to fill.
    """
    from deeptutor.multi_user import model_access
    from deeptutor.multi_user.role_templates import apply_role_template, build_role_template

    monkeypatch.setattr(model_access, "admin_catalog", lambda: {"services": {"llm": {}}})
    user_id = seed_user("parent1", role="parent")["id"]
    _allow_grant_save(monkeypatch, user_id, role="parent")

    assert build_role_template(user_id, "teacher") is not None
    assert build_role_template(user_id, "teacher")["models"]["llm"] == []
    grant = apply_role_template(user_id, "parent")
    assert grant is not None
    assert grant["models"]["llm"] == []
    assert grant["learning_policy"]["age_band"] == "9-12"
    assert load_grant(user_id)["learning_policy"]["age_band"] == "9-12"


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
    _allow_grant_save(monkeypatch, user_id, role="parent")

    grant = apply_role_template(user_id, "parent")
    assert grant is not None
    assert grant["models"]["llm"] == []  # owner-bound 活跃档位不外借，模型留空
    assert grant["learning_policy"]["age_band"] == "9-12"


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


# ── P5fix：模板补齐 skills（09-09 走查手工补的技能必须进模板才算配齐）────────


def _seed_admin_skill(name: str) -> None:
    """Drop a minimal admin-workspace skill into the isolated catalog."""
    from pathlib import Path

    from deeptutor.multi_user.paths import get_admin_path_service

    skill_dir = Path(get_admin_path_service().get_workspace_dir()) / "skills" / name
    skill_dir.mkdir(parents=True, exist_ok=True)
    (skill_dir / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: {name} 测试技能\n---\n正文\n", encoding="utf-8"
    )


def _skill_ids(template: dict) -> list[str]:
    return [item["skill_id"] for item in template["skills"]]


def test_teacher_template_seeds_whitelisted_skills(
    mu_isolated_root, llm_catalog, admin_kbs, seed_user
):
    from deeptutor.multi_user.role_templates import build_role_template

    for name in (
        "yuedu-alpha",
        "yuedu-beta",
        "s01",
        "s12",
        "concept-explainer",
        "exam-blueprint",
        "docx",
        "some-random-skill",
    ):
        _seed_admin_skill(name)
    user_id = seed_user("teacher-skills", role="teacher")["id"]

    template = build_role_template(user_id, "teacher")
    skills = _skill_ids(template)
    # yuedu-* 前缀整组收入，排在白名单显式名之前
    assert skills[:2] == ["yuedu-alpha", "yuedu-beta"]
    assert "s01" in skills and "s12" in skills
    assert "concept-explainer" in skills and "exam-blueprint" in skills
    # 内建在白名单内的（docx）收，不在的（skill-creator）不收
    assert "docx" in skills
    assert "skill-creator" not in skills
    # 目录里有但不在白名单 → 不收
    assert "some-random-skill" not in skills


def test_student_and_parent_templates_get_learning_skill_set(
    mu_isolated_root, llm_catalog, admin_kbs, seed_user
):
    from deeptutor.multi_user.role_templates import build_role_template

    for name in ("yuedu-alpha", "s01", "exam-blueprint", "rubric-builder", "docx"):
        _seed_admin_skill(name)
    student_id = seed_user("student-skills", role="student")["id"]
    parent_id = seed_user("parent-skills", role="parent")["id"]

    student = _skill_ids(build_role_template(student_id, "student"))
    parent = _skill_ids(build_role_template(parent_id, "parent"))

    # 学习集：yuedu-*、s01 收入；目录里没有的（concept-explainer）静默跳过
    assert student[0] == "yuedu-alpha"
    assert "s01" in student
    assert "concept-explainer" not in student
    # 教学专属技能与基础文档工具不进学生/家长集
    assert "exam-blueprint" not in student
    assert "rubric-builder" not in student
    assert "docx" not in student
    # parent = student 集
    assert parent == student


def test_missing_skill_names_are_silently_skipped(
    mu_isolated_root, llm_catalog, admin_kbs, seed_user
):
    """目录里没有 yuedu-*/s01~s12 也不能报错——只发目录里真实存在的白名单技能。"""
    from deeptutor.multi_user.role_templates import build_role_template

    _seed_admin_skill("docx")  # 显式盖一个同名（用户层覆盖内建，仍是同一名字）
    user_id = seed_user("teacher-bare", role="teacher")["id"]

    template = build_role_template(user_id, "teacher")
    skills = _skill_ids(template)

    assert "docx" in skills  # 内建存在 → 发
    assert not any(name.startswith("yuedu-") for name in skills)
    assert "s01" not in skills and "s12" not in skills
    assert "concept-explainer" not in skills


def test_role_change_endpoint_seeds_skills(
    mu_isolated_root, llm_catalog, admin_kbs, seed_user, monkeypatch
):
    import asyncio
    from types import SimpleNamespace

    from deeptutor.api.routers.auth import SetRoleRequest, update_user_role

    _seed_admin_skill("yuedu-alpha")
    seed_user("bootstrap-admin2", role="admin")
    user_id = seed_user("teacher10", role="user")["id"]
    _allow_grant_save(monkeypatch, user_id)

    asyncio.run(
        update_user_role(
            "teacher10",
            SetRoleRequest(role="teacher"),
            SimpleNamespace(username="bootstrap-admin2"),
        )
    )
    grant = load_grant(user_id)
    assert {"skill_id": "yuedu-alpha"} in grant["skills"]
    assert {"skill_id": "docx"} in grant["skills"]  # 内建技能随模板下发


# ── P5fix-phase2：student/parent 模板补 learning_policy（09-10 老板追加：
#    learner 账号缺 policy 即不可用）────────────────────────────────────────


def _policy(grant: dict) -> dict:
    return grant["learning_policy"]


def test_learner_templates_ship_valid_learning_policy(
    mu_isolated_root, llm_catalog, admin_kbs, seed_user, monkeypatch
):
    """student/parent 模板产出的 grant 过 normalize+validate 不报错，且
    daily-plan/assignments surface 可达；teacher 无 policy（默认全池）。"""
    from deeptutor.multi_user.grants import validate_grant
    from deeptutor.multi_user.role_templates import build_role_template

    student_id = seed_user("student-policy", role="student")["id"]
    parent_id = seed_user("parent-policy", role="parent")["id"]
    teacher_id = seed_user("teacher-policy", role="teacher")["id"]
    _allow_grant_save(monkeypatch, student_id, role="student")
    _allow_grant_save(monkeypatch, parent_id, role="parent")

    student = build_role_template(student_id, "student")
    parent = build_role_template(parent_id, "parent")
    teacher = build_role_template(teacher_id, "teacher")

    # teacher 保持缺省（None = 默认全池）
    assert _policy(teacher) is None

    for template in (student, parent):
        policy = _policy(template)
        # validate_grant 全量校验（age_band/persona/capabilities/surfaces/reading）
        validate_grant(template)
        assert policy["age_band"] in {"6-8", "9-12", "13-15"}
        assert policy["locked_persona"] == "teacher"
        assert set(policy["allowed_capabilities"]) <= {"chat", "immersive_reading"}
        assert policy["default_capability"] == "immersive_reading"
        assert policy["default_capability"] in policy["allowed_capabilities"]
        surfaces = set(policy["allowed_surfaces"])
        # family 不在合法 surface 集内，learner 以 daily-plan/assignments 为可达面
        assert {"daily-plan", "assignments"} <= surfaces
        assert surfaces <= {"chat", "reading", "daily-plan", "assignments"}
        reading = policy["reading"]
        assert isinstance(reading["material_ids"], list)
        # extensions 白名单基础项，且 id 格式合法
        assert set(reading["extensions"]) == {
            "read_aloud",
            "guided_learning",
            "vocabulary",
            "quiz",
            "translation",
        }
    # parent = student 同一策略
    assert _policy(parent) == _policy(student)


def test_learner_templates_apply_and_persist_policy(
    mu_isolated_root, llm_catalog, admin_kbs, seed_user, monkeypatch
):
    """apply 后账号 grant 携带合法 policy；save_grant 的 validate 全链路已过。"""
    from deeptutor.multi_user.role_templates import apply_role_template

    for role, name in (("student", "student-apply"), ("parent", "parent-apply")):
        user_id = seed_user(name, role=role)["id"]
        _allow_grant_save(monkeypatch, user_id, role=role)
        grant = apply_role_template(user_id, role)
        assert grant is not None
        saved = load_grant(user_id)
        policy = saved["learning_policy"]
        assert policy is not None
        assert "daily-plan" in policy["allowed_surfaces"]
        assert "assignments" in policy["allowed_surfaces"]
        assert policy["default_capability"] == "immersive_reading"


def test_existing_learner_grants_are_not_overwritten_by_policy(
    mu_isolated_root, llm_catalog, admin_kbs, seed_user, monkeypatch
):
    """已有 grants 的 learner 账号不被模板（含新 learning_policy）覆盖。"""
    from deeptutor.multi_user.role_templates import apply_role_template

    user_id = seed_user("student-keep", role="student")["id"]
    _allow_grant_save(monkeypatch, user_id, role="student")
    save_grant(
        user_id,
        {
            "models": {"llm": [{"profile_id": "prof-main", "model_ids": ["m-main"]}]},
            "learning_policy": {
                "age_band": "13-15",
                "locked_persona": "teacher",
                "allowed_capabilities": ["chat"],
                "default_capability": "chat",
                "allowed_surfaces": ["chat"],
                "reading": {"allow_upload": True, "material_ids": [], "extensions": ["quiz"]},
            },
        },
    )

    assert apply_role_template(user_id, "student") is None
    grant = load_grant(user_id)
    assert grant["learning_policy"]["age_band"] == "13-15"  # 管理员手调的原样保留
