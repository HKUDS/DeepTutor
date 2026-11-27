"""Tests for create mode: the ``creator`` loop capability, its tool, and kinds.

Covers activation (kind present / unknown / partner source), the
kind-specific prompt plus its dynamic names-in-use/latest-draft tail,
``propose_creation`` normalization (frontmatter stripping, references
validation, tags) and its name-collision vs same-session-revision logic.
Filesystem access (SkillService/PersonaService/CreationDraftStore) is
isolated per test the same way ``test_partners_router.py`` isolates
``PartnerDraftStore``.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from deeptutor.capabilities.creator.capability import CreatorCapability
from deeptutor.capabilities.creator.tools import ProposeCreationTool
from deeptutor.core.context import UnifiedContext
from deeptutor.multi_user.context import reset_current_user, set_current_user
from deeptutor.multi_user.models import CurrentUser, UserScope
from deeptutor.services.creations import drafts as drafts_module
from deeptutor.services.creations.drafts import CreationDraftStore
from deeptutor.services.creations.kinds import PersonaKind, SkillKind, get_creation_kind
from deeptutor.services.persona.service import PersonaService
from deeptutor.services.skill.service import SkillService


@pytest.fixture
def isolated(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Isolate every filesystem-backed service this feature touches."""
    import deeptutor.multi_user.paths as paths_module

    user = CurrentUser(
        id="learner-1",
        username="learner-1",
        role="user",
        scope=UserScope(kind="user", user_id="learner-1", root=tmp_path / "learner-1"),
    )
    token = set_current_user(user)

    user_root = tmp_path / "learner-1-root"
    monkeypatch.setattr(
        drafts_module,
        "get_current_path_service",
        lambda: SimpleNamespace(get_user_root=lambda: user_root),
    )

    skills = SkillService(root=tmp_path / "skills", builtin_root=None)
    personas = PersonaService(root=tmp_path / "personas")
    admin_personas_root = tmp_path / "admin-personas"
    monkeypatch.setattr("deeptutor.services.skill.get_skill_service", lambda: skills)
    monkeypatch.setattr("deeptutor.services.persona.get_persona_service", lambda: personas)
    monkeypatch.setattr(
        paths_module,
        "get_admin_path_service",
        lambda: SimpleNamespace(get_workspace_dir=lambda: admin_personas_root),
    )
    try:
        yield SimpleNamespace(
            skills=skills, personas=personas, admin_personas_root=admin_personas_root
        )
    finally:
        reset_current_user(token)


def _context(
    *, create_target: str | None, source: str = "", session_id: str = "s1"
) -> UnifiedContext:
    context = UnifiedContext(session_id=session_id, user_message="hi", language="en")
    if create_target is not None:
        context.metadata["create_target"] = create_target
    if source:
        context.metadata["source"] = source
    return context


class TestActivation:
    def test_inactive_without_create_target(self, isolated) -> None:
        cap = CreatorCapability()
        assert cap.is_active(_context(create_target=None)) is False
        assert cap.is_active(_context(create_target="")) is False

    def test_inactive_for_unknown_kind(self, isolated) -> None:
        cap = CreatorCapability()
        assert cap.is_active(_context(create_target="mindmap")) is False

    def test_active_for_known_kinds(self, isolated) -> None:
        cap = CreatorCapability()
        assert cap.is_active(_context(create_target="skill")) is True
        assert cap.is_active(_context(create_target="persona")) is True

    def test_inactive_on_partner_turns_even_with_a_known_kind(self, isolated) -> None:
        cap = CreatorCapability()
        context = _context(create_target="skill", source="partner")
        assert cap.is_active(context) is False


class TestSystemBlock:
    def test_prompt_picks_kind_and_language(self, isolated) -> None:
        cap = CreatorCapability()
        en_block = cap.system_block(_context(create_target="skill"), language="en", prompts={})
        assert en_block is not None
        assert "Skill" in en_block.content

        zh_block = cap.system_block(
            UnifiedContext(session_id="s1", language="zh", metadata={"create_target": "persona"}),
            language="zh",
            prompts={},
        )
        assert zh_block is not None
        assert "Persona" in zh_block.content

    def test_prompt_lists_existing_names_and_latest_draft(self, isolated) -> None:
        isolated.skills.create("existing-skill", "An existing skill.", "Body text.")
        store = CreationDraftStore()
        draft = store.create(
            kind="skill",
            session_id="s1",
            name="draft-skill",
            description="desc",
            content="body",
        )
        store.mark_created(draft, created_name="draft-skill", replaced=False)

        cap = CreatorCapability()
        block = cap.system_block(
            _context(create_target="skill", session_id="s1"), language="en", prompts={}
        )
        assert block is not None
        assert "existing-skill" in block.content
        assert "draft-skill" in block.content

    def test_returns_none_for_unknown_kind(self, isolated) -> None:
        cap = CreatorCapability()
        assert (
            cap.system_block(_context(create_target="mindmap"), language="en", prompts={}) is None
        )


class TestAugmentKwargs:
    def test_injects_context_only_for_its_own_tool(self, isolated) -> None:
        cap = CreatorCapability()
        context = _context(create_target="skill")
        kwargs = cap.augment_kwargs("propose_creation", {"name": "x"}, context)
        assert kwargs["_creation_context"] is context
        other = cap.augment_kwargs("web_search", {"q": "x"}, context)
        assert "_creation_context" not in other


class TestKindNormalize:
    def test_skill_strips_frontmatter_and_slugifies_name(self) -> None:
        kind = SkillKind()
        normalized = kind.normalize(
            {
                "name": "My Great Skill",
                "description": "Does the thing.",
                "content": "---\nalways: true\nname: evil\n---\n\n# Body\nStep one.",
                "tags": ["Tool", "bad tag!", "tool"],
            }
        )
        assert normalized["name"] == "my-great-skill"
        assert "always" not in normalized["content"]
        assert normalized["content"] == "# Body\nStep one."
        assert normalized["tags"] == ["tool"]

    def test_skill_rejects_too_many_tags(self) -> None:
        kind = SkillKind()
        with pytest.raises(ValueError):
            kind.normalize(
                {
                    "name": "skill",
                    "description": "desc",
                    "content": "body",
                    "tags": ["a", "b", "c", "d", "e", "f", "g"],
                }
            )

    def test_skill_rejects_bad_reference_path(self) -> None:
        kind = SkillKind()
        with pytest.raises(ValueError):
            kind.normalize(
                {
                    "name": "skill",
                    "description": "desc",
                    "content": "body",
                    "references": [{"path": "../etc/passwd", "content": "x"}],
                }
            )

    def test_skill_rejects_disallowed_reference_suffix(self) -> None:
        kind = SkillKind()
        with pytest.raises(ValueError):
            kind.normalize(
                {
                    "name": "skill",
                    "description": "desc",
                    "content": "body",
                    "references": [{"path": "references/evil.exe", "content": "x"}],
                }
            )

    def test_skill_accepts_a_valid_reference(self) -> None:
        kind = SkillKind()
        normalized = kind.normalize(
            {
                "name": "skill",
                "description": "desc",
                "content": "body",
                "references": [{"path": "references/notes.md", "content": "hello"}],
            }
        )
        assert normalized["references"] == [{"path": "references/notes.md", "content": "hello"}]

    def test_persona_ignores_tags_and_references(self) -> None:
        kind = PersonaKind()
        normalized = kind.normalize(
            {
                "name": "Peer Buddy",
                "description": "A friendly peer.",
                "content": "You are a friendly peer.",
                "tags": ["ignored"],
                "references": [{"path": "references/x.md", "content": "y"}],
            }
        )
        assert normalized["tags"] == []
        assert normalized["references"] == []

    def test_rejects_missing_description(self) -> None:
        with pytest.raises(ValueError):
            SkillKind().normalize({"name": "skill", "description": "", "content": "body"})

    def test_rejects_multiline_description(self) -> None:
        with pytest.raises(ValueError):
            SkillKind().normalize(
                {"name": "skill", "description": "line one\nline two", "content": "body"}
            )

    def test_get_creation_kind_unknown(self) -> None:
        assert get_creation_kind("mindmap") is None
        assert get_creation_kind(None) is None


class TestNameInUse:
    def test_skill_name_in_use_checks_user_layer(self, isolated) -> None:
        kind = SkillKind()
        assert kind.name_in_use("fresh-skill") is False
        isolated.skills.create("fresh-skill", "desc", "body")
        assert kind.name_in_use("fresh-skill") is True

    def test_persona_name_in_use_checks_admin_presets(self, isolated) -> None:
        kind = PersonaKind()
        assert kind.name_in_use("admin-preset") is False
        PersonaService(root=isolated.admin_personas_root / "personas").create(
            "admin-preset", "desc", "content"
        )
        assert kind.name_in_use("admin-preset") is True


class TestProposeCreationTool:
    async def _run(self, tool: ProposeCreationTool, context: UnifiedContext, **fields):
        return await tool.execute(_creation_context=context, **fields)

    @pytest.mark.asyncio
    async def test_requires_active_create_mode(self, isolated) -> None:
        tool = ProposeCreationTool()
        context = _context(create_target=None)
        result = await self._run(tool, context, name="x", description="d", content="c")
        assert result.success is False

    @pytest.mark.asyncio
    async def test_produces_a_draft_with_metadata(self, isolated) -> None:
        tool = ProposeCreationTool()
        context = _context(create_target="skill", session_id="session-a")
        result = await self._run(
            tool,
            context,
            name="New Skill",
            description="Does a thing.",
            content="# Body",
        )
        assert result.success is True
        assert result.metadata["creation_draft"]["kind"] == "skill"
        assert result.metadata["creation_draft"]["name"] == "new-skill"
        assert (
            context.extension("creator")["draft_id"]
            == result.metadata["creation_draft"]["draft_id"]
        )

    @pytest.mark.asyncio
    async def test_name_collision_blocks_a_different_session(self, isolated) -> None:
        isolated.skills.create("taken", "desc", "body")
        tool = ProposeCreationTool()
        context = _context(create_target="skill", session_id="other-session")
        result = await self._run(tool, context, name="taken", description="d", content="c")
        assert result.success is False

    @pytest.mark.asyncio
    async def test_same_session_revision_of_an_approved_name_is_allowed(self, isolated) -> None:
        isolated.skills.create("mine", "desc", "body")
        store = CreationDraftStore()
        earlier = store.create(
            kind="skill", session_id="session-a", name="mine", description="d", content="c"
        )
        store.mark_created(earlier, created_name="mine", replaced=False)

        tool = ProposeCreationTool()
        context = _context(create_target="skill", session_id="session-a")
        result = await self._run(
            tool, context, name="mine", description="updated", content="new body"
        )
        assert result.success is True

    @pytest.mark.asyncio
    async def test_normalize_error_surfaces_as_failed_result(self, isolated) -> None:
        tool = ProposeCreationTool()
        context = _context(create_target="skill")
        result = await self._run(tool, context, name="!!!", description="d", content="c")
        assert result.success is False
