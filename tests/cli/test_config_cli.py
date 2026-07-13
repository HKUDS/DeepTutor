"""CLI config command tests."""

from __future__ import annotations

from types import SimpleNamespace

from typer.testing import CliRunner

from deeptutor_cli.main import app

runner = CliRunner()


def test_config_show_handles_missing_embedding(monkeypatch) -> None:
    """CLI-only defaults skip embedding setup, so config show must not traceback."""
    import deeptutor.services.config as config

    monkeypatch.setattr(
        config,
        "load_system_settings",
        lambda: {"backend_port": 8001, "frontend_port": 3782},
    )
    monkeypatch.setattr(
        config,
        "resolve_llm_runtime_config",
        lambda: SimpleNamespace(
            binding_hint="openai",
            provider_name="openai",
            provider_mode="standard",
            model="gpt-4o-mini",
            effective_url="https://api.openai.com/v1",
            api_version=None,
            extra_headers={},
            api_key="",
        ),
    )

    def _missing_embedding() -> None:
        raise ValueError("No active embedding model is configured.")

    monkeypatch.setattr(config, "resolve_embedding_runtime_config", _missing_embedding)
    monkeypatch.setattr(
        config,
        "resolve_search_runtime_config",
        lambda: SimpleNamespace(
            provider="duckduckgo",
            requested_provider="duckduckgo",
            status="ok",
            fallback_reason=None,
            base_url="",
            proxy=None,
            api_key="",
        ),
    )
    monkeypatch.setattr(
        config,
        "load_config_with_main",
        lambda _name: {"system": {"language": "en"}, "tools": {}},
    )

    result = runner.invoke(app, ["config", "show"])

    assert result.exit_code == 0, result.output
    assert '"status": "not_configured"' in result.output
    assert "No active embedding model is configured." in result.output
