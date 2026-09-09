"""K12 四角色（admin/teacher/student/user）贯通测试。

背景：fork 曾在 API 校验层（SetRoleRequest）支持四角色，但 identity 存储层
白名单仍是 admin/user——teacher/student 是"写入被拒、读取被剥"的死角色。
本文件钉住存储层贯通：设角色、读回、token 映射、非法降级四环节。
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from deeptutor.multi_user.context import user_from_token_payload


@pytest.fixture()
def mu_root(tmp_path, monkeypatch):
    """Isolated identity store via the canonical env switch."""
    monkeypatch.setenv("DEEPTUTOR_AUTH_USERS_FILE", str(tmp_path / "users.json"))
    import importlib

    import deeptutor.multi_user.identity as identity

    identity.USERS_FILE = tmp_path / "users.json"
    identity.LEGACY_USERS_FILE = tmp_path / "legacy.json"
    return identity


def test_set_role_accepts_teacher_and_student(mu_root):
    from deeptutor.services.auth import add_user, list_users, set_role

    add_user("t1", "pw123456")
    assert set_role("t1", "teacher") is True
    add_user("s1", "pw123456")
    assert set_role("s1", "student") is True
    roles = {u["username"]: u["role"] for u in list_users()}
    assert roles["t1"] == "teacher"
    assert roles["s1"] == "student"


def test_readback_preserves_teacher_role(mu_root):
    from deeptutor.services.auth import add_user, list_users, set_role

    add_user("t1", "pw123456")
    set_role("t1", "teacher")
    # 重读规范化路径：role 不得被剥回 user
    roles = {u["username"]: u["role"] for u in list_users()}
    assert roles["t1"] == "teacher"


def test_token_payload_maps_teacher_through(mu_root):
    payload = SimpleNamespace(user_id="u_t", username="t1", role="teacher")
    current = user_from_token_payload(payload)
    assert current.role == "teacher"
    assert current.is_admin is False


def test_illegal_role_still_degrades_to_user():
    payload = SimpleNamespace(user_id="u_x", username="x", role="superadmin")
    current = user_from_token_payload(payload)
    assert current.role == "user"


def test_student_parent_roles_are_learners_regardless_of_preset(mu_root):
    """P4-A #5 复现：角色改出来的 student/parent 仍是 learner。

    preset 只在注册时写死，改角色不动 preset——若 learner 判定只看 preset，
    这些账号会在 /api/daily-plan 等 learner 面前 403，学习空间红字。
    """
    from deeptutor.multi_user.identity import is_learner_account

    assert is_learner_account("student", "standard") is True
    assert is_learner_account("parent", "standard") is True
    # learner preset 依旧生效（teacher/user 上的老路径不变）
    assert is_learner_account("teacher", "learner") is True
    assert is_learner_account("user", "learner") is True
    assert is_learner_account("user", "standard") is False
    assert is_learner_account("teacher", "standard") is False
    # admin 永远不是 learner
    assert is_learner_account("admin", "learner") is False
    assert is_learner_account("admin", None) is False
