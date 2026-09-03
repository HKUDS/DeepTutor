from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
import json
import os
from pathlib import Path
from typing import Any, Callable

from deeptutor.services.file_io import atomic_write_json as _atomic_write_json
from deeptutor.services.path_service import get_path_service

from .origins import normalize_origins

DEFAULT_SYSTEM_SETTINGS: dict[str, Any] = {
    "version": 1,
    # About → Updates performs at most one release lookup per process/day.
    # Operators may disable even that explicit network boundary for offline or
    # audited deployments; DEEPTUTOR_VERSION_CHECK_ENABLED is the deployment
    # override for read-only settings volumes.
    "version_check_enabled": True,
    "backend_port": 8001,
    "backend_workers": 1,
    "frontend_port": 3782,
    "next_public_api_base_external": "",
    "next_public_api_base": "",
    "cors_origin": "",
    "cors_origins": [],
    "disable_ssl_verify": False,
    "chat_attachment_dir": "",
    # Enable the restricted-subprocess code-execution sandbox (the `exec` /
    # `code_execution` tools the office skills — docx/pdf/pptx/xlsx — run on).
    # Default on so document generation works out of the box across all
    # deployment shapes; a stronger backend (runner sidecar / bwrap) still
    # takes precedence when available. Set false to disable host-side exec.
    "sandbox_allow_subprocess": True,
    # Conservative chat -> deep_question routing. Explicit requests only, and
    # callers can still pass config.auto_route=false for a single turn.
    "capability_routing_enabled": False,
    # Reference policy applied after every web-search provider. This belongs in
    # runtime JSON so packaged installs and the settings service share one
    # source of truth; project main.yaml is intentionally not an operator
    # configuration surface.
    "web_search_source_filtering": {
        "enabled": True,
        "blocked_domains": [],
        "trusted_domains": [],
    },
    # Chat attachment policy. Size caps gate what the composer accepts and
    # what the turn runtime / partner upload endpoints extract; the char
    # budgets bound how much extracted text is inlined into the LLM context
    # per document / per turn. Enforcement reads these at call time, so
    # changes apply to the next message — but uploads whose base64 payload
    # exceeds the WebSocket frame ceiling need a restart (see
    # ``compute_ws_max_size``, wired at every uvicorn launch point).
    "chat_attachment_max_file_mb": 20,
    "chat_attachment_max_total_mb": 25,
    "chat_attachment_max_chars_per_doc": 200_000,
    "chat_attachment_max_chars_total": 150_000,
}

# Clamp bounds for the chat attachment knobs. The MB ceilings are deliberately
# generous (local deployments parse in-process; the WS frame cap is derived
# from the total) while still refusing nonsense like 0 or 10^9.
CHAT_ATTACHMENT_MAX_FILE_MB_RANGE = (1, 1024)
CHAT_ATTACHMENT_MAX_TOTAL_MB_RANGE = (1, 2048)
CHAT_ATTACHMENT_CHARS_RANGE = (10_000, 5_000_000)

DEFAULT_AUTH_SETTINGS: dict[str, Any] = {
    "version": 1,
    "enabled": False,
    "username": "admin",
    "password_hash": "",
    "token_expire_hours": 24,
    "cookie_secure": False,
}

DEFAULT_INTEGRATIONS_SETTINGS: dict[str, Any] = {
    "version": 2,
    "pocketbase_url": "",
    "pocketbase_port": 8090,
    "pocketbase_external_url": "",
    "pocketbase_admin_email": "",
    "pocketbase_admin_password": "",
    "turn_coordination": {
        "backend": "memory",
        "redis_url": "",
        "key_prefix": "deeptutor",
        "lease_ttl_seconds": 30,
        "renew_interval_seconds": 10,
        "recovery_interval_seconds": 10,
        "stream_retention_seconds": 86_400,
    },
}

# Document parsing settings. The parse layer (deeptutor/services/parsing)
# supports several pluggable engines; one is active at a time. The persisted
# shape is v2::
#
#   {"version": 2, "engine": "<name>", "engines": {"text_only": {...},
#    "mineru": {...}, "docling": {...}, "markitdown": {...}}}
#
# Persisted as ``document_parsing.json``. It originally held only MinerU config
# and was named ``mineru.json``; the file is renamed in place on first load (see
# ``_migrate_legacy_document_parsing_file``) so existing installs keep their
# settings. ``load_mineru`` returns the MinerU engine *slice* (flat) so legacy
# readers keep working; ``load_document_parsing`` returns the whole structure
# for the multi-engine settings UI. A v1 flat file is migrated into
# ``engines.mineru`` on first load (and the active engine pinned to "mineru" so
# existing installs keep their behavior).
DOCUMENT_PARSING_SETTINGS_NAME = "document_parsing"
_LEGACY_DOCUMENT_PARSING_SETTINGS_NAME = "mineru"

MINERU_MODE_LOCAL = "local"
MINERU_MODE_CLOUD = "cloud"
_MINERU_MODES = frozenset({MINERU_MODE_LOCAL, MINERU_MODE_CLOUD})

DOCLING_MODE_LOCAL = "local"
DOCLING_MODE_REMOTE = "remote"
_DOCLING_MODES = frozenset({DOCLING_MODE_LOCAL, DOCLING_MODE_REMOTE})
_MINERU_MODEL_VERSIONS = frozenset({"pipeline", "vlm"})
_MINERU_DOWNLOAD_SOURCES = frozenset({"huggingface", "modelscope"})

DOCUMENT_PARSING_ENGINE_TEXT_ONLY = "text_only"
DOCUMENT_PARSING_ENGINE_MINERU = "mineru"
DOCUMENT_PARSING_ENGINE_DOCLING = "docling"
DOCUMENT_PARSING_ENGINE_MARKITDOWN = "markitdown"
DOCUMENT_PARSING_ENGINE_PYMUPDF4LLM = "pymupdf4llm"
DOCUMENT_PARSING_ENGINE_LITEPARSE = "liteparse"
DOCUMENT_PARSING_ENGINE_TIKA = "tika"
_DOCUMENT_PARSING_ENGINES = frozenset(
    {
        DOCUMENT_PARSING_ENGINE_TEXT_ONLY,
        DOCUMENT_PARSING_ENGINE_MINERU,
        DOCUMENT_PARSING_ENGINE_DOCLING,
        DOCUMENT_PARSING_ENGINE_MARKITDOWN,
        DOCUMENT_PARSING_ENGINE_PYMUPDF4LLM,
        DOCUMENT_PARSING_ENGINE_LITEPARSE,
        DOCUMENT_PARSING_ENGINE_TIKA,
    }
)
# Image formats PyMuPDF4LLM can write extracted page images as.
_PYMUPDF4LLM_IMAGE_FORMATS = frozenset({"png", "jpg", "jpeg", "webp"})
# How LiteParse presents images in its Markdown. Independent of whether the
# image bytes are extracted (that is the engine's ``extract_images`` knob).
LITEPARSE_IMAGE_MODES = frozenset({"off", "placeholder", "embed"})
# Fresh installs default to the built-in text extractor so parsing works out of
# the box without optional parser packages or model weights.
# Migrated v1 installs keep MinerU (see ``_normalize_document_parsing``).
_DEFAULT_DOCUMENT_PARSING_ENGINE = DOCUMENT_PARSING_ENGINE_TEXT_ONLY

# MinerU engine slice. ``mode`` selects a locally-installed MinerU CLI ("local")
# vs the hosted mineru.net cloud API ("cloud"); cloud needs ``api_token``. Every
# other field is a parsing knob both backends understand. ``allow_local_model_download``
# gates the first-parse model pull (default off → no silent multi-GB download).
_DEFAULT_MINERU_ENGINE: dict[str, Any] = {
    "mode": MINERU_MODE_LOCAL,
    "api_base_url": "https://mineru.net",
    "api_token": "",
    # Optional explicit path to a local MinerU executable. Empty = auto-detect
    # from PATH. Lets users install MinerU in an isolated env (uv tool / pipx /
    # separate conda) so its heavy deps never conflict with DeepTutor's.
    "local_cli_path": "",
    # Where local-mode model weights download from. ``model_download_endpoint``
    # is a custom HuggingFace mirror (HF_ENDPOINT, e.g. https://hf-mirror.com);
    # empty = the source's official address.
    "model_download_source": "huggingface",
    "model_download_endpoint": "",
    "model_version": "pipeline",
    # "auto" lets MinerU auto-detect; any other value is forwarded verbatim
    # as the API ``language`` hint (e.g. "ch", "en").
    "language": "auto",
    "enable_formula": True,
    "enable_table": True,
    "is_ocr": False,
    "allow_local_model_download": False,
}

# Docling engine slice. ``mode`` selects the in-process ``docling`` package
# ("local") or a Docling Serve HTTP server ("remote"; needs ``api_base_url`` and
# optionally ``api_token``). Local downloads layout/table models on first run,
# hence the same ``allow_local_model_download`` gate as MinerU local.
_DEFAULT_DOCLING_ENGINE: dict[str, Any] = {
    "mode": DOCLING_MODE_LOCAL,
    "api_base_url": "http://localhost:5001",
    "api_token": "",
    "do_ocr": False,
    "do_table_structure": True,
    "allow_local_model_download": False,
}

# markitdown engine slice. Pure-Python, no model downloads. Optionally uses
# DeepTutor's VLM to describe images.
_DEFAULT_MARKITDOWN_ENGINE: dict[str, Any] = {
    "enable_llm_image_description": False,
}

# PyMuPDF4LLM engine slice. Pure-Python on top of PyMuPDF — no model downloads,
# no CUDA, runs on low-end / GPU-less machines. Unlike text-only/markitdown it
# can also extract embedded images and rendered vector graphics into the parse's
# images/ dir. ``image_dpi`` is the render resolution for those images.
_DEFAULT_PYMUPDF4LLM_ENGINE: dict[str, Any] = {
    "write_images": True,
    "image_format": "png",
    "image_dpi": 150,
}

# LiteParse engine slice. Rust-backed, no model downloads. Like PyMuPDF4LLM it
# can extract embedded images into the parse's images/ dir. Output format and
# image directory are fixed by the workdir contract, so neither is a knob here
# (see engines/liteparse/engine.py). ``max_pages`` 0 means the whole document.
_DEFAULT_LITEPARSE_ENGINE: dict[str, Any] = {
    "image_mode": "placeholder",
    "extract_links": True,
    "extract_images": False,
    "max_pages": 0,
}

# Tika engine slice. Remote-only Apache Tika server; no local package or models.
_DEFAULT_TIKA_ENGINE: dict[str, Any] = {
    "server_url": "http://localhost:9998",
}

# Built-in text-only engine slice. It deliberately has no knobs: it reuses
# DeepTutor's legacy text extractors for PDF / Office / text-like files.
_DEFAULT_TEXT_ONLY_ENGINE: dict[str, Any] = {}

# Legacy flat keys that mark a v1 ``mineru.json`` (these live only at the top
# level in v1; v2 never writes them there).
_MINERU_ENGINE_KEYS = frozenset(_DEFAULT_MINERU_ENGINE.keys())

DEFAULT_DOCUMENT_PARSING_SETTINGS: dict[str, Any] = {
    "version": 2,
    "engine": _DEFAULT_DOCUMENT_PARSING_ENGINE,
    "engines": {
        DOCUMENT_PARSING_ENGINE_TEXT_ONLY: _DEFAULT_TEXT_ONLY_ENGINE,
        DOCUMENT_PARSING_ENGINE_MINERU: _DEFAULT_MINERU_ENGINE,
        DOCUMENT_PARSING_ENGINE_DOCLING: _DEFAULT_DOCLING_ENGINE,
        DOCUMENT_PARSING_ENGINE_MARKITDOWN: _DEFAULT_MARKITDOWN_ENGINE,
        DOCUMENT_PARSING_ENGINE_PYMUPDF4LLM: _DEFAULT_PYMUPDF4LLM_ENGINE,
        DOCUMENT_PARSING_ENGINE_LITEPARSE: _DEFAULT_LITEPARSE_ENGINE,
        DOCUMENT_PARSING_ENGINE_TIKA: _DEFAULT_TIKA_ENGINE,
    },
}

# Backward-compatible alias: the MinerU engine slice. Several call-sites and
# tests reference ``DEFAULT_MINERU_SETTINGS``; it now denotes the engine slice.
DEFAULT_MINERU_SETTINGS: dict[str, Any] = _DEFAULT_MINERU_ENGINE

# PageIndex cloud RAG engine. A KB indexed with the ``pageindex`` provider
# ships its documents to the hosted PageIndex service for tree building and
# reasoning-based retrieval. The SDK owns the official endpoint; the same
# deployment-level credential is reused by every ``pageindex`` KB.
# Kept in its own JSON file so the credential lives beside other per-feature
# settings and never leaks into model/network config.
DEFAULT_PAGEINDEX_SETTINGS: dict[str, Any] = {
    "version": 1,
    "api_key": "",
}

# Tencent IMA. The credential pair (``client_id`` + ``api_key``, issued at
# https://ima.qq.com/agent-interface) identifies one IMA account, and every
# library in that account is reachable with it — so it belongs here, beside the
# other engine credentials, rather than being retyped for each connected KB.
# A KB may still carry its own pair to reach a *different* IMA account; that
# per-KB binding wins (see ``pipelines/ima/config.py``).
DEFAULT_IMA_SETTINGS: dict[str, Any] = {
    "version": 1,
    "client_id": "",
    "api_key": "",
}

# LlamaIndex local RAG engine. These are the retrieval + chunking knobs the
# default engine exposes; they were previously hardcoded / env-only. Kept in
# their own JSON file so the engine's detail page can read/write them.
#
# * ``retrieval_profile`` — "hybrid" (BM25 + vector fusion) or "vector" only.
# * ``top_k`` — default number of chunks a query returns.
# * ``vector_top_k_multiplier`` / ``bm25_top_k_multiplier`` — how many extra
#   candidates each child retriever fetches before fusion re-ranks to ``top_k``.
# * ``reranker_model`` / ``rerank_top_k`` — optional cross-encoder refinement.
#   An empty model keeps the existing embedding-only ranking.
# * ``vector_index_type`` — FAISS index type for the next full index build.
#   HNSW is opt-in and trades exact recall for sub-linear search at scale.
# * ``chunk_size`` / ``chunk_overlap`` — indexing chunk geometry; changes apply
#   on the next (re-)index, not retroactively.
# * ``image_description_concurrency`` / ``image_description_timeout_seconds`` —
#   bounded multimodal LLM work while indexing image-heavy documents.
#
# ``fusion_num_queries`` is intentionally NOT exposed: query generation needs a
# real LLM, but the fusion retriever runs on a MockLLM, so any value > 1 would
# silently degrade results. It stays pinned to the dataclass default.
LLAMAINDEX_VECTOR_PROFILE = "vector"
LLAMAINDEX_HYBRID_PROFILE = "hybrid"
_LLAMAINDEX_PROFILES = frozenset({LLAMAINDEX_VECTOR_PROFILE, LLAMAINDEX_HYBRID_PROFILE})
LLAMAINDEX_FLAT_VECTOR_INDEX = "flat"
LLAMAINDEX_HNSW_VECTOR_INDEX = "hnsw"
_LLAMAINDEX_VECTOR_INDEX_TYPES = frozenset(
    {LLAMAINDEX_FLAT_VECTOR_INDEX, LLAMAINDEX_HNSW_VECTOR_INDEX}
)

DEFAULT_LLAMAINDEX_SETTINGS: dict[str, Any] = {
    "version": 1,
    "retrieval_profile": LLAMAINDEX_HYBRID_PROFILE,
    "top_k": 5,
    "vector_top_k_multiplier": 2,
    "bm25_top_k_multiplier": 2,
    "reranker_model": "",
    "rerank_top_k": 50,
    "vector_index_type": LLAMAINDEX_FLAT_VECTOR_INDEX,
    "hnsw_m": 32,
    "hnsw_ef_construction": 200,
    "hnsw_ef_search": 64,
    "chunk_size": 512,
    "chunk_overlap": 50,
    "image_description_concurrency": 4,
    "image_description_timeout_seconds": 60,
}

# GraphRAG retrieval knobs (microsoft/graphrag). Only query-time params that the
# engine passes explicitly (engine.py) are exposed; indexing knobs are left to
# GraphRAG's auto-config on purpose (the settings.yaml bridge is deliberately
# minimal). ``response_type`` is a free-form GraphRAG answer style; the UI offers
# presets but any string is accepted. ``community_level`` controls graph
# traversal granularity (local/drift). ``dynamic_community_selection`` only
# affects global search.
DEFAULT_GRAPHRAG_SETTINGS: dict[str, Any] = {
    "version": 1,
    "response_type": "Multiple Paragraphs",
    "community_level": 2,
    "dynamic_community_selection": False,
}

# LightRAG retrieval + indexing knobs (HKUDS/LightRAG native SDK). ``top_k``
# is the number of entities/relations the query pulls; ``response_type`` mirrors
# GraphRAG's. These ride into ``QueryParam`` and the pinned SDK constructor.
# ``max_concurrent_files`` sizes the native parser worker pool after DeepTutor
# has frozen each ParseService result; pre-parsing itself remains serial.
# Stable catalog references let LightRAG use a dedicated LLM while the global
# active chat model remains unchanged for ordinary chat.
DEFAULT_LIGHTRAG_SETTINGS: dict[str, Any] = {
    "version": 1,
    "top_k": 60,
    "response_type": "Multiple Paragraphs",
    "max_concurrent_files": 1,
    "llm_model_max_async": 4,
    "entity_extract_max_gleaning": 1,
    "llm_profile_id": "",
    "llm_model_id": "",
}

# LightRAG Server connection defaults. Individual knowledge bases remain free
# to override the URL/key when they are connected; this account-level slice is
# the reusable starting point shown on the engine page and in the create flow.
DEFAULT_LIGHTRAG_SERVER_SETTINGS: dict[str, Any] = {
    "version": 1,
    "server_url": "",
    "api_key": "",
}

IGNORE_PROCESS_OVERRIDES_ENV = "DEEPTUTOR_IGNORE_PROCESS_ENV_OVERRIDES"
TRUTHY = {"1", "true", "yes", "on"}
FALSY = {"0", "false", "no", "off"}


def _coerce_bool(value: Any, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if text in TRUTHY:
        return True
    if text in FALSY:
        return False
    return default


def _coerce_int(value: Any, default: int) -> int:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return default


def _coerce_clamped_int(value: Any, default: int, low: int, high: int) -> int:
    coerced = _coerce_int(value, default)
    return max(low, min(high, coerced))


def _coerce_port(value: Any, default: int) -> int:
    port = _coerce_int(value, default)
    return port if 1 <= port <= 65535 else default


def _coerce_origins(value: Any) -> list[str]:
    return normalize_origins(value)


def _deepcopy_default(defaults: dict[str, Any]) -> dict[str, Any]:
    return deepcopy(defaults)


def _json_object(path: Path) -> dict[str, Any]:
    if not path.exists() or path.stat().st_size == 0:
        return {}
    try:
        loaded = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return {}
    return loaded if isinstance(loaded, dict) else {}


def _string(value: Any) -> str:
    return "" if value is None else str(value).strip()


def _string_or_list(value: Any) -> str | list[str]:
    if isinstance(value, list):
        return [item for raw in value if (item := _string(raw))]
    return _string(value)


class RuntimeSettingsService:
    """JSON-backed runtime settings rooted in data/user/settings.

    Process environment values are explicit deployment overrides and are applied
    centrally here rather than scattered through the application. Project-root
    ``.env`` files are intentionally ignored.
    """

    _instances: dict[str, "RuntimeSettingsService"] = {}

    def __init__(
        self,
        settings_dir: Path,
        *,
        process_env: dict[str, str] | None = None,
    ) -> None:
        self.settings_dir = settings_dir
        self.process_env = process_env if process_env is not None else os.environ
        self._external_process_keys: set[str] = set()
        self._internal_exported_values: dict[str, str] = {}

    @classmethod
    def get_instance(
        cls,
        settings_dir: Path | None = None,
        *,
        process_env: dict[str, str] | None = None,
    ) -> "RuntimeSettingsService":
        resolved = (settings_dir or _global_settings_dir()).resolve()
        key = str(resolved)
        if process_env is not None:
            return cls(resolved, process_env=process_env)
        if key not in cls._instances:
            cls._instances[key] = cls(resolved)
        return cls._instances[key]

    def path_for(self, name: str) -> Path:
        if not name.endswith(".json"):
            name = f"{name}.json"
        return self.settings_dir / name

    def load_system(self, *, include_process_overrides: bool = True) -> dict[str, Any]:
        payload = self._load_or_create(
            "system",
            DEFAULT_SYSTEM_SETTINGS,
            self._normalize_system,
        )
        if include_process_overrides:
            payload = self._apply_system_process_overrides(payload)
        return payload

    def save_system(self, settings: dict[str, Any]) -> dict[str, Any]:
        payload = self._normalize_system({**DEFAULT_SYSTEM_SETTINGS, **settings})
        _atomic_write_json(self.path_for("system"), payload)
        return payload

    def load_auth(self, *, include_process_overrides: bool = True) -> dict[str, Any]:
        payload = self._load_or_create(
            "auth",
            DEFAULT_AUTH_SETTINGS,
            self._normalize_auth,
        )
        if include_process_overrides:
            payload = self._apply_auth_process_overrides(payload)
        return payload

    def save_auth(self, settings: dict[str, Any]) -> dict[str, Any]:
        payload = self._normalize_auth({**DEFAULT_AUTH_SETTINGS, **settings})
        _atomic_write_json(self.path_for("auth"), payload)
        return payload

    def load_integrations(self, *, include_process_overrides: bool = True) -> dict[str, Any]:
        payload = self._load_or_create(
            "integrations",
            DEFAULT_INTEGRATIONS_SETTINGS,
            self._normalize_integrations,
        )
        if include_process_overrides:
            payload = self._apply_integrations_process_overrides(payload)
        return payload

    def save_integrations(self, settings: dict[str, Any]) -> dict[str, Any]:
        payload = self._normalize_integrations({**DEFAULT_INTEGRATIONS_SETTINGS, **settings})
        _atomic_write_json(self.path_for("integrations"), payload)
        return payload

    def load_document_parsing(self, *, include_process_overrides: bool = True) -> dict[str, Any]:
        """Return the full v2 document-parsing structure (all engines)."""
        self._migrate_legacy_document_parsing_file()
        payload = self._load_or_create(
            DOCUMENT_PARSING_SETTINGS_NAME,
            DEFAULT_DOCUMENT_PARSING_SETTINGS,
            self._normalize_document_parsing,
        )
        if include_process_overrides:
            engines = dict(payload["engines"])
            engines[DOCUMENT_PARSING_ENGINE_MINERU] = self._apply_mineru_process_overrides(
                dict(engines[DOCUMENT_PARSING_ENGINE_MINERU])
            )
            engines[DOCUMENT_PARSING_ENGINE_DOCLING] = self._apply_docling_process_overrides(
                dict(engines[DOCUMENT_PARSING_ENGINE_DOCLING])
            )
            engines[DOCUMENT_PARSING_ENGINE_TIKA] = self._apply_tika_process_overrides(
                dict(engines[DOCUMENT_PARSING_ENGINE_TIKA])
            )
            payload = {**payload, "engines": engines}
        return payload

    def save_document_parsing(self, settings: dict[str, Any]) -> dict[str, Any]:
        self._migrate_legacy_document_parsing_file()
        payload = self._normalize_document_parsing(
            {**DEFAULT_DOCUMENT_PARSING_SETTINGS, **settings}
        )
        _atomic_write_json(self.path_for(DOCUMENT_PARSING_SETTINGS_NAME), payload)
        return payload

    def load_mineru(self, *, include_process_overrides: bool = True) -> dict[str, Any]:
        """Return the MinerU engine slice (flat) for legacy readers.

        Backed by the v2 structure on disk; env overrides apply to the slice.
        """
        slice_ = dict(
            self.load_document_parsing(include_process_overrides=False)["engines"][
                DOCUMENT_PARSING_ENGINE_MINERU
            ]
        )
        if include_process_overrides:
            slice_ = self._apply_mineru_process_overrides(slice_)
        return slice_

    def save_mineru(self, settings: dict[str, Any]) -> dict[str, Any]:
        """Persist only the MinerU engine slice, preserving the other engines."""
        full = self.load_document_parsing(include_process_overrides=False)
        engines = dict(full["engines"])
        engines[DOCUMENT_PARSING_ENGINE_MINERU] = self._normalize_mineru_engine(
            {**_DEFAULT_MINERU_ENGINE, **settings}
        )
        payload = self._normalize_document_parsing({**full, "engines": engines})
        _atomic_write_json(self.path_for(DOCUMENT_PARSING_SETTINGS_NAME), payload)
        return payload["engines"][DOCUMENT_PARSING_ENGINE_MINERU]

    def load_pageindex(self, *, include_process_overrides: bool = True) -> dict[str, Any]:
        payload = self._load_or_create(
            "pageindex",
            DEFAULT_PAGEINDEX_SETTINGS,
            self._normalize_pageindex,
        )
        if include_process_overrides:
            payload = self._apply_pageindex_process_overrides(payload)
        return payload

    def save_pageindex(self, settings: dict[str, Any]) -> dict[str, Any]:
        payload = self._normalize_pageindex({**DEFAULT_PAGEINDEX_SETTINGS, **settings})
        _atomic_write_json(self.path_for("pageindex"), payload)
        return payload

    def load_ima(self, *, include_process_overrides: bool = True) -> dict[str, Any]:
        payload = self._load_or_create("ima", DEFAULT_IMA_SETTINGS, self._normalize_ima)
        if include_process_overrides:
            payload = self._apply_ima_process_overrides(payload)
        return payload

    def save_ima(self, settings: dict[str, Any]) -> dict[str, Any]:
        payload = self._normalize_ima({**DEFAULT_IMA_SETTINGS, **settings})
        _atomic_write_json(self.path_for("ima"), payload)
        return payload

    def load_llamaindex(self, *, include_process_overrides: bool = True) -> dict[str, Any]:
        payload = self._load_or_create(
            "llamaindex",
            DEFAULT_LLAMAINDEX_SETTINGS,
            self._normalize_llamaindex,
        )
        if include_process_overrides:
            payload = self._apply_llamaindex_process_overrides(payload)
        return payload

    def save_llamaindex(self, settings: dict[str, Any]) -> dict[str, Any]:
        payload = self._normalize_llamaindex({**DEFAULT_LLAMAINDEX_SETTINGS, **settings})
        _atomic_write_json(self.path_for("llamaindex"), payload)
        return payload

    def load_graphrag(self) -> dict[str, Any]:
        return self._load_or_create("graphrag", DEFAULT_GRAPHRAG_SETTINGS, self._normalize_graphrag)

    def save_graphrag(self, settings: dict[str, Any]) -> dict[str, Any]:
        payload = self._normalize_graphrag({**DEFAULT_GRAPHRAG_SETTINGS, **settings})
        _atomic_write_json(self.path_for("graphrag"), payload)
        return payload

    def load_lightrag(self) -> dict[str, Any]:
        return self._load_or_create("lightrag", DEFAULT_LIGHTRAG_SETTINGS, self._normalize_lightrag)

    def save_lightrag(self, settings: dict[str, Any]) -> dict[str, Any]:
        payload = self._normalize_lightrag({**DEFAULT_LIGHTRAG_SETTINGS, **settings})
        _atomic_write_json(self.path_for("lightrag"), payload)
        return payload

    def load_lightrag_server(self) -> dict[str, Any]:
        return self._load_or_create(
            "lightrag_server",
            DEFAULT_LIGHTRAG_SERVER_SETTINGS,
            self._normalize_lightrag_server,
        )

    def save_lightrag_server(self, settings: dict[str, Any]) -> dict[str, Any]:
        payload = self._normalize_lightrag_server({**DEFAULT_LIGHTRAG_SERVER_SETTINGS, **settings})
        _atomic_write_json(self.path_for("lightrag_server"), payload)
        return payload

    def ensure_defaults(self) -> None:
        self.load_system(include_process_overrides=False)
        self.load_auth(include_process_overrides=False)
        self.load_integrations(include_process_overrides=False)
        self.load_mineru(include_process_overrides=False)
        self.load_pageindex(include_process_overrides=False)
        self.load_ima(include_process_overrides=False)
        self.load_llamaindex(include_process_overrides=False)
        self.load_graphrag()
        self.load_lightrag()
        self.load_lightrag_server()

    def render_environment(self) -> dict[str, str]:
        """Render non-model settings into process env names for subprocesses."""
        system = self.load_system()
        auth = self.load_auth()
        integrations = self.load_integrations()
        return {
            "DEEPTUTOR_VERSION_CHECK_ENABLED": _bool_env(system["version_check_enabled"]),
            "BACKEND_PORT": str(system["backend_port"]),
            "BACKEND_WORKERS": str(system["backend_workers"]),
            "FRONTEND_PORT": str(system["frontend_port"]),
            "NEXT_PUBLIC_API_BASE_EXTERNAL": system["next_public_api_base_external"],
            "NEXT_PUBLIC_API_BASE": system["next_public_api_base"],
            "CORS_ORIGIN": system["cors_origin"],
            "CORS_ORIGINS": ",".join(system["cors_origins"]),
            "DISABLE_SSL_VERIFY": _bool_env(system["disable_ssl_verify"]),
            "CHAT_ATTACHMENT_DIR": system["chat_attachment_dir"],
            "DEEPTUTOR_SANDBOX_ALLOW_SUBPROCESS": _bool_env(system["sandbox_allow_subprocess"]),
            "AUTH_ENABLED": _bool_env(auth["enabled"]),
            "AUTH_USERNAME": auth["username"],
            "AUTH_PASSWORD_HASH": auth["password_hash"],
            "AUTH_TOKEN_EXPIRE_HOURS": str(auth["token_expire_hours"]),
            "AUTH_COOKIE_SECURE": _bool_env(auth["cookie_secure"]),
            "NEXT_PUBLIC_AUTH_ENABLED": _bool_env(auth["enabled"]),
            # Consumed server-side by the Next.js middleware (web/proxy.ts) at
            # request time — NOT inlined into the browser bundle. The proxy
            # rewrites /api/* and /ws/* to DEEPTUTOR_API_BASE_URL and uses
            # DEEPTUTOR_AUTH_ENABLED to gate the login redirect. The launcher and
            # the Docker entrypoint both export these through render_environment,
            # so the two deployment paths stay in sync. DEEPTUTOR_API_BASE_URL is
            # the address the frontend *server* uses to reach the backend; the
            # browser itself only ever talks to the frontend origin.
            #
            # The fallback is the IPv4 loopback, not "localhost": on a dual-stack
            # host that name resolves to ::1 first, while uvicorn binds 0.0.0.0
            # (IPv4 only), so every rewritten /api/* request fails to connect.
            # The launcher passes the same literal (see runtime/launcher.py), so
            # both deployment paths agree.
            "DEEPTUTOR_API_BASE_URL": (
                system["next_public_api_base"]
                or system["next_public_api_base_external"]
                or f"http://127.0.0.1:{system['backend_port']}"
            ),
            "DEEPTUTOR_AUTH_ENABLED": _bool_env(auth["enabled"]),
            "POCKETBASE_URL": integrations["pocketbase_url"],
            "POCKETBASE_PORT": str(integrations["pocketbase_port"]),
            "POCKETBASE_EXTERNAL_URL": integrations["pocketbase_external_url"],
            "POCKETBASE_ADMIN_EMAIL": integrations["pocketbase_admin_email"],
            "POCKETBASE_ADMIN_PASSWORD": integrations["pocketbase_admin_password"],
        }

    def export_environment(self, *, overwrite: bool = True) -> dict[str, str]:
        env = self.render_environment()
        for key, value in env.items():
            current = os.environ.get(key)
            if current and self._internal_exported_values.get(key) != current:
                self._external_process_keys.add(key)
            if overwrite or key not in os.environ:
                os.environ[key] = value
                if key not in self._external_process_keys:
                    self._internal_exported_values[key] = value
        return env

    def _process_env_value(self, key: str) -> str:
        if self._ignore_process_overrides():
            return ""
        value = self.process_env.get(key, "")
        if not value:
            return ""
        if key in self._external_process_keys:
            return value
        internal_value = self._internal_exported_values.get(key)
        if internal_value is not None and value == internal_value:
            return ""
        return value

    def _load_or_create(
        self,
        name: str,
        defaults: dict[str, Any],
        normalizer: Callable[[dict[str, Any]], dict[str, Any]],
    ) -> dict[str, Any]:
        path = self.path_for(name)
        loaded = _json_object(path)
        if loaded:
            normalized = normalizer({**defaults, **loaded})
            if normalized != loaded:
                _atomic_write_json(path, normalized)
            return normalized

        normalized = normalizer(_deepcopy_default(defaults))
        _atomic_write_json(path, normalized)
        return normalized

    def _migrate_legacy_document_parsing_file(self) -> None:
        """Rename the legacy ``mineru.json`` to ``document_parsing.json``.

        The file holds the full multi-engine parsing config; the MinerU-specific
        name predates the other engines. Move it in place on first access so
        existing installs keep their settings (content migration to v2 happens in
        ``_normalize_document_parsing``). Idempotent: a no-op once migrated.
        """
        new_path = self.path_for(DOCUMENT_PARSING_SETTINGS_NAME)
        legacy_path = self.path_for(_LEGACY_DOCUMENT_PARSING_SETTINGS_NAME)
        if not legacy_path.exists():
            return
        if new_path.exists():
            # New file is authoritative; drop the stale legacy copy.
            legacy_path.unlink(missing_ok=True)
            return
        legacy_path.rename(new_path)

    def _ignore_process_overrides(self) -> bool:
        return _coerce_bool(self.process_env.get(IGNORE_PROCESS_OVERRIDES_ENV), False)

    def _apply_system_process_overrides(self, settings: dict[str, Any]) -> dict[str, Any]:
        payload = dict(settings)
        if value := self._process_env_value("DEEPTUTOR_VERSION_CHECK_ENABLED"):
            payload["version_check_enabled"] = value
        if value := self._process_env_value("BACKEND_PORT"):
            payload["backend_port"] = value
        if value := self._process_env_value("FRONTEND_PORT"):
            payload["frontend_port"] = value
        if value := self._process_env_value("NEXT_PUBLIC_API_BASE_EXTERNAL"):
            payload["next_public_api_base_external"] = value
        if value := self._process_env_value("PUBLIC_API_BASE"):
            payload["next_public_api_base_external"] = value
        if value := self._process_env_value("NEXT_PUBLIC_API_BASE"):
            payload["next_public_api_base"] = value
        if value := self._process_env_value("CORS_ORIGIN"):
            payload["cors_origin"] = value
        if value := self._process_env_value("CORS_ORIGINS"):
            payload["cors_origins"] = value
        if value := self._process_env_value("DISABLE_SSL_VERIFY"):
            payload["disable_ssl_verify"] = value
        if value := self._process_env_value("CHAT_ATTACHMENT_DIR"):
            payload["chat_attachment_dir"] = value
        if value := (
            self._process_env_value("DEEPTUTOR_BACKEND_WORKERS")
            or self._process_env_value("BACKEND_WORKERS")
        ):
            payload["backend_workers"] = value
        if value := self._process_env_value("DEEPTUTOR_SANDBOX_ALLOW_SUBPROCESS"):
            payload["sandbox_allow_subprocess"] = value
        if value := self._process_env_value("DEEPTUTOR_CAPABILITY_ROUTING_ENABLED"):
            payload["capability_routing_enabled"] = value
        if value := self._process_env_value("CHAT_ATTACHMENT_MAX_FILE_MB"):
            payload["chat_attachment_max_file_mb"] = value
        if value := self._process_env_value("CHAT_ATTACHMENT_MAX_TOTAL_MB"):
            payload["chat_attachment_max_total_mb"] = value
        if value := self._process_env_value("CHAT_ATTACHMENT_MAX_CHARS_PER_DOC"):
            payload["chat_attachment_max_chars_per_doc"] = value
        if value := self._process_env_value("CHAT_ATTACHMENT_MAX_CHARS_TOTAL"):
            payload["chat_attachment_max_chars_total"] = value
        return self._normalize_system(payload)

    def _apply_auth_process_overrides(self, settings: dict[str, Any]) -> dict[str, Any]:
        payload = dict(settings)
        if value := (
            self._process_env_value("AUTH_ENABLED")
            or self._process_env_value("NEXT_PUBLIC_AUTH_ENABLED")
        ):
            payload["enabled"] = value
        if value := self._process_env_value("AUTH_USERNAME"):
            payload["username"] = value
        if value := self._process_env_value("AUTH_PASSWORD_HASH"):
            payload["password_hash"] = value
        if value := self._process_env_value("AUTH_TOKEN_EXPIRE_HOURS"):
            payload["token_expire_hours"] = value
        if value := self._process_env_value("AUTH_COOKIE_SECURE"):
            payload["cookie_secure"] = value
        return self._normalize_auth(payload)

    def _apply_integrations_process_overrides(self, settings: dict[str, Any]) -> dict[str, Any]:
        payload = dict(settings)
        if value := self._process_env_value("POCKETBASE_URL"):
            payload["pocketbase_url"] = value
        if value := self._process_env_value("POCKETBASE_PORT"):
            payload["pocketbase_port"] = value
        if value := self._process_env_value("POCKETBASE_EXTERNAL_URL"):
            payload["pocketbase_external_url"] = value
        if value := self._process_env_value("POCKETBASE_ADMIN_EMAIL"):
            payload["pocketbase_admin_email"] = value
        if value := self._process_env_value("POCKETBASE_ADMIN_PASSWORD"):
            payload["pocketbase_admin_password"] = value
        coordination = dict(payload.get("turn_coordination") or {})
        if value := self._process_env_value("DEEPTUTOR_TURN_COORDINATION_BACKEND"):
            coordination["backend"] = value
        if value := self._process_env_value("DEEPTUTOR_REDIS_URL"):
            coordination["redis_url"] = value
        if value := self._process_env_value("DEEPTUTOR_REDIS_KEY_PREFIX"):
            coordination["key_prefix"] = value
        payload["turn_coordination"] = coordination
        return self._normalize_integrations(payload)

    def _apply_mineru_process_overrides(self, settings: dict[str, Any]) -> dict[str, Any]:
        payload = dict(settings)
        if value := self._process_env_value("MINERU_MODE"):
            payload["mode"] = value
        if value := self._process_env_value("MINERU_API_BASE_URL"):
            payload["api_base_url"] = value
        if value := self._process_env_value("MINERU_API_TOKEN"):
            payload["api_token"] = value
        if value := self._process_env_value("MINERU_LOCAL_CLI_PATH"):
            payload["local_cli_path"] = value
        if value := self._process_env_value("MINERU_MODEL_SOURCE"):
            payload["model_download_source"] = value
        if value := self._process_env_value("MINERU_MODEL_DOWNLOAD_ENDPOINT"):
            payload["model_download_endpoint"] = value
        if value := self._process_env_value("MINERU_MODEL_VERSION"):
            payload["model_version"] = value
        if value := self._process_env_value("MINERU_LANGUAGE"):
            payload["language"] = value
        if value := self._process_env_value("MINERU_ALLOW_LOCAL_MODEL_DOWNLOAD"):
            payload["allow_local_model_download"] = _coerce_bool(value, False)
        return self._normalize_mineru_engine(payload)

    def _apply_pageindex_process_overrides(self, settings: dict[str, Any]) -> dict[str, Any]:
        payload = dict(settings)
        if value := self._process_env_value("PAGEINDEX_API_KEY"):
            payload["api_key"] = value
        return self._normalize_pageindex(payload)

    def _normalize_pageindex(self, settings: dict[str, Any]) -> dict[str, Any]:
        return {
            "version": 1,
            "api_key": _string(settings.get("api_key")),
        }

    def _apply_ima_process_overrides(self, settings: dict[str, Any]) -> dict[str, Any]:
        payload = dict(settings)
        if value := self._process_env_value("IMA_CLIENT_ID"):
            payload["client_id"] = value
        if value := self._process_env_value("IMA_API_KEY"):
            payload["api_key"] = value
        return self._normalize_ima(payload)

    def _normalize_ima(self, settings: dict[str, Any]) -> dict[str, Any]:
        return {
            "version": 1,
            "client_id": _string(settings.get("client_id")),
            "api_key": _string(settings.get("api_key")),
        }

    def _apply_llamaindex_process_overrides(self, settings: dict[str, Any]) -> dict[str, Any]:
        # Only the retrieval profile had an env override historically
        # (DEEPTUTOR_RAG_RETRIEVAL_PROFILE / RAG_RETRIEVAL_PROFILE); preserve it.
        payload = dict(settings)
        if value := (
            self._process_env_value("DEEPTUTOR_RAG_RETRIEVAL_PROFILE")
            or self._process_env_value("RAG_RETRIEVAL_PROFILE")
        ):
            payload["retrieval_profile"] = value
        return self._normalize_llamaindex(payload)

    def _normalize_llamaindex(self, settings: dict[str, Any]) -> dict[str, Any]:
        profile = _string(settings.get("retrieval_profile")).lower()
        if profile not in _LLAMAINDEX_PROFILES:
            profile = LLAMAINDEX_HYBRID_PROFILE
        vector_index_type = _string(settings.get("vector_index_type")).lower()
        if vector_index_type not in _LLAMAINDEX_VECTOR_INDEX_TYPES:
            vector_index_type = LLAMAINDEX_FLAT_VECTOR_INDEX
        chunk_size = _coerce_clamped_int(settings.get("chunk_size"), 512, 64, 8192)
        # Overlap must stay below the chunk size or chunking degenerates.
        chunk_overlap = _coerce_clamped_int(
            settings.get("chunk_overlap"), 50, 0, max(0, chunk_size - 1)
        )
        return {
            "version": 1,
            "retrieval_profile": profile,
            "top_k": _coerce_clamped_int(settings.get("top_k"), 5, 1, 50),
            "vector_top_k_multiplier": _coerce_clamped_int(
                settings.get("vector_top_k_multiplier"), 2, 1, 10
            ),
            "bm25_top_k_multiplier": _coerce_clamped_int(
                settings.get("bm25_top_k_multiplier"), 2, 1, 10
            ),
            "reranker_model": _string(settings.get("reranker_model"))[:200],
            "rerank_top_k": _coerce_clamped_int(settings.get("rerank_top_k"), 50, 1, 100),
            "vector_index_type": vector_index_type,
            "hnsw_m": _coerce_clamped_int(settings.get("hnsw_m"), 32, 4, 64),
            "hnsw_ef_construction": _coerce_clamped_int(
                settings.get("hnsw_ef_construction"), 200, 16, 512
            ),
            "hnsw_ef_search": _coerce_clamped_int(settings.get("hnsw_ef_search"), 64, 1, 512),
            "chunk_size": chunk_size,
            "chunk_overlap": chunk_overlap,
            "image_description_concurrency": _coerce_clamped_int(
                settings.get("image_description_concurrency"), 4, 1, 16
            ),
            "image_description_timeout_seconds": _coerce_clamped_int(
                settings.get("image_description_timeout_seconds"), 60, 5, 600
            ),
        }

    def _normalize_response_type(self, value: Any) -> str:
        # GraphRAG/LightRAG accept any answer-style string; just trim + cap so a
        # pathological value can't blow up a prompt.
        text = _string(value) or "Multiple Paragraphs"
        return text[:80]

    def _normalize_graphrag(self, settings: dict[str, Any]) -> dict[str, Any]:
        return {
            "version": 1,
            "response_type": self._normalize_response_type(settings.get("response_type")),
            "community_level": _coerce_clamped_int(settings.get("community_level"), 2, 0, 5),
            "dynamic_community_selection": _coerce_bool(
                settings.get("dynamic_community_selection"), False
            ),
        }

    def _normalize_lightrag(self, settings: dict[str, Any]) -> dict[str, Any]:
        return {
            "version": 1,
            "top_k": _coerce_clamped_int(settings.get("top_k"), 60, 1, 200),
            "response_type": self._normalize_response_type(settings.get("response_type")),
            "max_concurrent_files": _coerce_clamped_int(
                settings.get("max_concurrent_files"), 1, 1, 16
            ),
            "llm_model_max_async": _coerce_clamped_int(
                settings.get("llm_model_max_async"), 4, 1, 32
            ),
            "entity_extract_max_gleaning": _coerce_clamped_int(
                settings.get("entity_extract_max_gleaning"), 1, 0, 5
            ),
            "llm_profile_id": _string(settings.get("llm_profile_id"))[:128],
            "llm_model_id": _string(settings.get("llm_model_id"))[:128],
        }

    def _normalize_lightrag_server(self, settings: dict[str, Any]) -> dict[str, Any]:
        return {
            "version": 1,
            "server_url": _string(settings.get("server_url")).rstrip("/"),
            "api_key": _string(settings.get("api_key")),
        }

    def _normalize_document_parsing(self, settings: dict[str, Any]) -> dict[str, Any]:
        """Normalize the full v2 structure, migrating a v1 flat file in place.

        v1 is detected by legacy flat MinerU keys at the top level (v2 never
        writes them there). When migrating, those values seed ``engines.mineru``
        and the active engine is pinned to MinerU so the install's behavior is
        preserved. Each known engine is always present (defaults fill gaps).
        """
        settings = dict(settings)
        legacy_flat = {key: settings[key] for key in _MINERU_ENGINE_KEYS if key in settings}
        migrating = bool(legacy_flat)

        raw_engines = settings.get("engines")
        engines_in = dict(raw_engines) if isinstance(raw_engines, dict) else {}
        if legacy_flat:
            mineru_in = dict(engines_in.get(DOCUMENT_PARSING_ENGINE_MINERU) or {})
            engines_in[DOCUMENT_PARSING_ENGINE_MINERU] = {**mineru_in, **legacy_flat}

        engines_out = {
            DOCUMENT_PARSING_ENGINE_TEXT_ONLY: self._normalize_text_only_engine(
                engines_in.get(DOCUMENT_PARSING_ENGINE_TEXT_ONLY) or {}
            ),
            DOCUMENT_PARSING_ENGINE_MINERU: self._normalize_mineru_engine(
                engines_in.get(DOCUMENT_PARSING_ENGINE_MINERU) or {}
            ),
            DOCUMENT_PARSING_ENGINE_DOCLING: self._normalize_docling_engine(
                engines_in.get(DOCUMENT_PARSING_ENGINE_DOCLING) or {}
            ),
            DOCUMENT_PARSING_ENGINE_MARKITDOWN: self._normalize_markitdown_engine(
                engines_in.get(DOCUMENT_PARSING_ENGINE_MARKITDOWN) or {}
            ),
            DOCUMENT_PARSING_ENGINE_PYMUPDF4LLM: self._normalize_pymupdf4llm_engine(
                engines_in.get(DOCUMENT_PARSING_ENGINE_PYMUPDF4LLM) or {}
            ),
            DOCUMENT_PARSING_ENGINE_LITEPARSE: self._normalize_liteparse_engine(
                engines_in.get(DOCUMENT_PARSING_ENGINE_LITEPARSE) or {}
            ),
            DOCUMENT_PARSING_ENGINE_TIKA: self._normalize_tika_engine(
                engines_in.get(DOCUMENT_PARSING_ENGINE_TIKA) or {}
            ),
        }

        engine = _string(settings.get("engine")).lower().replace("-", "_").replace(" ", "_")
        if migrating:
            engine = DOCUMENT_PARSING_ENGINE_MINERU
        if engine not in _DOCUMENT_PARSING_ENGINES:
            engine = _DEFAULT_DOCUMENT_PARSING_ENGINE

        return {"version": 2, "engine": engine, "engines": engines_out}

    def _normalize_mineru_engine(self, settings: dict[str, Any]) -> dict[str, Any]:
        mode = _string(settings.get("mode")).lower()
        if mode not in _MINERU_MODES:
            mode = MINERU_MODE_LOCAL
        model_version = _string(settings.get("model_version")).lower()
        if model_version not in _MINERU_MODEL_VERSIONS:
            model_version = "pipeline"
        download_source = _string(settings.get("model_download_source")).lower()
        if download_source not in _MINERU_DOWNLOAD_SOURCES:
            download_source = "huggingface"
        language = _string(settings.get("language")) or "auto"
        return {
            "mode": mode,
            "api_base_url": _string(settings.get("api_base_url")).rstrip("/")
            or "https://mineru.net",
            "api_token": _string_or_list(settings.get("api_token")),
            "local_cli_path": _string(settings.get("local_cli_path")),
            "model_download_source": download_source,
            "model_download_endpoint": _string(settings.get("model_download_endpoint")).rstrip("/"),
            "model_version": model_version,
            "language": language,
            "enable_formula": _coerce_bool(settings.get("enable_formula"), True),
            "enable_table": _coerce_bool(settings.get("enable_table"), True),
            "is_ocr": _coerce_bool(settings.get("is_ocr"), False),
            "allow_local_model_download": _coerce_bool(
                settings.get("allow_local_model_download"), False
            ),
        }

    def _normalize_docling_engine(self, settings: dict[str, Any]) -> dict[str, Any]:
        mode = _string(settings.get("mode")).lower()
        if mode not in _DOCLING_MODES:
            mode = DOCLING_MODE_LOCAL
        return {
            "mode": mode,
            "api_base_url": _string(settings.get("api_base_url")).rstrip("/")
            or "http://localhost:5001",
            "api_token": _string(settings.get("api_token")),
            "do_ocr": _coerce_bool(settings.get("do_ocr"), False),
            "do_table_structure": _coerce_bool(settings.get("do_table_structure"), True),
            "allow_local_model_download": _coerce_bool(
                settings.get("allow_local_model_download"), False
            ),
        }

    def _apply_docling_process_overrides(self, settings: dict[str, Any]) -> dict[str, Any]:
        payload = dict(settings)
        if value := self._process_env_value("DOCLING_MODE"):
            payload["mode"] = value
        if value := self._process_env_value("DOCLING_API_BASE_URL"):
            payload["api_base_url"] = value
        if value := self._process_env_value("DOCLING_API_TOKEN"):
            payload["api_token"] = value
        return self._normalize_docling_engine(payload)

    def _normalize_tika_engine(self, settings: dict[str, Any]) -> dict[str, Any]:
        return {
            "server_url": _string(settings.get("server_url")).rstrip("/")
            or "http://localhost:9998",
        }

    def _apply_tika_process_overrides(self, settings: dict[str, Any]) -> dict[str, Any]:
        payload = dict(settings)
        if value := self._process_env_value("TIKA_SERVER_URL"):
            payload["server_url"] = value
        return self._normalize_tika_engine(payload)

    def _normalize_markitdown_engine(self, settings: dict[str, Any]) -> dict[str, Any]:
        return {
            "enable_llm_image_description": _coerce_bool(
                settings.get("enable_llm_image_description"), False
            ),
        }

    def _normalize_liteparse_engine(self, settings: dict[str, Any]) -> dict[str, Any]:
        image_mode = _string(settings.get("image_mode")).lower() or "placeholder"
        if image_mode not in LITEPARSE_IMAGE_MODES:
            image_mode = "placeholder"
        return {
            "image_mode": image_mode,
            "extract_links": _coerce_bool(settings.get("extract_links"), True),
            "extract_images": _coerce_bool(settings.get("extract_images"), False),
            "max_pages": _coerce_clamped_int(settings.get("max_pages"), 0, 0, 100_000),
        }

    def _normalize_pymupdf4llm_engine(self, settings: dict[str, Any]) -> dict[str, Any]:
        image_format = _string(settings.get("image_format")).lower() or "png"
        if image_format not in _PYMUPDF4LLM_IMAGE_FORMATS:
            image_format = "png"
        return {
            "write_images": _coerce_bool(settings.get("write_images"), True),
            "image_format": image_format,
            "image_dpi": _coerce_clamped_int(settings.get("image_dpi"), 150, 72, 600),
        }

    def _normalize_text_only_engine(self, _settings: dict[str, Any]) -> dict[str, Any]:
        return {}

    def _normalize_system(self, settings: dict[str, Any]) -> dict[str, Any]:
        public_api_base = _string(settings.get("next_public_api_base_external")) or _string(
            settings.get("public_api_base")
        )
        raw_source_filter = settings.get("web_search_source_filtering")
        source_filter = raw_source_filter if isinstance(raw_source_filter, dict) else {}
        max_file_mb = _coerce_clamped_int(
            settings.get("chat_attachment_max_file_mb"),
            DEFAULT_SYSTEM_SETTINGS["chat_attachment_max_file_mb"],
            *CHAT_ATTACHMENT_MAX_FILE_MB_RANGE,
        )
        max_total_mb = _coerce_clamped_int(
            settings.get("chat_attachment_max_total_mb"),
            DEFAULT_SYSTEM_SETTINGS["chat_attachment_max_total_mb"],
            *CHAT_ATTACHMENT_MAX_TOTAL_MB_RANGE,
        )
        # A per-message total below the per-file cap is contradictory; lift it.
        max_total_mb = max(max_total_mb, max_file_mb)
        return {
            "version": 1,
            "version_check_enabled": _coerce_bool(settings.get("version_check_enabled"), True),
            "backend_port": _coerce_port(settings.get("backend_port"), 8001),
            "backend_workers": _coerce_clamped_int(settings.get("backend_workers"), 1, 1, 64),
            "frontend_port": _coerce_port(settings.get("frontend_port"), 3782),
            "next_public_api_base_external": public_api_base,
            "next_public_api_base": _string(settings.get("next_public_api_base")),
            "cors_origin": _string(settings.get("cors_origin")),
            "cors_origins": _coerce_origins(settings.get("cors_origins")),
            "disable_ssl_verify": _coerce_bool(settings.get("disable_ssl_verify"), False),
            "chat_attachment_dir": _string(settings.get("chat_attachment_dir")),
            "sandbox_allow_subprocess": _coerce_bool(
                settings.get("sandbox_allow_subprocess"), True
            ),
            "capability_routing_enabled": _coerce_bool(
                settings.get("capability_routing_enabled"), False
            ),
            "web_search_source_filtering": {
                "enabled": _coerce_bool(source_filter.get("enabled"), True),
                "blocked_domains": _string_or_list(source_filter.get("blocked_domains")),
                "trusted_domains": _string_or_list(source_filter.get("trusted_domains")),
            },
            "chat_attachment_max_file_mb": max_file_mb,
            "chat_attachment_max_total_mb": max_total_mb,
            "chat_attachment_max_chars_per_doc": _coerce_clamped_int(
                settings.get("chat_attachment_max_chars_per_doc"),
                DEFAULT_SYSTEM_SETTINGS["chat_attachment_max_chars_per_doc"],
                *CHAT_ATTACHMENT_CHARS_RANGE,
            ),
            "chat_attachment_max_chars_total": _coerce_clamped_int(
                settings.get("chat_attachment_max_chars_total"),
                DEFAULT_SYSTEM_SETTINGS["chat_attachment_max_chars_total"],
                *CHAT_ATTACHMENT_CHARS_RANGE,
            ),
        }

    def _normalize_auth(self, settings: dict[str, Any]) -> dict[str, Any]:
        return {
            "version": 1,
            "enabled": _coerce_bool(settings.get("enabled"), False),
            "username": _string(settings.get("username")) or "admin",
            "password_hash": _string(settings.get("password_hash")),
            "token_expire_hours": max(1, _coerce_int(settings.get("token_expire_hours"), 24)),
            "cookie_secure": _coerce_bool(settings.get("cookie_secure"), False),
        }

    def _normalize_integrations(self, settings: dict[str, Any]) -> dict[str, Any]:
        raw_coordination = settings.get("turn_coordination")
        coordination = raw_coordination if isinstance(raw_coordination, dict) else {}
        backend = _string(coordination.get("backend")).lower()
        if backend not in {"memory", "redis"}:
            backend = "memory"
        key_prefix = _string(coordination.get("key_prefix")).strip(":") or "deeptutor"
        return {
            "version": 2,
            "pocketbase_url": _string(settings.get("pocketbase_url")).rstrip("/"),
            "pocketbase_port": _coerce_port(settings.get("pocketbase_port"), 8090),
            "pocketbase_external_url": _string(settings.get("pocketbase_external_url")).rstrip("/"),
            "pocketbase_admin_email": _string(settings.get("pocketbase_admin_email")),
            "pocketbase_admin_password": _string(settings.get("pocketbase_admin_password")),
            "turn_coordination": {
                "backend": backend,
                "redis_url": _string(coordination.get("redis_url")),
                "key_prefix": key_prefix,
                "lease_ttl_seconds": _coerce_clamped_int(
                    coordination.get("lease_ttl_seconds"), 30, 10, 300
                ),
                "renew_interval_seconds": _coerce_clamped_int(
                    coordination.get("renew_interval_seconds"), 10, 1, 100
                ),
                "recovery_interval_seconds": _coerce_clamped_int(
                    coordination.get("recovery_interval_seconds"), 10, 1, 300
                ),
                "stream_retention_seconds": _coerce_clamped_int(
                    coordination.get("stream_retention_seconds"), 86_400, 60, 2_592_000
                ),
            },
        }


def _bool_env(value: Any) -> str:
    return "true" if _coerce_bool(value, False) else "false"


def _global_settings_dir() -> Path:
    try:
        from deeptutor.multi_user.paths import get_admin_path_service

        return get_admin_path_service().get_settings_dir()
    except Exception:
        return get_path_service().get_settings_dir()


def get_runtime_settings_service() -> RuntimeSettingsService:
    return RuntimeSettingsService.get_instance(_global_settings_dir())


def ensure_runtime_settings_files() -> None:
    """Create missing JSON settings files using migration/default rules.

    Startup callers use this as the single "settings bootstrap" hook:
    missing runtime files are created with safe defaults. Process
    environment variables remain deployment overrides and are intentionally
    not persisted into the JSON files.
    """
    get_runtime_settings_service().ensure_defaults()
    from .model_catalog import get_model_catalog_service

    get_model_catalog_service().load()


def load_system_settings() -> dict[str, Any]:
    return get_runtime_settings_service().load_system()


@dataclass(frozen=True)
class ChatAttachmentLimits:
    """Effective chat-attachment policy, in enforcement-ready units."""

    max_file_bytes: int
    max_total_bytes: int
    max_chars_per_doc: int
    max_chars_total: int


def get_chat_attachment_limits() -> ChatAttachmentLimits:
    """Resolve the chat attachment policy from system.json (+ env overrides).

    Read at call time by every enforcement site (turn runtime extraction,
    partner uploads, the composer via the settings API) so edits apply to the
    next message without a restart.
    """
    system = load_system_settings()
    return ChatAttachmentLimits(
        max_file_bytes=int(system["chat_attachment_max_file_mb"]) * 1024 * 1024,
        max_total_bytes=int(system["chat_attachment_max_total_mb"]) * 1024 * 1024,
        max_chars_per_doc=int(system["chat_attachment_max_chars_per_doc"]),
        max_chars_total=int(system["chat_attachment_max_chars_total"]),
    )


# uvicorn's default WebSocket frame ceiling. Never derive below it so chat
# behaves identically to older builds even if the configured totals are tiny.
_WS_MAX_SIZE_FLOOR = 16 * 1024 * 1024


def compute_ws_max_size(max_total_bytes: int) -> int:
    """WebSocket message ceiling that fits a full attachment batch.

    Chat attachments ride the unified WS as base64 inside one JSON message
    (×4/3 inflation), so uvicorn's frame cap — not the policy above — is the
    binding constraint for large uploads. Add slack for the JSON envelope
    (message text, metadata, quoting) on top of the inflated payload.
    """
    inflated = (max_total_bytes * 4) // 3
    return max(_WS_MAX_SIZE_FLOOR, inflated + 8 * 1024 * 1024)


def get_ws_max_size() -> int:
    """Frame ceiling for the current settings — wire into every uvicorn launch."""
    return compute_ws_max_size(get_chat_attachment_limits().max_total_bytes)


# Idle keep-alive window for backend HTTP connections — wire into every uvicorn
# launch. The browser never reaches the backend directly: `web/proxy.ts` rewrites
# `/api/*` and Next.js forwards over Node's `http.globalAgent`, which pools idle
# sockets and reaps them on its own 5s `timeout`. uvicorn's `timeout_keep_alive`
# also defaults to 5s, so both ends armed an identical idle timer on the same
# socket and raced to close it: when the server's FIN landed on a socket the pool
# was simultaneously handing to a new request, the request died with `ECONNRESET`
# and the proxy turned it into a 500 ("Failed to proxy ... socket hang up" ->
# "Failed to load sessions" in the UI). Any value comfortably above the proxy's
# 5s reaper leaves the client as the only side that closes an idle connection,
# which is the safe direction — a pool retiring its own socket removes it before
# any request can be assigned to it, so the collision cannot happen at all.
HTTP_KEEP_ALIVE_TIMEOUT = 300


def load_auth_settings() -> dict[str, Any]:
    return get_runtime_settings_service().load_auth()


def load_integrations_settings() -> dict[str, Any]:
    return get_runtime_settings_service().load_integrations()


def load_mineru_settings() -> dict[str, Any]:
    return get_runtime_settings_service().load_mineru()


def load_llamaindex_settings() -> dict[str, Any]:
    return get_runtime_settings_service().load_llamaindex()


def load_graphrag_settings() -> dict[str, Any]:
    return get_runtime_settings_service().load_graphrag()


def load_lightrag_settings() -> dict[str, Any]:
    return get_runtime_settings_service().load_lightrag()


def load_lightrag_server_settings() -> dict[str, Any]:
    return get_runtime_settings_service().load_lightrag_server()


def load_document_parsing_settings() -> dict[str, Any]:
    return get_runtime_settings_service().load_document_parsing()


def export_runtime_settings_to_env(*, overwrite: bool = True) -> dict[str, str]:
    return get_runtime_settings_service().export_environment(overwrite=overwrite)


__all__ = [
    "CHAT_ATTACHMENT_CHARS_RANGE",
    "CHAT_ATTACHMENT_MAX_FILE_MB_RANGE",
    "CHAT_ATTACHMENT_MAX_TOTAL_MB_RANGE",
    "DEFAULT_AUTH_SETTINGS",
    "DEFAULT_DOCUMENT_PARSING_SETTINGS",
    "DEFAULT_GRAPHRAG_SETTINGS",
    "DEFAULT_IMA_SETTINGS",
    "DEFAULT_INTEGRATIONS_SETTINGS",
    "DEFAULT_LIGHTRAG_SETTINGS",
    "DEFAULT_LIGHTRAG_SERVER_SETTINGS",
    "DEFAULT_LLAMAINDEX_SETTINGS",
    "DEFAULT_MINERU_SETTINGS",
    "DEFAULT_PAGEINDEX_SETTINGS",
    "DEFAULT_SYSTEM_SETTINGS",
    "DOCUMENT_PARSING_ENGINE_DOCLING",
    "DOCUMENT_PARSING_ENGINE_LITEPARSE",
    "DOCUMENT_PARSING_ENGINE_MARKITDOWN",
    "DOCUMENT_PARSING_ENGINE_MINERU",
    "DOCUMENT_PARSING_ENGINE_PYMUPDF4LLM",
    "DOCUMENT_PARSING_ENGINE_TEXT_ONLY",
    "DOCUMENT_PARSING_ENGINE_TIKA",
    "DOCLING_MODE_LOCAL",
    "DOCLING_MODE_REMOTE",
    "LITEPARSE_IMAGE_MODES",
    "MINERU_MODE_CLOUD",
    "MINERU_MODE_LOCAL",
    "ChatAttachmentLimits",
    "RuntimeSettingsService",
    "compute_ws_max_size",
    "ensure_runtime_settings_files",
    "export_runtime_settings_to_env",
    "get_chat_attachment_limits",
    "get_runtime_settings_service",
    "get_ws_max_size",
    "load_auth_settings",
    "load_document_parsing_settings",
    "load_graphrag_settings",
    "load_integrations_settings",
    "load_lightrag_settings",
    "load_lightrag_server_settings",
    "load_llamaindex_settings",
    "load_mineru_settings",
    "load_system_settings",
]
