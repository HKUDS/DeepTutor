"""The Settings task-model probe follows the background-task selection."""

from __future__ import annotations

from pathlib import Path

import pytest

from deeptutor.services.config import test_runner as test_runner_module
from deeptutor.services.config.model_catalog import ModelCatalogService
from deeptutor.services.config.test_runner import ConfigTestRunner, TestRun
from deeptutor.services.llm import factory as llm_factory


def test_unconfigured_task_probe_skips_the_llm_request(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service = ModelCatalogService(path=tmp_path / "model_catalog.json")
    monkeypatch.setattr(test_runner_module, "get_model_catalog_service", lambda: service)

    async def unexpected_llm_probe(_run: TestRun, _catalog: dict) -> None:
        raise AssertionError("an inherited task model should not start an LLM probe")

    runner = ConfigTestRunner()
    monkeypatch.setattr(runner, "_test_llm", unexpected_llm_probe)
    run = TestRun(id="task-inherits", service="task")

    runner._run_sync(run, service.load())

    assert run.status == "completed"
    assert any(
        event["type"] == "completed" and "inherit the main LLM" in event["message"]
        for event in run.events
    )


@pytest.mark.asyncio
async def test_configured_task_probe_preserves_the_selected_wire_format(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    service = ModelCatalogService(path=tmp_path / "model_catalog.json")
    catalog = service.load()
    catalog["services"]["task"] = {
        "active_profile_id": "task-profile",
        "active_model_id": "task-model",
        "profiles": [
            {
                "id": "task-profile",
                "name": "Responses relay",
                "binding": "custom",
                "base_url": "https://relay.example/v1",
                "api_key": "test-key",
                "api_format": "openai_responses",
                "models": [{"id": "task-model", "model": "gpt-4o-mini"}],
            }
        ],
    }
    captured: dict = {}

    async def fake_complete(config, **kwargs):
        captured["config"] = config
        captured["kwargs"] = kwargs
        return "Configuration check"

    monkeypatch.setattr(llm_factory, "complete_with_config", fake_complete)
    run = TestRun(id="task-responses", service="task")

    await ConfigTestRunner()._test_task(run, catalog)

    assert captured["config"].model == "gpt-4o-mini"
    assert captured["config"].wire_api == "responses"
    assert captured["config"].api_format == "openai_responses"
    assert captured["kwargs"]["prompt"].startswith("Write a title")
    assert any(key in captured["kwargs"] for key in ("max_tokens", "max_completion_tokens"))
    assert not any(event["type"] == "context_window" for event in run.events)
    assert any(event["type"] == "response" for event in run.events)
