"""``kb_files`` — enumerate a knowledge base, the query ``rag`` cannot serve.

``rag`` returns passages, so "how many files are in here" and "is X in this KB"
have no answer on that path. This tool reads the inventory instead, through the
same access-checked seam the chat manifest uses, and it mounts under the same
gate as ``rag``: attached KB or nothing.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from deeptutor.agents._shared.tool_composition import (
    AUTO_MOUNTED_TOOLS,
    ToolMountFlags,
    compose_enabled_tools,
)
from deeptutor.knowledge.manifest import (
    KB_FILES_DEFAULT_LIMIT,
    KB_FILES_MAX_LIMIT,
    build_manifest,
)
from deeptutor.tools.builtin import BUILTIN_TOOL_NAMES, KbFilesTool

_READY = {"rag_provider": "llamaindex", "status": "ready"}


def _kb(tmp_path: Path, *files: str) -> Path:
    raw = tmp_path / "Course" / "raw"
    raw.mkdir(parents=True, exist_ok=True)
    for name in files:
        (raw / name).write_bytes(b"x" * 1024)
    return tmp_path / "Course"


def _stub_resolver(monkeypatch: pytest.MonkeyPatch, kb_dir: Path | None) -> list[dict[str, Any]]:
    """Stand in for the access-checked resolver, recording its arguments."""
    calls: list[dict[str, Any]] = []

    def _resolve(kb_ref: str, *, limit: int = KB_FILES_DEFAULT_LIMIT, pattern: str = ""):
        calls.append({"kb_ref": kb_ref, "limit": limit, "pattern": pattern})
        if kb_dir is None:
            return None
        return build_manifest(
            name=kb_ref, kb_dir=kb_dir, entry=_READY, limit=limit, pattern=pattern
        )

    monkeypatch.setattr(
        "deeptutor.multi_user.knowledge_access.resolve_kb_manifest", _resolve, raising=False
    )
    return calls


class TestRegistration:
    def test_tool_is_registered(self) -> None:
        assert "kb_files" in BUILTIN_TOOL_NAMES

    def test_mounting_is_pipeline_owned_like_rag(self) -> None:
        assert "kb_files" in AUTO_MOUNTED_TOOLS

    def test_definition_steers_counting_questions_away_from_rag(self) -> None:
        definition = KbFilesTool().get_definition()
        assert definition.name == "kb_files"
        assert "never rag" in definition.description
        assert {param.name for param in definition.parameters} == {"kb_name", "pattern", "limit"}
        assert [param.name for param in definition.parameters if param.required] == ["kb_name"]


class TestMountGate:
    def test_mounts_with_a_knowledge_base_attached(self) -> None:
        tools = compose_enabled_tools(
            registry=_EmptyRegistry(),
            requested_tools=[],
            optional_whitelist=[],
            mount_flags=ToolMountFlags(has_kb=True),
        )
        assert "kb_files" in tools and "rag" in tools

    def test_absent_without_a_knowledge_base(self) -> None:
        tools = compose_enabled_tools(
            registry=_EmptyRegistry(),
            requested_tools=[],
            optional_whitelist=[],
            mount_flags=ToolMountFlags(has_kb=False),
        )
        assert "kb_files" not in tools

    def test_coexists_with_an_exclusive_knowledge_capability(self) -> None:
        """An Obsidian vault owns the turn; co-selected KBs stay enumerable (#650)."""
        tools = compose_enabled_tools(
            registry=_EmptyRegistry(),
            requested_tools=[],
            optional_whitelist=[],
            mount_flags=ToolMountFlags(has_kb=True),
            capability_owned=["obsidian_read"],
            exclusive=True,
        )
        assert tools == ["obsidian_read", "rag", "kb_files", "ask_user"]

    def test_a_partner_can_deny_it(self) -> None:
        tools = compose_enabled_tools(
            registry=_EmptyRegistry(),
            requested_tools=[],
            optional_whitelist=[],
            mount_flags=ToolMountFlags(has_kb=True),
            builtin_whitelist={"rag"},
        )
        assert "rag" in tools and "kb_files" not in tools


class _EmptyRegistry:
    @staticmethod
    def get_enabled(_selected: list[str]) -> list[Any]:
        return []


class TestExecute:
    @pytest.mark.asyncio
    async def test_reports_count_and_names(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        _stub_resolver(monkeypatch, _kb(tmp_path, "a.pdf", "b.pdf"))

        result = await KbFilesTool().execute(kb_name="Course", language="en")

        assert "2 documents." in result.content
        assert "a.pdf" in result.content
        assert result.metadata["total"] == 2
        assert result.metadata["listed"] == ["a.pdf", "b.pdf"]

    @pytest.mark.asyncio
    async def test_pattern_is_forwarded(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        calls = _stub_resolver(monkeypatch, _kb(tmp_path, "a.pdf", "b.md"))

        result = await KbFilesTool().execute(kb_name="Course", pattern="*.md", language="en")

        assert calls[0]["pattern"] == "*.md"
        assert result.metadata["matched"] == 1
        assert result.metadata["total"] == 2

    @pytest.mark.asyncio
    async def test_limit_is_clamped(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        calls = _stub_resolver(monkeypatch, _kb(tmp_path, "a.pdf"))
        tool = KbFilesTool()

        await tool.execute(kb_name="Course", limit=999_999)
        await tool.execute(kb_name="Course", limit=0)
        await tool.execute(kb_name="Course", limit="not a number")

        assert [call["limit"] for call in calls] == [
            KB_FILES_MAX_LIMIT,
            KB_FILES_DEFAULT_LIMIT,
            KB_FILES_DEFAULT_LIMIT,
        ]

    @pytest.mark.asyncio
    async def test_language_follows_the_turn(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        _stub_resolver(monkeypatch, _kb(tmp_path, "a.pdf"))

        result = await KbFilesTool().execute(kb_name="Course", language="zh")

        assert "共 1 个文档" in result.content

    @pytest.mark.asyncio
    async def test_missing_kb_name_is_rejected(self, monkeypatch: pytest.MonkeyPatch) -> None:
        _stub_resolver(monkeypatch, None)

        with pytest.raises(ValueError, match="explicit kb_name"):
            await KbFilesTool().execute(kb_name="  ")

    @pytest.mark.asyncio
    async def test_inaccessible_kb_is_an_error_not_an_empty_list(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Reporting "no documents" for a KB the user cannot reach would mislead."""
        _stub_resolver(monkeypatch, None)

        with pytest.raises(ValueError, match="not accessible"):
            await KbFilesTool().execute(kb_name="secret")
