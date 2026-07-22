"""Tests for the Obsidian knowledge capability: vault ops, hooks, tools, exclusivity."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from deeptutor.agents._shared.tool_composition import ToolMountFlags, compose_enabled_tools
from deeptutor.capabilities import any_exclusive_capability_active
from deeptutor.capabilities.obsidian import OBSIDIAN_TOOL_NAMES, ObsidianCapability
from deeptutor.capabilities.obsidian import binding as obsidian_binding
from deeptutor.capabilities.obsidian import vault as V
from deeptutor.capabilities.obsidian.tools import (
    ObsidianAppendTool,
    ObsidianBacklinksTool,
    ObsidianReadTool,
    ObsidianSearchTool,
)
from deeptutor.core.context import UnifiedContext
from deeptutor.runtime.registry.tool_registry import get_tool_registry


def _seed_vault(root: Path) -> None:
    (root / "notes").mkdir(parents=True, exist_ok=True)
    (root / ".obsidian").mkdir(exist_ok=True)
    (root / ".obsidian" / "app.json").write_text("{}", encoding="utf-8")
    (root / "notes" / "Photosynthesis.md").write_text(
        "---\ntags: [biology]\nstatus: draft\n---\n"
        "# Photosynthesis\nConverts light. See [[Chlorophyll]] and #biology.\n",
        encoding="utf-8",
    )
    (root / "Chlorophyll.md").write_text("# Chlorophyll\nGreen pigment.\n", encoding="utf-8")
    (root / "Index.md").write_text("Map: [[Photosynthesis]] is key.\n", encoding="utf-8")


# ---- vault operations (pure) -------------------------------------------------


def test_vault_read_parses_frontmatter_and_body(tmp_path: Path) -> None:
    _seed_vault(tmp_path)
    note = V.read_note(tmp_path, "Photosynthesis")
    assert note["frontmatter"] == {"tags": ["biology"], "status": "draft"}
    assert note["body"].startswith("# Photosynthesis")
    assert note["path"] == "notes/Photosynthesis.md"


def test_vault_search_and_list_skip_internal_dirs(tmp_path: Path) -> None:
    _seed_vault(tmp_path)
    assert [h["path"] for h in V.search_notes(tmp_path, "light")] == ["notes/Photosynthesis.md"]
    assert all(".obsidian" not in p for p in V.list_notes(tmp_path))


def test_vault_links_and_backlinks_follow_wikilinks(tmp_path: Path) -> None:
    _seed_vault(tmp_path)
    assert V.outgoing_links(tmp_path, "Photosynthesis") == ["Chlorophyll"]
    assert [b["path"] for b in V.backlinks(tmp_path, "Photosynthesis")] == ["Index.md"]


def test_vault_tags_ranked_by_count(tmp_path: Path) -> None:
    _seed_vault(tmp_path)
    tags = {row["tag"]: row["count"] for row in V.collect_tags(tmp_path)}
    assert tags["biology"] == 2  # frontmatter list + inline #biology


def test_vault_writes_are_additive(tmp_path: Path) -> None:
    _seed_vault(tmp_path)
    created = V.create_note(
        tmp_path, "Summaries/Light.md", "body [[Photosynthesis]]", {"tags": ["s"]}
    )
    assert created == "Summaries/Light.md"
    with pytest.raises(V.VaultError):
        V.create_note(tmp_path, "Summaries/Light.md", "dup")  # no overwrite
    V.append_note(tmp_path, "Chlorophyll", "extra line")
    assert "extra line" in (tmp_path / "Chlorophyll.md").read_text(encoding="utf-8")
    V.set_property(tmp_path, "Chlorophyll", "reviewed", "yes")
    assert V.read_note(tmp_path, "Chlorophyll")["frontmatter"]["reviewed"] == "yes"


def test_vault_refuses_path_traversal(tmp_path: Path) -> None:
    _seed_vault(tmp_path)
    with pytest.raises(V.VaultError):
        V.create_note(tmp_path, "../escape.md", "x")


# ---- capability hooks --------------------------------------------------------


def _bind(monkeypatch, vault_path: str, name: str = "myvault") -> None:
    """Make ``resolve_kb_metadata`` report ``name`` as an Obsidian vault."""
    monkeypatch.setattr(
        "deeptutor.multi_user.knowledge_access.resolve_kb_metadata",
        lambda ref: (
            {"name": ref, "type": "obsidian", "vault_path": vault_path}
            if ref == name
            else {"name": ref, "type": None}
        ),
    )


def test_capability_inactive_without_obsidian_kb(monkeypatch, tmp_path: Path) -> None:
    _bind(monkeypatch, str(tmp_path))
    cap = ObsidianCapability()
    ctx = UnifiedContext(user_message="hi", knowledge_bases=["plain-kb"])
    assert cap.is_active(ctx) is False
    assert cap.system_block(ctx, language="en", prompts={}) is None


def test_capability_active_injects_vault_path(monkeypatch, tmp_path: Path) -> None:
    _bind(monkeypatch, str(tmp_path))
    cap = ObsidianCapability()
    ctx = UnifiedContext(user_message="hi", knowledge_bases=["myvault"])
    assert cap.is_active(ctx) is True
    assert tuple(cap.owned_tools) == OBSIDIAN_TOOL_NAMES
    # vault path injected for obsidian tools, even overwriting a forged value...
    assert cap.augment_kwargs("obsidian_read", {}, ctx)["_vault_path"] == str(tmp_path)
    assert cap.augment_kwargs("obsidian_read", {"_vault_path": "/etc"}, ctx)["_vault_path"] == str(
        tmp_path
    )
    # ...but never for a non-obsidian tool.
    assert "_vault_path" not in cap.augment_kwargs("rag", {}, ctx)
    block = cap.system_block(ctx, language="en", prompts={})
    assert block is not None and "myvault" in block.content


def test_binding_resolved_once_and_cached(monkeypatch, tmp_path: Path) -> None:
    calls = {"n": 0}

    def fake(ref):
        calls["n"] += 1
        return {"name": ref, "type": "obsidian", "vault_path": str(tmp_path)}

    monkeypatch.setattr("deeptutor.multi_user.knowledge_access.resolve_kb_metadata", fake)
    ctx = UnifiedContext(user_message="hi", knowledge_bases=["v"])
    obsidian_binding.vault_for_turn(ctx)
    obsidian_binding.vault_for_turn(ctx)
    assert calls["n"] == 1  # second call hits the per-turn cache


# ---- tools -------------------------------------------------------------------


@pytest.mark.asyncio
async def test_tools_fail_without_vault_path() -> None:
    res = await ObsidianSearchTool().execute(query="x")
    assert res.success is False and "vault" in res.content.lower()


@pytest.mark.asyncio
async def test_tools_round_trip_against_vault(tmp_path: Path) -> None:
    _seed_vault(tmp_path)
    vp = str(tmp_path)
    hits = json.loads((await ObsidianSearchTool().execute(query="light", _vault_path=vp)).content)
    assert hits["count"] == 1
    read = json.loads(
        (await ObsidianReadTool().execute(note="Photosynthesis", _vault_path=vp)).content
    )
    assert read["frontmatter"]["status"] == "draft"
    back = json.loads(
        (await ObsidianBacklinksTool().execute(note="Photosynthesis", _vault_path=vp)).content
    )
    assert back["backlinks"][0]["path"] == "Index.md"
    appended = await ObsidianAppendTool().execute(
        note="Chlorophyll", content="line", _vault_path=vp
    )
    assert appended.success and json.loads(appended.content)["status"] == "appended"


@pytest.mark.asyncio
async def test_read_missing_note_is_graceful(tmp_path: Path) -> None:
    res = await ObsidianReadTool().execute(note="Nope", _vault_path=str(tmp_path))
    assert res.success is False  # VaultError surfaced as a clean failure


# ---- exclusivity & registry --------------------------------------------------


def test_exclusive_compose_drops_everything_but_owned_and_ask_user() -> None:
    composed = compose_enabled_tools(
        registry=get_tool_registry(),
        requested_tools=["web_search", "reason"],
        optional_whitelist=["web_search", "reason"],
        mount_flags=ToolMountFlags(has_kb=True, has_code=True, has_memory=True),
        capability_owned=["obsidian_search", "obsidian_read"],
        exclusive=True,
    )
    assert set(composed) == {"obsidian_search", "obsidian_read", "ask_user"}


def test_registry_flags_obsidian_turn_as_exclusive(monkeypatch, tmp_path: Path) -> None:
    _bind(monkeypatch, str(tmp_path))
    obsidian_turn = UnifiedContext(user_message="hi", knowledge_bases=["myvault"])
    plain_turn = UnifiedContext(user_message="hi", knowledge_bases=["plain-kb"])
    assert any_exclusive_capability_active(obsidian_turn) is True
    assert any_exclusive_capability_active(plain_turn) is False
