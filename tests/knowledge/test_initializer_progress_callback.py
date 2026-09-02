from __future__ import annotations

from pathlib import Path

import pytest

import deeptutor.knowledge.initializer as initializer_module
from deeptutor.knowledge.progress_tracker import ProgressStage


@pytest.mark.asyncio
async def test_initialize_knowledge_base_forwards_progress_callback(
    monkeypatch, tmp_path: Path
) -> None:
    seen: list[dict[str, object]] = []

    class FakeInitializer:
        def __init__(self, *, kb_name, base_dir, progress_tracker, **kwargs):
            self.kb_name = kb_name
            self.base_dir = Path(base_dir)
            self.progress_tracker = progress_tracker
            self.raw_dir = self.base_dir / kb_name / "raw"

        def create_directory_structure(self) -> None:
            self.raw_dir.mkdir(parents=True, exist_ok=True)

        def copy_documents(self, source_files: list[str]) -> list[str]:
            return list(source_files)

        async def process_documents(self) -> bool:
            self.progress_tracker.update(
                ProgressStage.PROCESSING_DOCUMENTS,
                "sentinel progress",
                current=1,
                total=2,
            )
            return True

    monkeypatch.setattr(initializer_module, "KnowledgeBaseInitializer", FakeInitializer)

    result = await initializer_module.initialize_knowledge_base(
        kb_name="callback-kb",
        source_files=["/tmp/sentinel.md"],
        base_dir=str(tmp_path),
        progress_callback=seen.append,
    )

    assert result is True
    assert seen
    assert seen[-1]["stage"] == "processing_documents"
    assert seen[-1]["message"] == "sentinel progress"
