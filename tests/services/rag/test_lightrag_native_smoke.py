"""Offline integration smoke tests against the real pinned LightRAG SDK."""

from __future__ import annotations

import asyncio
from dataclasses import replace
from pathlib import Path

import numpy as np
import pytest

EmbeddingFunc = pytest.importorskip("lightrag.utils").EmbeddingFunc

from deeptutor.services.parsing.types import ParsedDocument
from deeptutor.services.rag.index_versioning import list_kb_versions
from deeptutor.services.rag.pipelines.lightrag import engine, ingress, storage


async def _fake_llm(_prompt, **_kwargs) -> str:
    # This superset satisfies rc2's table/equation analysis schemas. Entity
    # extraction may validly produce zero records; the document still reaches
    # PROCESSED with real parser, chunk, storage and embedding code.
    return '{"name":"fixture","description":"fixture analysis","equation":"x^2","type":"Other"}'


async def _fake_embedding(texts: list[str]) -> np.ndarray:
    return np.ones((len(texts), 32), dtype=float)


def _configure_real_sdk(monkeypatch, llm=_fake_llm) -> None:
    monkeypatch.setattr(engine, "build_llm_model_func", lambda **_kwargs: llm)
    monkeypatch.setattr(
        engine,
        "build_embedding_func",
        lambda **_kwargs: EmbeddingFunc(
            embedding_dim=32,
            max_token_size=4096,
            func=_fake_embedding,
        ),
    )
    monkeypatch.setattr(
        engine, "indexing_kwargs_from_settings", lambda: {"max_parallel_parse_native": 1}
    )
    monkeypatch.setattr(
        engine, "constructor_kwargs_from_settings", lambda: {"entity_extract_max_gleaning": 0}
    )


async def _process(working_dir: Path, staged: ingress.StagedDocument) -> dict:
    rag = engine.build_rag(working_dir, enable_vlm=False)
    await engine.initialize(rag)
    failed = True
    try:
        track_id = await engine.enqueue(rag, [staged])
        await rag.apipeline_process_enqueue_documents()
        rows = await rag.aget_docs_by_track_id(track_id)
        failed = False
        return rows
    finally:
        await engine.finalize(rag, cancel_pending=failed)


def test_real_rc2_raw_bridge_reaches_processed(monkeypatch, tmp_path: Path) -> None:
    _configure_real_sdk(monkeypatch)
    working = tmp_path / "version-1"
    working.mkdir()
    source = tmp_path / "notes.md"
    source.write_text("DeepTutor native LightRAG fixture.", encoding="utf-8")
    staged = ingress.freeze_document(
        working,
        source,
        ParsedDocument(
            markdown="# Native fixture\n\nDeepTutor uses LightRAG.",
            engine="text_only",
            source_hash="fixture-source",
            parser_signature="fixture-parser",
        ),
    )

    rows = asyncio.run(_process(working, staged))

    assert len(rows) == 1
    row = next(iter(rows.values()))
    assert getattr(row.status, "value", row.status) == "processed"
    assert row.file_path == "notes.md"
    assert storage.has_output(working) is True
    monkeypatch.setattr(
        "deeptutor.services.rag.embedding_signature.embedding_meta_fields",
        lambda: {"embedding": "fixture"},
    )
    storage.write_meta(working)
    assert storage.meta_is_native_published(working) is True
    assert list_kb_versions(tmp_path)[0]["ready"] is True
    meta = storage._read_meta(working)
    assert meta["parser_inputs"] == [{"engine": "text_only", "parser_signature": "fixture-parser"}]


def test_real_rc2_sidecar_bridge_reaches_processed(monkeypatch, tmp_path: Path) -> None:
    _configure_real_sdk(monkeypatch)
    working = tmp_path / "version-1"
    working.mkdir()
    source = tmp_path / "paper.pdf"
    source.write_bytes(b"%PDF-1.4 fixture")
    assets = tmp_path / "assets"
    assets.mkdir()
    (assets / "figure.png").write_bytes(b"fixture image")
    staged = ingress.freeze_document(
        working,
        source,
        ParsedDocument(
            markdown="# Structured fixture",
            blocks=[
                {"type": "text", "text": "Structured fixture", "text_level": 1, "page_idx": 0},
                {"type": "text", "text": "DeepTutor structured body.", "page_idx": 0},
                {
                    "type": "table",
                    "table_body": "<table><tr><td>value</td></tr></table>",
                    "page_idx": 0,
                },
                {"type": "image", "img_path": "figure.png", "page_idx": 0},
                {"type": "equation", "text": "x^2", "page_idx": 0},
            ],
            asset_dir=assets,
            engine="mineru",
            source_hash="fixture-source",
            parser_signature="fixture-parser",
        ),
    )
    # The image asset still passes through the real Sidecar writer; disabling
    # i only avoids requiring a vision call in this deterministic offline test.
    staged = replace(staged, process_options=staged.process_options.replace("i", ""))

    rows = asyncio.run(_process(working, staged))

    assert len(rows) == 1
    row = next(iter(rows.values()))
    assert getattr(row.status, "value", row.status) == "processed"
    assert row.file_path == "paper.pdf"
    assert storage.has_output(working) is True
    assert list((ingress.pending_root(working) / "__parsed__").glob("paper.pdf"))


def test_real_rc2_append_uses_only_new_doc_and_links_existing_entity(
    monkeypatch, tmp_path: Path
) -> None:
    async def entity_llm(prompt, **_kwargs) -> str:
        if "Second document" in prompt:
            return (
                "(entity<|#|>SECOND<|#|>CONCEPT<|#|>Second entity)\n"
                "(relation<|#|>SHARED<|#|>SECOND<|#|>links<|#|>Shared links to Second)"
                "<|COMPLETE|>"
            )
        return "(entity<|#|>SHARED<|#|>CONCEPT<|#|>Shared entity)<|COMPLETE|>"

    _configure_real_sdk(monkeypatch, entity_llm)
    working = tmp_path / "version-1"
    working.mkdir()
    first_source = tmp_path / "first.md"
    second_source = tmp_path / "second.md"
    first_source.write_text("First document names Shared.", encoding="utf-8")
    second_source.write_text("Second document links Shared to Second.", encoding="utf-8")
    first = ingress.freeze_document(
        working,
        first_source,
        ParsedDocument(markdown="First document names Shared.", engine="text_only"),
    )

    async def run() -> None:
        rag = engine.build_rag(working)
        await engine.initialize(rag)
        failed = True
        try:
            first_track = await engine.enqueue(rag, [first])
            await rag.apipeline_process_enqueue_documents()
            first_rows = await rag.aget_docs_by_track_id(first_track)
            assert [row.file_path for row in first_rows.values()] == ["first.md"]

            second = ingress.freeze_document(
                working,
                second_source,
                ParsedDocument(
                    markdown="Second document links Shared to Second.", engine="text_only"
                ),
            )
            second_track = await engine.enqueue(rag, [second])
            await rag.apipeline_process_enqueue_documents()
            second_rows = await rag.aget_docs_by_track_id(second_track)
            assert [row.file_path for row in second_rows.values()] == ["second.md"]
            assert await rag.chunk_entity_relation_graph.get_node("SHARED") is not None
            assert await rag.chunk_entity_relation_graph.get_node("SECOND") is not None
            assert await rag.chunk_entity_relation_graph.get_edge("SHARED", "SECOND") is not None
            failed = False
        finally:
            await engine.finalize(rag, cancel_pending=failed)

    asyncio.run(run())
