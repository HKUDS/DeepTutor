"""The system prompt states what the attached knowledge bases contain.

Retrieval cannot answer "how many files are in this KB" — passages carry no
information about the size of the collection they came from, so a model holding
only ``rag`` guesses. The turn therefore reads the inventory off disk once and
puts it in the system prompt, where a count is answerable with no tool call at
all (the failure mode where a weaker model never calls the tool) and where the
prompt stays byte-stable for the whole turn.

These tests pin the wiring: the note reaches the prompt, PageIndex KBs are not
described twice, and an unreadable KB costs the manifest rather than the turn.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from deeptutor.agents.chat.agentic_pipeline import AgenticChatPipeline
from deeptutor.core.context import UnifiedContext
from deeptutor.knowledge.manifest import KbDocument, KbManifest


def _manifest(name: str, *documents: str, total: int | None = None) -> KbManifest:
    docs = tuple(KbDocument(name=doc, size=1024) for doc in documents)
    return KbManifest(
        name=name,
        provider="llamaindex",
        status="ready",
        total=total if total is not None else len(docs),
        matched=total if total is not None else len(docs),
        documents=docs,
    )


def _pipeline(monkeypatch: pytest.MonkeyPatch, *, language: str = "en") -> AgenticChatPipeline:
    monkeypatch.setattr(
        "deeptutor.agents.loop.pipeline.get_llm_config",
        lambda: SimpleNamespace(
            binding="openai", model="gpt-test", api_key="k", base_url="u", api_version=None
        ),
    )
    return AgenticChatPipeline(language=language)


def _stub_resolver(
    monkeypatch: pytest.MonkeyPatch, manifests: dict[str, KbManifest | None]
) -> list[str]:
    """Replace the access-checked resolver; record which KBs were asked for."""
    asked: list[str] = []

    def _resolve(kb_ref: str, **_kwargs: Any) -> KbManifest | None:
        asked.append(kb_ref)
        return manifests.get(kb_ref)

    monkeypatch.setattr(
        "deeptutor.multi_user.knowledge_access.resolve_kb_manifest", _resolve, raising=False
    )
    return asked


@pytest.mark.asyncio
async def test_manifest_reaches_the_system_prompt(monkeypatch: pytest.MonkeyPatch) -> None:
    pipeline = _pipeline(monkeypatch)
    _stub_resolver(monkeypatch, {"course": _manifest("course", "a.pdf", "notes/week3.md")})
    context = UnifiedContext(
        session_id="s1", user_message="how many files?", knowledge_bases=["course"]
    )

    await pipeline._prepare_kb_manifests(context)
    prompt = pipeline._build_system_prompt(["rag", "kb_files"], context)

    assert "[Knowledge Base Inventory]" in prompt
    assert "2 documents" in prompt
    assert "notes/week3.md" in prompt
    # The authority rule (C): passages are not evidence about the collection.
    assert "must never be used to infer how many documents" in prompt


@pytest.mark.asyncio
async def test_manifest_is_localised(monkeypatch: pytest.MonkeyPatch) -> None:
    pipeline = _pipeline(monkeypatch, language="zh")
    _stub_resolver(monkeypatch, {"course": _manifest("course", "a.pdf")})
    context = UnifiedContext(session_id="s1", user_message="有几个文件", knowledge_bases=["course"])

    await pipeline._prepare_kb_manifests(context)

    assert "共 1 个文档" in pipeline._kb_system_note(context)


@pytest.mark.asyncio
async def test_every_attached_kb_is_described(monkeypatch: pytest.MonkeyPatch) -> None:
    pipeline = _pipeline(monkeypatch)
    asked = _stub_resolver(
        monkeypatch,
        {"course": _manifest("course", "a.pdf"), "papers": _manifest("papers", "p1.pdf", "p2.pdf")},
    )
    context = UnifiedContext(
        session_id="s1", user_message="what's in there?", knowledge_bases=["course", "papers"]
    )

    await pipeline._prepare_kb_manifests(context)
    note = pipeline._kb_system_note(context)

    assert asked == ["course", "papers"]
    assert "course" in note and "papers" in note


@pytest.mark.asyncio
async def test_pageindex_kbs_are_not_described_twice(monkeypatch: pytest.MonkeyPatch) -> None:
    """PageIndex discovery belongs to its tools, not the generic inventory."""
    pipeline = _pipeline(monkeypatch)
    monkeypatch.setattr(
        "deeptutor.services.rag.pipelines.pageindex.is_pageindex_kb",
        lambda name: name == "hosted",
    )
    asked = _stub_resolver(monkeypatch, {"course": _manifest("course", "a.pdf")})
    context = UnifiedContext(
        session_id="s1", user_message="how many?", knowledge_bases=["course", "hosted"]
    )

    await pipeline._prepare_kb_manifests(context)

    assert asked == ["course"]
    assert [manifest.name for manifest in pipeline._kb_manifests] == ["course"]


@pytest.mark.asyncio
async def test_no_kb_attached_yields_no_inventory(monkeypatch: pytest.MonkeyPatch) -> None:
    pipeline = _pipeline(monkeypatch)
    asked = _stub_resolver(monkeypatch, {})
    context = UnifiedContext(session_id="s1", user_message="hello", knowledge_bases=[])

    await pipeline._prepare_kb_manifests(context)

    assert asked == []
    assert pipeline._kb_manifests == []
    assert "[Knowledge Base Inventory]" not in pipeline._build_system_prompt(
        ["web_search"], context
    )


@pytest.mark.asyncio
async def test_inaccessible_kb_is_skipped(monkeypatch: pytest.MonkeyPatch) -> None:
    """A KB the user cannot see must not appear — resolution returns None."""
    pipeline = _pipeline(monkeypatch)
    _stub_resolver(monkeypatch, {"course": _manifest("course", "a.pdf"), "secret": None})
    context = UnifiedContext(
        session_id="s1", user_message="how many?", knowledge_bases=["course", "secret"]
    )

    await pipeline._prepare_kb_manifests(context)

    assert [manifest.name for manifest in pipeline._kb_manifests] == ["course"]


@pytest.mark.asyncio
async def test_unreadable_kb_costs_the_manifest_not_the_turn(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pipeline = _pipeline(monkeypatch)

    def _boom(kb_ref: str, **_kwargs: Any) -> KbManifest:
        if kb_ref == "broken":
            raise OSError("permission denied")
        return _manifest(kb_ref, "a.pdf")

    monkeypatch.setattr(
        "deeptutor.multi_user.knowledge_access.resolve_kb_manifest", _boom, raising=False
    )
    context = UnifiedContext(
        session_id="s1", user_message="how many?", knowledge_bases=["broken", "course"]
    )

    await pipeline._prepare_kb_manifests(context)

    assert [manifest.name for manifest in pipeline._kb_manifests] == ["course"]
