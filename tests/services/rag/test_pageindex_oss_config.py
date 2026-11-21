"""PageIndex OSS indexing follows the background-task model, not the chat model."""

from __future__ import annotations

import asyncio
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


def test_inherited_task_model_uses_the_oauth_chat_model(catalog) -> None:
    catalog(llm=_codex_llm())

    assert resolve_oss_sdk_config() == ("deeptutor_oauth/gpt-6-luna", {})


@pytest.mark.asyncio
async def test_local_indexing_uses_the_native_provider_on_the_sdk_worker(
    catalog, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    pytest.importorskip("pageindex")
    from pageindex.local_api import LocalAPI
    from pageindex.utils import llm_acompletion, llm_completion

    from deeptutor.multi_user.context import get_current_user_or_none
    from deeptutor.multi_user.paths import local_admin_user, user_context
    from deeptutor.services.llm import provider_factory
    from deeptutor.services.llm.provider_core.base import LLMResponse
    from deeptutor.services.rag.pipelines.oauth_completion import OAuthModelAccessError
    from deeptutor.services.rag.pipelines.pageindex.client import PageIndexClient

    loop = asyncio.get_running_loop()
    owner = local_admin_user()

    class Provider:
        async def chat(self, **kwargs):
            assert asyncio.get_running_loop() is loop
            assert get_current_user_or_none() == owner
            assert kwargs["model"] == "gpt-6-luna"
            assert kwargs["messages"] == [{"role": "user", "content": "Summarize this page."}]
            return LLMResponse(content="A sample page.")

        async def aclose(self):
            pass

    def build_provider(config):
        assert config.binding == "openai_codex"
        return Provider()

    def index(self, _file_path):
        summary = llm_completion(self._model, "Summarize this page.")
        assert asyncio.run(llm_acompletion(self._summary_model, "Summarize this page.")) == summary
        return [{"title": summary, "start_index": 1, "end_index": 1}], summary

    catalog(llm=_codex_llm())
    monkeypatch.setattr(provider_factory, "build_isolated_provider", build_provider)
    monkeypatch.setattr(LocalAPI, "_extract_page_texts", lambda *_: ["Sample page"])
    monkeypatch.setattr(LocalAPI, "_index_flash", index)
    doc = tmp_path / "example.pdf"
    doc.touch()
    with pytest.raises(OAuthModelAccessError, match="explicit DeepTutor user"):
        PageIndexClient.local(tmp_path / "library")
    with user_context(owner):
        client = PageIndexClient.local(tmp_path / "library")
        assert (await client.submit_document(doc)).startswith("pi-")


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
