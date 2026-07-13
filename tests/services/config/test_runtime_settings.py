from __future__ import annotations

import json
from pathlib import Path

from deeptutor.services.config.runtime_settings import (
    RuntimeSettingsService,
    ensure_runtime_settings_files,
)

RUNTIME_ENV_KEYS = (
    "BACKEND_PORT",
    "FRONTEND_PORT",
    "NEXT_PUBLIC_API_BASE_EXTERNAL",
    "PUBLIC_API_BASE",
    "NEXT_PUBLIC_API_BASE",
    "CORS_ORIGIN",
    "CORS_ORIGINS",
    "DISABLE_SSL_VERIFY",
    "CHAT_ATTACHMENT_DIR",
    "AUTH_ENABLED",
    "NEXT_PUBLIC_AUTH_ENABLED",
    "AUTH_USERNAME",
    "AUTH_PASSWORD_HASH",
    "AUTH_TOKEN_EXPIRE_HOURS",
    "AUTH_COOKIE_SECURE",
    "POCKETBASE_URL",
    "POCKETBASE_PORT",
    "POCKETBASE_EXTERNAL_URL",
    "POCKETBASE_ADMIN_EMAIL",
    "POCKETBASE_ADMIN_PASSWORD",
)


def _read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def _clear_runtime_env(monkeypatch) -> None:
    for key in RUNTIME_ENV_KEYS:
        monkeypatch.delenv(key, raising=False)


def test_runtime_settings_creates_defaults_without_reading_dotenv(tmp_path: Path) -> None:
    legacy_env = tmp_path / ".env"
    legacy_env.write_text(
        "BACKEND_PORT=9001\nAUTH_ENABLED=true\nPOCKETBASE_URL=http://legacy.invalid\n",
        encoding="utf-8",
    )
    service = RuntimeSettingsService(tmp_path / "settings")

    assert service.load_system(include_process_overrides=False)["backend_port"] == 8001
    assert service.load_auth(include_process_overrides=False)["enabled"] is False
    assert service.load_integrations(include_process_overrides=False)["pocketbase_url"] == ""

    assert _read_json(service.path_for("system"))["backend_port"] == 8001
    assert _read_json(service.path_for("auth"))["enabled"] is False


def test_runtime_process_env_is_explicit_override(tmp_path: Path) -> None:
    service = RuntimeSettingsService(
        tmp_path / "settings",
        process_env={
            "BACKEND_PORT": "9100",
            "AUTH_ENABLED": "true",
            "POCKETBASE_PORT": "9090",
        },
    )
    service.save_system({"backend_port": 8001, "frontend_port": 3782})
    service.save_auth({"enabled": False, "username": "admin"})
    service.save_integrations({"pocketbase_port": 8090})

    assert service.load_system()["backend_port"] == 9100
    assert service.load_auth()["enabled"] is True
    assert service.load_integrations()["pocketbase_port"] == 9090
    assert _read_json(service.path_for("system"))["backend_port"] == 8001
    assert _read_json(service.path_for("auth"))["enabled"] is False
    assert _read_json(service.path_for("integrations"))["pocketbase_port"] == 8090


def test_render_environment_uses_json_backed_runtime_names(monkeypatch, tmp_path: Path) -> None:
    _clear_runtime_env(monkeypatch)
    service = RuntimeSettingsService(tmp_path / "settings")
    service.save_system(
        {
            "backend_port": 8010,
            "frontend_port": 3790,
            "cors_origins": ["https://app.example"],
            "disable_ssl_verify": True,
        }
    )
    service.save_auth({"enabled": True, "username": "admin", "token_expire_hours": 12})
    service.save_integrations(
        {
            "pocketbase_url": "http://pocketbase:8090",
            "pocketbase_admin_email": "admin@example.com",
        }
    )

    env = service.render_environment()

    assert env["BACKEND_PORT"] == "8010"
    assert env["FRONTEND_PORT"] == "3790"
    assert env["CORS_ORIGINS"] == "https://app.example"
    assert env["DISABLE_SSL_VERIFY"] == "true"
    assert env["AUTH_ENABLED"] == "true"
    assert env["NEXT_PUBLIC_AUTH_ENABLED"] == "true"
    # Server-side proxy contract consumed by web/proxy.ts (the Next.js
    # middleware). DEEPTUTOR_AUTH_ENABLED gates the login redirect;
    # DEEPTUTOR_API_BASE_URL is where the frontend server reaches the backend
    # (falls back to localhost:<backend_port> when no in-network / external base
    # is configured).
    assert env["DEEPTUTOR_AUTH_ENABLED"] == "true"
    assert env["DEEPTUTOR_API_BASE_URL"] == "http://localhost:8010"
    assert env["AUTH_TOKEN_EXPIRE_HOURS"] == "12"
    assert env["POCKETBASE_URL"] == "http://pocketbase:8090"
    assert "AUTH_SECRET" not in env


def test_system_settings_accept_public_api_base_alias_and_normalize_origins(
    monkeypatch, tmp_path: Path
) -> None:
    _clear_runtime_env(monkeypatch)
    service = RuntimeSettingsService(tmp_path / "settings")

    system = service.save_system(
        {
            "public_api_base": "https://api.example.com/base",
            "cors_origins": "app.example.com; https://learn.example.com/path",
        }
    )

    assert system["next_public_api_base_external"] == "https://api.example.com/base"
    assert system["cors_origins"] == [
        "http://app.example.com",
        "https://learn.example.com",
    ]
    assert "public_api_base" not in _read_json(service.path_for("system"))


def test_exported_environment_does_not_become_runtime_override(monkeypatch, tmp_path: Path) -> None:
    _clear_runtime_env(monkeypatch)

    service = RuntimeSettingsService(tmp_path / "settings")
    service.save_system({"backend_port": 8010})
    service.save_auth({"enabled": False})

    service.export_environment(overwrite=True)
    assert service.load_system()["backend_port"] == 8010
    assert service.load_auth()["enabled"] is False

    service.save_system({"backend_port": 8020})
    service.save_auth({"enabled": True})

    assert service.load_system()["backend_port"] == 8020
    assert service.load_auth()["enabled"] is True


def test_existing_process_environment_remains_deployment_override(
    monkeypatch, tmp_path: Path
) -> None:
    monkeypatch.setenv("BACKEND_PORT", "9100")
    service = RuntimeSettingsService(tmp_path / "settings")
    service.save_system({"backend_port": 8010})

    service.export_environment(overwrite=True)
    service.save_system({"backend_port": 8020})

    assert service.load_system()["backend_port"] == 9100


def test_startup_ensure_creates_missing_runtime_jsons_with_defaults(
    monkeypatch, tmp_path: Path
) -> None:
    _clear_runtime_env(monkeypatch)
    settings_dir = tmp_path / "settings"

    from deeptutor.services.config import model_catalog as model_catalog_module
    from deeptutor.services.config import runtime_settings as runtime_settings_module

    runtime_settings_module.RuntimeSettingsService._instances.clear()
    model_catalog_module.ModelCatalogService._instances.clear()
    monkeypatch.setattr(runtime_settings_module, "_global_settings_dir", lambda: settings_dir)
    monkeypatch.setattr(
        model_catalog_module.get_path_service(),
        "get_settings_file",
        lambda name: settings_dir / f"{name}.json",
    )

    ensure_runtime_settings_files()

    assert (settings_dir / "system.json").exists()
    assert (settings_dir / "auth.json").exists()
    assert (settings_dir / "integrations.json").exists()
    assert (settings_dir / "document_parsing.json").exists()
    assert (settings_dir / "model_catalog.json").exists()
    _parsing_file = _read_json(settings_dir / "document_parsing.json")
    assert _parsing_file["version"] == 2
    assert _parsing_file["engines"]["mineru"]["mode"] == "local"
    assert _read_json(settings_dir / "system.json")["backend_port"] == 8001
    assert _read_json(settings_dir / "auth.json")["enabled"] is False
    assert _read_json(settings_dir / "integrations.json")["pocketbase_url"] == ""
    assert set(_read_json(settings_dir / "model_catalog.json")["services"]) == {
        "llm",
        "embedding",
        "search",
        "tts",
        "stt",
        "imagegen",
        "videogen",
    }


def test_mineru_defaults_and_normalization(tmp_path: Path) -> None:
    service = RuntimeSettingsService(tmp_path / "settings", process_env={})

    defaults = service.load_mineru(include_process_overrides=False)
    assert defaults["mode"] == "local"
    assert defaults["model_version"] == "pipeline"
    assert defaults["api_token"] == ""

    saved = service.save_mineru(
        {
            "mode": "CLOUD",  # case-insensitive
            "api_base_url": "https://mineru.net/",  # trailing slash stripped
            "api_token": "  tok-123  ",  # trimmed
            "model_version": "bogus",  # invalid → pipeline
            "language": "",  # empty → auto
            "enable_formula": "no",  # coerced to bool
            "is_ocr": 1,
        }
    )
    assert saved["mode"] == "cloud"
    assert saved["api_base_url"] == "https://mineru.net"
    assert saved["api_token"] == "tok-123"
    assert saved["model_version"] == "pipeline"
    assert saved["language"] == "auto"
    assert saved["enable_formula"] is False
    assert saved["is_ocr"] is True
    # Unknown mode falls back to local.
    assert service.save_mineru({"mode": "weird"})["mode"] == "local"

    # Model-download fields: source whitelisted, endpoint trimmed.
    saved = service.save_mineru(
        {
            "model_download_source": "ModelScope",
            "model_download_endpoint": " https://hf-mirror.com/ ",
        }
    )
    assert saved["model_download_source"] == "modelscope"
    assert saved["model_download_endpoint"] == "https://hf-mirror.com"
    assert service.save_mineru({"model_download_source": "weird"})["model_download_source"] == (
        "huggingface"
    )


def test_mineru_local_cli_path_roundtrip(tmp_path: Path) -> None:
    service = RuntimeSettingsService(tmp_path / "settings", process_env={})
    saved = service.save_mineru({"local_cli_path": "  /envs/mineru/bin/mineru  "})
    assert saved["local_cli_path"] == "/envs/mineru/bin/mineru"
    assert service.load_mineru()["local_cli_path"] == "/envs/mineru/bin/mineru"
    # Default is empty (auto-detect from PATH).
    assert service.save_mineru({})["local_cli_path"] == ""


def test_mineru_process_env_override(tmp_path: Path) -> None:
    service = RuntimeSettingsService(
        tmp_path / "settings",
        process_env={
            "MINERU_MODE": "cloud",
            "MINERU_API_TOKEN": "env-token",
            "MINERU_LOCAL_CLI_PATH": "/env/bin/mineru",
        },
    )
    service.save_mineru({"mode": "local", "api_token": "file-token"})

    effective = service.load_mineru()
    assert effective["mode"] == "cloud"
    assert effective["api_token"] == "env-token"
    assert effective["local_cli_path"] == "/env/bin/mineru"
    # The persisted file keeps the on-disk values (nested under engines.mineru),
    # not the env overrides.
    persisted = _read_json(service.path_for("document_parsing"))["engines"]["mineru"]
    assert persisted["mode"] == "local"
    assert persisted["api_token"] == "file-token"


def test_document_parsing_v1_to_v2_migration(tmp_path: Path) -> None:
    """A legacy flat mineru.json is folded into engines.mineru on first load,
    with the active engine pinned to MinerU (preserve existing behavior)."""
    from deeptutor.services.config.runtime_settings import _atomic_write_json

    service = RuntimeSettingsService(tmp_path / "settings", process_env={})
    legacy = {
        "version": 1,
        "mode": "cloud",
        "api_token": "legacy-tok",
        "model_version": "vlm",
        "language": "ch",
    }
    _atomic_write_json(service.path_for("mineru"), legacy)

    full = service.load_document_parsing(include_process_overrides=False)
    assert full["version"] == 2
    assert full["engine"] == "mineru"  # migrated installs keep MinerU
    mineru = full["engines"]["mineru"]
    assert mineru["mode"] == "cloud"
    assert mineru["api_token"] == "legacy-tok"
    assert mineru["model_version"] == "vlm"
    assert mineru["language"] == "ch"
    assert mineru["allow_local_model_download"] is False
    # All engines are always present after normalization.
    assert set(full["engines"]) == {
        "text_only",
        "mineru",
        "docling",
        "markitdown",
        "pymupdf4llm",
    }
    # Migration is persisted to the renamed file (v2, no top-level flat keys);
    # the legacy mineru.json is gone.
    assert not service.path_for("mineru").exists()
    on_disk = _read_json(service.path_for("document_parsing"))
    assert on_disk["version"] == 2
    assert "mode" not in on_disk


def test_document_parsing_legacy_filename_rename(tmp_path: Path) -> None:
    """A pre-existing v2 ``mineru.json`` is renamed to ``document_parsing.json``
    on first load, preserving its contents."""
    from deeptutor.services.config.runtime_settings import _atomic_write_json

    service = RuntimeSettingsService(tmp_path / "settings", process_env={})
    existing = service.save_document_parsing({"engine": "docling"})
    # save_document_parsing already writes the new filename; simulate an old
    # install by moving it back to the legacy name.
    service.path_for("document_parsing").rename(service.path_for("mineru"))
    assert service.path_for("mineru").exists()
    assert not service.path_for("document_parsing").exists()

    full = service.load_document_parsing(include_process_overrides=False)
    assert full["engine"] == "docling"
    assert full["engines"]["mineru"] == existing["engines"]["mineru"]
    # File was renamed in place, not duplicated.
    assert service.path_for("document_parsing").exists()
    assert not service.path_for("mineru").exists()


def test_document_parsing_fresh_default_engine_is_text_only(tmp_path: Path) -> None:
    service = RuntimeSettingsService(tmp_path / "settings", process_env={})
    full = service.load_document_parsing(include_process_overrides=False)
    assert full["engine"] == "text_only"
    assert full["engines"]["text_only"] == {}


def test_mineru_allow_local_model_download_default_off_and_env(tmp_path: Path) -> None:
    service = RuntimeSettingsService(tmp_path / "settings", process_env={})
    assert service.load_mineru()["allow_local_model_download"] is False
    assert (
        service.save_mineru({"allow_local_model_download": True})["allow_local_model_download"]
        is True
    )

    env_service = RuntimeSettingsService(
        tmp_path / "settings2",
        process_env={"MINERU_ALLOW_LOCAL_MODEL_DOWNLOAD": "1"},
    )
    assert env_service.load_mineru()["allow_local_model_download"] is True


def test_runtime_settings_can_ignore_process_overrides(tmp_path: Path) -> None:
    service = RuntimeSettingsService(
        tmp_path / "settings",
        process_env={
            "DEEPTUTOR_IGNORE_PROCESS_ENV_OVERRIDES": "1",
            "BACKEND_PORT": "9901",
            "AUTH_ENABLED": "true",
        },
    )
    service.save_system({"backend_port": 8001})
    service.save_auth({"enabled": False})

    assert service.load_system()["backend_port"] == 8001
    assert service.load_auth()["enabled"] is False
