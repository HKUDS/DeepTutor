from __future__ import annotations

from copy import deepcopy
import json
import os
from pathlib import Path
import tempfile
from typing import Any, Callable

from deeptutor.services.path_service import get_path_service

from .origins import normalize_origins

DEFAULT_SYSTEM_SETTINGS: dict[str, Any] = {
    "version": 1,
    "backend_port": 8001,
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
}

DEFAULT_AUTH_SETTINGS: dict[str, Any] = {
    "version": 1,
    "enabled": False,
    "username": "admin",
    "password_hash": "",
    "token_expire_hours": 24,
    "cookie_secure": False,
}

DEFAULT_INTEGRATIONS_SETTINGS: dict[str, Any] = {
    "version": 1,
    "pocketbase_url": "",
    "pocketbase_port": 8090,
    "pocketbase_external_url": "",
    "pocketbase_admin_email": "",
    "pocketbase_admin_password": "",
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
_MINERU_MODEL_VERSIONS = frozenset({"pipeline", "vlm"})
_MINERU_DOWNLOAD_SOURCES = frozenset({"huggingface", "modelscope"})

DOCUMENT_PARSING_ENGINE_TEXT_ONLY = "text_only"
DOCUMENT_PARSING_ENGINE_MINERU = "mineru"
DOCUMENT_PARSING_ENGINE_DOCLING = "docling"
DOCUMENT_PARSING_ENGINE_MARKITDOWN = "markitdown"
DOCUMENT_PARSING_ENGINE_PYMUPDF4LLM = "pymupdf4llm"
_DOCUMENT_PARSING_ENGINES = frozenset(
    {
        DOCUMENT_PARSING_ENGINE_TEXT_ONLY,
        DOCUMENT_PARSING_ENGINE_MINERU,
        DOCUMENT_PARSING_ENGINE_DOCLING,
        DOCUMENT_PARSING_ENGINE_MARKITDOWN,
        DOCUMENT_PARSING_ENGINE_PYMUPDF4LLM,
    }
)
# Image formats PyMuPDF4LLM can write extracted page images as.
_PYMUPDF4LLM_IMAGE_FORMATS = frozenset({"png", "jpg", "jpeg", "webp"})
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

# Docling engine slice. Downloads layout/table models on first run, hence the
# same ``allow_local_model_download`` gate as MinerU local.
_DEFAULT_DOCLING_ENGINE: dict[str, Any] = {
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
    },
}

# Backward-compatible alias: the MinerU engine slice. Several call-sites and
# tests reference ``DEFAULT_MINERU_SETTINGS``; it now denotes the engine slice.
DEFAULT_MINERU_SETTINGS: dict[str, Any] = _DEFAULT_MINERU_ENGINE

# PageIndex cloud RAG engine. A KB indexed with the ``pageindex`` provider
# ships its documents to the hosted PageIndex service for tree building and
# reasoning-based retrieval. Only an API key (per PageIndex account) and the
# API base URL are needed; the same key is reused by every ``pageindex`` KB.
# Kept in its own JSON file so the credential lives beside other per-feature
# settings and never leaks into model/network config.
DEFAULT_PAGEINDEX_SETTINGS: dict[str, Any] = {
    "version": 1,
    "api_key": "",
    "api_base_url": "https://api.pageindex.ai",
}

# LlamaIndex local RAG engine. These are the retrieval + chunking knobs the
# default engine exposes; they were previously hardcoded / env-only. Kept in
# their own JSON file so the engine's detail page can read/write them.
#
# * ``retrieval_profile`` — "hybrid" (BM25 + vector fusion) or "vector" only.
# * ``top_k`` — default number of chunks a query returns.
# * ``vector_top_k_multiplier`` / ``bm25_top_k_multiplier`` — how many extra
#   candidates each child retriever fetches before fusion re-ranks to ``top_k``.
# * ``chunk_size`` / ``chunk_overlap`` — indexing chunk geometry; changes apply
#   on the next (re-)index, not retroactively.
#
# ``fusion_num_queries`` is intentionally NOT exposed: query generation needs a
# real LLM, but the fusion retriever runs on a MockLLM, so any value > 1 would
# silently degrade results. It stays pinned to the dataclass default.
LLAMAINDEX_VECTOR_PROFILE = "vector"
LLAMAINDEX_HYBRID_PROFILE = "hybrid"
_LLAMAINDEX_PROFILES = frozenset({LLAMAINDEX_VECTOR_PROFILE, LLAMAINDEX_HYBRID_PROFILE})

DEFAULT_LLAMAINDEX_SETTINGS: dict[str, Any] = {
    "version": 1,
    "retrieval_profile": LLAMAINDEX_HYBRID_PROFILE,
    "top_k": 5,
    "vector_top_k_multiplier": 2,
    "bm25_top_k_multiplier": 2,
    "chunk_size": 512,
    "chunk_overlap": 50,
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

# LightRAG retrieval knobs (HKUDS/LightRAG via RAG-Anything). ``top_k`` is the
# number of entities/relations the query pulls; ``response_type`` mirrors
# GraphRAG's. These ride into ``QueryParam`` via the engine's aquery() call;
# wiring is defensive (an older RAG-Anything that rejects a kwarg degrades to a
# mode-only query).
DEFAULT_LIGHTRAG_SETTINGS: dict[str, Any] = {
    "version": 1,
    "top_k": 60,
    "response_type": "Multiple Paragraphs",
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


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w",
        encoding="utf-8",
        dir=str(path.parent),
        delete=False,
    ) as handle:
        json.dump(payload, handle, indent=2, ensure_ascii=False)
        handle.write("\n")
        tmp_path = Path(handle.name)
    tmp_path.replace(path)


def _string(value: Any) -> str:
    return "" if value is None else str(value).strip()


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

    def ensure_defaults(self) -> None:
        self.load_system(include_process_overrides=False)
        self.load_auth(include_process_overrides=False)
        self.load_integrations(include_process_overrides=False)
        self.load_mineru(include_process_overrides=False)
        self.load_pageindex(include_process_overrides=False)
        self.load_llamaindex(include_process_overrides=False)
        self.load_graphrag()
        self.load_lightrag()

    def render_environment(self) -> dict[str, str]:
        """Render non-model settings into process env names for subprocesses."""
        system = self.load_system()
        auth = self.load_auth()
        integrations = self.load_integrations()
        return {
            "BACKEND_PORT": str(system["backend_port"]),
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
            "DEEPTUTOR_API_BASE_URL": (
                system["next_public_api_base"]
                or system["next_public_api_base_external"]
                or f"http://localhost:{system['backend_port']}"
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
        if value := self._process_env_value("DEEPTUTOR_SANDBOX_ALLOW_SUBPROCESS"):
            payload["sandbox_allow_subprocess"] = value
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
        if value := self._process_env_value("PAGEINDEX_API_BASE_URL"):
            payload["api_base_url"] = value
        return self._normalize_pageindex(payload)

    def _normalize_pageindex(self, settings: dict[str, Any]) -> dict[str, Any]:
        return {
            "version": 1,
            "api_key": _string(settings.get("api_key")),
            "api_base_url": _string(settings.get("api_base_url")).rstrip("/")
            or "https://api.pageindex.ai",
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
            "chunk_size": chunk_size,
            "chunk_overlap": chunk_overlap,
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
            "api_token": _string(settings.get("api_token")),
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
        return {
            "do_ocr": _coerce_bool(settings.get("do_ocr"), False),
            "do_table_structure": _coerce_bool(settings.get("do_table_structure"), True),
            "allow_local_model_download": _coerce_bool(
                settings.get("allow_local_model_download"), False
            ),
        }

    def _normalize_markitdown_engine(self, settings: dict[str, Any]) -> dict[str, Any]:
        return {
            "enable_llm_image_description": _coerce_bool(
                settings.get("enable_llm_image_description"), False
            ),
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
        return {
            "version": 1,
            "backend_port": _coerce_port(settings.get("backend_port"), 8001),
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
        return {
            "version": 1,
            "pocketbase_url": _string(settings.get("pocketbase_url")).rstrip("/"),
            "pocketbase_port": _coerce_port(settings.get("pocketbase_port"), 8090),
            "pocketbase_external_url": _string(settings.get("pocketbase_external_url")).rstrip("/"),
            "pocketbase_admin_email": _string(settings.get("pocketbase_admin_email")),
            "pocketbase_admin_password": _string(settings.get("pocketbase_admin_password")),
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


def load_document_parsing_settings() -> dict[str, Any]:
    return get_runtime_settings_service().load_document_parsing()


def export_runtime_settings_to_env(*, overwrite: bool = True) -> dict[str, str]:
    return get_runtime_settings_service().export_environment(overwrite=overwrite)


__all__ = [
    "DEFAULT_AUTH_SETTINGS",
    "DEFAULT_DOCUMENT_PARSING_SETTINGS",
    "DEFAULT_GRAPHRAG_SETTINGS",
    "DEFAULT_INTEGRATIONS_SETTINGS",
    "DEFAULT_LIGHTRAG_SETTINGS",
    "DEFAULT_LLAMAINDEX_SETTINGS",
    "DEFAULT_MINERU_SETTINGS",
    "DEFAULT_PAGEINDEX_SETTINGS",
    "DEFAULT_SYSTEM_SETTINGS",
    "DOCUMENT_PARSING_ENGINE_DOCLING",
    "DOCUMENT_PARSING_ENGINE_MARKITDOWN",
    "DOCUMENT_PARSING_ENGINE_MINERU",
    "DOCUMENT_PARSING_ENGINE_PYMUPDF4LLM",
    "DOCUMENT_PARSING_ENGINE_TEXT_ONLY",
    "MINERU_MODE_CLOUD",
    "MINERU_MODE_LOCAL",
    "RuntimeSettingsService",
    "ensure_runtime_settings_files",
    "export_runtime_settings_to_env",
    "get_runtime_settings_service",
    "load_auth_settings",
    "load_document_parsing_settings",
    "load_graphrag_settings",
    "load_integrations_settings",
    "load_lightrag_settings",
    "load_llamaindex_settings",
    "load_mineru_settings",
    "load_system_settings",
]
