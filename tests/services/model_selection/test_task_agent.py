"""task_model_agent binds an agent to the Settings task model, or returns None."""

from __future__ import annotations

from types import SimpleNamespace

from deeptutor.services.config import model_catalog, provider_runtime
from deeptutor.services.model_selection import runtime, tasks
from deeptutor.services.model_selection.task_agent import task_model_agent


class _Agent:
    def __init__(self, *, api_key, base_url, api_version) -> None:
        self.api_key, self.base_url, self.api_version = api_key, base_url, api_version
        self.model, self.binding = "main-model", "openai"
        self.calls: list[dict] = []

    def stream_llm(self, *args, reasoning_effort=None, **kwargs):
        self.calls.append({"reasoning_effort": reasoning_effort, **kwargs})
        return "stream"


def _patch(monkeypatch, *, configured: bool, effort: str | None = None) -> None:
    monkeypatch.setattr(
        model_catalog, "get_model_catalog_service", lambda: SimpleNamespace(load=lambda: {})
    )
    monkeypatch.setattr(tasks, "catalog_for_task", lambda catalog, kind: catalog)
    monkeypatch.setattr(tasks, "task_service_configured", lambda catalog: configured)
    monkeypatch.setattr(provider_runtime, "resolve_llm_runtime_config", lambda c, service_name: c)
    monkeypatch.setattr(
        runtime,
        "llm_config_from_resolved",
        lambda resolved: SimpleNamespace(
            api_key="k",
            base_url="https://task.example/v1",
            api_version=None,
            model="fast-model",
            binding="zhipu",
            reasoning_effort=effort,
        ),
    )


def test_returns_none_without_a_task_model(monkeypatch) -> None:
    _patch(monkeypatch, configured=False)
    assert task_model_agent(_Agent) is None


def test_binds_the_task_model(monkeypatch) -> None:
    _patch(monkeypatch, configured=True)
    agent = task_model_agent(_Agent)
    assert agent is not None
    assert (agent.model, agent.binding, agent.base_url) == (
        "fast-model",
        "zhipu",
        "https://task.example/v1",
    )
    agent.stream_llm(user_prompt="x")
    assert agent.calls[-1]["reasoning_effort"] is None


def test_applies_the_task_models_reasoning_effort(monkeypatch) -> None:
    _patch(monkeypatch, configured=True, effort="none")
    agent = task_model_agent(_Agent)
    agent.stream_llm(user_prompt="x")
    assert agent.calls[-1]["reasoning_effort"] == "none"
    agent.stream_llm(user_prompt="x", reasoning_effort="high")
    assert agent.calls[-1]["reasoning_effort"] == "high"


def test_resolution_errors_fall_back(monkeypatch) -> None:
    def boom():
        raise RuntimeError("catalog unreadable")

    monkeypatch.setattr(model_catalog, "get_model_catalog_service", boom)
    assert task_model_agent(_Agent) is None
