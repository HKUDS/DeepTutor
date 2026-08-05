from __future__ import annotations

from collections.abc import Callable
from copy import deepcopy
import json
import os
from pathlib import Path
import re
import tempfile
import threading
from typing import Any
from uuid import uuid4

from deeptutor.services.path_service import get_path_service

from .embedding_endpoint import normalize_embedding_endpoint_for_display

# Fallback only — frozen at admin scope at import time. Production code should
# enter through ``get_model_catalog_service()`` so the path is resolved from the
# current user's PathService on every call.
CATALOG_PATH = get_path_service().get_settings_file("model_catalog")

# LLM profile API-protocol contract (FT-05). ``auto`` is the compatibility value
# migrated from legacy profiles that predate the field; the three explicit values
# are the selectable protocols the Models UI offers. ``strict_protocol=true``
# means the runtime must never silently fall back to another protocol.
LLM_API_PROTOCOLS = (
    "auto",
    "openai_chat_completions",
    "openai_responses",
    "anthropic_messages",
)
EXPLICIT_LLM_API_PROTOCOLS = (
    "openai_chat_completions",
    "openai_responses",
    "anthropic_messages",
)

# Capability-probe states written onto the active LLM profile by the config test
# runner (Settings > Diagnostics > Run test). ``unknown`` is the default until
# the first probe completes; the UI renders passed/failed badges.
CAPABILITY_PROBE_STATUSES = ("unknown", "probing", "passed", "failed")


def _service_shell() -> dict[str, Any]:
    return {
        "active_profile_id": None,
        "active_model_id": None,
        "profiles": [],
    }


def _search_shell() -> dict[str, Any]:
    return {
        "active_profile_id": None,
        "profiles": [],
    }


def _default_catalog() -> dict[str, Any]:
    return {
        "version": 1,
        "services": {
            "llm": _service_shell(),
            "embedding": _service_shell(),
            "search": _search_shell(),
            "tts": _service_shell(),
            "stt": _service_shell(),
            "imagegen": _service_shell(),
            "videogen": _service_shell(),
        },
    }


class ModelCatalogService:
    _instances: dict[str, "ModelCatalogService"] = {}

    def __init__(self, path: Path | None = None):
        self.path = path or CATALOG_PATH
        self._lock = threading.RLock()

    @classmethod
    def get_instance(cls, path: Path | None = None) -> "ModelCatalogService":
        resolved = (path or get_path_service().get_settings_file("model_catalog")).resolve()
        key = str(resolved)
        if key not in cls._instances:
            cls._instances[key] = cls(resolved)
        return cls._instances[key]

    def load(self) -> dict[str, Any]:
        loaded = self._read_existing_catalog()
        if loaded:
            catalog = _default_catalog()
            catalog.update({k: v for k, v in loaded.items() if k != "services"})
            catalog["services"].update(loaded.get("services", {}))
            merged_defaults = catalog != loaded
            before = deepcopy(catalog)
            self._normalize(catalog)
            if merged_defaults or catalog != before:
                self.save(catalog)
            return catalog

        catalog = _default_catalog()
        self._normalize(catalog)
        self.save(catalog)
        return catalog

    def _read_existing_catalog(self) -> dict[str, Any]:
        if not self.path.exists() or self.path.stat().st_size == 0:
            return {}
        try:
            loaded = json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            return {}
        return loaded if isinstance(loaded, dict) else {}

    def save(self, catalog: dict[str, Any]) -> dict[str, Any]:
        with self._lock:
            normalized = deepcopy(catalog)
            self._normalize(normalized)
            self.path.parent.mkdir(parents=True, exist_ok=True)
            fd, temp_name = tempfile.mkstemp(
                prefix=f".{self.path.name}.",
                suffix=".tmp",
                dir=self.path.parent,
            )
            temp_path = Path(temp_name)
            try:
                with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
                    json.dump(normalized, handle, indent=2, ensure_ascii=False)
                    handle.write("\n")
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(temp_path, self.path)
            finally:
                temp_path.unlink(missing_ok=True)
            return normalized

    def update(self, mutator: Callable[[dict[str, Any]], None]) -> dict[str, Any]:
        with self._lock:
            catalog = self.load()
            mutator(catalog)
            return self.save(catalog)

    def apply(self, catalog: dict[str, Any] | None = None) -> dict[str, Any]:
        current = self.save(catalog or self.load())
        return {"catalog_path": str(self.path), "services": list(current.get("services", {}))}

    def _normalize(self, catalog: dict[str, Any]) -> bool:
        services = catalog.setdefault("services", {})
        changed = False
        services.setdefault("llm", _service_shell())
        services.setdefault("embedding", _service_shell())
        services.setdefault("search", _search_shell())
        services.setdefault("tts", _service_shell())
        services.setdefault("stt", _service_shell())
        services.setdefault("imagegen", _service_shell())
        services.setdefault("videogen", _service_shell())
        for service_name in ("llm", "embedding", "search", "tts", "stt", "imagegen", "videogen"):
            service = services[service_name]
            profiles = service.setdefault("profiles", [])
            for profile in profiles:
                profile.setdefault("id", f"{service_name}-profile-{uuid4().hex[:8]}")
                profile.setdefault("name", "Untitled Profile")
                profile.setdefault("api_version", "")
                profile.setdefault("base_url", "")
                profile.setdefault("api_key", "")
                if service_name == "llm":
                    # Legacy profiles lack the protocol fields; they migrate to
                    # ``auto`` to preserve the pre-protocol heuristic. Newly
                    # created profiles always carry an explicit value.
                    profile.setdefault("api_protocol", "auto")
                    profile.setdefault("strict_protocol", False)
                    profile.setdefault("capability_probe_status", "unknown")
                    profile.setdefault("capability_probe_at", "")
                    profile.setdefault("capability_probe_message", "")
                    if profile.get("api_protocol") not in LLM_API_PROTOCOLS:
                        profile["api_protocol"] = "auto"
                        changed = True
                    if not isinstance(profile.get("strict_protocol"), bool):
                        raw = str(profile.get("strict_protocol") or "").strip().lower()
                        profile["strict_protocol"] = raw in {"true", "1", "yes", "on"}
                        changed = True
                    if profile.get("capability_probe_status") not in CAPABILITY_PROBE_STATUSES:
                        profile["capability_probe_status"] = "unknown"
                        changed = True
                if service_name == "search":
                    profile.setdefault("provider", "brave")
                    profile.setdefault("proxy", "")
                    profile["models"] = []
                else:
                    profile.setdefault("binding", "openai")
                    profile.setdefault("extra_headers", {})
                    if service_name == "embedding":
                        models = profile.setdefault("models", [])
                        active_model_id = service.get("active_model_id")
                        active_model = next(
                            (item for item in models if item.get("id") == active_model_id),
                            models[0] if models else {},
                        )
                        before = str(profile.get("base_url") or "")
                        after = normalize_embedding_endpoint_for_display(
                            profile.get("binding"),
                            before,
                            model=active_model.get("model"),
                        )
                        if after != before:
                            profile["base_url"] = after
                            changed = True
                    else:
                        models = profile.setdefault("models", [])
                    for model in models:
                        model.setdefault("id", f"{service_name}-model-{uuid4().hex[:8]}")
                        model.setdefault("name", model.get("model") or "Untitled Model")
                        model.setdefault("model", "")
                        if service_name == "embedding":
                            # Empty default → test_runner auto-fills from the
                            # actual API response on first connection test.
                            model.setdefault("dimension", "")
                            # CSV of supported dims discovered during the last
                            # successful "Test connection" — drives the UI
                            # dropdown. Empty when the model is not in any
                            # adapter's MODELS_INFO map.
                            model.setdefault("supported_dimensions", "")
                        elif service_name == "tts":
                            # Provider/model-specific free-form voice string
                            # (e.g. "alloy", "autumn", "model:voice").
                            model.setdefault("voice", "")
                            model.setdefault("response_format", "mp3")
                        elif service_name == "imagegen":
                            # Generation knobs; empty → provider default.
                            model.setdefault("size", "")
                            model.setdefault("quality", "")
                            model.setdefault("style", "")
                            model.setdefault("response_format", "")
                        elif service_name == "videogen":
                            model.setdefault("aspect_ratio", "")
                            model.setdefault("duration", "")
                            model.setdefault("resolution", "")
            profile_ids = {profile.get("id") for profile in profiles}
            if profiles and service.get("active_profile_id") not in profile_ids:
                service["active_profile_id"] = profiles[0]["id"]
                changed = True
            if service_name in {"llm", "embedding", "tts", "stt", "imagegen", "videogen"}:
                active_profile = self.get_active_profile(catalog, service_name)
                models = (active_profile or {}).get("models") or []
                model_ids = {model.get("id") for model in models}
                if models and service.get("active_model_id") not in model_ids:
                    service["active_model_id"] = models[0]["id"]
                    changed = True
        return changed

    def get_active_profile(
        self, catalog: dict[str, Any], service_name: str
    ) -> dict[str, Any] | None:
        service = catalog.get("services", {}).get(service_name, {})
        active_id = service.get("active_profile_id")
        for profile in service.get("profiles", []):
            if profile.get("id") == active_id:
                return profile
        profiles = service.get("profiles", [])
        return profiles[0] if profiles else None

    def get_active_model(self, catalog: dict[str, Any], service_name: str) -> dict[str, Any] | None:
        if service_name == "search":
            return None
        service = catalog.get("services", {}).get(service_name, {})
        active_model_id = service.get("active_model_id")
        profile = self.get_active_profile(catalog, service_name)
        if not profile:
            return None
        for model in profile.get("models", []):
            if model.get("id") == active_model_id:
                return model
        models = profile.get("models", [])
        return models[0] if models else None


def get_model_catalog_service() -> ModelCatalogService:
    try:
        from deeptutor.multi_user.context import get_current_user
        from deeptutor.multi_user.paths import get_admin_path_service

        if not get_current_user().is_admin:
            return ModelCatalogService.get_instance(
                get_admin_path_service().get_settings_file("model_catalog")
            )
    except Exception:
        pass
    return ModelCatalogService.get_instance(get_path_service().get_settings_file("model_catalog"))


# Credential-looking material that provider backends sometimes echo back in
# probe/connection error text (the failing request headers, an invalid token,
# an API key). Applied to ``capability_probe_message`` and LLM test events so a
# failure can never leak a secret to the stored catalog or the browser.
_PROBE_SECRET_PATTERNS = (
    # OpenAI / Anthropic style keys: sk-..., sk-ant-api03-...
    re.compile(r"\bsk-[A-Za-z0-9_\-]{6,}\b"),
    # Authorization header values (optionally with a Bearer scheme).
    re.compile(
        r"\bAuthorization\s*[:=]\s*(?:Bearer\s+)?[A-Za-z0-9._~+\-/=]{6,}",
        re.IGNORECASE,
    ),
    # Standalone Bearer tokens.
    re.compile(r"\bBearer\s+[A-Za-z0-9._~+\-/=]{6,}", re.IGNORECASE),
    # Explicit API-key header values: api-key / x-api-key / x-goog-api-key.
    re.compile(
        r"\b[a-z0-9\-_]*api[-_]?key[a-z0-9\-_]*\s*[:=]\s*[A-Za-z0-9._~+\-/=]{4,}",
        re.IGNORECASE,
    ),
)


def sanitize_probe_message(message: str) -> str:
    """Redact credential material from a provider error message.

    Provider backends sometimes echo the failing request — the Authorization
    header, the Bearer token, an API key — back in the exception text. This is
    the single scrub point for probe messages before they are persisted to the
    catalog or emitted to the browser via SSE.
    """
    if not message:
        return message or ""
    safe = message
    for pattern in _PROBE_SECRET_PATTERNS:
        safe = pattern.sub("[REDACTED]", safe)
    return safe


def redact_catalog(catalog: dict[str, Any]) -> dict[str, Any]:
    """Return a browser-safe copy of the catalog.

    Profile ``api_key`` values never leave the server. Each profile carries an
    ``api_key_set`` boolean instead so the UI can show whether credentials are
    configured, and the tri-state merge on save preserves an untouched key.
    The LLM capability-probe message is scrubbed for credential material too —
    a provider failure text must never leak a key/token/header to the browser.
    """
    redacted = deepcopy(catalog)
    for service in redacted.get("services", {}).values():
        for profile in service.get("profiles", []):
            if not isinstance(profile, dict):
                continue
            profile["api_key_set"] = bool(profile.get("api_key"))
            profile["api_key"] = ""
            message = profile.get("capability_probe_message")
            if message:
                profile["capability_probe_message"] = sanitize_probe_message(str(message))
    return redacted


def merge_profile_secrets(
    stored: dict[str, Any],
    incoming: dict[str, Any],
) -> dict[str, Any]:
    """Resolve tri-state ``api_key`` from an incoming (redacted) catalog.

    The browser never holds the raw key, so the PUT payload can only express
    intent:

    - a non-empty ``api_key`` replaces the stored value;
    - ``api_key_set=false`` (with an empty ``api_key``) clears it;
    - otherwise (untouched field) the stored value is preserved.

    ``api_key_set`` is transient and popped before persisting.
    """
    incoming_services = incoming.get("services", {})
    stored_services = stored.get("services", {})
    for service_name, service in incoming_services.items():
        if not isinstance(service, dict):
            continue
        stored_service = stored_services.get(service_name, {})
        stored_by_id = {
            str(profile.get("id")): profile
            for profile in stored_service.get("profiles", [])
            if isinstance(profile, dict)
        }
        for profile in service.get("profiles", []):
            if not isinstance(profile, dict):
                continue
            stored_profile = stored_by_id.get(str(profile.get("id") or ""))
            if stored_profile is None:
                # Brand-new profile from the UI — no stored secret to preserve.
                profile.pop("api_key_set", None)
                continue
            incoming_key = profile.get("api_key")
            key_set = profile.get("api_key_set")
            if incoming_key:
                stored_key = incoming_key
            elif key_set is False:
                stored_key = ""
            else:
                stored_key = stored_profile.get("api_key", "")
            profile["api_key"] = stored_key
            profile.pop("api_key_set", None)
    return incoming


__all__ = [
    "CATALOG_PATH",
    "ModelCatalogService",
    "get_model_catalog_service",
    "LLM_API_PROTOCOLS",
    "EXPLICIT_LLM_API_PROTOCOLS",
    "CAPABILITY_PROBE_STATUSES",
    "sanitize_probe_message",
    "redact_catalog",
    "merge_profile_secrets",
]
