"""Exercise the headless setup flow against real, isolated settings files."""

from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys

import pytest
from typer.testing import CliRunner

from deeptutor_cli.main import app
from deeptutor_cli.setup_config import select_runtime_home

runner = CliRunner()


@pytest.fixture
def runtime_home(tmp_path, monkeypatch):
    from deeptutor.multi_user import paths

    for name in (
        "PROJECT_ROOT",
        "ADMIN_WORKSPACE_ROOT",
        "USERS_ROOT",
        "SYSTEM_ROOT",
        "LEGACY_MULTI_USER_ROOT",
        "_path_services",
        "_legacy_migration_done",
    ):
        monkeypatch.setattr(paths, name, {} if name == "_path_services" else getattr(paths, name))
    home = tmp_path / "runtime"
    monkeypatch.setenv("DEEPTUTOR_HOME", str(home))
    monkeypatch.setenv("DT_SETUP_TEST_KEY", "setup-test-secret")
    # API imports during suite collection can export the developer's ports.
    # This fixture exercises saved settings, without operator env overrides.
    monkeypatch.delenv("BACKEND_PORT", raising=False)
    monkeypatch.delenv("FRONTEND_PORT", raising=False)
    select_runtime_home(home)
    yield home
    from deeptutor_cli.init_cmd import _reset_runtime_singletons

    _reset_runtime_singletons()


def apply_file(tmp_path, payload, *options):
    path = tmp_path / "setup.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    return runner.invoke(app, ["config", "apply", str(path), *options])


def test_setup_applies_runtime_resolvable_models_and_preserves_other_profiles(
    runtime_home, tmp_path
):
    from deeptutor.services.config import (
        get_model_catalog_service,
        get_runtime_settings_service,
        resolve_embedding_runtime_config,
        resolve_llm_runtime_config,
        resolve_search_runtime_config,
    )

    catalog_service = get_model_catalog_service()
    catalog = catalog_service.load()
    original = {
        "id": "existing",
        "name": "Keep me",
        "binding": "openai",
        "api_key": "existing-secret",
        "base_url": "https://api.openai.com/v1",
        "models": [{"id": "existing-model", "model": "existing-model"}],
    }
    catalog["services"]["llm"]["profiles"].append(original)
    catalog_service.save(catalog)
    runtime = get_runtime_settings_service()
    system = runtime.load_system(include_process_overrides=False)
    system["sandbox_allow_subprocess"] = False
    runtime.save_system(system)

    payload = {
        "llm": {
            "provider": "openai",
            "model": "chosen-model",
            "api_key_env": "DT_SETUP_TEST_KEY",
            "api_format": "openai_responses",
        },
        "embedding": {
            "provider": "gemini",
            "model": "gemini-embedding-2",
            "api_key_env": "DT_SETUP_TEST_KEY",
            "dimension": 3072,
        },
        "search": {"provider": "duckduckgo"},
        "system": {"backend_port": 8101, "frontend_port": 3882},
    }
    for _ in range(2):
        result = apply_file(tmp_path, payload)
        assert result.exit_code == 0, result.output
        assert json.loads(result.stdout)["status"] == "applied"
        assert "setup-test-secret" not in result.output

    profiles = catalog_service.load()["services"]["llm"]["profiles"]
    assert len(profiles) == 2
    assert profiles[0]["api_key"] == "existing-secret"
    assert profiles[0]["models"][0]["model"] == "existing-model"
    llm = resolve_llm_runtime_config()
    assert llm.model == "chosen-model"
    assert llm.api_key == "setup-test-secret"
    assert llm.api_format == "openai_responses"
    embedding = resolve_embedding_runtime_config()
    assert embedding.effective_url.endswith("/gemini-embedding-2:batchEmbedContents")
    assert embedding.dimension == 3072
    assert resolve_search_runtime_config().provider == "duckduckgo"
    saved_system = runtime.load_system(include_process_overrides=False)
    assert saved_system["backend_port"] == 8101
    assert saved_system["sandbox_allow_subprocess"] is False


def test_check_creates_no_runtime_files_and_apply_honors_explicit_home(runtime_home, tmp_path):
    target = tmp_path / "explicit-home"
    payload = {"llm": {"provider": "ollama", "model": "local-model"}}
    checked = apply_file(tmp_path, payload, "--home", str(target), "--check")
    assert checked.exit_code == 0, checked.output
    assert json.loads(checked.stdout)["status"] == "validated"
    assert not target.exists()
    assert not runtime_home.exists()

    applied = apply_file(tmp_path, payload, "--home", str(target))
    assert applied.exit_code == 0, applied.output
    assert (target / "data/user/settings/model_catalog.json").exists()
    assert not runtime_home.exists()
    shown = runner.invoke(app, ["config", "show", "--home", str(target)])
    assert shown.exit_code == 0, shown.output
    assert json.loads(shown.stdout)["llm"]["model"] == "local-model"


@pytest.mark.parametrize(
    "payload",
    [
        {},
        {"system": {"backend_port": 0}},
        {"system": {"frontend_port": True}},
        {"system": {"backend_port": 8001, "frontend_port": 8001}},
        {"llm": {"provider": "unknown", "model": "model"}},
        {"llm": {"provider": "openai", "model": "model", "api_key": "do-not-echo"}},
        {"llm": {"provider": "openai", "model": "model", "api_key_env": "MISSING_SETUP_KEY"}},
        {
            "llm": {
                "provider": "ollama",
                "model": "model",
                "base_url": "https://host/v1?api_key=do-not-echo",
            }
        },
        {"llm": {"provider": "ollama", "model": "model"}, "search": {"provider": "searxng"}},
        {"llm": {"provider": "ollama", "model": "model", "api_format": "anthropic"}},
    ],
)
def test_invalid_setup_fails_before_writes(runtime_home, tmp_path, payload, monkeypatch):
    monkeypatch.delenv("MISSING_SETUP_KEY", raising=False)
    result = apply_file(tmp_path, payload)
    assert result.exit_code == 2, result.output
    assert json.loads(result.stdout)["ok"] is False
    assert "do-not-echo" not in result.output
    assert not runtime_home.exists()


def test_partial_port_conflict_does_not_apply_llm(runtime_home, tmp_path):
    from deeptutor.services.config import get_runtime_settings_service

    runtime = get_runtime_settings_service()
    system = runtime.load_system(include_process_overrides=False)
    before = runtime.path_for("system").read_bytes()
    result = apply_file(
        tmp_path,
        {
            "llm": {"provider": "ollama", "model": "local-model"},
            "system": {"backend_port": system["frontend_port"]},
        },
    )
    assert result.exit_code == 2, result.output
    assert runtime.path_for("system").read_bytes() == before
    assert not (runtime_home / "data/user/settings/model_catalog.json").exists()


def test_non_interactive_init_never_prompts_or_overwrites_saved_choices(
    runtime_home, tmp_path, monkeypatch
):
    def unexpected_prompt(*args, **kwargs):
        pytest.fail("Headless initialization must not prompt")

    monkeypatch.setattr("typer.prompt", unexpected_prompt)
    monkeypatch.setattr("typer.confirm", unexpected_prompt)
    applied = apply_file(tmp_path, {"llm": {"provider": "ollama", "model": "keep-local"}})
    assert applied.exit_code == 0, applied.output
    catalog_path = runtime_home / "data/user/settings/model_catalog.json"
    before = catalog_path.read_bytes()
    for _ in range(2):
        result = runner.invoke(app, ["init", "--non-interactive", "--home", str(runtime_home)])
        assert result.exit_code == 0, result.output
        assert json.loads(result.stdout)["status"] == "initialized"
        assert catalog_path.read_bytes() == before
    assert (runtime_home / "data/user/settings/system.json").exists()


def test_provider_discovery_includes_local_and_oauth_choices(runtime_home):
    result = runner.invoke(app, ["config", "providers"])
    assert result.exit_code == 0, result.output
    choices = json.loads(result.stdout)
    assert any(row["provider"] == "ollama" for row in choices["llm"])
    assert any(row["auth"] == "oauth" for row in choices["llm"])
    assert any(
        row["provider"] == "searxng" and row["requires_base_url"] for row in choices["search"]
    )
    assert not runtime_home.exists()


def test_setup_json_is_parseable_across_separate_cli_processes(runtime_home, tmp_path):
    target = tmp_path / "explicit-process-home"
    path = tmp_path / "setup.json"
    path.write_text(
        json.dumps(
            {
                "llm": {
                    "provider": "openai",
                    "model": "process-test-model",
                    "api_key_env": "DT_SETUP_TEST_KEY",
                },
                "system": {"backend_port": 8123, "frontend_port": 3891},
            }
        ),
        encoding="utf-8",
    )
    steps = [
        ["init", "--non-interactive", "--home", str(target)],
        ["config", "apply", str(path), "--home", str(target), "--check"],
        ["config", "apply", str(path), "--home", str(target)],
        ["config", "show", "--home", str(target)],
    ]
    for step in steps:
        result = subprocess.run(
            [sys.executable, "-m", "deeptutor_cli.main", *step],
            cwd=Path(__file__).resolve().parents[2],
            env=os.environ.copy(),
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode == 0, result.stderr
        payload = json.loads(result.stdout)
        assert "setup-test-secret" not in result.stdout + result.stderr
        if step[:2] == ["config", "show"]:
            assert payload["ports"] == {"backend": 8123, "frontend": 3891}
            assert payload["llm"]["model"] == "process-test-model"
    assert (target / "data/user/settings/model_catalog.json").exists()
    assert not (runtime_home / "data/user/settings/system.json").exists()


def test_unreadable_existing_catalog_is_preserved(runtime_home, tmp_path):
    path = runtime_home / "data/user/settings/model_catalog.json"
    path.parent.mkdir(parents=True)
    path.write_text("{broken JSON", encoding="utf-8")
    result = apply_file(tmp_path, {"llm": {"provider": "ollama", "model": "local-model"}})
    assert result.exit_code == 2, result.output
    assert path.read_text(encoding="utf-8") == "{broken JSON"
