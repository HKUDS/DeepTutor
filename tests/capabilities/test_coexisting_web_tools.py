"""Exclusive knowledge capabilities keep the web pair mounted and mentioned.

Issue #2612: while a knowledge capability owned the turn
(``compose_enabled_tools(exclusive=True)``), the surface dropped ``web_search``
(the user's composer toggle, still shown on in settings) and ``web_fetch``
(always-on) together with every other built-in — the model could only claim
the turn had no search or fetch tool. Following the coexistence pattern issue
#650 established for co-selected KBs (``rag`` / ``kb_files`` /
``knowledge_frontier``), the capability now declares the web pair as
``coexisting_tools``; composition mounts each declared name under its usual
gate, and the capability's own system prompt names what actually mounted.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from deeptutor.agents._shared.tool_composition import ToolMountFlags, compose_enabled_tools
from deeptutor.agents.chat.agentic_pipeline import AgenticChatPipeline
from deeptutor.capabilities import any_exclusive_capability_active
from deeptutor.capabilities.marginnote4 import MarginNoteCapability
from deeptutor.capabilities.obsidian import ObsidianCapability
from deeptutor.capabilities.protocol import KnowledgeCapability
from deeptutor.capabilities.subagent import SubagentCapability
from deeptutor.core.context import UnifiedContext
from deeptutor.runtime.registry.tool_registry import get_tool_registry

WEB_PAIR = ("web_search", "web_fetch")
BASELINE = {
    "workspace_list",
    "workspace_read",
    "workspace_search",
    "workspace_present",
    "write_note",
    "search_notes",
    "ask_user",
}


# ---- composition (#2612) ------------------------------------------------------


def test_exclusive_compose_keeps_web_pair_when_user_toggled_web_search_on() -> None:
    composed = compose_enabled_tools(
        registry=get_tool_registry(),
        requested_tools=["web_search"],
        optional_whitelist=["web_search", "reason"],
        mount_flags=ToolMountFlags(has_kb=False),
        capability_owned=["obsidian_search", "obsidian_read"],
        exclusive=True,
        coexisting=WEB_PAIR,
    )
    assert set(composed) == BASELINE | {"obsidian_search", "obsidian_read"} | set(WEB_PAIR)


def test_exclusive_compose_drops_web_search_when_toggle_off_keeps_web_fetch() -> None:
    # web_search is the user's toggle: off means not mounted. web_fetch follows
    # the product's always-available rule, exactly as on a plain chat turn.
    composed = compose_enabled_tools(
        registry=get_tool_registry(),
        requested_tools=["reason"],
        optional_whitelist=["web_search", "reason"],
        mount_flags=ToolMountFlags(has_kb=False),
        capability_owned=["obsidian_search"],
        exclusive=True,
        coexisting=WEB_PAIR,
    )
    assert "web_search" not in composed
    assert set(composed) == BASELINE | {"obsidian_search", "web_fetch"}


def test_exclusive_compose_partner_whitelist_filters_the_web_pair() -> None:
    # A partner builtin whitelist that denies the web tools subtracts on top:
    # the declaration never bypasses it — not even for a toggled-on
    # web_search.
    composed = compose_enabled_tools(
        registry=get_tool_registry(),
        requested_tools=["web_search"],
        optional_whitelist=["web_search", "reason"],
        mount_flags=ToolMountFlags(has_kb=False),
        capability_owned=["obsidian_search"],
        exclusive=True,
        coexisting=WEB_PAIR,
        builtin_whitelist={"rag", "ask_user"},
    )
    assert "web_search" not in composed
    assert "web_fetch" not in composed
    assert set(composed) == BASELINE | {"obsidian_search"}


def test_exclusive_compose_without_declaration_mounts_no_web_tools() -> None:
    # Default coexisting declaration is empty: a capability that declares
    # nothing keeps the pre-#2612 owned surface untouched.
    composed = compose_enabled_tools(
        registry=get_tool_registry(),
        requested_tools=["web_search"],
        optional_whitelist=["web_search", "reason"],
        mount_flags=ToolMountFlags(has_kb=False),
        capability_owned=["obsidian_search"],
        exclusive=True,
    )
    assert set(composed) == BASELINE | {"obsidian_search"}


def test_exclusive_compose_web_pair_coexists_with_coselected_rag_kbs() -> None:
    # #650 and #2612 stack: co-selected LlamaIndex KBs keep their rag surface
    # while the web pair keeps its gates on the same exclusive turn.
    composed = compose_enabled_tools(
        registry=get_tool_registry(),
        requested_tools=["web_search"],
        optional_whitelist=["web_search", "reason"],
        mount_flags=ToolMountFlags(has_kb=True),
        capability_owned=["obsidian_search"],
        exclusive=True,
        coexisting=WEB_PAIR,
    )
    assert {"rag", "kb_files", "knowledge_frontier"} <= set(composed)
    assert set(WEB_PAIR) <= set(composed)


# ---- declarations ------------------------------------------------------------


def test_product_knowledge_capabilities_declare_the_web_pair() -> None:
    for cap in (ObsidianCapability(), MarginNoteCapability(), SubagentCapability()):
        assert cap.coexisting_tools == WEB_PAIR


def test_knowledge_capability_default_declares_nothing() -> None:
    assert KnowledgeCapability().coexisting_tools == ()


# ---- capability system prompt mentions what mounted --------------------------


def test_coexisting_block_names_the_mounted_web_pair() -> None:
    cap = ObsidianCapability()
    ctx = UnifiedContext(user_message="hi")
    block = cap.coexisting_tools_block(
        ctx, language="en", mounted_tools=["obsidian_search", *WEB_PAIR]
    )
    assert block is not None
    assert "web_search" in block.content and "web_fetch" in block.content

    zh = cap.coexisting_tools_block(
        ctx, language="zh", mounted_tools=["obsidian_search", *WEB_PAIR]
    )
    assert zh is not None
    assert "web_search" in zh.content and "web_fetch" in zh.content


def test_coexisting_block_never_advertises_a_tool_that_did_not_mount() -> None:
    # web_search toggled off: only web_fetch mounted, so only web_fetch is
    # mentioned — the prompt must not name a tool the model cannot call.
    cap = ObsidianCapability()
    ctx = UnifiedContext(user_message="hi")
    block = cap.coexisting_tools_block(ctx, language="en", mounted_tools=["web_fetch"])
    assert block is not None
    assert "web_fetch" in block.content
    assert "web_search" not in block.content


def test_coexisting_block_absent_when_nothing_mounted() -> None:
    cap = ObsidianCapability()
    ctx = UnifiedContext(user_message="hi")
    assert cap.coexisting_tools_block(ctx, language="en", mounted_tools=[]) is None


# ---- pipeline wiring: mount + prompt together ---------------------------------


def _bind_vault(monkeypatch: pytest.MonkeyPatch, vault_path: str, name: str = "myvault") -> None:
    monkeypatch.setattr(
        "deeptutor.multi_user.knowledge_access.resolve_kb_metadata",
        lambda ref: (
            {"name": ref, "type": "obsidian", "vault_path": vault_path}
            if ref == name
            else {"name": ref, "type": None}
        ),
    )


def _chat_pipeline(monkeypatch: pytest.MonkeyPatch) -> AgenticChatPipeline:
    monkeypatch.setattr(
        "deeptutor.services.memory.get_memory_store",
        lambda: SimpleNamespace(read_raw=lambda *_a, **_k: ""),
    )
    monkeypatch.setattr(
        "deeptutor.services.notebook.get_notebook_manager",
        lambda: SimpleNamespace(list_notebooks=lambda: []),
    )
    pipeline = AgenticChatPipeline.__new__(AgenticChatPipeline)
    pipeline._deferred_loader = None
    pipeline._exec_enabled = False
    pipeline.language = "en"
    pipeline._prompts = {}
    pipeline.registry = SimpleNamespace(
        get_enabled=lambda selected: [SimpleNamespace(name=n) for n in selected]
    )
    return pipeline


def test_vault_turn_mounts_and_mentions_web_pair_when_web_search_on(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _bind_vault(monkeypatch, str(tmp_path))
    pipeline = _chat_pipeline(monkeypatch)
    context = UnifiedContext(
        user_message="hi", knowledge_bases=["myvault"], enabled_tools=["web_search"]
    )
    assert any_exclusive_capability_active(context) is True

    tools = pipeline._compose_enabled_tools(context)
    assert "obsidian_search" in tools
    assert set(WEB_PAIR) <= set(tools)

    blocks = pipeline._capability_system_blocks(context, tools)
    capability_prompt = "\n".join(block.content for block in blocks)
    assert "web_search" in capability_prompt and "web_fetch" in capability_prompt


def test_vault_turn_without_web_search_toggle_mounts_only_web_fetch(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _bind_vault(monkeypatch, str(tmp_path))
    pipeline = _chat_pipeline(monkeypatch)
    context = UnifiedContext(user_message="hi", knowledge_bases=["myvault"])

    tools = pipeline._compose_enabled_tools(context)
    assert "obsidian_search" in tools
    assert "web_search" not in tools
    assert "web_fetch" in tools

    blocks = pipeline._capability_system_blocks(context, tools)
    capability_prompt = "\n".join(block.content for block in blocks)
    assert "web_fetch" in capability_prompt
    assert "web_search" not in capability_prompt
