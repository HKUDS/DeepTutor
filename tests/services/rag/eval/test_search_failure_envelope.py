"""Keep production retrieval failures out of quality averages."""

from pathlib import Path

import pytest

from deeptutor.services.rag.eval import EvalDataset, evaluate_dataset
from deeptutor.services.rag.pipelines.llamaindex import pipeline as pipeline_module


@pytest.mark.asyncio
async def test_native_index_read_failure_is_excluded_from_quality_average(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    index_dir = tmp_path / "index"
    index_dir.mkdir()
    (index_dir / "docstore.json").write_text("{}", encoding="utf-8")
    pipeline = pipeline_module.LlamaIndexPipeline(
        kb_base_dir=str(tmp_path), signature_provider=lambda: None
    )
    monkeypatch.setattr(pipeline, "_configure_settings", lambda: None)
    monkeypatch.setattr(pipeline_module, "resolve_storage_dir_for_read", lambda *_: index_dir)

    def retrieve(*_, **__):
        return (index_dir / "missing-index.json").read_text(encoding="utf-8")

    monkeypatch.setattr(pipeline_module.storage, "retrieve_nodes", retrieve)

    async def search(query: str, **kwargs):
        if query == "working":
            return {"sources": [{"content": "alpha beta gamma delta"}]}
        return await pipeline.search(query, kwargs["kb_name"], top_k=kwargs["top_k"])

    dataset = EvalDataset.from_cases(
        [
            {"query": "broken", "gold": "alpha beta gamma delta"},
            {"query": "working", "gold": "alpha beta gamma delta"},
        ]
    )
    report = await evaluate_dataset(dataset, kb_name="example", search_fn=search)
    assert report.evaluations[0].failed
    assert "missing-index.json" in report.evaluations[0].error
    assert report.aggregate()["queries_failed"] == 1
    assert report.aggregate()["queries_scored"] == 1
    assert report.aggregate()["recall@5"] == 1.0
