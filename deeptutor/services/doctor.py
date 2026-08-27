"""Local and opt-in online diagnostics for the DeepTutor CLI."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import asdict, dataclass
from pathlib import Path
import re
import tempfile
from typing import Any, Literal
from urllib.parse import urlsplit, urlunsplit

from deeptutor.services.llm.utils import is_local_llm_server, sanitize_url
from deeptutor.services.provider_registry import find_by_name

CheckStatus = Literal["pass", "fail", "skip"]


@dataclass(frozen=True)
class DoctorCheck:
    """One diagnostic result shown by ``deeptutor doctor``."""

    key: str
    label: str
    status: CheckStatus
    detail: str
    required: bool = True

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class DoctorReport:
    """Complete diagnostic report."""

    online: bool
    checks: list[DoctorCheck]

    @property
    def ok(self) -> bool:
        return all(check.status != "fail" for check in self.checks if check.required)

    def to_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "online": self.online,
            "checks": [check.to_dict() for check in self.checks],
        }


def _safe_endpoint(raw_url: str | None) -> tuple[bool, str]:
    if not raw_url:
        return False, "No provider endpoint is configured."

    normalized = sanitize_url(raw_url)
    try:
        parsed = urlsplit(normalized)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            return False, "The configured provider endpoint is not a valid HTTP(S) URL."
        host = parsed.hostname
        if ":" in host and not host.startswith("["):
            host = f"[{host}]"
        port = f":{parsed.port}" if parsed.port is not None else ""
        display_url = urlunsplit((parsed.scheme, f"{host}{port}", "", "", ""))
    except (ValueError, TypeError):
        return False, "The configured provider endpoint is not a valid HTTP(S) URL."
    return True, display_url.rstrip("/")


def _has_authentication_header(headers: Any) -> bool:
    if not isinstance(headers, Mapping):
        return False

    exact_names = {
        "authorization",
        "proxy-authorization",
        "api-key",
        "x-api-key",
        "x-goog-api-key",
    }
    auth_suffixes = (
        "-authorization",
        "-auth",
        "-api-key",
        "-apikey",
        "-access-token",
        "-auth-token",
    )
    for name, value in headers.items():
        normalized_name = re.sub(r"[_\s]+", "-", str(name).strip().lower())
        if str(value or "").strip() and (
            normalized_name in exact_names or normalized_name.endswith(auth_suffixes)
        ):
            return True
    return False


def _credentials_check(config: Any) -> DoctorCheck:
    provider_name = str(getattr(config, "provider_name", "") or "")
    provider_mode = str(getattr(config, "provider_mode", "") or "")
    api_key = str(getattr(config, "api_key", "") or "")
    endpoint = str(
        getattr(config, "effective_url", None) or getattr(config, "base_url", None) or ""
    )
    extra_headers = getattr(config, "extra_headers", None) or {}
    provider = find_by_name(provider_name)
    placeholders = {"", "no-key", "sk-no-key-required"}

    if provider_mode == "oauth" or (provider and provider.is_oauth):
        return DoctorCheck(
            key="llm_credentials",
            label="LLM credentials",
            status="pass",
            detail=f"{provider_name or 'Selected provider'} uses provider-managed OAuth.",
        )
    if (
        provider_mode == "local"
        or (provider and provider.is_local)
        or is_local_llm_server(endpoint)
    ):
        return DoctorCheck(
            key="llm_credentials",
            label="LLM credentials",
            status="pass",
            detail="The selected local provider does not require an API key.",
        )
    if api_key not in placeholders or _has_authentication_header(extra_headers):
        return DoctorCheck(
            key="llm_credentials",
            label="LLM credentials",
            status="pass",
            detail=f"Credentials are configured for {provider_name or 'the selected provider'}.",
        )
    if provider and provider.is_direct and provider.name != "azure_openai":
        return DoctorCheck(
            key="llm_credentials",
            label="LLM credentials",
            status="skip",
            detail=(
                "No recognized credential is configured for this custom endpoint. "
                "Use --online to verify whether it accepts unauthenticated requests."
            ),
            required=False,
        )
    return DoctorCheck(
        key="llm_credentials",
        label="LLM credentials",
        status="fail",
        detail=f"No credentials are configured for {provider_name or 'the selected provider'}.",
    )


def _llm_checks(config: Any) -> list[DoctorCheck]:
    model = str(getattr(config, "model", "") or "")
    provider_name = str(getattr(config, "provider_name", "") or "")
    provider_mode = str(getattr(config, "provider_mode", "") or "")
    endpoint = getattr(config, "effective_url", None) or getattr(config, "base_url", None)

    checks = [
        DoctorCheck(
            key="llm_config",
            label="LLM configuration",
            status="pass" if model else "fail",
            detail=(
                f"Active model: {model} ({provider_name or 'unknown provider'})."
                if model
                else "No active LLM model is configured."
            ),
        ),
        _credentials_check(config),
    ]

    provider = find_by_name(provider_name)
    if provider_mode == "oauth" or (provider and provider.is_oauth):
        checks.append(
            DoctorCheck(
                key="llm_endpoint",
                label="LLM endpoint",
                status="pass",
                detail="The OAuth provider manages its endpoint.",
            )
        )
    else:
        endpoint_ok, detail = _safe_endpoint(endpoint)
        checks.append(
            DoctorCheck(
                key="llm_endpoint",
                label="LLM endpoint",
                status="pass" if endpoint_ok else "fail",
                detail=detail,
            )
        )
    return checks


def _storage_check(data_root: Path) -> DoctorCheck:
    try:
        data_root.mkdir(parents=True, exist_ok=True)
        with tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            prefix=".deeptutor-doctor-",
            dir=data_root,
            delete=True,
        ) as handle:
            handle.write("ok")
            handle.flush()
    except OSError as exc:
        return DoctorCheck(
            key="storage",
            label="Runtime storage",
            status="fail",
            detail=f"Cannot write to {data_root}: {exc}",
        )
    return DoctorCheck(
        key="storage",
        label="Runtime storage",
        status="pass",
        detail=f"Writable: {data_root}",
    )


def _rag_check(
    config: dict[str, Any],
    preflight: Callable[[str], dict[str, Any]],
) -> DoctorCheck:
    knowledge_bases = config.get("knowledge_bases", {})
    if not isinstance(knowledge_bases, dict) or not knowledge_bases:
        return DoctorCheck(
            key="rag",
            label="RAG prerequisites",
            status="skip",
            detail="No knowledge bases are configured.",
            required=False,
        )

    defaults = config.get("defaults", {})
    default_provider = (
        str(defaults.get("rag_provider", "llamaindex"))
        if isinstance(defaults, dict)
        else "llamaindex"
    )
    from deeptutor.services.rag.factory import (
        LIGHTRAG_SERVER_PROVIDER,
        normalize_provider_name,
    )

    providers: set[str] = set()
    failures: list[str] = []
    for kb_name, entry in knowledge_bases.items():
        if not isinstance(entry, dict):
            continue
        provider = normalize_provider_name(str(entry.get("rag_provider") or default_provider))
        providers.add(provider)
        if provider != LIGHTRAG_SERVER_PROVIDER:
            continue

        from deeptutor.services.rag.pipelines.lightrag_server.config import (
            config_from_entry,
        )

        try:
            server_config = config_from_entry(entry)
            endpoint_ok, _ = _safe_endpoint(server_config.base_url)
            if not endpoint_ok:
                failures.append(f"{kb_name}: invalid LightRAG server URL")
        except Exception as exc:
            failures.append(f"{kb_name}: {_redact_error(exc, None)}")

    for provider in sorted(providers - {LIGHTRAG_SERVER_PROVIDER}):
        try:
            report = preflight(provider)
            for check in report.get("checks", []):
                if not check.get("ok") and not check.get("optional", False):
                    failures.append(f"{provider}: {check.get('label', 'requirement failed')}")
        except Exception as exc:
            failures.append(f"{provider}: preflight could not run ({_redact_error(exc, None)})")

    if failures:
        return DoctorCheck(
            key="rag",
            label="RAG prerequisites",
            status="fail",
            detail="; ".join(failures),
            required=False,
        )
    return DoctorCheck(
        key="rag",
        label="RAG prerequisites",
        status="pass",
        detail=f"Ready for configured provider(s): {', '.join(sorted(providers))}.",
        required=False,
    )


def _redact_error(exc: Exception, config: Any) -> str:
    message = str(exc).strip() or type(exc).__name__
    extra_headers = getattr(config, "extra_headers", None) or {}
    header_values = (
        [str(value or "") for value in extra_headers.values()]
        if isinstance(extra_headers, Mapping)
        else []
    )
    secrets = [
        str(getattr(config, "api_key", "") or ""),
        str(getattr(config, "effective_url", "") or ""),
        str(getattr(config, "base_url", "") or ""),
        *header_values,
    ]
    for secret in secrets:
        if secret and secret not in {"no-key", "sk-no-key-required"}:
            message = message.replace(secret, "[redacted]")
    message = re.sub(r"\bsk-[A-Za-z0-9_-]{4,}\b", "[redacted]", message)
    message = re.sub(
        r"(?i)((?:api[_-]?key|authorization|token|password)\s*[:=]\s*)[^\s,;]+",
        r"\1[redacted]",
        message,
    )
    return message


async def _probe_provider(config: Any) -> None:
    from deeptutor.services.llm import complete

    response = await complete(
        model=str(config.model),
        prompt="Reply with OK.",
        system_prompt="Reply with only OK.",
        binding=str(config.binding),
        api_key=str(config.api_key or ""),
        base_url=str(config.effective_url or config.base_url or ""),
        api_version=config.api_version,
        temperature=0,
        extra_headers=config.extra_headers,
        reasoning_effort=config.reasoning_effort,
        max_retries=0,
        allow_image_fallback=False,
        max_tokens=64,
    )
    if not (response or "").strip():
        raise RuntimeError("The model returned an empty response.")


async def run_diagnostics(
    *,
    online: bool = False,
    resolve_llm: Callable[[], Any] | None = None,
    data_root: Path | None = None,
    load_rag_config: Callable[[], dict[str, Any]] | None = None,
    rag_preflight: Callable[[str], dict[str, Any]] | None = None,
    online_probe: Callable[[Any], Awaitable[None]] | None = None,
) -> DoctorReport:
    """Run setup diagnostics without network access unless ``online`` is set."""
    if resolve_llm is None:
        from deeptutor.services.config import resolve_llm_runtime_config

        resolve_llm = resolve_llm_runtime_config
    if data_root is None:
        from deeptutor.services.path_service import get_path_service

        data_root = get_path_service().get_user_root()
    if load_rag_config is None:
        from deeptutor.services.config import get_kb_config_service

        load_rag_config = get_kb_config_service().get_all_configs
    if rag_preflight is None:
        from deeptutor.services.rag.preflight import engine_preflight

        rag_preflight = engine_preflight
    if online_probe is None:
        online_probe = _probe_provider

    checks: list[DoctorCheck] = []
    config = None
    llm_ready = False
    try:
        config = resolve_llm()
        llm_checks = _llm_checks(config)
        checks.extend(llm_checks)
        llm_ready = all(check.status != "fail" for check in llm_checks if check.required)
    except Exception as exc:
        checks.append(
            DoctorCheck(
                key="llm_config",
                label="LLM configuration",
                status="fail",
                detail=f"Could not resolve active LLM settings: {_redact_error(exc, None)}",
            )
        )

    checks.append(_storage_check(data_root))
    try:
        checks.append(_rag_check(load_rag_config(), rag_preflight))
    except Exception as exc:
        checks.append(
            DoctorCheck(
                key="rag",
                label="RAG prerequisites",
                status="fail",
                detail=f"Could not inspect RAG settings: {_redact_error(exc, None)}",
                required=False,
            )
        )

    if not online:
        checks.append(
            DoctorCheck(
                key="online",
                label="Provider response",
                status="skip",
                detail="Not requested. Use --online to send a small model request.",
                required=False,
            )
        )
    elif config is None or not llm_ready:
        checks.append(
            DoctorCheck(
                key="online",
                label="Provider response",
                status="skip",
                detail="Skipped because local LLM checks failed.",
                required=False,
            )
        )
    else:
        try:
            await online_probe(config)
            checks.append(
                DoctorCheck(
                    key="online",
                    label="Provider response",
                    status="pass",
                    detail="The model returned a response.",
                )
            )
        except Exception as exc:
            checks.append(
                DoctorCheck(
                    key="online",
                    label="Provider response",
                    status="fail",
                    detail=_redact_error(exc, config),
                )
            )

    return DoctorReport(online=online, checks=checks)


__all__ = ["DoctorCheck", "DoctorReport", "run_diagnostics"]
