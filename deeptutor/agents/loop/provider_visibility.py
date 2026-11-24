"""Provider-failure copy for the agent loop (issue #2693, P0).

The loop already told the user "the provider connection was interrupted;
retrying" and, on exhaustion, "unable to reach the model provider". Both were
anonymous: no provider name, no attempt count, and no mention that the
deployment may already have an alternative configured.

This module builds those two sentences. It takes the pipeline's banner-style
``_t`` translator rather than importing i18n state, so it is testable on its
own and every capability's prompt pack can override the copy.
"""

from __future__ import annotations

from typing import Any, Callable
from urllib.parse import urlparse

from deeptutor.services.llm.error_mapping import map_error
from deeptutor.services.llm.exceptions import (
    LLMAPIError,
    LLMAuthenticationError,
    LLMError,
    LLMModelNotFoundError,
    LLMProviderError,
    LLMRateLimitError,
)

#: Capabilities without these keys in their prompt pack fall back to these.
DEFAULT_RETRY = "The model provider connection was interrupted; retrying."
DEFAULT_UNAVAILABLE = "Unable to reach the model provider. Please retry."
DEFAULT_FALLBACKS_AVAILABLE = (
    "{count} other model provider(s) are configured; this version does not "
    "switch to them automatically."
)
DEFAULT_AUTH_FAILED = "The model provider rejected the credentials ({provider})."
DEFAULT_RATE_LIMITED = "The model provider is rate-limiting or out of quota ({provider})."
DEFAULT_MODEL_MISSING = "The model provider has no such model ({provider} / {model})."
DEFAULT_SERVER_ERROR = "The model provider returned a server-side error ({provider}); retry later."
DEFAULT_PROVIDER_ERROR = "The model provider call failed ({provider}): {error}"

Translate = Callable[..., str]

#: Errors whose copy names the provider and suggests the next action. A config
#: error already says what to fix, and a parse error is not a provider outage.
_ANNOTATABLE = (LLMAPIError, LLMProviderError)


def provider_label(pipeline: Any) -> tuple[str, str]:
    """``(provider, model)`` for the turn, best-effort and never raising.

    The provider binding alone ("openai") does not tell an operator *which*
    endpoint failed, and a deployment can point several profiles at different
    gateways. The host is appended when there is one.
    """
    provider = str(getattr(pipeline, "binding", "") or "").strip() or "unknown"
    model = str(getattr(pipeline, "model", "") or "").strip()
    base_url = str(getattr(pipeline, "base_url", "") or "").strip()
    if base_url:
        try:
            host = urlparse(base_url).netloc
        except ValueError:
            host = ""
        if host and host not in provider:
            provider = f"{provider} ({host})"
    return provider, model


def retry_notice(
    translate: Translate,
    *,
    provider: str,
    model: str,
    attempt: int,
    total: int,
) -> str:
    """Sentence shown between attempts, now naming who is being retried."""
    return translate(
        "notices.provider_retry",
        default=DEFAULT_RETRY,
        provider=provider,
        model=model,
        attempt=attempt,
        total=total,
    )


def unavailable_message(
    translate: Translate,
    *,
    provider: str,
    model: str,
    attempts: int,
    fallbacks: int,
) -> str:
    """Final failure copy, with the attempt count and any configured alternative.

    ``fallbacks`` is only a count: P0 does not switch, and the sentence says so
    rather than implying a failover that does not exist yet.
    """
    message = translate(
        "notices.provider_unavailable",
        default=DEFAULT_UNAVAILABLE,
        provider=provider,
        model=model,
        attempts=attempts,
    )
    if fallbacks > 0:
        suffix = translate(
            "notices.provider_fallbacks_available",
            default=DEFAULT_FALLBACKS_AVAILABLE,
            count=fallbacks,
        )
        message = f"{message} {suffix}"
    return message.strip()


def failure_message(
    translate: Translate,
    exc: Exception,
    *,
    provider: str,
    model: str,
    fallbacks: int,
) -> str:
    """Copy for a provider failure that is *not* retried.

    Before P0 a 401/429/502 surfaced as the SDK's raw text ("Error code: 502"),
    with no provider, no cause and no hint that an alternative is configured.
    """
    status = getattr(exc, "status_code", None)
    if isinstance(exc, LLMRateLimitError):
        message = translate(
            "notices.provider_rate_limited",
            default=DEFAULT_RATE_LIMITED,
            provider=provider,
            model=model,
        )
    elif isinstance(exc, LLMAuthenticationError):
        message = translate(
            "notices.provider_auth_failed",
            default=DEFAULT_AUTH_FAILED,
            provider=provider,
            model=model,
        )
    elif isinstance(exc, LLMModelNotFoundError):
        message = translate(
            "notices.provider_model_missing",
            default=DEFAULT_MODEL_MISSING,
            provider=provider,
            model=model,
        )
    elif isinstance(status, int) and status >= 500:
        message = translate(
            "notices.provider_server_error",
            default=DEFAULT_SERVER_ERROR,
            provider=provider,
            model=model,
        )
    else:
        message = translate(
            "notices.provider_error",
            default=DEFAULT_PROVIDER_ERROR,
            provider=provider,
            model=model,
            error=str(exc),
        )
    if fallbacks > 0:
        suffix = translate(
            "notices.provider_fallbacks_available",
            default=DEFAULT_FALLBACKS_AVAILABLE,
            count=fallbacks,
        )
        message = f"{message} {suffix}"
    return message.strip()


def _looks_like_provider_error(exc: Exception) -> bool:
    """Whether *exc* is worth rewriting as a provider failure.

    ``map_error`` turns anything into an ``LLMError``, so without this a bug in
    our own code ("not a provider problem") would be relabelled as a model
    outage and hide the real stack.
    """
    if isinstance(exc, LLMError):
        return isinstance(exc, _ANNOTATABLE)
    if getattr(exc, "status_code", None) is not None:
        return True
    module = type(exc).__module__ or ""
    return module.startswith(("openai", "anthropic", "httpx", "httpcore"))


def annotate_provider_failure(
    exc: Exception,
    translate: Translate,
    *,
    provider: str,
    model: str,
    fallbacks: int,
) -> Exception:
    """Attach the readable copy to a provider error, keeping its classification.

    ``map_error`` returns the caller's own exception when it is already an
    ``LLMError``, so the retry flags and error code downstream callers branch on
    are preserved; only the human-readable message is replaced.
    """
    if not _looks_like_provider_error(exc):
        return exc
    try:
        typed = map_error(exc, provider=provider)
    except Exception:  # pragma: no cover - mapping must never mask the failure
        return exc
    if not isinstance(typed, _ANNOTATABLE):
        return exc
    typed.message = failure_message(
        translate,
        typed,
        provider=provider,
        model=model,
        fallbacks=fallbacks,
    )
    return typed


__all__ = [
    "DEFAULT_AUTH_FAILED",
    "DEFAULT_FALLBACKS_AVAILABLE",
    "DEFAULT_MODEL_MISSING",
    "DEFAULT_PROVIDER_ERROR",
    "DEFAULT_RATE_LIMITED",
    "DEFAULT_RETRY",
    "DEFAULT_SERVER_ERROR",
    "DEFAULT_UNAVAILABLE",
    "annotate_provider_failure",
    "failure_message",
    "provider_label",
    "retry_notice",
    "unavailable_message",
]
