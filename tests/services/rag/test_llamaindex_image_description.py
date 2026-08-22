"""Concurrency, per-image timeout, and progress for image description.

``_load_image_nodes`` describes each extracted image with the configured
multimodal LLM. With ~92 images per KB this is the slowest indexing step, so it
now fans out (bounded by a Semaphore), enforces a per-image timeout, and
reports progress via ``image_progress_callback``. These tests pin that behavior.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
import time

import pytest


def _make_images(tmp_path: Path, names: list[str]) -> list[Path]:
    paths: list[Path] = []
    for name in names:
        p = tmp_path / name
        p.write_bytes(b"\x89PNG\r\n")
        paths.append(p)
    return paths


def _install_multimodal_clients(
    monkeypatch: pytest.MonkeyPatch,
    *,
    complete_fn,
    limits: tuple[int, float] = (4, 60.0),
) -> None:
    """Wire fake multimodal embedding + vision clients so images are described."""
    from types import SimpleNamespace

    from deeptutor.services.rag.pipelines.llamaindex import document_loader as loader_module

    monkeypatch.setattr(loader_module, "image_description_limits", lambda: limits)

    class _EmbeddingClient:
        config = SimpleNamespace(binding="siliconflow", model="qwen3-vl")

        def supports_multimodal_contents(self) -> bool:
            return True

        async def embed_contents(self, contents):
            return [[0.1, 0.2, 0.3] for _ in contents]

    class _VisionClient:
        config = SimpleNamespace(binding="openai", model="gpt-4o")

        def supports_multimodal_images(self) -> bool:
            return True

        async def complete(self, prompt, **kwargs):
            return await complete_fn(prompt, **kwargs)

    monkeypatch.setattr(loader_module, "get_embedding_client", lambda: _EmbeddingClient())
    monkeypatch.setattr(loader_module, "get_llm_client", lambda: _VisionClient())


@pytest.mark.asyncio
async def test_image_description_runs_bounded_concurrently(tmp_path, monkeypatch):
    pytest.importorskip("llama_index.core")
    from deeptutor.services.rag.pipelines.llamaindex import document_loader as loader_module

    state = {"inflight": 0, "max": 0}

    async def complete(prompt, **kwargs):
        state["inflight"] += 1
        state["max"] = max(state["max"], state["inflight"])
        await asyncio.sleep(0.05)  # let multiple calls overlap
        state["inflight"] -= 1
        return "desc"

    _install_multimodal_clients(monkeypatch, complete_fn=complete)

    paths = _make_images(tmp_path, [f"img{i}.png" for i in range(10)])
    docs = await loader_module.LlamaIndexDocumentLoader().load([str(p) for p in paths])

    assert 2 <= state["max"] <= 4  # concurrent, but capped by the semaphore
    assert len(docs) == 10


@pytest.mark.asyncio
async def test_image_description_per_image_timeout_skips_and_keeps_order(tmp_path, monkeypatch):
    pytest.importorskip("llama_index.core")
    from deeptutor.services.rag.pipelines.llamaindex import document_loader as loader_module

    async def complete(prompt, image_filename=None, **kwargs):
        if "slow" in (image_filename or ""):
            await asyncio.sleep(1.0)  # exceeds the 0.2s timeout -> skipped
        return "ok"

    _install_multimodal_clients(monkeypatch, complete_fn=complete, limits=(4, 0.2))

    names = ["slow0.png", "fast0.png", "slow1.png", "fast1.png", "slow2.png", "fast2.png"]
    paths = _make_images(tmp_path, names)

    start = time.monotonic()
    docs = await loader_module.LlamaIndexDocumentLoader().load([str(p) for p in paths])
    elapsed = time.monotonic() - start

    # Slow images time out and are skipped; fast ones are kept in original order.
    assert [d.metadata["file_name"] for d in docs] == ["fast0.png", "fast1.png", "fast2.png"]
    assert elapsed < 2.0  # did not hang


@pytest.mark.asyncio
async def test_image_description_reports_progress(tmp_path, monkeypatch):
    pytest.importorskip("llama_index.core")
    from deeptutor.services.rag.pipelines.llamaindex import document_loader as loader_module

    async def complete(prompt, **kwargs):
        return "desc"

    _install_multimodal_clients(monkeypatch, complete_fn=complete)

    callbacks: list[tuple[int, int]] = []
    paths = _make_images(tmp_path, [f"img{i}.png" for i in range(5)])
    await loader_module.LlamaIndexDocumentLoader().load(
        [str(p) for p in paths],
        image_progress_callback=lambda c, t: callbacks.append((c, t)),
    )

    assert len(callbacks) == 5
    # `current` is a completion counter, so it climbs 1..N regardless of order.
    assert [c for c, _ in callbacks] == [1, 2, 3, 4, 5]
    assert all(t == 5 for _, t in callbacks)
    assert callbacks[-1] == (5, 5)


@pytest.mark.asyncio
async def test_image_description_skips_failed_and_empty(tmp_path, monkeypatch):
    pytest.importorskip("llama_index.core")
    from deeptutor.services.rag.pipelines.llamaindex import document_loader as loader_module

    async def complete(prompt, image_filename=None, **kwargs):
        name = image_filename or ""
        if "raise" in name:
            raise RuntimeError("boom")
        if "empty" in name:
            return ""
        return "ok"

    _install_multimodal_clients(monkeypatch, complete_fn=complete)

    names = ["ok0.png", "raise0.png", "empty0.png", "ok1.png"]
    paths = _make_images(tmp_path, names)
    docs = await loader_module.LlamaIndexDocumentLoader().load([str(p) for p in paths])

    # Only the two "ok" images survive; order preserved.
    assert [d.metadata["file_name"] for d in docs] == ["ok0.png", "ok1.png"]
