from __future__ import annotations

import asyncio
import importlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from deeptutor.multi_user.context import (
    get_current_user_or_none,
    reset_current_user,
    set_current_user,
)
from deeptutor.multi_user.models import CurrentUser, UserScope
import deeptutor.services.config as config_module
from deeptutor.services.config.runtime_settings import RuntimeSettingsService
from deeptutor.services.rag.pipelines.ima.client import (
    ImaAPIError,
    ImaAuthError,
    ImaRateLimitError,
)
import deeptutor.services.rag.pipelines.ima.config as ima_config_module

try:
    from fastapi import FastAPI, HTTPException
    from fastapi.testclient import TestClient
except Exception:  # pragma: no cover - optional dependency in lightweight envs
    FastAPI = None
    TestClient = None

pytestmark = pytest.mark.skipif(
    FastAPI is None or TestClient is None, reason="fastapi not installed"
)

if FastAPI is not None and TestClient is not None:
    knowledge_router_module = importlib.import_module("deeptutor.api.routers.knowledge")
    router = knowledge_router_module.router
else:  # pragma: no cover - optional dependency in lightweight envs
    knowledge_router_module = None
    router = None


def _build_app() -> FastAPI:
    if FastAPI is None or router is None:  # pragma: no cover - guarded by pytestmark
        raise RuntimeError("fastapi is not installed")
    app = FastAPI()
    app.include_router(router, prefix="/api")
    return app


def test_knowledge_source_error_translation_is_consistent_and_sanitized() -> None:
    translate = knowledge_router_module._knowledge_source_errors

    with pytest.raises(HTTPException) as invalid:
        with translate("demo", validation_status=400):
            raise ValueError("invalid source")
    assert invalid.value.status_code == 400
    assert invalid.value.detail == "invalid source"

    with pytest.raises(HTTPException) as missing:
        with translate("demo"):
            raise ValueError("implementation-specific text")
    assert missing.value.status_code == 404
    assert missing.value.detail == "KB 'demo' not found"

    expected = HTTPException(status_code=409, detail="busy")
    with pytest.raises(HTTPException) as preserved:
        with translate("demo"):
            raise expected
    assert preserved.value is expected

    with pytest.raises(HTTPException) as unexpected:
        with translate("demo"):
            raise RuntimeError("internal secret")
    assert unexpected.value.status_code == 500
    assert unexpected.value.detail == "Knowledge source operation failed"


class _FakeKBManager:
    def __init__(self, base_dir: Path) -> None:
        self.base_dir = base_dir
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.config_file = self.base_dir / "kb_config.json"
        self.config: dict[str, dict] = {"knowledge_bases": {}}

    def _load_config(self) -> dict:
        return self.config

    def _save_config(self) -> None:
        pass

    def list_knowledge_bases(self) -> list[str]:
        return sorted(self.config.get("knowledge_bases", {}).keys())

    def update_kb_status(self, name: str, status: str, progress: dict | None = None) -> None:
        entry = self.config.setdefault("knowledge_bases", {}).setdefault(name, {"path": name})
        entry["status"] = status
        entry["progress"] = progress or {}

    def get_default(self, *, available_names: list[str] | None = None) -> str | None:
        names = available_names if available_names is not None else self.list_knowledge_bases()
        return names[0] if names else None

    def get_knowledge_base_path(self, name: str) -> Path:
        kb_dir = self.base_dir / name
        kb_dir.mkdir(parents=True, exist_ok=True)
        return kb_dir

    def register_lightrag_server_kb(
        self,
        name: str,
        server_url: str,
        *,
        api_key: str = "",
        search_mode: str = "",
        description: str = "",
    ) -> dict:
        if name in self.config.get("knowledge_bases", {}):
            raise ValueError(f"A knowledge base named '{name}' already exists.")
        entry = {
            "path": name,
            "type": "lightrag_server",
            "rag_provider": "lightrag-server",
            "server_url": server_url,
            "api_key": api_key,
            "status": "ready",
        }
        if search_mode:
            entry["search_mode"] = search_mode
        self.config.setdefault("knowledge_bases", {})[name] = entry
        return entry

    def register_weknora_kb(
        self,
        name: str,
        server_url: str,
        api_key: str,
        knowledge_base_id: str,
        *,
        description: str = "",
    ) -> dict:
        if name in self.config.get("knowledge_bases", {}):
            raise ValueError(f"A knowledge base named '{name}' already exists.")
        entry = {
            "path": name,
            "type": "weknora",
            "rag_provider": "weknora",
            "server_url": server_url,
            "api_key": api_key,
            "knowledge_base_id": knowledge_base_id,
            "status": "ready",
        }
        self.config.setdefault("knowledge_bases", {})[name] = entry
        return entry


class _FakeInitializer:
    def __init__(self, kb_name: str, base_dir: str, **_kwargs) -> None:
        self.kb_name = kb_name
        self.base_dir = base_dir
        self.kb_dir = Path(base_dir) / kb_name
        self.raw_dir = self.kb_dir / "raw"
        self.progress_tracker = _kwargs.get("progress_tracker")

    def create_directory_structure(self) -> None:
        self.raw_dir.mkdir(parents=True, exist_ok=True)

    def _register_to_config(self) -> None:
        pass


def _upload_payload() -> list[tuple[str, tuple[str, bytes, str]]]:
    return [("files", ("demo.txt", b"hello", "text/plain"))]


def _invalid_upload_payload() -> list[tuple[str, tuple[str, bytes, str]]]:
    return [("files", ("archive.unsupported", b"binary", "application/octet-stream"))]


def _uppercase_upload_payload() -> list[tuple[str, tuple[str, bytes, str]]]:
    return [("files", ("报告.PDF", b"%PDF-1.4\n", "application/pdf"))]


def _write_ready_llamaindex_version(kb_dir: Path) -> None:
    version_dir = kb_dir / "version-1"
    version_dir.mkdir(parents=True, exist_ok=True)
    (version_dir / "docstore.json").write_text("{}", encoding="utf-8")
    (version_dir / "index_store.json").write_text("{}", encoding="utf-8")
    (version_dir / "meta.json").write_text(
        json.dumps({"provider": "llamaindex", "signature": "sig", "version": "version-1"}),
        encoding="utf-8",
    )


def test_rag_providers_lists_llamaindex_and_pageindex(monkeypatch) -> None:
    monkeypatch.setattr(ima_config_module, "is_ima_configured", lambda: True)
    with TestClient(_build_app()) as client:
        response = client.get("/api/knowledge-bases/rag-providers")

    assert response.status_code == 200
    payload = response.json()
    by_id = {p["id"]: p for p in payload["providers"]}
    assert set(by_id) == {
        "llamaindex",
        "pageindex",
        "pageindex-oss",
        "graphrag",
        "lightrag",
        "lightrag-server",
        "ima",
        "weknora",
    }
    # LlamaIndex works out of the box; PageIndex needs an API key; GraphRAG and
    # LightRAG are optional local engines (no API key, configured = installed).
    assert by_id["llamaindex"]["requires_api_key"] is False
    assert by_id["pageindex"]["requires_api_key"] is True
    assert by_id["pageindex-oss"]["requires_api_key"] is False
    assert by_id["graphrag"]["requires_api_key"] is False
    assert by_id["lightrag"]["requires_api_key"] is False
    # LightRAG Server is a thin HTTP client: always available, no API key gate
    # (the per-KB endpoint is configured at connect time).
    assert by_id["lightrag-server"]["requires_api_key"] is False
    assert by_id["lightrag-server"]["configured"] is True
    assert by_id["weknora"]["requires_api_key"] is True
    assert by_id["weknora"]["configured"] is True
    # IMA is a thin HTTPS client with no install, but it does need an account
    # credential pair — configured here by the patched account settings.
    assert by_id["ima"]["requires_api_key"] is True
    assert by_id["ima"]["configured"] is True
    # Mode-aware engines advertise their retrieval modes; vector engines don't.
    assert "hybrid" in by_id["lightrag"]["modes"]
    assert "mix" in by_id["lightrag-server"]["modes"]
    assert not by_id["llamaindex"].get("modes")
    # IMA exposes a single retrieval call, so it advertises no modes.
    assert not by_id["ima"].get("modes")


class _ImaListStub:
    def __init__(self, *, result: dict | None = None, error: Exception | None = None) -> None:
        self.result = result or {
            "knowledge_bases": [],
            "next_cursor": "",
            "is_end": True,
        }
        self.error = error
        self.call: tuple[str, str, int] | None = None

    async def search_knowledge_bases(
        self, query: str = "", *, cursor: str = "", limit: int = 20
    ) -> dict:
        self.call = (query, cursor, limit)
        if self.error is not None:
            raise self.error
        return self.result


def test_list_ima_returns_normalized_page(monkeypatch) -> None:
    captured: dict = {}
    stub = _ImaListStub(
        result={
            "knowledge_bases": [{"id": "kb-1", "name": "My Library", "description": "notes"}],
            "next_cursor": "cursor-2",
            "is_end": False,
        }
    )

    def build_client(config):
        captured["config"] = config
        return stub

    monkeypatch.setattr(knowledge_router_module, "ImaClient", build_client, raising=False)
    with TestClient(_build_app()) as client:
        response = client.post(
            "/api/knowledge-bases/list-ima",
            json={
                "client_id": " private-client ",
                "api_key": " private-key ",
                "cursor": " cursor-1 ",
                "limit": 20,
            },
        )

    assert response.status_code == 200
    assert stub.call == ("", "cursor-1", 20)
    assert captured["config"].client_id == "private-client"
    assert captured["config"].api_key == "private-key"
    assert captured["config"].knowledge_base_id == ""
    assert response.json() == stub.result
    assert "private-client" not in response.text
    assert "private-key" not in response.text


def test_list_ima_returns_an_empty_final_page(monkeypatch) -> None:
    stub = _ImaListStub()
    monkeypatch.setattr(knowledge_router_module, "ImaClient", lambda _config: stub, raising=False)

    with TestClient(_build_app()) as client:
        response = client.post(
            "/api/knowledge-bases/list-ima",
            json={"client_id": "cid", "api_key": "key"},
        )

    assert response.status_code == 200
    assert response.json() == {
        "knowledge_bases": [],
        "next_cursor": "",
        "is_end": True,
    }


@pytest.mark.parametrize(
    "payload",
    [
        {"client_id": "", "api_key": "key"},
        {"client_id": "cid", "api_key": ""},
        {"client_id": "   ", "api_key": "key"},
        {"client_id": "cid", "api_key": "   "},
    ],
)
def test_list_ima_rejects_missing_credentials(payload: dict) -> None:
    with TestClient(_build_app()) as client:
        response = client.post("/api/knowledge-bases/list-ima", json=payload)

    assert response.status_code == 400
    assert "required" in response.json()["detail"]


@pytest.mark.parametrize("limit", [0, 51])
def test_list_ima_validates_official_page_limit(limit: int) -> None:
    with TestClient(_build_app()) as client:
        response = client.post(
            "/api/knowledge-bases/list-ima",
            json={"client_id": "cid", "api_key": "key", "limit": limit},
        )

    assert response.status_code == 422


@pytest.mark.parametrize(
    ("error", "expected_status", "expected_detail"),
    [
        (ImaAuthError("private-key rejected"), 401, "IMA rejected the supplied credentials."),
        (ImaRateLimitError("private-key throttled"), 429, "IMA rate limit reached."),
        (ImaAPIError("private-key appeared upstream"), 502, "IMA returned an invalid response."),
        (RuntimeError("private-key transport failure"), 502, "Could not reach Tencent IMA."),
    ],
)
def test_list_ima_maps_upstream_errors_without_leaking_credentials(
    monkeypatch,
    error: Exception,
    expected_status: int,
    expected_detail: str,
) -> None:
    stub = _ImaListStub(error=error)
    monkeypatch.setattr(knowledge_router_module, "ImaClient", lambda _config: stub, raising=False)

    with TestClient(_build_app()) as client:
        response = client.post(
            "/api/knowledge-bases/list-ima",
            json={"client_id": "private-client", "api_key": "private-key"},
        )

    assert response.status_code == expected_status
    assert expected_detail in response.json()["detail"]
    assert "private-client" not in response.text
    assert "private-key" not in response.text


@pytest.fixture
def ima_account(tmp_path: Path, monkeypatch) -> RuntimeSettingsService:
    """Account-level IMA settings backed by a throwaway directory."""
    service = RuntimeSettingsService(tmp_path / "settings", process_env={})
    monkeypatch.setattr(config_module, "get_runtime_settings_service", lambda: service)
    return service


def test_list_ima_falls_back_to_the_account_credentials(monkeypatch, ima_account) -> None:
    ima_account.save_ima({"client_id": "account-client", "api_key": "account-key"})
    captured: dict = {}
    stub = _ImaListStub()

    def build_client(config):
        captured["config"] = config
        return stub

    monkeypatch.setattr(knowledge_router_module, "ImaClient", build_client, raising=False)
    with TestClient(_build_app()) as client:
        response = client.post("/api/knowledge-bases/list-ima", json={})

    assert response.status_code == 200
    assert captured["config"].client_id == "account-client"
    assert captured["config"].api_key == "account-key"


def test_list_ima_does_not_complete_half_a_supplied_pair(monkeypatch, ima_account) -> None:
    # Mixing one account's Client ID with another's key would fail at IMA with
    # a confusing verdict; ask for the missing half instead.
    ima_account.save_ima({"client_id": "account-client", "api_key": "account-key"})

    with TestClient(_build_app()) as client:
        response = client.post("/api/knowledge-bases/list-ima", json={"client_id": "other"})

    assert response.status_code == 400
    assert "required" in response.json()["detail"]


def test_ima_config_reports_state_without_echoing_the_key(ima_account) -> None:
    with TestClient(_build_app()) as client:
        assert client.get("/api/knowledge-bases/rag-pipelines/ima/config").json() == {
            "client_id": "",
            "api_key_set": False,
            "configured": False,
        }

        response = client.put(
            "/api/knowledge-bases/rag-pipelines/ima/config",
            json={"client_id": " account-client ", "api_key": " private-key "},
        )

    assert response.status_code == 200
    assert response.json() == {
        "client_id": "account-client",
        "api_key_set": True,
        "configured": True,
    }
    assert "private-key" not in response.text
    assert ima_account.load_ima(include_process_overrides=False)["api_key"] == "private-key"


def test_ima_config_keeps_the_stored_key_when_omitted(ima_account) -> None:
    ima_account.save_ima({"client_id": "account-client", "api_key": "private-key"})

    with TestClient(_build_app()) as client:
        response = client.put(
            "/api/knowledge-bases/rag-pipelines/ima/config",
            json={"client_id": "renamed-client"},
        )

    assert response.status_code == 200
    assert response.json()["api_key_set"] is True
    stored = ima_account.load_ima(include_process_overrides=False)
    assert stored == {"version": 1, "client_id": "renamed-client", "api_key": "private-key"}


def test_ima_config_clears_the_key_on_an_empty_string(ima_account) -> None:
    ima_account.save_ima({"client_id": "account-client", "api_key": "private-key"})

    with TestClient(_build_app()) as client:
        response = client.put(
            "/api/knowledge-bases/rag-pipelines/ima/config",
            json={"api_key": ""},
        )

    assert response.json() == {
        "client_id": "account-client",
        "api_key_set": False,
        "configured": False,
    }


class _ProbeResult:
    def __init__(self) -> None:
        self.ok = True
        self.error = None
        self.description = "notes"

    def to_dict(self) -> dict:
        return {"ok": True, "error": None, "description": self.description}


def _capture_probe(monkeypatch) -> list[tuple[str, str, str]]:
    """Record the credentials the router probes with, without any network."""
    import deeptutor.services.rag.pipelines.ima.probe as probe_module

    calls: list[tuple[str, str, str]] = []

    async def fake_probe(client_id: str, api_key: str, knowledge_base_id: str, **_kwargs):
        calls.append((client_id, api_key, knowledge_base_id))
        return _ProbeResult()

    monkeypatch.setattr(probe_module, "probe_knowledge_base", fake_probe)
    return calls


def _real_manager(monkeypatch, tmp_path: Path):
    from deeptutor.knowledge.manager import KnowledgeBaseManager

    manager = KnowledgeBaseManager(base_dir=str(tmp_path / "kbs"))
    monkeypatch.setattr(knowledge_router_module, "get_kb_manager", lambda: manager)
    return manager


def test_connect_ima_uses_the_account_pair_without_copying_it(
    monkeypatch, tmp_path: Path, ima_account
) -> None:
    ima_account.save_ima({"client_id": "account-client", "api_key": "account-key"})
    calls = _capture_probe(monkeypatch)
    manager = _real_manager(monkeypatch, tmp_path)

    with TestClient(_build_app()) as client:
        response = client.post(
            "/api/knowledge-bases/connect-ima",
            json={"name": "IMA", "knowledge_base_id": "kb-1"},
        )

    assert response.status_code == 200
    # Probed with the account credentials …
    assert calls == [("account-client", "account-key", "kb-1")]
    # … but the KB keeps only the pointer, so rotating the key keeps it working.
    entry = manager.config["knowledge_bases"]["IMA"]
    assert entry["knowledge_base_id"] == "kb-1"
    assert "client_id" not in entry and "api_key" not in entry


def test_connect_ima_pins_supplied_credentials_to_the_kb(
    monkeypatch, tmp_path: Path, ima_account
) -> None:
    ima_account.save_ima({"client_id": "account-client", "api_key": "account-key"})
    calls = _capture_probe(monkeypatch)
    manager = _real_manager(monkeypatch, tmp_path)

    with TestClient(_build_app()) as client:
        response = client.post(
            "/api/knowledge-bases/connect-ima",
            json={
                "name": "Other",
                "client_id": "other-client",
                "api_key": "other-key",
                "knowledge_base_id": "kb-2",
            },
        )

    assert response.status_code == 200
    assert calls == [("other-client", "other-key", "kb-2")]
    entry = manager.config["knowledge_bases"]["Other"]
    assert entry["client_id"] == "other-client"
    assert entry["api_key"] == "other-key"


def test_set_rag_provider_mode_persists_validates_and_reflects() -> None:
    with TestClient(_build_app()) as client:
        ok = client.put("/api/knowledge-bases/rag-providers/lightrag/mode", json={"mode": "MIX"})
        assert ok.status_code == 200
        assert ok.json()["mode"] == "mix"  # normalized

        providers = client.get("/api/knowledge-bases/rag-providers").json()["providers"]
        by_id = {p["id"]: p for p in providers}
        assert by_id["lightrag"]["default_mode"] == "mix"

        # Invalid mode for the engine → 400; mode-less engine → 404.
        assert (
            client.put(
                "/api/knowledge-bases/rag-providers/lightrag/mode", json={"mode": "bogus"}
            ).status_code
            == 400
        )
        assert (
            client.put(
                "/api/knowledge-bases/rag-providers/llamaindex/mode", json={"mode": "x"}
            ).status_code
            == 404
        )


def test_supported_file_types_returns_upload_policy() -> None:
    with TestClient(_build_app()) as client:
        response = client.get("/api/knowledge-bases/supported-file-types")

    assert response.status_code == 200
    payload = response.json()
    assert ".pdf" in payload["extensions"]
    assert ".docx" in payload["extensions"]
    assert ".xlsx" in payload["extensions"]
    assert ".pptx" in payload["extensions"]
    assert ".md" in payload["extensions"]
    assert ".png" in payload["extensions"]
    assert ".pages" in payload["extensions"]
    assert ".mp4" in payload["extensions"]
    assert ".dclg.xml" in payload["extensions"]
    assert ".tar.gz" in payload["extensions"]
    assert ".ipynb" in payload["extensions"]
    assert ".cbz" in payload["extensions"]
    assert ".key" in payload["extensions"]
    assert ".vsdx" in payload["extensions"]
    assert ".sqlite3" in payload["extensions"]
    assert payload["max_file_size_bytes"] > 0
    assert "max_pdf_size_bytes" not in payload
    assert ".pdf" in payload["accept"]
    assert ".docx" in payload["accept"]
    assert ".png" in payload["accept"]
    assert ".tar.gz" in payload["accept"]
    assert "image/png" in payload["accept"]
    assert payload["allow_any_extension"] is False


def test_supported_file_types_can_delegate_all_extensions(monkeypatch) -> None:
    monkeypatch.setattr(
        knowledge_router_module.FileTypeRouter,
        "active_parser_accepts_any_format",
        classmethod(lambda cls: True),
    )

    with TestClient(_build_app()) as client:
        response = client.get("/api/knowledge-bases/supported-file-types")

    assert response.status_code == 200
    payload = response.json()
    assert payload["allow_any_extension"] is True
    assert payload["extensions"] == []
    assert payload["accept"] == ""


def test_graphrag_model_compatibility_probes_candidate_without_switching(
    monkeypatch,
) -> None:
    captured: dict[str, str] = {}

    async def _probe(profile_id: str, model_id: str) -> dict:
        captured.update({"profile_id": profile_id, "model_id": model_id})
        return {
            "status": "compatible",
            "compatible": True,
            "code": "graphrag_model_compatible",
            "message": "The model returned valid GraphRAG structured output.",
            "model": "gpt-4o-mini",
            "binding": "openai",
            "retryable": False,
        }

    monkeypatch.setattr(
        knowledge_router_module,
        "_probe_graphrag_model_compatibility",
        _probe,
        raising=False,
    )

    with TestClient(_build_app()) as client:
        response = client.post(
            "/api/knowledge-bases/rag-pipelines/graphrag/model-compatibility",
            json={"profile_id": "profile-a", "model_id": "model-b"},
        )

    assert response.status_code == 200
    assert captured == {"profile_id": "profile-a", "model_id": "model-b"}
    assert response.json() == {
        "status": "compatible",
        "compatible": True,
        "code": "graphrag_model_compatible",
        "message": "The model returned valid GraphRAG structured output.",
        "model": "gpt-4o-mini",
        "binding": "openai",
        "retryable": False,
    }


def test_graphrag_model_compatibility_hides_unexpected_provider_details(
    monkeypatch,
) -> None:
    async def _probe(_profile_id: str, _model_id: str) -> dict:
        raise RuntimeError("provider leaked sk-secret-must-not-reach-client")

    monkeypatch.setattr(
        knowledge_router_module,
        "_probe_graphrag_model_compatibility",
        _probe,
        raising=False,
    )

    with TestClient(_build_app()) as client:
        response = client.post(
            "/api/knowledge-bases/rag-pipelines/graphrag/model-compatibility",
            json={"profile_id": "profile-a", "model_id": "model-b"},
        )

    assert response.status_code == 500
    assert response.json()["detail"] == (
        "GraphRAG compatibility could not be tested because of an internal error."
    )
    assert "sk-secret" not in response.text


def test_create_kb_does_not_require_llm_precheck(monkeypatch, tmp_path: Path) -> None:
    manager = _FakeKBManager(tmp_path / "knowledge_bases")
    monkeypatch.setattr(knowledge_router_module, "get_kb_manager", lambda: manager)
    monkeypatch.setattr(knowledge_router_module, "KnowledgeBaseInitializer", _FakeInitializer)
    monkeypatch.setattr(
        knowledge_router_module,
        "get_llm_config",
        lambda: (_ for _ in ()).throw(RuntimeError("should not be called")),
        raising=False,
    )

    async def _noop_init_task(*_args, **_kwargs):
        return None

    monkeypatch.setattr(knowledge_router_module, "run_initialization_task", _noop_init_task)
    monkeypatch.setattr(knowledge_router_module, "_kb_base_dir", tmp_path / "knowledge_bases")

    with TestClient(_build_app()) as client:
        response = client.post(
            "/api/knowledge-bases",
            data={"name": "kb-new", "rag_provider": "llamaindex"},
            files=_upload_payload(),
        )

    assert response.status_code == 200
    body = response.json()
    assert body["name"] == "kb-new"
    assert isinstance(body.get("task_id"), str) and body["task_id"]
    assert manager.config["knowledge_bases"]["kb-new"]["rag_provider"] == "llamaindex"
    assert manager.config["knowledge_bases"]["kb-new"]["needs_reindex"] is False


def test_create_coerces_legacy_provider_to_llamaindex(monkeypatch, tmp_path: Path) -> None:
    """Unknown/removed provider strings silently normalize to llamaindex."""
    manager = _FakeKBManager(tmp_path / "knowledge_bases")
    monkeypatch.setattr(knowledge_router_module, "get_kb_manager", lambda: manager)

    async def _noop_init_task(*_args, **_kwargs):
        return None

    monkeypatch.setattr(knowledge_router_module, "run_initialization_task", _noop_init_task)
    monkeypatch.setattr(knowledge_router_module, "_kb_base_dir", tmp_path / "knowledge_bases")

    with TestClient(_build_app()) as client:
        response = client.post(
            "/api/knowledge-bases",
            data={"name": "kb-legacy", "rag_provider": "raganything"},
            files=_upload_payload(),
        )

    assert response.status_code == 200
    assert manager.config["knowledge_bases"]["kb-legacy"]["rag_provider"] == "llamaindex"


def test_create_preserves_known_nondefault_provider(monkeypatch, tmp_path: Path) -> None:
    manager = _FakeKBManager(tmp_path / "knowledge_bases")
    monkeypatch.setattr(knowledge_router_module, "get_kb_manager", lambda: manager)
    monkeypatch.setattr(knowledge_router_module, "KnowledgeBaseInitializer", _FakeInitializer)
    monkeypatch.setattr(knowledge_router_module, "_kb_base_dir", tmp_path / "knowledge_bases")

    pageindex_config = importlib.import_module("deeptutor.services.rag.pipelines.pageindex.config")
    monkeypatch.setattr(pageindex_config, "is_pageindex_configured", lambda: True)

    async def _noop_init_task(*_args, **_kwargs):
        return None

    monkeypatch.setattr(knowledge_router_module, "run_initialization_task", _noop_init_task)

    with TestClient(_build_app()) as client:
        response = client.post(
            "/api/knowledge-bases",
            data={"name": "kb-page", "rag_provider": "pageindex"},
            files=[("files", ("demo.pdf", b"%PDF-1.4\n", "application/pdf"))],
        )

    assert response.status_code == 200
    assert manager.config["knowledge_bases"]["kb-page"]["rag_provider"] == "pageindex"


def test_create_rejects_invalid_files_before_registering_kb(monkeypatch, tmp_path: Path) -> None:
    manager = _FakeKBManager(tmp_path / "knowledge_bases")
    monkeypatch.setattr(knowledge_router_module, "get_kb_manager", lambda: manager)
    monkeypatch.setattr(knowledge_router_module, "_kb_base_dir", tmp_path / "knowledge_bases")

    with TestClient(_build_app()) as client:
        response = client.post(
            "/api/knowledge-bases",
            data={"name": "kb-invalid", "rag_provider": "llamaindex"},
            files=_invalid_upload_payload(),
        )

    assert response.status_code == 400
    assert "unsupported file type" in response.json()["detail"].lower()
    assert "kb-invalid" not in manager.config["knowledge_bases"]


def test_create_rejects_invalid_kb_name_before_registering_kb(monkeypatch, tmp_path: Path) -> None:
    manager = _FakeKBManager(tmp_path / "knowledge_bases")
    monkeypatch.setattr(knowledge_router_module, "get_kb_manager", lambda: manager)
    monkeypatch.setattr(knowledge_router_module, "_kb_base_dir", tmp_path / "knowledge_bases")

    with TestClient(_build_app()) as client:
        response = client.post(
            "/api/knowledge-bases",
            data={"name": "bad/name", "rag_provider": "llamaindex"},
            files=_upload_payload(),
        )

    assert response.status_code == 400
    assert "reserved characters" in response.json()["detail"].lower()
    assert manager.config["knowledge_bases"] == {}


def test_create_normalizes_uploaded_extension_to_lowercase(monkeypatch, tmp_path: Path) -> None:
    manager = _FakeKBManager(tmp_path / "knowledge_bases")
    monkeypatch.setattr(knowledge_router_module, "get_kb_manager", lambda: manager)
    monkeypatch.setattr(knowledge_router_module, "KnowledgeBaseInitializer", _FakeInitializer)
    monkeypatch.setattr(knowledge_router_module, "_kb_base_dir", tmp_path / "knowledge_bases")

    async def _noop_init_task(*_args, **_kwargs):
        return None

    monkeypatch.setattr(knowledge_router_module, "run_initialization_task", _noop_init_task)

    with TestClient(_build_app()) as client:
        response = client.post(
            "/api/knowledge-bases",
            data={"name": "kb-uppercase", "rag_provider": "llamaindex"},
            files=_uppercase_upload_payload(),
        )

    assert response.status_code == 200
    assert response.json()["files"] == ["报告.pdf"]
    assert (tmp_path / "knowledge_bases" / "kb-uppercase" / "raw" / "报告.pdf").exists()


@pytest.mark.parametrize(("role", "fail"), [("user", False), ("admin", True)])
def test_initialization_task_installs_owner_scope_and_restores_caller(
    monkeypatch, tmp_path: Path, role: str, fail: bool
) -> None:
    manager = _FakeKBManager(tmp_path / "knowledge_bases")
    manager.config["knowledge_bases"]["kb"] = {"path": "kb", "status": "initializing"}
    raw_dir = manager.base_dir / "kb" / "raw"
    raw_dir.mkdir(parents=True)
    owner = CurrentUser(
        id=f"owner-{role}",
        username=f"owner-{role}",
        role=role,
        scope=UserScope(kind=role, user_id=f"owner-{role}", root=tmp_path / "owner"),
    )
    ambient = CurrentUser(
        id="ambient",
        username="ambient",
        role="user",
        scope=UserScope(kind="user", user_id="ambient", root=tmp_path / "ambient"),
    )

    async def process_documents():
        assert get_current_user_or_none() == owner
        if fail:
            raise RuntimeError("indexing failed")

    tracker = SimpleNamespace(task_id=None, update=lambda *_args, **_kwargs: None)
    initializer = SimpleNamespace(
        owner=owner,
        progress_tracker=tracker,
        kb_name="kb",
        base_dir=manager.base_dir,
        raw_dir=raw_dir,
        process_documents=process_documents,
        index_published=False,
    )
    monkeypatch.setattr(knowledge_router_module, "get_kb_manager", lambda: manager)
    token = set_current_user(ambient)
    try:
        asyncio.run(
            knowledge_router_module.run_initialization_task(
                initializer, f"owner-scope-{role}-{fail}"
            )
        )
        assert get_current_user_or_none() == ambient
    finally:
        reset_current_user(token)


def test_upload_returns_409_when_kb_needs_reindex(monkeypatch, tmp_path: Path) -> None:
    manager = _FakeKBManager(tmp_path / "knowledge_bases")
    manager.config["knowledge_bases"]["legacy-kb"] = {
        "path": "legacy-kb",
        "rag_provider": "llamaindex",
        "needs_reindex": True,
        "status": "needs_reindex",
    }
    monkeypatch.setattr(knowledge_router_module, "get_kb_manager", lambda: manager)

    with TestClient(_build_app()) as client:
        response = client.post("/api/knowledge-bases/legacy-kb/upload", files=_upload_payload())

    assert response.status_code == 409
    assert "needs reindex" in response.json()["detail"].lower()


def test_upload_ready_kb_returns_task_id(monkeypatch, tmp_path: Path) -> None:
    manager = _FakeKBManager(tmp_path / "knowledge_bases")
    manager.config["knowledge_bases"]["ready-kb"] = {
        "path": "ready-kb",
        "rag_provider": "llamaindex",
        "needs_reindex": False,
        "status": "ready",
    }
    monkeypatch.setattr(knowledge_router_module, "get_kb_manager", lambda: manager)
    monkeypatch.setattr(knowledge_router_module, "_kb_base_dir", tmp_path / "knowledge_bases")

    async def _noop_upload_task(*_args, **_kwargs):
        return None

    monkeypatch.setattr(knowledge_router_module, "run_upload_processing_task", _noop_upload_task)

    with TestClient(_build_app()) as client:
        response = client.post("/api/knowledge-bases/ready-kb/upload", files=_upload_payload())

    assert response.status_code == 200
    body = response.json()
    assert isinstance(body.get("task_id"), str) and body["task_id"]


def test_upload_flips_ready_kb_to_processing_before_dispatch(monkeypatch, tmp_path: Path) -> None:
    """An existing ready KB must not keep reporting ``ready`` between the
    accepted upload response and the background task's first progress write."""
    manager = _FakeKBManager(tmp_path / "knowledge_bases")
    manager.config["knowledge_bases"]["ready-kb"] = {
        "path": "ready-kb",
        "rag_provider": "llamaindex",
        "needs_reindex": False,
        "status": "ready",
    }
    monkeypatch.setattr(knowledge_router_module, "get_kb_manager", lambda: manager)
    monkeypatch.setattr(knowledge_router_module, "_kb_base_dir", tmp_path / "knowledge_bases")

    async def _noop_upload_task(*_args, **_kwargs):
        return None

    monkeypatch.setattr(knowledge_router_module, "run_upload_processing_task", _noop_upload_task)

    with TestClient(_build_app()) as client:
        response = client.post("/api/knowledge-bases/ready-kb/upload", files=_upload_payload())

    assert response.status_code == 200
    entry = manager.config["knowledge_bases"]["ready-kb"]
    assert entry["status"] == "processing"
    # Stage must be a member of the frontend's LIVE_PROGRESS_STAGES set.
    assert entry["progress"]["stage"] == "starting"
    assert entry["progress"]["task_id"] == response.json()["task_id"]


def test_upload_task_marks_provider_failures_as_error(monkeypatch, tmp_path: Path) -> None:
    base_dir = tmp_path / "knowledge_bases"
    kb_dir = base_dir / "kb"
    raw_dir = kb_dir / "raw"
    raw_dir.mkdir(parents=True)
    _write_ready_llamaindex_version(kb_dir)
    (base_dir / "kb_config.json").write_text(
        json.dumps(
            {
                "knowledge_bases": {
                    "kb": {
                        "path": "kb",
                        "rag_provider": "llamaindex",
                        "status": "ready",
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    source = tmp_path / "bad.txt"
    source.write_text("bad", encoding="utf-8")

    class _FailingRagService:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        async def add_documents(self, *_args, **_kwargs) -> bool:
            raise RuntimeError("parse failed loudly")

    monkeypatch.setattr(
        "deeptutor.knowledge.add_documents.RAGService",
        _FailingRagService,
    )

    asyncio.run(
        knowledge_router_module.run_upload_processing_task(
            kb_name="kb",
            base_dir=str(base_dir),
            uploaded_file_paths=[str(source)],
            task_id="upload-failure-test",
            rag_provider="llamaindex",
        )
    )

    persisted = json.loads((base_dir / "kb_config.json").read_text(encoding="utf-8"))
    entry = persisted["knowledge_bases"]["kb"]
    assert entry["status"] == "error"
    assert "parse failed loudly" in entry["last_error"]
    assert entry["progress"]["stage"] == "error"
    assert entry["progress"]["indexed_count"] == 0


def test_upload_task_with_folder_root_preserves_subfolder_structure(
    monkeypatch, tmp_path: Path
) -> None:
    """A linked-folder sync (folder_root set) stages a nested file under the
    same relative subpath in raw/, instead of flattening it to its basename
    and colliding with a same-named file from another subfolder (#866)."""
    base_dir = tmp_path / "knowledge_bases"
    kb_dir = base_dir / "kb"
    raw_dir = kb_dir / "raw"
    raw_dir.mkdir(parents=True)
    _write_ready_llamaindex_version(kb_dir)
    (base_dir / "kb_config.json").write_text(
        json.dumps(
            {
                "knowledge_bases": {
                    "kb": {
                        "path": "kb",
                        "rag_provider": "llamaindex",
                        "status": "ready",
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    linked_folder = tmp_path / "linked"
    (linked_folder / "sub").mkdir(parents=True)
    doc = linked_folder / "sub" / "note.md"
    doc.write_text("hello", encoding="utf-8")

    class _SucceedingRagService:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        async def add_documents(self, *_args, **_kwargs) -> bool:
            return True

    monkeypatch.setattr(
        "deeptutor.knowledge.add_documents.RAGService",
        _SucceedingRagService,
    )

    asyncio.run(
        knowledge_router_module.run_upload_processing_task(
            kb_name="kb",
            base_dir=str(base_dir),
            uploaded_file_paths=[str(doc)],
            task_id="folder-sync-test",
            rag_provider="llamaindex",
            folder_root=str(linked_folder),
        )
    )

    assert (raw_dir / "sub" / "note.md").read_text(encoding="utf-8") == "hello"
    assert not (raw_dir / "note.md").exists()


def test_list_files_accepts_default_alias(monkeypatch, tmp_path: Path) -> None:
    manager = _FakeKBManager(tmp_path / "knowledge_bases")
    manager.config["knowledge_bases"]["actual-kb"] = {
        "path": "actual-kb",
        "status": "ready",
    }
    raw_dir = manager.base_dir / "actual-kb" / "raw"
    raw_dir.mkdir(parents=True)
    (raw_dir / "demo.txt").write_text("hello", encoding="utf-8")
    monkeypatch.setattr(knowledge_router_module, "get_kb_manager", lambda: manager)

    with TestClient(_build_app()) as client:
        response = client.get("/api/knowledge-bases/default/files")

    assert response.status_code == 200
    assert response.json()["files"][0]["name"] == "demo.txt"


def test_list_fallback_reports_error_status(monkeypatch, tmp_path: Path) -> None:
    manager = _FakeKBManager(tmp_path / "knowledge_bases")
    manager.config["knowledge_bases"]["broken-kb"] = {
        "path": "broken-kb",
        "status": "ready",
    }
    (manager.base_dir / "broken-kb").mkdir(parents=True)
    monkeypatch.setattr(knowledge_router_module, "get_kb_manager", lambda: manager)

    with TestClient(_build_app()) as client:
        response = client.get("/api/knowledge-bases")

    assert response.status_code == 200
    [item] = response.json()
    assert item["status"] == "error"
    assert item["progress"]["stage"] == "error"
    assert "get_info" in item["progress"]["error"]


def test_list_reuses_manager_config_snapshot(monkeypatch, tmp_path: Path) -> None:
    class _CountingKBManager:
        def __init__(self) -> None:
            self.base_dir = tmp_path / "knowledge_bases"
            self.base_dir.mkdir(parents=True)
            self.names = ["kb-a", "kb-b", "kb-c"]
            self.list_calls = 0
            self.default_calls = 0
            self.info_calls: list[tuple[str, bool, str | None]] = []

        def list_knowledge_bases(self) -> list[str]:
            self.list_calls += 1
            return self.names

        def get_default(self, *, available_names: list[str] | None = None) -> str:
            self.default_calls += 1
            assert available_names == self.names
            return self.names[0]

        def get_info(
            self,
            name: str,
            *,
            refresh_config: bool,
            default_name: str | None,
        ) -> dict:
            self.info_calls.append((name, refresh_config, default_name))
            return {
                "name": name,
                "path": str(self.base_dir / name),
                "is_default": name == default_name,
                "statistics": {},
                "metadata": {"name": name},
                "status": "ready",
                "progress": None,
            }

    manager = _CountingKBManager()
    monkeypatch.setattr(knowledge_router_module, "get_kb_manager", lambda: manager)
    monkeypatch.setattr(knowledge_router_module, "list_visible_kb_access", lambda: [])

    with TestClient(_build_app()) as client:
        response = client.get("/api/knowledge-bases")

    assert response.status_code == 200
    assert [item["name"] for item in response.json()] == manager.names
    assert manager.list_calls == 1
    assert manager.default_calls == 1
    assert manager.info_calls == [(name, False, "kb-a") for name in manager.names]


def _ready_kb_manager(tmp_path: Path, name: str = "kb") -> "_FakeKBManager":
    manager = _FakeKBManager(tmp_path / "knowledge_bases")
    manager.config["knowledge_bases"][name] = {
        "path": name,
        "rag_provider": "llamaindex",
        "needs_reindex": False,
        "status": "ready",
    }
    (manager.base_dir / name / "raw").mkdir(parents=True, exist_ok=True)
    return manager


def test_create_folder_makes_subdir(monkeypatch, tmp_path: Path) -> None:
    manager = _ready_kb_manager(tmp_path)
    monkeypatch.setattr(knowledge_router_module, "get_kb_manager", lambda: manager)
    monkeypatch.setattr(knowledge_router_module, "_kb_base_dir", tmp_path / "knowledge_bases")

    with TestClient(_build_app()) as client:
        response = client.post("/api/knowledge-bases/kb/folders", json={"path": "Papers/2024"})

    assert response.status_code == 200
    assert response.json()["path"] == "Papers/2024"
    assert (manager.base_dir / "kb" / "raw" / "Papers" / "2024").is_dir()


def test_create_folder_rejects_traversal(monkeypatch, tmp_path: Path) -> None:
    manager = _ready_kb_manager(tmp_path)
    monkeypatch.setattr(knowledge_router_module, "get_kb_manager", lambda: manager)
    monkeypatch.setattr(knowledge_router_module, "_kb_base_dir", tmp_path / "knowledge_bases")

    with TestClient(_build_app()) as client:
        response = client.post("/api/knowledge-bases/kb/folders", json={"path": "../escape"})

    assert response.status_code == 400


def test_list_files_returns_nested_tree(monkeypatch, tmp_path: Path) -> None:
    manager = _ready_kb_manager(tmp_path)
    raw = manager.base_dir / "kb" / "raw"
    (raw / "Papers").mkdir(parents=True)
    (raw / "Papers" / "a.pdf").write_text("%PDF-1.4\n", encoding="utf-8")
    (raw / "root.txt").write_text("hi", encoding="utf-8")
    (raw / "Empty").mkdir()
    monkeypatch.setattr(knowledge_router_module, "get_kb_manager", lambda: manager)

    with TestClient(_build_app()) as client:
        response = client.get("/api/knowledge-bases/kb/files")

    assert response.status_code == 200
    entries = {e["name"]: e for e in response.json()["files"]}
    assert entries["Papers"]["type"] == "folder"
    assert entries["Empty"]["type"] == "folder"  # empty folder still shows
    assert entries["Papers/a.pdf"]["type"] == "file"
    assert entries["root.txt"]["type"] == "file"


def test_remote_kb_file_listing_is_empty_without_creating_local_storage(
    monkeypatch, tmp_path: Path
) -> None:
    manager = _FakeKBManager(tmp_path / "knowledge_bases")
    manager.register_lightrag_server_kb("remote", "http://localhost:9621")
    monkeypatch.setattr(knowledge_router_module, "get_kb_manager", lambda: manager)

    with TestClient(_build_app()) as client:
        response = client.get("/api/knowledge-bases/remote/files")

    assert response.status_code == 200
    assert response.json() == {"files": []}
    assert not (manager.base_dir / "remote").exists()


@pytest.mark.parametrize(
    ("method", "url", "kwargs"),
    [
        ("get", "/api/knowledge-bases/remote/files/demo.txt", {}),
        ("get", "/api/knowledge-bases/remote/file-preview-text/demo.txt", {}),
        ("delete", "/api/knowledge-bases/remote/files/demo.txt", {}),
        ("post", "/api/knowledge-bases/remote/folders", {"json": {"path": "notes"}}),
        (
            "post",
            "/api/knowledge-bases/remote/files/move",
            {"json": {"source": "demo.txt", "dest_folder": "notes"}},
        ),
        ("post", "/api/knowledge-bases/remote/upload", {"files": _upload_payload()}),
    ],
)
def test_remote_kb_rejects_local_file_operations_without_creating_storage(
    monkeypatch, tmp_path: Path, method: str, url: str, kwargs: dict
) -> None:
    manager = _FakeKBManager(tmp_path / "knowledge_bases")
    manager.register_lightrag_server_kb("remote", "http://localhost:9621")
    monkeypatch.setattr(knowledge_router_module, "get_kb_manager", lambda: manager)

    with TestClient(_build_app()) as client:
        response = getattr(client, method)(url, **kwargs)

    assert response.status_code == 409
    assert "external resource" in response.json()["detail"]
    assert not (manager.base_dir / "remote").exists()


def test_list_files_returns_404_for_unknown_kb_without_creating_storage(
    monkeypatch, tmp_path: Path
) -> None:
    manager = _FakeKBManager(tmp_path / "knowledge_bases")
    monkeypatch.setattr(knowledge_router_module, "get_kb_manager", lambda: manager)

    with TestClient(_build_app()) as client:
        response = client.get("/api/knowledge-bases/missing/files")

    assert response.status_code == 404
    assert not (manager.base_dir / "missing").exists()


def test_raw_file_download_rejects_traversal(monkeypatch, tmp_path: Path) -> None:
    manager = _ready_kb_manager(tmp_path)
    (manager.base_dir / "secret.txt").write_text("secret", encoding="utf-8")
    monkeypatch.setattr(knowledge_router_module, "get_kb_manager", lambda: manager)

    with TestClient(_build_app()) as client:
        response = client.get("/api/knowledge-bases/kb/files/%2E%2E/secret.txt")

    assert response.status_code == 403


def test_upload_preserves_folder_structure(monkeypatch, tmp_path: Path) -> None:
    manager = _ready_kb_manager(tmp_path)
    monkeypatch.setattr(knowledge_router_module, "get_kb_manager", lambda: manager)
    monkeypatch.setattr(knowledge_router_module, "_kb_base_dir", tmp_path / "knowledge_bases")

    async def _noop_upload_task(*_args, **_kwargs):
        return None

    monkeypatch.setattr(knowledge_router_module, "run_upload_processing_task", _noop_upload_task)

    with TestClient(_build_app()) as client:
        response = client.post(
            "/api/knowledge-bases/kb/upload",
            files=[("files", ("note.txt", b"hi", "text/plain"))],
            data={"rel_paths": "MyFolder/sub/note.txt"},
        )

    assert response.status_code == 200
    assert (manager.base_dir / "kb" / "raw" / "MyFolder" / "sub" / "note.txt").is_file()


def test_upload_allows_same_filename_in_different_folders(monkeypatch, tmp_path: Path) -> None:
    manager = _ready_kb_manager(tmp_path)
    monkeypatch.setattr(knowledge_router_module, "get_kb_manager", lambda: manager)
    monkeypatch.setattr(knowledge_router_module, "_kb_base_dir", tmp_path / "knowledge_bases")

    async def _noop_upload_task(*_args, **_kwargs):
        return None

    monkeypatch.setattr(knowledge_router_module, "run_upload_processing_task", _noop_upload_task)

    with TestClient(_build_app()) as client:
        response = client.post(
            "/api/knowledge-bases/kb/upload",
            files=[
                ("files", ("note.txt", b"one", "text/plain")),
                ("files", ("note.txt", b"two", "text/plain")),
            ],
            data={"rel_paths": ["ModuleA/note.txt", "ModuleB/note.txt"]},
        )

    assert response.status_code == 200
    assert (manager.base_dir / "kb" / "raw" / "ModuleA" / "note.txt").is_file()
    assert (manager.base_dir / "kb" / "raw" / "ModuleB" / "note.txt").is_file()


def test_upload_places_a_batch_under_dest_subdir(monkeypatch, tmp_path: Path) -> None:
    """A folder pick reports paths relative to the chosen directory, so its
    ancestors never reach the server. dest_subdir re-attaches the batch where
    it belongs instead of stacking every batch at the KB root (#866)."""
    manager = _ready_kb_manager(tmp_path)
    monkeypatch.setattr(knowledge_router_module, "get_kb_manager", lambda: manager)
    monkeypatch.setattr(knowledge_router_module, "_kb_base_dir", tmp_path / "knowledge_bases")

    async def _noop_upload_task(*_args, **_kwargs):
        return None

    monkeypatch.setattr(knowledge_router_module, "run_upload_processing_task", _noop_upload_task)

    with TestClient(_build_app()) as client:
        response = client.post(
            "/api/knowledge-bases/kb/upload",
            files=[("files", ("README.txt", b"cli", "text/plain"))],
            data={
                "rel_paths": "DingTalkCLI/README.txt",
                "dest_subdir": "AppDev",
            },
        )

    assert response.status_code == 200
    raw = manager.base_dir / "kb" / "raw"
    assert (raw / "AppDev" / "DingTalkCLI" / "README.txt").is_file()
    assert not (raw / "DingTalkCLI").exists()


def test_upload_dest_subdir_refuses_traversal(monkeypatch, tmp_path: Path) -> None:
    """dest_subdir is caller-supplied, so it goes through the same guard as a
    directory upload's own relative path — it can never escape raw/."""
    manager = _ready_kb_manager(tmp_path)
    monkeypatch.setattr(knowledge_router_module, "get_kb_manager", lambda: manager)
    monkeypatch.setattr(knowledge_router_module, "_kb_base_dir", tmp_path / "knowledge_bases")

    async def _noop_upload_task(*_args, **_kwargs):
        return None

    monkeypatch.setattr(knowledge_router_module, "run_upload_processing_task", _noop_upload_task)

    with TestClient(_build_app()) as client:
        response = client.post(
            "/api/knowledge-bases/kb/upload",
            files=[("files", ("note.txt", b"hi", "text/plain"))],
            data={"dest_subdir": "../../escaped"},
        )

    assert response.status_code == 400
    assert not (manager.base_dir.parent / "escaped").exists()


def test_upload_without_dest_subdir_is_unchanged(monkeypatch, tmp_path: Path) -> None:
    """The parameter is optional; omitting it keeps the previous placement."""
    manager = _ready_kb_manager(tmp_path)
    monkeypatch.setattr(knowledge_router_module, "get_kb_manager", lambda: manager)
    monkeypatch.setattr(knowledge_router_module, "_kb_base_dir", tmp_path / "knowledge_bases")

    async def _noop_upload_task(*_args, **_kwargs):
        return None

    monkeypatch.setattr(knowledge_router_module, "run_upload_processing_task", _noop_upload_task)

    with TestClient(_build_app()) as client:
        response = client.post(
            "/api/knowledge-bases/kb/upload",
            files=[("files", ("note.txt", b"hi", "text/plain"))],
            data={"rel_paths": "Folder/note.txt"},
        )

    assert response.status_code == 200
    assert (manager.base_dir / "kb" / "raw" / "Folder" / "note.txt").is_file()


def test_move_file_into_folder(monkeypatch, tmp_path: Path) -> None:
    manager = _ready_kb_manager(tmp_path)
    raw = manager.base_dir / "kb" / "raw"
    (raw / "demo.txt").write_text("hi", encoding="utf-8")
    (raw / "Papers").mkdir()
    monkeypatch.setattr(knowledge_router_module, "get_kb_manager", lambda: manager)
    monkeypatch.setattr(knowledge_router_module, "_kb_base_dir", tmp_path / "knowledge_bases")

    with TestClient(_build_app()) as client:
        response = client.post(
            "/api/knowledge-bases/kb/files/move",
            json={"source": "demo.txt", "dest_folder": "Papers"},
        )

    assert response.status_code == 200
    assert (raw / "Papers" / "demo.txt").is_file()
    assert not (raw / "demo.txt").exists()


def test_list_files_preserves_kb_named_default(monkeypatch, tmp_path: Path) -> None:
    manager = _FakeKBManager(tmp_path / "knowledge_bases")
    manager.config["knowledge_bases"]["actual-kb"] = {
        "path": "actual-kb",
        "status": "ready",
    }
    manager.config["knowledge_bases"]["default"] = {
        "path": "default",
        "status": "ready",
    }
    actual_raw = manager.base_dir / "actual-kb" / "raw"
    actual_raw.mkdir(parents=True)
    (actual_raw / "actual.txt").write_text("hello", encoding="utf-8")
    default_raw = manager.base_dir / "default" / "raw"
    default_raw.mkdir(parents=True)
    (default_raw / "default.txt").write_text("hello", encoding="utf-8")
    monkeypatch.setattr(knowledge_router_module, "get_kb_manager", lambda: manager)

    with TestClient(_build_app()) as client:
        response = client.get("/api/knowledge-bases/default/files")

    assert response.status_code == 200
    assert response.json()["files"][0]["name"] == "default.txt"


def test_file_preview_text_accepts_default_alias(monkeypatch, tmp_path: Path) -> None:
    manager = _FakeKBManager(tmp_path / "knowledge_bases")
    manager.config["knowledge_bases"]["actual-kb"] = {
        "path": "actual-kb",
        "status": "ready",
    }
    raw_dir = manager.base_dir / "actual-kb" / "raw"
    raw_dir.mkdir(parents=True)
    target = raw_dir / "slides.pptx"
    target.write_bytes(b"PK\x03\x04")
    calls: dict[str, object] = {}

    def _fake_extract(path: Path, **kwargs) -> str:
        calls["path"] = path
        calls["kwargs"] = kwargs
        return "--- Slide 1 ---\nTitle"

    monkeypatch.setattr(knowledge_router_module, "get_kb_manager", lambda: manager)
    monkeypatch.setattr(knowledge_router_module, "extract_text_from_path", _fake_extract)

    with TestClient(_build_app()) as client:
        response = client.get("/api/knowledge-bases/default/file-preview-text/slides.pptx")

    assert response.status_code == 200
    assert response.text == "--- Slide 1 ---\nTitle"
    assert calls["path"] == target
    assert calls["kwargs"]["max_chars"] == 200_000


def test_file_preview_text_returns_422_for_extraction_errors(monkeypatch, tmp_path: Path) -> None:
    manager = _FakeKBManager(tmp_path / "knowledge_bases")
    manager.config["knowledge_bases"]["actual-kb"] = {
        "path": "actual-kb",
        "status": "ready",
    }
    raw_dir = manager.base_dir / "actual-kb" / "raw"
    raw_dir.mkdir(parents=True)
    (raw_dir / "slides.pptx").write_bytes(b"PK\x03\x04")
    extraction_error = knowledge_router_module.DocumentExtractionError

    def _fake_extract(*_args, **_kwargs) -> str:
        raise extraction_error("slides.pptx: no extractable text")

    monkeypatch.setattr(knowledge_router_module, "get_kb_manager", lambda: manager)
    monkeypatch.setattr(knowledge_router_module, "extract_text_from_path", _fake_extract)

    with TestClient(_build_app()) as client:
        response = client.get("/api/knowledge-bases/actual-kb/file-preview-text/slides.pptx")

    assert response.status_code == 422
    assert "no extractable text" in response.json()["detail"]


def test_reindex_accepts_default_alias(monkeypatch, tmp_path: Path) -> None:
    manager = _FakeKBManager(tmp_path / "knowledge_bases")
    manager.config["knowledge_bases"]["actual-kb"] = {
        "path": "actual-kb",
        "status": "ready",
    }
    monkeypatch.setattr(knowledge_router_module, "get_kb_manager", lambda: manager)
    monkeypatch.setattr(knowledge_router_module, "_kb_base_dir", manager.base_dir)

    class _Signature:
        def hash(self) -> str:
            return "sig"

    embedding_signature = importlib.import_module("deeptutor.services.rag.embedding_signature")
    index_versioning = importlib.import_module("deeptutor.services.rag.index_versioning")
    monkeypatch.setattr(
        embedding_signature, "signature_from_embedding_config", lambda: _Signature()
    )
    monkeypatch.setattr(index_versioning, "find_matching_version", lambda *_args, **_kwargs: None)

    async def _noop_reindex_task(*_args, **_kwargs):
        return None

    monkeypatch.setattr(knowledge_router_module, "run_reindex_task", _noop_reindex_task)

    with TestClient(_build_app()) as client:
        response = client.post("/api/knowledge-bases/default/reindex")

    assert response.status_code == 200
    body = response.json()
    assert body["noop"] is False
    assert isinstance(body.get("task_id"), str) and body["task_id"]
    assert manager.config["knowledge_bases"]["actual-kb"]["status"] == "initializing"


def test_reindex_error_status_bypasses_existing_match_noop(monkeypatch, tmp_path: Path) -> None:
    manager = _FakeKBManager(tmp_path / "knowledge_bases")
    manager.config["knowledge_bases"]["failed-kb"] = {
        "path": "failed-kb",
        "status": "error",
        "progress": {"stage": "error", "message": "previous indexing failed"},
    }
    monkeypatch.setattr(knowledge_router_module, "get_kb_manager", lambda: manager)
    monkeypatch.setattr(knowledge_router_module, "_kb_base_dir", manager.base_dir)

    class _Signature:
        def hash(self) -> str:
            return "sig"

    embedding_signature = importlib.import_module("deeptutor.services.rag.embedding_signature")
    index_versioning = importlib.import_module("deeptutor.services.rag.index_versioning")
    monkeypatch.setattr(
        embedding_signature, "signature_from_embedding_config", lambda: _Signature()
    )
    monkeypatch.setattr(
        index_versioning,
        "find_matching_version",
        lambda *_args, **_kwargs: {"layout": "flat", "ready": True},
    )

    async def _noop_reindex_task(*_args, **_kwargs):
        return None

    monkeypatch.setattr(knowledge_router_module, "run_reindex_task", _noop_reindex_task)

    with TestClient(_build_app()) as client:
        response = client.post("/api/knowledge-bases/failed-kb/reindex")

    assert response.status_code == 200
    body = response.json()
    assert body["noop"] is False
    assert isinstance(body.get("task_id"), str) and body["task_id"]
    assert manager.config["knowledge_bases"]["failed-kb"]["status"] == "initializing"


def test_reindex_task_persists_completed_progress(monkeypatch, tmp_path: Path) -> None:
    base_dir = tmp_path / "knowledge_bases"
    raw_dir = base_dir / "kb" / "raw"
    raw_dir.mkdir(parents=True)
    (raw_dir / "fixture.txt").write_text("synthetic fixture", encoding="utf-8")
    (base_dir / "kb_config.json").write_text(
        json.dumps(
            {
                "knowledge_bases": {
                    "kb": {
                        "path": "kb",
                        "rag_provider": "lightrag",
                        "status": "processing",
                        "needs_reindex": True,
                        "embedding_mismatch": {"reason": "test"},
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    class _SuccessfulRagService:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        async def initialize(self, *_args, **kwargs) -> bool:
            kwargs["progress_callback"](1, 1)
            return True

    rag_service_module = importlib.import_module("deeptutor.services.rag.service")
    manager_module = importlib.import_module("deeptutor.knowledge.manager")
    manager = manager_module.KnowledgeBaseManager(base_dir=str(base_dir))
    monkeypatch.setattr(rag_service_module, "RAGService", _SuccessfulRagService)
    monkeypatch.setattr(
        knowledge_router_module,
        "get_kb_manager",
        lambda: manager,
    )

    asyncio.run(
        knowledge_router_module.run_reindex_task(
            kb_name="kb",
            base_dir=str(base_dir),
            task_id="reindex-success-test",
            signature_hash="lightrag",
        )
    )

    progress = json.loads((base_dir / "kb" / ".progress.json").read_text(encoding="utf-8"))
    assert progress == {
        "kb_name": "kb",
        "task_id": "reindex-success-test",
        "stage": "completed",
        "message": "Re-index complete",
        "current": 1,
        "total": 1,
        "file_name": "",
        "progress_percent": 100,
        "timestamp": progress["timestamp"],
        "indexed_count": 1,
        "index_changed": True,
        "index_action": "reindex",
    }
    monkeypatch.setattr(
        knowledge_router_module,
        "resolve_kb",
        lambda _name: SimpleNamespace(name="kb", base_dir=base_dir),
    )
    with TestClient(_build_app()) as client:
        response = client.get("/api/knowledge-bases/kb/progress")
    assert response.status_code == 200
    assert response.json() == progress

    persisted = json.loads((base_dir / "kb_config.json").read_text(encoding="utf-8"))
    entry = persisted["knowledge_bases"]["kb"]
    assert entry["status"] == "ready"
    assert "progress" not in entry
    assert entry["last_indexed_count"] == 1
    assert entry["last_indexed_action"] == "reindex"
    assert entry["needs_reindex"] is False
    assert "embedding_mismatch" not in entry


def test_reindex_task_preserves_prepublication_failure(monkeypatch, tmp_path: Path) -> None:
    base_dir = tmp_path / "knowledge_bases"
    raw_dir = base_dir / "kb" / "raw"
    raw_dir.mkdir(parents=True)
    (raw_dir / "fixture.txt").write_text("fixture", encoding="utf-8")
    (base_dir / "kb_config.json").write_text(
        json.dumps(
            {
                "knowledge_bases": {
                    "kb": {
                        "path": "kb",
                        "rag_provider": "lightrag",
                        "status": "processing",
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    class _FailingRagService:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        async def initialize(self, *_args, **_kwargs) -> bool:
            raise RuntimeError("original indexing failure")

    rag_service_module = importlib.import_module("deeptutor.services.rag.service")
    monkeypatch.setattr(rag_service_module, "RAGService", _FailingRagService)
    task_id = knowledge_router_module._build_unique_task_id("kb_reindex", "prepublish-fail")

    asyncio.run(
        knowledge_router_module.run_reindex_task(
            kb_name="kb",
            base_dir=str(base_dir),
            task_id=task_id,
            signature_hash="lightrag",
        )
    )

    task = knowledge_router_module.TaskIDManager.get_instance().get_task_metadata(task_id)
    assert task is not None
    assert task["status"] == "error"
    assert task["error"] == "original indexing failure"


@pytest.mark.parametrize("failed_sink", ["progress_file", "central_config"])
def test_reindex_task_does_not_report_a_published_version_as_failed_when_bookkeeping_fails(
    monkeypatch, tmp_path: Path, failed_sink: str
) -> None:
    base_dir = tmp_path / "knowledge_bases"
    raw_dir = base_dir / "kb" / "raw"
    raw_dir.mkdir(parents=True)
    (raw_dir / "fixture.txt").write_text("synthetic fixture", encoding="utf-8")
    (base_dir / "kb_config.json").write_text(
        json.dumps(
            {
                "knowledge_bases": {
                    "kb": {
                        "path": "kb",
                        "rag_provider": "lightrag",
                        "status": "processing",
                        "needs_reindex": True,
                        "embedding_mismatch": {"reason": "test"},
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    class _SuccessfulRagService:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        async def initialize(self, *_args, **kwargs) -> bool:
            kwargs["progress_callback"](1, 1)
            return True

    rag_service_module = importlib.import_module("deeptutor.services.rag.service")
    manager_module = importlib.import_module("deeptutor.knowledge.manager")
    progress_module = importlib.import_module("deeptutor.knowledge.progress_tracker")
    task_manager = knowledge_router_module.TaskIDManager.get_instance()
    task_id = knowledge_router_module._build_unique_task_id(
        "kb_reindex", f"terminal-persistence-{failed_sink}"
    )
    manager = manager_module.KnowledgeBaseManager(base_dir=str(base_dir))
    monkeypatch.setattr(rag_service_module, "RAGService", _SuccessfulRagService)
    monkeypatch.setattr(knowledge_router_module, "get_kb_manager", lambda: manager)

    if failed_sink == "progress_file":
        original_atomic_write_json = progress_module.atomic_write_json

        def _fail_completed_progress_file(path: Path, payload: dict) -> None:
            if path.name == ".progress.json" and payload.get("stage") == "completed":
                raise OSError("synthetic completed progress failure")
            original_atomic_write_json(path, payload)

        monkeypatch.setattr(progress_module, "atomic_write_json", _fail_completed_progress_file)
    else:
        original_update_kb_status = manager_module.KnowledgeBaseManager.update_kb_status

        def _fail_ready_status(self, name: str, status: str, progress=None) -> None:
            if name == "kb" and status == "ready":
                raise OSError("synthetic ready status failure")
            original_update_kb_status(self, name=name, status=status, progress=progress)

        monkeypatch.setattr(
            manager_module.KnowledgeBaseManager,
            "update_kb_status",
            _fail_ready_status,
        )

    asyncio.run(
        knowledge_router_module.run_reindex_task(
            kb_name="kb",
            base_dir=str(base_dir),
            task_id=task_id,
            signature_hash="lightrag",
        )
    )

    task = task_manager.get_task_metadata(task_id)
    assert task is not None
    assert task["status"] == "completed"
    progress = json.loads((base_dir / "kb" / ".progress.json").read_text(encoding="utf-8"))
    persisted = json.loads((base_dir / "kb_config.json").read_text(encoding="utf-8"))
    entry = persisted["knowledge_bases"]["kb"]
    if failed_sink == "progress_file":
        assert progress["stage"] != "error"
        assert entry["status"] == "ready"
    else:
        assert progress["stage"] == "completed"
        assert entry["status"] == "processing"
    assert entry["needs_reindex"] is True
    assert entry["embedding_mismatch"] == {"reason": "test"}


def test_retry_error_status_queues_reindex(monkeypatch, tmp_path: Path) -> None:
    manager = _FakeKBManager(tmp_path / "knowledge_bases")
    manager.config["knowledge_bases"]["failed-kb"] = {
        "path": "failed-kb",
        "status": "error",
        "progress": {"stage": "error", "message": "previous indexing failed"},
    }
    monkeypatch.setattr(knowledge_router_module, "get_kb_manager", lambda: manager)
    monkeypatch.setattr(knowledge_router_module, "_kb_base_dir", manager.base_dir)

    class _Signature:
        def hash(self) -> str:
            return "sig"

    embedding_signature = importlib.import_module("deeptutor.services.rag.embedding_signature")
    index_versioning = importlib.import_module("deeptutor.services.rag.index_versioning")
    monkeypatch.setattr(
        embedding_signature, "signature_from_embedding_config", lambda: _Signature()
    )
    monkeypatch.setattr(
        index_versioning,
        "find_matching_version",
        lambda *_args, **_kwargs: {"layout": "flat", "ready": True},
    )

    async def _noop_reindex_task(*_args, **_kwargs):
        return None

    monkeypatch.setattr(knowledge_router_module, "run_reindex_task", _noop_reindex_task)

    with TestClient(_build_app()) as client:
        response = client.post("/api/knowledge-bases/failed-kb/retry")

    assert response.status_code == 200
    body = response.json()
    assert body["noop"] is False
    assert isinstance(body.get("task_id"), str) and body["task_id"]
    assert manager.config["knowledge_bases"]["failed-kb"]["status"] == "initializing"


def test_retry_rejects_non_error_kb(monkeypatch, tmp_path: Path) -> None:
    manager = _FakeKBManager(tmp_path / "knowledge_bases")
    manager.config["knowledge_bases"]["ready-kb"] = {
        "path": "ready-kb",
        "status": "ready",
    }
    monkeypatch.setattr(knowledge_router_module, "get_kb_manager", lambda: manager)
    monkeypatch.setattr(knowledge_router_module, "_kb_base_dir", manager.base_dir)

    with TestClient(_build_app()) as client:
        response = client.post("/api/knowledge-bases/ready-kb/retry")

    assert response.status_code == 409
    assert "not in an error state" in response.json()["detail"]


def test_reindex_bypasses_existing_match_when_vectors_are_invalid(
    monkeypatch, tmp_path: Path
) -> None:
    manager = _FakeKBManager(tmp_path / "knowledge_bases")
    manager.config["knowledge_bases"]["bad-index-kb"] = {
        "path": "bad-index-kb",
        "status": "ready",
    }
    monkeypatch.setattr(knowledge_router_module, "get_kb_manager", lambda: manager)
    monkeypatch.setattr(knowledge_router_module, "_kb_base_dir", manager.base_dir)

    class _Signature:
        def hash(self) -> str:
            return "sig"

    kb_dir = manager.base_dir / "bad-index-kb"
    version_dir = kb_dir / "version-1"
    version_dir.mkdir(parents=True)
    (version_dir / "docstore.json").write_text("{}", encoding="utf-8")
    (version_dir / "index_store.json").write_text("{}", encoding="utf-8")
    (version_dir / "meta.json").write_text(
        json.dumps({"signature": "sig", "version": "version-1"}),
        encoding="utf-8",
    )
    (version_dir / "default__vector_store.json").write_text(
        json.dumps({"embedding_dict": {"bad-node": [0.1, None, 0.3]}}),
        encoding="utf-8",
    )

    embedding_signature = importlib.import_module("deeptutor.services.rag.embedding_signature")
    monkeypatch.setattr(
        embedding_signature, "signature_from_embedding_config", lambda: _Signature()
    )

    async def _noop_reindex_task(*_args, **_kwargs):
        return None

    monkeypatch.setattr(knowledge_router_module, "run_reindex_task", _noop_reindex_task)

    with TestClient(_build_app()) as client:
        response = client.post("/api/knowledge-bases/bad-index-kb/reindex")

    assert response.status_code == 200
    body = response.json()
    assert body["noop"] is False
    assert isinstance(body.get("task_id"), str) and body["task_id"]
    assert manager.config["knowledge_bases"]["bad-index-kb"]["status"] == "initializing"


def test_update_config_coerces_legacy_provider_to_llamaindex() -> None:
    """Legacy `rag_provider` values are accepted and normalized to llamaindex."""

    class _FakeConfigService:
        def __init__(self) -> None:
            self.config: dict = {}

        def set_kb_config(self, kb_name: str, config: dict) -> None:
            self.kb_name = kb_name
            self.config = config

        def get_kb_config(self, _kb_name: str) -> dict:
            return self.config

    fake_service = _FakeConfigService()

    config_module = importlib.import_module("deeptutor.services.config")
    app = _build_app()

    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setattr(config_module, "get_kb_config_service", lambda: fake_service)
        with TestClient(app) as client:
            response = client.put(
                "/api/knowledge-bases/demo/config",
                json={"rag_provider": "raganything"},
            )

    assert response.status_code in {200, 204}
    assert fake_service.config.get("rag_provider") == "llamaindex"


def test_update_config_preserves_known_provider() -> None:
    class _FakeConfigService:
        def __init__(self) -> None:
            self.config: dict = {}

        def set_kb_config(self, kb_name: str, config: dict) -> None:
            self.kb_name = kb_name
            self.config = config

        def get_kb_config(self, _kb_name: str) -> dict:
            return self.config

    fake_service = _FakeConfigService()

    config_module = importlib.import_module("deeptutor.services.config")
    app = _build_app()

    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setattr(config_module, "get_kb_config_service", lambda: fake_service)
        with TestClient(app) as client:
            response = client.put(
                "/api/knowledge-bases/demo/config",
                json={"rag_provider": "pageindex"},
            )

    assert response.status_code in {200, 204}
    assert fake_service.config.get("rag_provider") == "pageindex"


def test_update_config_rejects_provider_change_for_ready_index(monkeypatch, tmp_path: Path) -> None:
    kb_dir = tmp_path / "demo"
    kb_dir.mkdir(parents=True)
    _write_ready_llamaindex_version(kb_dir)

    class _FakeConfigService:
        def __init__(self) -> None:
            self.config: dict = {"rag_provider": "llamaindex"}

        def set_kb_config(self, kb_name: str, config: dict) -> None:
            self.kb_name = kb_name
            self.config.update(config)

        def get_kb_config(self, _kb_name: str) -> dict:
            return dict(self.config)

    fake_service = _FakeConfigService()
    config_module = importlib.import_module("deeptutor.services.config")

    monkeypatch.setattr(config_module, "get_kb_config_service", lambda: fake_service)
    monkeypatch.setattr(knowledge_router_module, "_current_kb_base_dir", lambda: tmp_path)

    with TestClient(_build_app()) as client:
        response = client.put(
            "/api/knowledge-bases/demo/config",
            json={"rag_provider": "pageindex"},
        )

    assert response.status_code == 409
    assert "ready llamaindex index" in response.json()["detail"]
    assert fake_service.config["rag_provider"] == "llamaindex"


def test_rag_providers_marks_linkable() -> None:
    with TestClient(_build_app()) as client:
        providers = client.get("/api/knowledge-bases/rag-providers").json()["providers"]
    by_id = {p["id"]: p for p in providers}
    # Self-contained local indexes can be linked in place; PageIndex (cloud) and
    # LightRAG Server (remote, no local folder) can't.
    assert by_id["llamaindex"]["linkable"] is True
    assert by_id["graphrag"]["linkable"] is True
    assert by_id["lightrag"]["linkable"] is True
    assert by_id["pageindex"]["linkable"] is False
    assert by_id["lightrag-server"]["linkable"] is False


def test_probe_folder_endpoint_finds_ready_index(tmp_path: Path) -> None:
    version = tmp_path / "version-1"
    version.mkdir()
    (version / "docstore.json").write_text("{}", encoding="utf-8")
    (version / "index_store.json").write_text("{}", encoding="utf-8")
    (version / "meta.json").write_text(
        json.dumps({"version": "version-1", "signature": "x", "layout": "flat"}),
        encoding="utf-8",
    )

    with TestClient(_build_app()) as client:
        response = client.post(
            "/api/knowledge-bases/probe-folder",
            json={"folder_path": str(tmp_path), "rag_provider": "llamaindex"},
        )

    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["version"] == "version-1"


def test_probe_folder_endpoint_rejects_pageindex(tmp_path: Path) -> None:
    with TestClient(_build_app()) as client:
        response = client.post(
            "/api/knowledge-bases/probe-folder",
            json={"folder_path": str(tmp_path), "rag_provider": "pageindex"},
        )
    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is False
    assert payload["error"]


def _patch_server_probe(monkeypatch, *, ok: bool, error: str | None = None) -> None:
    """Stub the LightRAG server probe so router tests need no live server."""
    from deeptutor.services.rag.pipelines.lightrag_server import probe as probe_module

    async def _fake_probe(server_url: str, api_key: str = "", **_kwargs):
        result = probe_module.ServerProbe(base_url=server_url.rstrip("/"))
        result.ok = ok
        result.reachable = ok
        result.auth_required = bool(api_key)
        result.auth_ok = ok
        result.error = error
        return result

    monkeypatch.setattr(probe_module, "probe_server", _fake_probe)


def test_probe_lightrag_server_endpoint_reports_verdict(monkeypatch) -> None:
    _patch_server_probe(monkeypatch, ok=True)
    with TestClient(_build_app()) as client:
        response = client.post(
            "/api/knowledge-bases/probe-lightrag-server",
            json={"server_url": "http://localhost:9621", "api_key": "k"},
        )
    assert response.status_code == 200
    payload = response.json()
    assert payload["ok"] is True
    assert payload["base_url"] == "http://localhost:9621"


def test_connect_lightrag_server_registers_pointer(monkeypatch, tmp_path: Path) -> None:
    manager = _FakeKBManager(tmp_path / "knowledge_bases")
    monkeypatch.setattr(knowledge_router_module, "get_kb_manager", lambda: manager)
    _patch_server_probe(monkeypatch, ok=True)

    with TestClient(_build_app()) as client:
        response = client.post(
            "/api/knowledge-bases/connect-lightrag-server",
            json={
                "name": "remote-kb",
                "server_url": "http://localhost:9621/",
                "api_key": "secret",
                "search_mode": "MIX",
            },
        )

    assert response.status_code == 200
    body = response.json()
    assert body["rag_provider"] == "lightrag-server"
    entry = manager.config["knowledge_bases"]["remote-kb"]
    assert entry["type"] == "lightrag_server"
    assert entry["server_url"] == "http://localhost:9621"
    assert entry["search_mode"] == "mix"  # normalized + validated


def test_connect_lightrag_server_rejects_unreachable(monkeypatch, tmp_path: Path) -> None:
    manager = _FakeKBManager(tmp_path / "knowledge_bases")
    monkeypatch.setattr(knowledge_router_module, "get_kb_manager", lambda: manager)
    _patch_server_probe(monkeypatch, ok=False, error="Could not reach a LightRAG server")

    with TestClient(_build_app()) as client:
        response = client.post(
            "/api/knowledge-bases/connect-lightrag-server",
            json={"name": "bad", "server_url": "http://nope:9621"},
        )

    assert response.status_code == 400
    assert "LightRAG" in response.json()["detail"]
    assert "bad" not in manager.config["knowledge_bases"]


def _patch_weknora_probe(monkeypatch, *, ok: bool, error: str | None = None) -> None:
    from deeptutor.services.rag.pipelines.weknora import probe as probe_module

    async def _fake_probe(server_url: str, api_key: str, knowledge_base_id: str, **_kwargs):
        result = probe_module.WeKnoraProbe(
            base_url=server_url.rstrip("/"),
            knowledge_base_id=knowledge_base_id,
        )
        result.ok = ok
        result.reachable = ok
        result.credentials_ok = ok
        result.knowledge_base_found = ok
        result.knowledge_base_name = "Research" if ok else None
        result.error = error
        return result

    monkeypatch.setattr(probe_module, "probe_weknora", _fake_probe)


def test_weknora_probe_and_connect_endpoints(monkeypatch, tmp_path: Path) -> None:
    manager = _FakeKBManager(tmp_path / "knowledge_bases")
    monkeypatch.setattr(knowledge_router_module, "get_kb_manager", lambda: manager)
    _patch_weknora_probe(monkeypatch, ok=True)

    with TestClient(_build_app()) as client:
        probe = client.post(
            "/api/knowledge-bases/probe-weknora",
            json={
                "server_url": "http://localhost:8080/",
                "api_key": "secret",
                "knowledge_base_id": "kb-1",
            },
        )
        connected = client.post(
            "/api/knowledge-bases/connect-weknora",
            json={
                "name": "weknora-kb",
                "server_url": "http://localhost:8080/",
                "api_key": "secret",
                "knowledge_base_id": "kb-1",
            },
        )

    assert probe.status_code == 200
    assert probe.json()["ok"] is True
    assert probe.json()["knowledge_base_name"] == "Research"
    assert connected.status_code == 200
    body = connected.json()
    assert body["rag_provider"] == "weknora"
    entry = manager.config["knowledge_bases"]["weknora-kb"]
    assert entry["server_url"] == "http://localhost:8080"
    assert entry["knowledge_base_id"] == "kb-1"


def test_weknora_connection_routes_are_admin_gated() -> None:
    from deeptutor.api.routers.auth import require_admin

    routes = {
        route.path: route
        for route in knowledge_router_module.router.routes
        if route.path in {"/knowledge-bases/probe-weknora", "/knowledge-bases/connect-weknora"}
    }
    assert set(routes) == {
        "/knowledge-bases/probe-weknora",
        "/knowledge-bases/connect-weknora",
    }
    for route in routes.values():
        assert any(dependency.call is require_admin for dependency in route.dependant.dependencies)


def test_connect_weknora_rejects_failed_probe(monkeypatch, tmp_path: Path) -> None:
    manager = _FakeKBManager(tmp_path / "knowledge_bases")
    monkeypatch.setattr(knowledge_router_module, "get_kb_manager", lambda: manager)
    _patch_weknora_probe(monkeypatch, ok=False, error="Knowledge base missing")

    with TestClient(_build_app()) as client:
        response = client.post(
            "/api/knowledge-bases/connect-weknora",
            json={
                "name": "bad",
                "server_url": "http://localhost:8080",
                "api_key": "secret",
                "knowledge_base_id": "missing",
            },
        )

    assert response.status_code == 400
    assert "WeKnora" in response.json()["detail"] or "Knowledge base" in response.json()["detail"]
    assert "bad" not in manager.config["knowledge_bases"]


def test_assert_not_connected_kb_blocks_connected_writes() -> None:
    from fastapi import HTTPException

    guard = knowledge_router_module._assert_not_connected_kb
    for kind in ("linked", "obsidian", "lightrag_server", "weknora"):
        with pytest.raises(HTTPException) as excinfo:
            guard("kb", {"type": kind})
        assert excinfo.value.status_code == 409
    # An ordinary KB is writable — the guard is a no-op.
    guard("kb", {"path": "kb", "status": "ready"})


def _write_upload_task_kb(tmp_path: Path) -> Path:
    base_dir = tmp_path / "knowledge_bases"
    kb_dir = base_dir / "kb"
    (kb_dir / "raw").mkdir(parents=True)
    _write_ready_llamaindex_version(kb_dir)
    (base_dir / "kb_config.json").write_text(
        json.dumps(
            {
                "knowledge_bases": {
                    "kb": {
                        "path": "kb",
                        "rag_provider": "llamaindex",
                        "status": "ready",
                    }
                }
            }
        ),
        encoding="utf-8",
    )
    return base_dir


def test_create_pageindex_oss_persists_optional_mode(monkeypatch, tmp_path: Path) -> None:
    manager = _FakeKBManager(tmp_path / "knowledge_bases")
    monkeypatch.setattr(knowledge_router_module, "get_kb_manager", lambda: manager)
    monkeypatch.setattr(knowledge_router_module, "KnowledgeBaseInitializer", _FakeInitializer)
    monkeypatch.setattr(knowledge_router_module, "_kb_base_dir", tmp_path / "knowledge_bases")
    preflight = importlib.import_module("deeptutor.services.rag.preflight")
    monkeypatch.setattr(preflight, "engine_preflight", lambda _provider: {"ok": True, "checks": []})

    async def _noop_init_task(*_args, **_kwargs):
        return None

    monkeypatch.setattr(knowledge_router_module, "run_initialization_task", _noop_init_task)
    with TestClient(_build_app()) as client:
        response = client.post(
            "/api/knowledge-bases",
            data={
                "name": "kb-oss",
                "rag_provider": "pageindex-oss",
                "pageindex_mode": "standard",
            },
            files=[("files", ("demo.pdf", b"%PDF-1.4\n", "application/pdf"))],
        )

    assert response.status_code == 200
    entry = manager.config["knowledge_bases"]["kb-oss"]
    assert entry["rag_provider"] == "pageindex-oss"
    assert entry["pageindex_mode"] == "standard"


def test_create_mode_aware_kb_persists_per_kb_search_mode(monkeypatch, tmp_path: Path) -> None:
    manager = _FakeKBManager(tmp_path / "knowledge_bases")
    snapshot = SimpleNamespace(
        persisted_policy=lambda: {
            "policy": "pinned",
            "selection": {"profile_id": "profile-1", "model_id": "model-1"},
            "descriptor": {"model": "safe-model"},
            "fingerprint": "a" * 64,
            "vision_available": True,
        }
    )
    monkeypatch.setattr(knowledge_router_module, "get_kb_manager", lambda: manager)
    monkeypatch.setattr(knowledge_router_module, "KnowledgeBaseInitializer", _FakeInitializer)
    monkeypatch.setattr(knowledge_router_module, "_kb_base_dir", tmp_path / "knowledge_bases")
    preflight = importlib.import_module("deeptutor.services.rag.preflight")
    monkeypatch.setattr(preflight, "engine_preflight", lambda _provider: {"ok": True, "checks": []})
    lightrag_config = importlib.import_module("deeptutor.services.rag.pipelines.lightrag.config")
    monkeypatch.setattr(lightrag_config, "is_lightrag_available", lambda: True)
    monkeypatch.setattr(
        knowledge_router_module,
        "_freeze_default_indexing_llm",
        lambda: snapshot,
    )

    async def _noop_init_task(*_args, **_kwargs):
        return None

    monkeypatch.setattr(knowledge_router_module, "run_initialization_task", _noop_init_task)
    with TestClient(_build_app()) as client:
        response = client.post(
            "/api/knowledge-bases",
            data={
                "name": "kb-light",
                "rag_provider": "lightrag",
                "search_mode": "hybrid",
            },
            files=_upload_payload(),
        )

    assert response.status_code == 200
    assert manager.config["knowledge_bases"]["kb-light"]["search_mode"] == "hybrid"


def test_create_empty_lightrag_kb_persists_redacted_pending_policy(
    monkeypatch, tmp_path: Path
) -> None:
    manager = _FakeKBManager(tmp_path / "knowledge_bases")
    snapshot = SimpleNamespace(
        persisted_policy=lambda: {
            "policy": "pinned",
            "selection": {"profile_id": "profile-1", "model_id": "model-1"},
            "descriptor": {"model": "safe-model"},
            "fingerprint": "a" * 64,
            "vision_available": True,
        }
    )
    seen: list[str] = []

    def freeze_form(raw: str):
        seen.append(raw)
        return {"profile_id": "profile-1", "model_id": "model-1"}, snapshot

    monkeypatch.setattr(knowledge_router_module, "get_kb_manager", lambda: manager)
    monkeypatch.setattr(knowledge_router_module, "KnowledgeBaseInitializer", _FakeInitializer)
    monkeypatch.setattr(knowledge_router_module, "_kb_base_dir", manager.base_dir)
    monkeypatch.setattr(knowledge_router_module, "_assert_provider_ready", lambda _provider: None)
    monkeypatch.setattr(knowledge_router_module, "_freeze_indexing_llm_form", freeze_form)

    with TestClient(_build_app()) as client:
        response = client.post(
            "/api/knowledge-bases",
            data={
                "name": "kb-pending",
                "rag_provider": "lightrag",
                "indexing_llm": json.dumps({"profile_id": "profile-1", "model_id": "model-1"}),
            },
        )

    assert response.status_code == 200
    assert len(seen) == 1
    pending = manager.config["knowledge_bases"]["kb-pending"]["pending_indexing_policy"]
    assert pending["policy"] == "pending_pinned"
    assert pending["fingerprint"] == "a" * 64
    assert pending["selection"] == {"profile_id": "profile-1", "model_id": "model-1"}
    assert not list((manager.base_dir / "kb-pending").glob("version-*"))


def test_create_rejects_indexing_selection_for_other_provider_before_registration(
    monkeypatch, tmp_path: Path
) -> None:
    manager = _FakeKBManager(tmp_path / "knowledge_bases")
    monkeypatch.setattr(knowledge_router_module, "get_kb_manager", lambda: manager)
    monkeypatch.setattr(knowledge_router_module, "_kb_base_dir", manager.base_dir)

    with TestClient(_build_app()) as client:
        response = client.post(
            "/api/knowledge-bases",
            data={
                "name": "wrong-provider",
                "rag_provider": "llamaindex",
                "indexing_llm": json.dumps({"profile_id": "profile-1", "model_id": "model-1"}),
            },
        )

    assert response.status_code == 400
    assert manager.config["knowledge_bases"] == {}


def test_empty_lightrag_kb_can_update_pending_indexing_policy(monkeypatch, tmp_path: Path) -> None:
    manager = _FakeKBManager(tmp_path / "knowledge_bases")
    manager.config["knowledge_bases"]["empty"] = {
        "rag_provider": "lightrag",
        "status": "ready",
        "progress": {"stage": "completed"},
    }
    (manager.base_dir / "empty" / "raw").mkdir(parents=True)
    policy = {
        "policy": "pending_pinned",
        "selection": {
            "profile_id": "profile-1",
            "model_id": "model-1",
            "reasoning_effort": "none",
        },
        "descriptor": {"model": "safe-model", "reasoning_effort": "none"},
        "fingerprint": "b" * 64,
        "vision_available": False,
    }
    monkeypatch.setattr(knowledge_router_module, "get_kb_manager", lambda: manager)
    monkeypatch.setattr(
        "deeptutor.services.rag.pipelines.lightrag.storage.latest_published_root",
        lambda _kb_dir: None,
    )
    monkeypatch.setattr(
        "deeptutor.services.rag.pipelines.lightrag.indexing_policy.pending_policy_for_selection",
        lambda selection: policy if selection["reasoning_effort"] == "none" else None,
    )

    with TestClient(_build_app()) as client:
        response = client.put(
            "/api/knowledge-bases/empty/indexing-policy",
            json={
                "profile_id": "profile-1",
                "model_id": "model-1",
                "reasoning_effort": "none",
            },
        )

    assert response.status_code == 200
    assert response.json()["indexing_policy"] == policy
    assert manager.config["knowledge_bases"]["empty"]["pending_indexing_policy"] == policy


@pytest.mark.parametrize("reason", ["published", "documents", "active"])
def test_pending_indexing_policy_update_rejects_ineligible_kb(
    monkeypatch, tmp_path: Path, reason: str
) -> None:
    manager = _FakeKBManager(tmp_path / "knowledge_bases")
    entry = {"rag_provider": "lightrag", "status": "ready"}
    manager.config["knowledge_bases"]["kb"] = entry
    raw_dir = manager.base_dir / "kb" / "raw"
    raw_dir.mkdir(parents=True)
    if reason == "documents":
        (raw_dir / "doc.txt").write_text("content", encoding="utf-8")
    if reason == "active":
        entry.update({"status": "processing", "progress": {"stage": "processing_file"}})
    monkeypatch.setattr(knowledge_router_module, "get_kb_manager", lambda: manager)
    monkeypatch.setattr(
        "deeptutor.services.rag.pipelines.lightrag.storage.latest_published_root",
        lambda _kb_dir: object() if reason == "published" else None,
    )

    with TestClient(_build_app()) as client:
        response = client.put(
            "/api/knowledge-bases/kb/indexing-policy",
            json={"profile_id": "profile-1", "model_id": "model-1"},
        )

    assert response.status_code == 409
    assert "pending_indexing_policy" not in entry


def test_reindex_passes_frozen_lightrag_snapshot_to_background_task(
    monkeypatch, tmp_path: Path
) -> None:
    manager = _FakeKBManager(tmp_path / "knowledge_bases")
    manager.config["knowledge_bases"]["kb"] = {
        "path": "kb",
        "rag_provider": "lightrag",
        "status": "ready",
    }
    (manager.base_dir / "kb" / "raw").mkdir(parents=True)
    snapshot = object()
    captured: dict[str, object] = {}

    async def capture_task(*_args, **kwargs):
        captured.update(kwargs)

    monkeypatch.setattr(knowledge_router_module, "get_kb_manager", lambda: manager)
    monkeypatch.setattr(knowledge_router_module, "_kb_base_dir", manager.base_dir)
    monkeypatch.setattr(knowledge_router_module, "_assert_provider_ready", lambda _provider: None)
    monkeypatch.setattr(
        knowledge_router_module,
        "_freeze_indexing_llm_form",
        lambda _raw: ({"profile_id": "profile-1", "model_id": "model-1"}, snapshot),
    )
    monkeypatch.setattr(knowledge_router_module, "run_reindex_task", capture_task)

    with TestClient(_build_app()) as client:
        response = client.post(
            "/api/knowledge-bases/kb/reindex",
            data={"indexing_llm": json.dumps({"profile_id": "profile-1", "model_id": "model-1"})},
        )

    assert response.status_code == 200
    assert captured["indexing_snapshot"] is snapshot


def test_create_pageindex_oss_rejects_non_pdf(monkeypatch, tmp_path: Path) -> None:
    manager = _FakeKBManager(tmp_path / "knowledge_bases")
    monkeypatch.setattr(knowledge_router_module, "get_kb_manager", lambda: manager)
    monkeypatch.setattr(knowledge_router_module, "_kb_base_dir", tmp_path / "knowledge_bases")
    preflight = importlib.import_module("deeptutor.services.rag.preflight")
    monkeypatch.setattr(preflight, "engine_preflight", lambda _provider: {"ok": True, "checks": []})

    with TestClient(_build_app()) as client:
        response = client.post(
            "/api/knowledge-bases",
            data={"name": "kb-oss-docx", "rag_provider": "pageindex-oss"},
            files=[
                (
                    "files",
                    (
                        "demo.docx",
                        b"placeholder",
                        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
                    ),
                )
            ],
        )

    assert response.status_code == 400
    assert "accept: .pdf" in response.json()["detail"]
    assert "kb-oss-docx" not in manager.config["knowledge_bases"]


def test_upload_progress_counts_completed_files_and_reports_reliable_stages(
    monkeypatch, tmp_path: Path
) -> None:
    base_dir = _write_upload_task_kb(tmp_path)
    source = tmp_path / "ok.txt"
    source.write_text("ok", encoding="utf-8")

    class _SuccessfulRagService:
        def __init__(self, *_args, **_kwargs) -> None:
            pass

        async def add_documents(self, *_args, **_kwargs) -> bool:
            return True

    monkeypatch.setattr(
        "deeptutor.knowledge.add_documents.RAGService",
        _SuccessfulRagService,
    )
    updates: list[tuple[str, int, int]] = []
    original_update = knowledge_router_module.ProgressTracker.update

    def _record_update(self, stage, message="", current=0, total=0, **kwargs):
        # Producers name a template plus its values so the web log box can
        # translate; record the line a consumer actually sees, which is what
        # this test is about.
        from deeptutor.knowledge.progress_tracker import render_message_template

        key = kwargs.get("message_key")
        rendered = message or (
            render_message_template(key, kwargs.get("message_params") or {}) if key else ""
        )
        updates.append((rendered, current, total))
        return original_update(
            self,
            stage,
            message,
            current=current,
            total=total,
            **kwargs,
        )

    monkeypatch.setattr(knowledge_router_module.ProgressTracker, "update", _record_update)

    asyncio.run(
        knowledge_router_module.run_upload_processing_task(
            kb_name="kb",
            base_dir=str(base_dir),
            uploaded_file_paths=[str(source)],
            task_id="upload-progress-test",
            rag_provider="llamaindex",
        )
    )

    assert updates == [
        ("Validating 1 file(s)...", 0, 1),
        ("Staged 1 new file(s)", 0, 1),
        ("Indexing ok.txt", 0, 1),
        ("Indexed ok.txt", 1, 1),
        ("Saving metadata...", 1, 1),
        ("Successfully processed 1 files!", 1, 1),
    ]


def test_lightrag_config_endpoint_round_trips_the_indexing_knobs(
    monkeypatch, tmp_path: Path
) -> None:
    """The contract the settings UI edits: GET exposes the knobs, PUT keeps them.

    EngineDetail's LightRAG form reads every field off this payload and sends
    all five back on save, so a field the router drops is a field the UI
    silently cannot change.
    """
    from deeptutor.services.config.runtime_settings import RuntimeSettingsService

    service = RuntimeSettingsService(tmp_path, process_env={})
    monkeypatch.setattr(
        "deeptutor.services.config.get_runtime_settings_service",
        lambda: service,
    )

    client = TestClient(_build_app())

    initial = client.get("/api/knowledge-bases/rag-pipelines/lightrag/config")
    assert initial.status_code == 200
    for key in ("top_k", "response_type", "max_concurrent_files", "llm_model_max_async"):
        assert key in initial.json(), f"{key} missing from the payload the UI reads"

    saved = client.put(
        "/api/knowledge-bases/rag-pipelines/lightrag/config",
        json={
            "top_k": 42,
            "response_type": "Single Paragraph",
            "max_concurrent_files": 4,
            "llm_model_max_async": 8,
            "entity_extract_max_gleaning": 2,
        },
    )
    assert saved.status_code == 200
    assert saved.json()["max_concurrent_files"] == 4
    assert saved.json()["llm_model_max_async"] == 8
    assert saved.json()["entity_extract_max_gleaning"] == 2

    # And they survive a reload rather than living only in the response.
    again = client.get("/api/knowledge-bases/rag-pipelines/lightrag/config").json()
    assert again["max_concurrent_files"] == 4
    assert again["entity_extract_max_gleaning"] == 2
    assert again["top_k"] == 42


def test_lightrag_server_defaults_are_redacted_and_reused_for_probe(
    monkeypatch, tmp_path: Path
) -> None:
    service = RuntimeSettingsService(tmp_path, process_env={})
    monkeypatch.setattr(config_module, "get_runtime_settings_service", lambda: service)
    monkeypatch.setattr(
        config_module, "load_lightrag_server_settings", service.load_lightrag_server
    )

    calls: list[tuple[str, str]] = []

    class Result:
        ok = True

        def to_dict(self) -> dict:
            return {
                "ok": True,
                "base_url": "http://localhost:9621",
                "reachable": True,
                "auth_required": True,
                "auth_ok": True,
                "core_version": "1.0",
                "api_version": "1",
                "error": None,
            }

    async def fake_probe(server_url: str, api_key: str):
        calls.append((server_url, api_key))
        return Result()

    probe_module = importlib.import_module("deeptutor.services.rag.pipelines.lightrag_server.probe")
    monkeypatch.setattr(probe_module, "probe_server", fake_probe)

    with TestClient(_build_app()) as client:
        saved = client.put(
            "/api/knowledge-bases/rag-pipelines/lightrag-server/config",
            json={"server_url": "http://localhost:9621/", "api_key": "private-key"},
        )
        assert saved.status_code == 200
        assert saved.json() == {
            "server_url": "http://localhost:9621",
            "api_key_set": True,
            "configured": True,
        }
        assert "private-key" not in saved.text

        probed = client.post(
            "/api/knowledge-bases/probe-lightrag-server",
            json={
                "server_url": "http://localhost:9621",
                "use_saved_api_key": True,
            },
        )

    assert probed.status_code == 200
    assert calls == [("http://localhost:9621", "private-key")]


def test_llamaindex_config_endpoint_round_trips_vector_index_knobs(
    monkeypatch, tmp_path: Path
) -> None:
    """The vector-index form depends on every field surviving a save/reload."""
    service = RuntimeSettingsService(tmp_path, process_env={})
    monkeypatch.setattr(config_module, "get_runtime_settings_service", lambda: service)

    client = TestClient(_build_app())
    initial = client.get("/api/knowledge-bases/rag-pipelines/llamaindex/config")
    assert initial.status_code == 200
    assert initial.json()["vector_index_type"] == "flat"

    saved = client.put(
        "/api/knowledge-bases/rag-pipelines/llamaindex/config",
        json={
            "vector_index_type": "hnsw",
            "hnsw_m": 24,
            "hnsw_ef_construction": 128,
            "hnsw_ef_search": 48,
        },
    )
    assert saved.status_code == 200
    assert saved.json()["vector_index_type"] == "hnsw"
    assert saved.json()["hnsw_m"] == 24
    assert saved.json()["hnsw_ef_construction"] == 128
    assert saved.json()["hnsw_ef_search"] == 48

    again = client.get("/api/knowledge-bases/rag-pipelines/llamaindex/config").json()
    assert again["vector_index_type"] == "hnsw"
    assert again["hnsw_ef_search"] == 48


def test_llamaindex_config_endpoint_round_trips_reranker_knobs(monkeypatch, tmp_path: Path) -> None:
    """The reranker form depends on both fields surviving save/reload."""
    service = RuntimeSettingsService(tmp_path, process_env={})
    monkeypatch.setattr(config_module, "get_runtime_settings_service", lambda: service)

    client = TestClient(_build_app())
    initial = client.get("/api/knowledge-bases/rag-pipelines/llamaindex/config")
    assert initial.status_code == 200
    assert initial.json()["reranker_model"] == ""
    assert initial.json()["rerank_top_k"] == 50

    saved = client.put(
        "/api/knowledge-bases/rag-pipelines/llamaindex/config",
        json={
            "reranker_model": " BAAI/bge-reranker-base ",
            "rerank_top_k": 25,
        },
    )
    assert saved.status_code == 200
    assert saved.json()["reranker_model"] == "BAAI/bge-reranker-base"
    assert saved.json()["rerank_top_k"] == 25

    again = client.get("/api/knowledge-bases/rag-pipelines/llamaindex/config").json()
    assert again["reranker_model"] == "BAAI/bge-reranker-base"
    assert again["rerank_top_k"] == 25


def test_lightrag_config_validates_dedicated_llm_selection(monkeypatch, tmp_path: Path) -> None:
    from deeptutor.services.config.model_catalog import ModelCatalogService

    settings_service = RuntimeSettingsService(tmp_path, process_env={})
    catalog_service = ModelCatalogService(tmp_path / "model_catalog.json")
    catalog_service.save(
        {
            "services": {
                "llm": {
                    "active_profile_id": "profile-1",
                    "active_model_id": "model-1",
                    "profiles": [
                        {
                            "id": "profile-1",
                            "name": "Dedicated",
                            "binding": "openai",
                            "base_url": "https://api.openai.com/v1",
                            "api_key": "secret",
                            "models": [{"id": "model-1", "name": "Model", "model": "gpt-4o"}],
                        }
                    ],
                }
            }
        }
    )
    monkeypatch.setattr(config_module, "get_runtime_settings_service", lambda: settings_service)
    monkeypatch.setattr(config_module, "get_model_catalog_service", lambda: catalog_service)

    client = TestClient(_build_app())
    saved = client.put(
        "/api/knowledge-bases/rag-pipelines/lightrag/config",
        json={"llm_profile_id": "profile-1", "llm_model_id": "model-1"},
    )
    assert saved.status_code == 200

    unknown = client.put(
        "/api/knowledge-bases/rag-pipelines/lightrag/config",
        json={"llm_model_id": "missing"},
    )
    assert unknown.status_code == 422

    cleared = client.put(
        "/api/knowledge-bases/rag-pipelines/lightrag/config",
        json={"llm_profile_id": "", "llm_model_id": ""},
    )
    assert cleared.status_code == 200
