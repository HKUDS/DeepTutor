"""Tests for LLM diagnostic probe max_tokens configuration via agents.yaml."""

from __future__ import annotations

from pathlib import Path
import textwrap
from typing import Any
from unittest.mock import AsyncMock, patch

import pytest
import yaml

from deeptutor.services.config import loader as loader_module
from deeptutor.services.config.loader import get_agent_params

# ---------------------------------------------------------------------------
# get_agent_params("llm_probe") — reads diagnostics.llm_probe from agents.yaml
# ---------------------------------------------------------------------------


def _write_agents_yaml(tmp_path: Path, content: dict[str, Any]) -> Path:
    settings_dir = tmp_path / "data" / "user" / "settings"
    settings_dir.mkdir(parents=True, exist_ok=True)
    agents_file = settings_dir / "agents.yaml"
    agents_file.write_text(yaml.dump(content), encoding="utf-8")
    return tmp_path


class TestGetAgentParamsLlmProbe:
    """Verify get_agent_params correctly resolves ``diagnostics.llm_probe``."""

    def test_reads_configured_max_tokens(self, tmp_path: Path, monkeypatch):
        project_root = _write_agents_yaml(
            tmp_path,
            {
                "diagnostics": {"llm_probe": {"max_tokens": 2048}},
            },
        )
        monkeypatch.setattr(loader_module, "PROJECT_ROOT", project_root)
        params = get_agent_params("llm_probe")
        assert params["max_tokens"] == 2048

    def test_uses_default_when_section_absent(self, tmp_path: Path, monkeypatch):
        project_root = _write_agents_yaml(
            tmp_path,
            {
                "capabilities": {"solve": {"temperature": 0.3}},
            },
        )
        monkeypatch.setattr(loader_module, "PROJECT_ROOT", project_root)
        params = get_agent_params("llm_probe")
        assert params["max_tokens"] == 4096
        assert params["temperature"] == 0.5

    def test_uses_default_when_max_tokens_key_absent(self, tmp_path: Path, monkeypatch):
        project_root = _write_agents_yaml(
            tmp_path,
            {
                "diagnostics": {"llm_probe": {"temperature": 0.1}},
            },
        )
        monkeypatch.setattr(loader_module, "PROJECT_ROOT", project_root)
        params = get_agent_params("llm_probe")
        assert params["max_tokens"] == 4096
        assert params["temperature"] == 0.1

    def test_custom_value_overrides_default(self, tmp_path: Path, monkeypatch):
        project_root = _write_agents_yaml(
            tmp_path,
            {
                "diagnostics": {"llm_probe": {"max_tokens": 512, "temperature": 0.2}},
            },
        )
        monkeypatch.setattr(loader_module, "PROJECT_ROOT", project_root)
        params = get_agent_params("llm_probe")
        assert params["max_tokens"] == 512
        assert params["temperature"] == 0.2


# ---------------------------------------------------------------------------
# _test_llm integration: verify probe picks up max_tokens from agents.yaml
# ---------------------------------------------------------------------------


@pytest.fixture()
def _patch_project_root(tmp_path: Path, monkeypatch):
    """Create a minimal agents.yaml and point PROJECT_ROOT at tmp_path."""
    project_root = _write_agents_yaml(
        tmp_path,
        {
            "diagnostics": {"llm_probe": {"max_tokens": 768}},
        },
    )
    monkeypatch.setattr(loader_module, "PROJECT_ROOT", project_root)
    return project_root


class TestLlmProbeUsesAgentsYaml:
    """End-to-end: ConfigTestRunner._test_llm reads max_tokens from agents.yaml."""

    @pytest.mark.asyncio
    @pytest.mark.usefixtures("_patch_project_root")
    async def test_probe_passes_configured_max_tokens(self, monkeypatch):
        from deeptutor.services import llm as llm_module
        from deeptutor.services.config import test_runner as test_runner_module
        from deeptutor.services.config.test_runner import ConfigTestRunner, TestRun

        captured_kwargs: dict[str, Any] = {}

        async def _fake_llm_complete(**kwargs):
            captured_kwargs.update(kwargs)
            return "OK I am gpt-4o-mini"

        monkeypatch.setattr(
            test_runner_module,
            "resolve_llm_runtime_config",
            lambda catalog: _stub_resolved_llm(),
        )
        monkeypatch.setattr(
            test_runner_module,
            "detect_context_window",
            _stub_context_window_detection,
        )
        monkeypatch.setattr(llm_module, "get_token_limit_kwargs", _real_get_token_limit_kwargs)
        monkeypatch.setattr(llm_module, "complete", _fake_llm_complete)
        monkeypatch.setattr(llm_module, "clear_llm_config_cache", lambda: None)

        runner = ConfigTestRunner()
        run = TestRun(id="test-llm-probe", service="llm")
        await runner._test_llm(run, catalog={})

        assert (
            captured_kwargs.get("max_tokens") == 768
            or captured_kwargs.get("max_completion_tokens") == 768
        )
        assert any(
            "Basic LLM completion succeeded" in str(event.get("message", ""))
            for event in run.events
        )

    @pytest.mark.asyncio
    async def test_probe_defaults_when_no_diagnostics_section(self, tmp_path, monkeypatch):
        """When diagnostics section is absent, falls back to get_agent_params default (4096)."""
        project_root = _write_agents_yaml(tmp_path, {"capabilities": {}})
        monkeypatch.setattr(loader_module, "PROJECT_ROOT", project_root)

        from deeptutor.services import llm as llm_module
        from deeptutor.services.config import test_runner as test_runner_module
        from deeptutor.services.config.test_runner import ConfigTestRunner, TestRun

        captured_kwargs: dict[str, Any] = {}

        async def _fake_llm_complete(**kwargs):
            captured_kwargs.update(kwargs)
            return "OK I am gpt-4o-mini"

        monkeypatch.setattr(
            test_runner_module,
            "resolve_llm_runtime_config",
            lambda catalog: _stub_resolved_llm(),
        )
        monkeypatch.setattr(
            test_runner_module,
            "detect_context_window",
            _stub_context_window_detection,
        )
        monkeypatch.setattr(llm_module, "get_token_limit_kwargs", _real_get_token_limit_kwargs)
        monkeypatch.setattr(llm_module, "complete", _fake_llm_complete)
        monkeypatch.setattr(llm_module, "clear_llm_config_cache", lambda: None)

        runner = ConfigTestRunner()
        run = TestRun(id="test-llm-probe-default", service="llm")
        await runner._test_llm(run, catalog={})

        assert (
            captured_kwargs.get("max_tokens") == 4096
            or captured_kwargs.get("max_completion_tokens") == 4096
        )

    @pytest.mark.asyncio
    async def test_probe_passes_runtime_api_version_and_reasoning_effort(self, monkeypatch):
        from deeptutor.services import llm as llm_module
        from deeptutor.services.config import test_runner as test_runner_module
        from deeptutor.services.config.test_runner import ConfigTestRunner, TestRun

        captured_kwargs: dict[str, Any] = {}

        async def _fake_llm_complete(**kwargs):
            captured_kwargs.update(kwargs)
            return "OK I am a reasoning model"

        monkeypatch.setattr(
            test_runner_module,
            "resolve_llm_runtime_config",
            lambda catalog: _stub_resolved_llm(
                api_version="2026-05-01",
                reasoning_effort="high",
            ),
        )
        monkeypatch.setattr(
            test_runner_module,
            "detect_context_window",
            _stub_context_window_detection,
        )
        monkeypatch.setattr(llm_module, "get_token_limit_kwargs", _real_get_token_limit_kwargs)
        monkeypatch.setattr(llm_module, "complete", _fake_llm_complete)
        monkeypatch.setattr(llm_module, "clear_llm_config_cache", lambda: None)

        runner = ConfigTestRunner()
        run = TestRun(id="test-llm-probe-runtime-fields", service="llm")
        await runner._test_llm(run, catalog={})

        assert captured_kwargs["api_version"] == "2026-05-01"
        assert captured_kwargs["reasoning_effort"] == "high"

    @pytest.mark.asyncio
    async def test_probe_reports_detected_context_window_without_persisting_catalog(
        self, tmp_path, monkeypatch
    ):
        from deeptutor.services import llm as llm_module
        from deeptutor.services.config import test_runner as test_runner_module
        from deeptutor.services.config.model_catalog import ModelCatalogService
        from deeptutor.services.config.test_runner import ConfigTestRunner, TestRun

        catalog = {
            "version": 1,
            "services": {
                "llm": {
                    "active_profile_id": "llm-p",
                    "active_model_id": "llm-m",
                    "profiles": [
                        {
                            "id": "llm-p",
                            "name": "LLM",
                            "binding": "openai",
                            "base_url": "https://api.example.com/v1",
                            "api_key": "sk-test",
                            "api_version": "",
                            "extra_headers": {},
                            "models": [
                                {
                                    "id": "llm-m",
                                    "name": "GPT",
                                    "model": "gpt-4o-mini",
                                }
                            ],
                        }
                    ],
                },
                "embedding": {
                    "active_profile_id": None,
                    "active_model_id": None,
                    "profiles": [],
                },
                "search": {"active_profile_id": None, "profiles": []},
            },
        }
        service = ModelCatalogService(path=tmp_path / "model_catalog.json")
        service.save(catalog)

        async def _fake_llm_complete(**_kwargs):
            return "OK I am gpt-4o-mini"

        monkeypatch.setattr(
            test_runner_module,
            "get_model_catalog_service",
            lambda: service,
        )
        monkeypatch.setattr(
            test_runner_module,
            "resolve_llm_runtime_config",
            lambda catalog: _stub_resolved_llm(),
        )
        monkeypatch.setattr(
            test_runner_module,
            "detect_context_window",
            _stub_metadata_context_window_detection,
        )
        monkeypatch.setattr(llm_module, "get_token_limit_kwargs", _real_get_token_limit_kwargs)
        monkeypatch.setattr(llm_module, "complete", _fake_llm_complete)
        monkeypatch.setattr(llm_module, "clear_llm_config_cache", lambda: None)

        runner = ConfigTestRunner()
        run = TestRun(id="test-llm-context-window", service="llm")
        await runner._test_llm(run, catalog=catalog)

        saved = service.load()
        saved_model = saved["services"]["llm"]["profiles"][0]["models"][0]
        assert "context_window" not in saved_model
        assert "context_window_source" not in saved_model
        assert "context_window_detected_at" not in saved_model
        context_event = next(event for event in run.events if event["type"] == "context_window")
        assert context_event["context_window"] == 128000
        assert context_event["source"] == "metadata"
        assert context_event["detected_at"] == "2026-04-24T08:00:00+00:00"
        assert not any(event["type"] == "catalog" for event in run.events)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _stub_resolved_llm(**overrides: Any):
    """Return a minimal resolved LLM config stub."""
    from deeptutor.services.config.provider_runtime import ResolvedLLMConfig

    values = {
        "model": "gpt-4o-mini",
        "api_key": "sk-test",
        "base_url": "https://api.example.com/v1",
        "effective_url": "https://api.example.com/v1",
        "binding": "openai",
        "provider_name": "openai",
        "provider_mode": "standard",
        "api_version": "",
        "extra_headers": {},
        "reasoning_effort": None,
    }
    values.update(overrides)
    return ResolvedLLMConfig(
        **values,
    )


def _real_get_token_limit_kwargs(model: str, max_tokens: int) -> dict[str, int]:
    """Inline reimplementation to avoid importing the full LLM stack in tests."""
    from deeptutor.services.llm.config import uses_max_completion_tokens

    if uses_max_completion_tokens(model):
        return {"max_completion_tokens": max_tokens}
    return {"max_tokens": max_tokens}


async def _stub_context_window_detection(*_args, **_kwargs):
    from deeptutor.services.config.context_window_detection import (
        ContextWindowDetectionResult,
    )

    return ContextWindowDetectionResult(
        context_window=65536,
        source="default",
        detail="stub",
        detected_at="2026-04-24T00:00:00+00:00",
    )


async def _stub_metadata_context_window_detection(*_args, **_kwargs):
    from deeptutor.services.config.context_window_detection import (
        ContextWindowDetectionResult,
    )

    return ContextWindowDetectionResult(
        context_window=128000,
        source="metadata",
        detail="stub",
        detected_at="2026-04-24T08:00:00+00:00",
    )
