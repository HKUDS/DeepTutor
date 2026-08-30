"""The two task call sites actually run inside the scope they claim to.

Configuring a task model is only worth anything if the LLM call at the other
end resolves it. Both tests assert the model *observed from inside
the call*: a scope wrapped around the wrong statement, or a call site that was
never wired at all, still looks correct from the outside.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from typing import Any

import pytest

from deeptutor.services.config import model_catalog as model_catalog_module
from deeptutor.services.config.model_catalog import ModelCatalogService
from deeptutor.services.llm.config import clear_llm_config_cache, get_llm_config


class _FakePathService:
    def __init__(self, root: Path) -> None:
        self._root = root

    def get_settings_file(self, name: str) -> Path:
        return self._root / "settings" / f"{name}.json"


def _pin(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, task_model: str | None) -> None:
    """Point every catalog reader at a tmp catalog, optionally with a task model.

    Patching the path service rather than ``get_model_catalog_service`` is
    deliberate: several modules import that function by value, so patching it
    in one place would leave the others resolving the real user's catalog.
    """
    fake = _FakePathService(tmp_path)
    monkeypatch.setattr(model_catalog_module, "get_path_service", lambda: fake)

    service = ModelCatalogService(path=fake.get_settings_file("model_catalog"))
    catalog = service.load()
    catalog["services"]["llm"]["profiles"] = [
        {
            "id": "llm-1",
            "name": "OpenAI",
            "binding": "openai",
            "base_url": "https://api.openai.com/v1",
            "api_key": "sk-test",
            "models": [
                {"id": "model-default", "model": "gpt-5"},
                {"id": "model-task", "model": "gpt-5-mini"},
            ],
        }
    ]
    catalog["services"]["llm"]["active_profile_id"] = "llm-1"
    catalog["services"]["llm"]["active_model_id"] = "model-default"
    if task_model:
        catalog["services"]["task"]["profiles"] = [
            {
                "id": "task-1",
                "name": "OpenAI",
                "binding": "openai",
                "base_url": "https://api.openai.com/v1",
                "api_key": "sk-test",
                "models": [{"id": "task-model", "model": task_model}],
            }
        ]
        catalog["services"]["task"]["active_profile_id"] = "task-1"
        catalog["services"]["task"]["active_model_id"] = "task-model"
    service.save(catalog)

    # get_instance memoizes per resolved path; every reader must land on the
    # instance holding this tmp file rather than a cached admin-scope one.
    monkeypatch.setattr(
        ModelCatalogService, "get_instance", classmethod(lambda cls, path=None: service)
    )
    clear_llm_config_cache()


@pytest.fixture(autouse=True)
def _clear_llm_cache() -> Any:
    clear_llm_config_cache()
    yield
    clear_llm_config_cache()


def test_starter_generation_calls_the_task_model(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _pin(tmp_path, monkeypatch, "gpt-5-mini")

    from deeptutor.services import suggestions
    import deeptutor.services.llm as llm

    observed: list[str] = []

    async def _complete(prompt: str, **kwargs: Any) -> str:
        observed.append(get_llm_config().model)
        return "[]"

    monkeypatch.setattr(llm, "complete", _complete)

    material = suggestions._Material(
        profile="A learner.",
        topics=[suggestions._Topic(surface="chat", label="Agentic RAG", days_ago=1)],
    )
    asyncio.run(suggestions._generate("en", material))

    assert observed == ["gpt-5-mini"]


def test_starter_generation_inherits_when_unconfigured(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _pin(tmp_path, monkeypatch, None)

    from deeptutor.services import suggestions
    import deeptutor.services.llm as llm

    observed: list[str] = []

    async def _complete(prompt: str, **kwargs: Any) -> str:
        observed.append(get_llm_config().model)
        return "[]"

    monkeypatch.setattr(llm, "complete", _complete)

    material = suggestions._Material(
        profile="A learner.",
        topics=[suggestions._Topic(surface="chat", label="Agentic RAG", days_ago=1)],
    )
    asyncio.run(suggestions._generate("en", material))

    assert observed == ["gpt-5"]


class _Store:
    def __init__(self) -> None:
        self.title = ""

    async def get_session(self, session_id: str) -> dict[str, Any]:
        return {"id": session_id, "title": "New conversation"}

    async def get_messages(self, session_id: str) -> list[dict[str, Any]]:
        return [
            {"role": "user", "content": "Explain the chain rule."},
            {"role": "assistant", "content": "It composes derivatives."},
        ]

    async def update_session_title(self, session_id: str, title: str) -> None:
        self.title = title


class _Runtime:
    def __init__(self) -> None:
        self.store = _Store()

    async def _publish_live_event(self, execution: Any, event: Any) -> Any:
        return event


def _run_title(monkeypatch: pytest.MonkeyPatch, observed: list[str]) -> _Runtime:
    import deeptutor.services.llm as llm
    from deeptutor.services.session import turn_runtime as turn_runtime_module

    async def _stream(**kwargs: Any):
        observed.append(get_llm_config().model)
        yield "Chain rule basics"

    monkeypatch.setattr(llm, "stream", _stream)

    runtime = _Runtime()
    asyncio.run(
        turn_runtime_module.TurnRuntimeManager._maybe_generate_session_title(
            runtime,
            execution=object(),
            session_id="session-1",
            ui_language="en",
        )
    )
    return runtime


def test_title_generation_calls_the_task_model(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _pin(tmp_path, monkeypatch, "gpt-5-mini")

    observed: list[str] = []
    runtime = _run_title(monkeypatch, observed)

    assert observed == ["gpt-5-mini"]
    assert runtime.store.title == "Chain rule basics"


def test_title_generation_inherits_the_turn_model_when_unconfigured(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    _pin(tmp_path, monkeypatch, None)

    from deeptutor.services.llm.config import (
        LLMConfig,
        reset_scoped_llm_config,
        set_scoped_llm_config,
    )

    # Stand in for the turn's own scope: unpinned must keep resolving whatever
    # the conversation is already running on, not the global default.
    token = set_scoped_llm_config(LLMConfig(model="turn-model", api_key="sk-test"))
    try:
        observed: list[str] = []
        _run_title(monkeypatch, observed)
    finally:
        reset_scoped_llm_config(token)

    assert observed == ["turn-model"]
