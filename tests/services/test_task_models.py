"""The task service: configured like the LLM, inherited when empty."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from deeptutor.services.config.model_catalog import ModelCatalogService
from deeptutor.services.model_selection.tasks import task_service_configured


def _catalog(service: ModelCatalogService, **task: Any) -> dict[str, Any]:
    catalog = service.load()
    catalog["services"]["llm"]["profiles"] = [
        {
            "id": "llm-1",
            "name": "OpenAI",
            "binding": "openai",
            "base_url": "https://api.openai.com/v1",
            "api_key": "sk-live",
            "models": [{"id": "llm-model", "model": "gpt-5"}],
        }
    ]
    catalog["services"]["llm"]["active_profile_id"] = "llm-1"
    catalog["services"]["llm"]["active_model_id"] = "llm-model"
    catalog["services"]["task"].update(task)
    return catalog


def test_the_task_service_exists_and_starts_empty(tmp_path: Path) -> None:
    service = ModelCatalogService(path=tmp_path / "model_catalog.json")

    catalog = service.load()

    assert catalog["services"]["task"] == {
        "active_profile_id": None,
        "active_model_id": None,
        "profiles": [],
    }
    assert not task_service_configured(catalog)


def test_an_empty_task_service_inherits(tmp_path: Path) -> None:
    service = ModelCatalogService(path=tmp_path / "model_catalog.json")

    catalog = service.save(_catalog(service))

    assert not task_service_configured(catalog)


def test_a_configured_task_service_is_used(tmp_path: Path) -> None:
    service = ModelCatalogService(path=tmp_path / "model_catalog.json")
    catalog = service.save(
        _catalog(
            service,
            profiles=[
                {
                    "id": "task-1",
                    "name": "OpenAI",
                    "binding": "openai",
                    "base_url": "https://api.openai.com/v1",
                    "api_key": "sk-live",
                    "models": [{"id": "task-model", "model": "gpt-5-mini"}],
                }
            ],
            active_profile_id="task-1",
            active_model_id="task-model",
        )
    )

    assert task_service_configured(catalog)


def test_a_profile_without_a_model_id_still_inherits(tmp_path: Path) -> None:
    """Half-configured is not configured — a blank model would resolve to nothing."""
    service = ModelCatalogService(path=tmp_path / "model_catalog.json")
    catalog = service.save(
        _catalog(
            service,
            profiles=[
                {
                    "id": "task-1",
                    "name": "OpenAI",
                    "binding": "openai",
                    "api_key": "sk-live",
                    "models": [{"id": "task-model", "model": ""}],
                }
            ],
            active_profile_id="task-1",
            active_model_id="task-model",
        )
    )

    assert not task_service_configured(catalog)


def test_the_task_service_resolves_its_own_model(tmp_path: Path) -> None:
    from deeptutor.services.config.provider_runtime import resolve_llm_runtime_config

    service = ModelCatalogService(path=tmp_path / "model_catalog.json")
    catalog = service.save(
        _catalog(
            service,
            profiles=[
                {
                    "id": "task-1",
                    "name": "OpenAI",
                    "binding": "openai",
                    "base_url": "https://api.openai.com/v1",
                    "api_key": "sk-task",
                    "models": [{"id": "task-model", "model": "gpt-5-mini"}],
                }
            ],
            active_profile_id="task-1",
            active_model_id="task-model",
        )
    )

    task = resolve_llm_runtime_config(catalog, service=service, service_name="task")
    llm = resolve_llm_runtime_config(catalog, service=service)

    assert task.model == "gpt-5-mini"
    assert llm.model == "gpt-5"


def test_the_short_lived_per_task_pins_are_dropped(tmp_path: Path) -> None:
    service = ModelCatalogService(path=tmp_path / "model_catalog.json")
    catalog = _catalog(service)
    catalog["services"]["llm"]["tasks"] = {
        "session_title": {"profile_id": "llm-1", "model_id": "llm-model"}
    }

    saved = service.save(catalog)

    assert "tasks" not in saved["services"]["llm"]
