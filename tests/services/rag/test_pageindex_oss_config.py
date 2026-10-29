"""PageIndex OSS indexing follows the background-task model, not the chat model."""

from __future__ import annotations

from pathlib import Path

import pytest

from deeptutor.services.config import provider_runtime
from deeptutor.services.config.model_catalog import ModelCatalogService
from deeptutor.services.model_selection import tasks
from deeptutor.services.rag.pipelines.pageindex.client import resolve_oss_sdk_config


def _codex_llm() -> dict:
    return {
        "active_profile_id": "codex",
        "active_model_id": "codex-model",
        "profiles": [
            {
                "id": "codex",
                "name": "OpenAI Codex",
                "binding": "openai_codex",
                "models": [{"id": "codex-model", "model": "gpt-6-luna"}],
            }
        ],
    }


def _anthropic_profile(model: str) -> dict:
    return {
        "id": "claude",
        "name": "Anthropic",
        "binding": "anthropic",
        "api_key": "sk-test",
        "models": [{"id": "claude-model", "model": model}],
    }


@pytest.fixture
def catalog(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    service = ModelCatalogService(path=tmp_path / "model_catalog.json")
    monkeypatch.setattr(provider_runtime, "get_model_catalog_service", lambda: service)
    monkeypatch.setattr(tasks, "get_model_catalog_service", lambda: service)

    def save(**services: dict) -> None:
        data = service.load()
        data["services"].update(services)
        service.save(data)

    return save


def test_task_model_indexes_while_chat_stays_on_oauth(catalog) -> None:
    llm = _codex_llm()
    llm["profiles"].append(_anthropic_profile("claude-haiku"))
    catalog(
        llm=llm,
        task={
            "mode": "reference",
            "selection": {"profile_id": "claude", "model_id": "claude-model"},
            "active_profile_id": None,
            "active_model_id": None,
            "profiles": [],
        },
    )

    model, backend = resolve_oss_sdk_config()

    assert model == "anthropic/claude-haiku"
    assert backend["api_key"] == "sk-test"


def test_inherited_task_model_still_rejects_an_oauth_chat_model(catalog) -> None:
    catalog(llm=_codex_llm())

    with pytest.raises(RuntimeError, match="OAuth-only"):
        resolve_oss_sdk_config()


def test_inherited_task_model_uses_the_api_key_chat_model(catalog) -> None:
    llm = {
        "active_profile_id": "claude",
        "active_model_id": "claude-model",
        "profiles": [_anthropic_profile("claude-sonnet")],
    }
    catalog(llm=llm)

    model, _backend = resolve_oss_sdk_config()

    assert model == "anthropic/claude-sonnet"


def test_anthropic_base_url_drops_the_version_segment_litellm_appends(catalog) -> None:
    profile = _anthropic_profile("claude-haiku")
    profile["base_url"] = "https://api.anthropic.com/v1"
    catalog(
        llm={
            "active_profile_id": "claude",
            "active_model_id": "claude-model",
            "profiles": [profile],
        }
    )

    _model, backend = resolve_oss_sdk_config()

    assert backend["api_base"] == "https://api.anthropic.com"
