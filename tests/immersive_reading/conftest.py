"""Shared isolated storage for immersive-reading tests."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from deeptutor.immersive_reading.service import ImmersiveReadingService
from deeptutor.services.path_service import PathService


@pytest.fixture
def reading_service(tmp_path, monkeypatch) -> ImmersiveReadingService:
    import deeptutor.immersive_reading.service as service_module

    paths = PathService(workspace_root=tmp_path / "data")
    monkeypatch.setattr(service_module, "get_path_service", lambda: paths)
    monkeypatch.setattr(
        service_module,
        "get_llm_config",
        lambda: SimpleNamespace(
            model="test-model",
            binding="test-binding",
            context_window=128_000,
            max_tokens=4_096,
        ),
    )
    # Clear the class-level dictionary cache so tests are isolated.
    ImmersiveReadingService._dict_cache.clear()
    service = ImmersiveReadingService()
    service._translation_cache.clear()
    service._translation_tasks.clear()
    service._translation_jobs.clear()
    service._translation_jobs_lock = asyncio.Lock()
    service._translation_cache_db_initialized = False
    service._ollama_models_cache = None
    return service


@pytest.fixture
def imported_document(reading_service: ImmersiveReadingService) -> dict:
    padding = "A quiet detail carries the story forward without changing its direction. " * 8
    source = "\n\n".join(
        [
            "Title page and publication notes.",
            "# Chapter 1\nAda follows a brass compass through the old observatory. " + padding,
            "# Chapter 2\nAda follows a brass compass through the old harbor. " + padding,
            "# Chapter 3\nAda follows a brass compass through the old library. " + padding,
        ]
    )
    return reading_service.import_document("ada-journey.txt", source.encode("utf-8"))
