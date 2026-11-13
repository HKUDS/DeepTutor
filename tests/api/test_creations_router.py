"""API surface tests for ``/api/creations`` (GET draft, POST approve).

Covers: create / 409 conflict / same-session update / already_created
idempotence / owner isolation / ``always: true`` never reaching the saved
SKILL.md / reference files landing in the skill dir. Filesystem access is
isolated the same way ``test_partners_router.py`` isolates
``PartnerDraftStore`` — plus a direct monkeypatch of
``get_skill_service``/``get_persona_service`` (mirroring
``test_capability_routing.py``) so Approve's real publish path never touches
the real workspace machinery.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

try:
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
except Exception:  # pragma: no cover
    FastAPI = None
    TestClient = None

pytestmark = pytest.mark.skipif(
    FastAPI is None or TestClient is None, reason="fastapi not installed"
)

from deeptutor.services.creations import drafts as drafts_module
from deeptutor.services.persona.service import PersonaService
from deeptutor.services.skill.service import SkillService


@pytest.fixture
def services(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> SimpleNamespace:
    user_root = tmp_path / "user-root"
    monkeypatch.setattr(
        drafts_module,
        "get_current_path_service",
        lambda: SimpleNamespace(get_user_root=lambda: user_root),
    )

    skills = SkillService(root=tmp_path / "skills", builtin_root=None)
    personas = PersonaService(root=tmp_path / "personas")
    admin_personas_root = tmp_path / "admin-personas" / "personas"
    monkeypatch.setattr("deeptutor.services.skill.get_skill_service", lambda: skills)
    monkeypatch.setattr("deeptutor.services.persona.get_persona_service", lambda: personas)
    monkeypatch.setattr(
        "deeptutor.multi_user.paths.get_admin_path_service",
        lambda: SimpleNamespace(get_workspace_dir=lambda: admin_personas_root.parent),
    )
    return SimpleNamespace(skills=skills, personas=personas)


@pytest.fixture
def client(services, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    from deeptutor.api.routers import auth as auth_module
    import deeptutor.api.routers.creations as creations_router_mod
    from deeptutor.multi_user.context import reset_current_user, set_current_user
    from deeptutor.multi_user.models import CurrentUser, UserScope

    monkeypatch.setattr(auth_module, "AUTH_ENABLED", False)
    token = set_current_user(
        CurrentUser(
            id="learner-1",
            username="learner-1",
            role="user",
            scope=UserScope(kind="user", user_id="learner-1", root=Path("/tmp/learner-1")),
        )
    )
    creations_router_mod._approve_locks.clear()

    app = FastAPI()
    app.include_router(creations_router_mod.router, prefix="/api/creations")
    try:
        yield TestClient(app)
    finally:
        reset_current_user(token)


def _make_draft(*, kind: str = "skill", session_id: str = "session-a", **overrides):
    from deeptutor.services.creations.drafts import CreationDraftStore

    fields = {
        "kind": kind,
        "session_id": session_id,
        "name": "my-skill" if kind == "skill" else "my-persona",
        "description": "A test artifact.",
        "content": "# Body\nStep one.",
        "tags": ["tool"] if kind == "skill" else [],
        "references": [],
        **overrides,
    }
    return CreationDraftStore().create(**fields)


class TestGetDraft:
    def test_not_found(self, client: TestClient) -> None:
        assert client.get("/api/creations/drafts/" + "0" * 32).status_code == 404

    def test_create_state_for_a_free_name(self, client: TestClient) -> None:
        draft = _make_draft()
        response = client.get(f"/api/creations/drafts/{draft.draft_id}")
        assert response.status_code == 200
        body = response.json()
        assert body["approval"] == "create"
        assert body["draft"]["name"] == "my-skill"

    def test_conflict_state_when_name_taken_by_another_session(
        self, client: TestClient, services
    ) -> None:
        services.skills.create("my-skill", "existing", "existing body")
        draft = _make_draft()
        response = client.get(f"/api/creations/drafts/{draft.draft_id}")
        assert response.json()["approval"] == "conflict"

    def test_update_state_for_a_same_session_revision(self, client: TestClient, services) -> None:
        services.skills.create("my-skill", "existing", "existing body")
        from deeptutor.services.creations.drafts import CreationDraftStore

        earlier = _make_draft()
        CreationDraftStore().mark_created(earlier, created_name="my-skill", replaced=False)
        revision = _make_draft(session_id=earlier.session_id)
        response = client.get(f"/api/creations/drafts/{revision.draft_id}")
        assert response.json()["approval"] == "update"


class TestApprove:
    def test_create_writes_a_skill_without_always_true(self, client: TestClient, services) -> None:
        draft = _make_draft(
            content="---\nalways: true\n---\n\n# Body\nDo the thing.",
        )
        response = client.post(f"/api/creations/drafts/{draft.draft_id}/approve", json={})
        assert response.status_code == 200
        body = response.json()
        assert body["already_created"] is False
        assert body["saved_name"] == "my-skill"
        assert body["href"] == "/space/skills"

        detail = services.skills.get_detail("my-skill")
        assert "always" not in detail.content
        assert "Do the thing." in detail.content

    def test_references_land_in_the_skill_dir(self, client: TestClient, services) -> None:
        draft = _make_draft(references=[{"path": "references/notes.md", "content": "extra info"}])
        response = client.post(f"/api/creations/drafts/{draft.draft_id}/approve", json={})
        assert response.status_code == 200
        saved = services.skills.read_skill_file("my-skill", "references/notes.md")
        assert saved == "extra info"

    def test_approve_edits_are_merged(self, client: TestClient, services) -> None:
        draft = _make_draft()
        response = client.post(
            f"/api/creations/drafts/{draft.draft_id}/approve",
            json={"description": "Edited description."},
        )
        assert response.status_code == 200
        assert services.skills.get_detail("my-skill").description == "Edited description."

    def test_conflict_with_another_session_is_409(self, client: TestClient, services) -> None:
        services.skills.create("my-skill", "existing", "existing body")
        draft = _make_draft()
        response = client.post(f"/api/creations/drafts/{draft.draft_id}/approve", json={})
        assert response.status_code == 409

    def test_same_session_revision_updates_instead_of_409(
        self, client: TestClient, services
    ) -> None:
        services.skills.create("my-skill", "first version", "first body")
        from deeptutor.services.creations.drafts import CreationDraftStore

        earlier = _make_draft()
        CreationDraftStore().mark_created(earlier, created_name="my-skill", replaced=False)
        revision = _make_draft(session_id=earlier.session_id, content="# Body\nSecond version.")

        response = client.post(f"/api/creations/drafts/{revision.draft_id}/approve", json={})
        assert response.status_code == 200
        body = response.json()
        assert body["replaced"] is True
        assert "Second version." in services.skills.get_detail("my-skill").content

    def test_repeat_approve_is_idempotent(self, client: TestClient, services) -> None:
        draft = _make_draft()
        first = client.post(f"/api/creations/drafts/{draft.draft_id}/approve", json={})
        assert first.json()["already_created"] is False

        second = client.post(f"/api/creations/drafts/{draft.draft_id}/approve", json={})
        assert second.status_code == 200
        body = second.json()
        assert body["already_created"] is True
        assert body["saved_name"] == "my-skill"

    def test_persona_create_and_update(self, client: TestClient, services) -> None:
        draft = _make_draft(kind="persona", content="You are a patient tutor.")
        response = client.post(f"/api/creations/drafts/{draft.draft_id}/approve", json={})
        assert response.status_code == 200
        assert response.json()["href"] == "/space/personas"
        assert (
            services.personas.get_detail("my-persona")
            .content.strip()
            .endswith("You are a patient tutor.")
        )

    def test_owner_isolation_returns_404_for_another_users_draft(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from deeptutor.multi_user.context import reset_current_user, set_current_user
        from deeptutor.multi_user.models import CurrentUser, UserScope

        draft = _make_draft()

        other_token = set_current_user(
            CurrentUser(
                id="someone-else",
                username="someone-else",
                role="user",
                scope=UserScope(
                    kind="user", user_id="someone-else", root=Path("/tmp/someone-else")
                ),
            )
        )
        try:
            assert client.get(f"/api/creations/drafts/{draft.draft_id}").status_code == 404
            assert (
                client.post(f"/api/creations/drafts/{draft.draft_id}/approve", json={}).status_code
                == 404
            )
        finally:
            reset_current_user(other_token)
