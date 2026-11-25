"""Ordered provider fallback with cooldown-based failback (issue #2693).

Scope of this module:

* one ordered candidate list per request — the active model first, then the
  ``services.llm.fallbacks`` entries from the catalog;
* a process-local health registry that cools a candidate down instead of
  removing it, so the primary is retried as soon as its cooldown expires
  (that retry *is* the failback: there is no separate probe);
* the two call shapes DeepTutor uses: a whole-response call (services layer) and
  a streaming call (agent loop, which advances after a pre-output failure);
* message preparation for a different provider: foreign replay state is
  dropped, and the candidate's own context window is respected.

What this module deliberately does not do: switch after visible output, replay
a dispatched tool call, or share cooldowns across processes.
"""

from __future__ import annotations

from dataclasses import dataclass
import threading
import time
from typing import Any, Awaitable, Callable, Sequence

from deeptutor.services.llm.config import LLMConfig
from deeptutor.services.llm.exceptions import (
    LLMAuthenticationError,
    LLMModelNotFoundError,
    LLMRateLimitError,
)
from deeptutor.services.llm.request_compat import is_transient_transport_error

#: Mirrors the catalog validation bound (four *fallbacks*). The chain itself is
#: the primary plus those, so five entries — the bound that keeps a failure
#: from multiplying the retry budget.
MAX_CANDIDATES = 5

#: Cooldowns. Rate limits honour their own hint; transport failures get a short
#: cooldown because they are often a blip; consecutive failures escalate.
RATE_LIMIT_COOLDOWN_S = 60.0
TRANSPORT_COOLDOWN_S = 30.0
COOLDOWN_LADDER_S = (60.0, 300.0, 900.0)

#: Trace metadata contract for a switch, so the loop/UI can render one notice.
SwitchHook = Callable[["SwitchReport"], Awaitable[None]]


@dataclass(frozen=True, slots=True)
class Candidate:
    """One ``(profile, model)`` the request may run on."""

    profile_id: str
    model_id: str
    config: LLMConfig

    @property
    def key(self) -> tuple[str, str]:
        return (self.profile_id, self.model_id)

    @property
    def label(self) -> str:
        provider = getattr(self.config, "provider_name", "") or self.profile_id
        model = getattr(self.config, "model", "") or self.model_id
        return f"{provider} / {model}"


@dataclass(frozen=True, slots=True)
class SwitchReport:
    """Why a request moved on, and where to."""

    failed: Candidate
    next_candidate: Candidate | None
    reason: str
    error: str


@dataclass(slots=True)
class _Health:
    state: str = "closed"  # closed | cooling | disabled
    until: float = 0.0
    failures: int = 0


class ProviderHealthRegistry:
    """Process-local cooldown table, keyed by owner and candidate.

    Keyed by owner because a per-user API key that runs out of quota must not
    cool the same profile down for everybody else.
    """

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._lock = threading.Lock()
        self._health: dict[tuple[str, str, str], _Health] = {}

    def _key(self, owner: str, candidate: Candidate) -> tuple[str, str, str]:
        return (owner, candidate.profile_id, candidate.model_id)

    def is_available(self, owner: str, candidate: Candidate) -> bool:
        with self._lock:
            health = self._health.get(self._key(owner, candidate))
            if health is None:
                return True
            if health.state == "closed":
                return True
            if health.state == "cooling" and health.until <= self._clock():
                # Cooldown over: the next request tries this candidate again,
                # which is the failback. Failures are only cleared on success.
                return True
            return False

    def record_failure(self, owner: str, candidate: Candidate, exc: Exception) -> str:
        """Record a failure and return the reason used for the switch notice."""
        reason = classify_error(exc)
        with self._lock:
            health = self._health.setdefault(self._key(owner, candidate), _Health())
            health.failures += 1
            if reason in {"auth", "model_missing"}:
                # Retrying cannot help until the operator edits the profile.
                health.state = "disabled"
                health.until = 0.0
            elif reason == "rate_limit":
                hint = getattr(exc, "retry_after", None)
                cooldown = float(hint) if hint else _ladder(health.failures, RATE_LIMIT_COOLDOWN_S)
                health.state = "cooling"
                health.until = self._clock() + cooldown
            else:
                cooldown = _ladder(health.failures, TRANSPORT_COOLDOWN_S)
                health.state = "cooling"
                health.until = self._clock() + cooldown
        return reason

    def record_success(self, owner: str, candidate: Candidate) -> None:
        with self._lock:
            self._health.pop(self._key(owner, candidate), None)

    def state_for(self, owner: str, candidate: Candidate) -> str:
        with self._lock:
            health = self._health.get(self._key(owner, candidate))
            if health is None:
                return "closed"
            if health.state == "cooling" and health.until <= self._clock():
                return "closed"
            return health.state

    def reset(self) -> None:
        with self._lock:
            self._health.clear()


def _ladder(failures: int, first: float) -> float:
    """Escalate 60s → 5min → 15min so a flapping primary cannot ping-pong."""
    if failures <= 1:
        return first
    index = min(failures - 1, len(COOLDOWN_LADDER_S) - 1)
    return max(first, COOLDOWN_LADDER_S[index])


REGISTRY = ProviderHealthRegistry()


def classify_error(exc: Exception) -> str:
    """Bucket an exception for the cooldown table."""
    if isinstance(exc, LLMRateLimitError):
        return "rate_limit"
    if isinstance(exc, LLMAuthenticationError):
        return "auth"
    if isinstance(exc, LLMModelNotFoundError):
        return "model_missing"
    status = getattr(exc, "status_code", None)
    if isinstance(status, int) and status >= 500:
        return "server"
    if is_transient_transport_error(exc):
        return "transport"
    return "other"


def is_switchable(exc: Exception) -> bool:
    """Whether moving to the next candidate could plausibly help."""
    # Partial output already reached the user: replaying it on another provider
    # would splice two answers together.
    if getattr(exc, "partial_response", False):
        return False
    return classify_error(exc) != "other"


def current_owner() -> str:
    """The account a request is charged to, for per-owner cooldowns."""
    try:
        from deeptutor.multi_user.context import get_current_user

        return str(get_current_user().id or "anonymous")
    except Exception:
        return "anonymous"


def chain_configured() -> bool:
    """Whether the catalog declares at least one fallback (cheap check)."""
    try:
        from deeptutor.services.config import get_model_catalog_service
        from deeptutor.services.model_selection.fallbacks import configured_fallbacks

        return bool(configured_fallbacks(get_model_catalog_service().load()))
    except Exception:
        return False


def chain_from_config(config: Any, owner_id: str = "anonymous") -> list[Candidate]:
    """Chain for a caller that already resolved its own config (task models).

    The explicit config stays the primary: `factory.complete(config=...)` may be
    running a task model, and re-resolving the catalog's active LLM there would
    silently swap the model the caller asked for.
    """
    from deeptutor.services.model_selection.fallbacks import configured_fallbacks
    from deeptutor.services.model_selection.runtime import resolve_llm_config_for_selection

    primary = Candidate(
        str(getattr(config, "provider_name", "primary")),
        str(getattr(config, "model", "model")),
        config,
    )
    candidates = [primary]
    for entry in configured_fallbacks():
        try:
            resolved = resolve_llm_config_for_selection(
                {"profile_id": entry["profile_id"], "model_id": entry["model_id"]}
            )
        except Exception:
            continue
        candidates.append(Candidate(entry["profile_id"], entry["model_id"], resolved))
        if len(candidates) >= MAX_CANDIDATES:
            break
    return candidates


def resolve_candidates(owner_id: str = "anonymous") -> list[Candidate]:
    """The ordered chain for this request: active model, then declared fallbacks.

    Unresolvable entries are dropped (a deleted profile must not take the turn
    down); the active model is always first so the primary is retried as soon as
    its cooldown expires.
    """
    from deeptutor.services.config import get_model_catalog_service
    from deeptutor.services.model_selection.fallbacks import configured_fallbacks
    from deeptutor.services.model_selection.runtime import resolve_llm_config_for_selection

    try:
        catalog = get_model_catalog_service().load()
    except Exception:
        return []
    services = catalog.get("services") if isinstance(catalog, dict) else None
    llm = services.get("llm") if isinstance(services, dict) else None
    if not isinstance(llm, dict):
        return []

    candidates: list[Candidate] = []
    seen: set[tuple[str, str]] = set()
    for entry in active_and_declared(llm, configured_fallbacks(catalog)):
        key = (entry["profile_id"], entry["model_id"])
        if key in seen:
            continue
        seen.add(key)
        try:
            config = resolve_llm_config_for_selection(
                {"profile_id": entry["profile_id"], "model_id": entry["model_id"]}
            )
        except Exception:
            continue
        candidates.append(Candidate(entry["profile_id"], entry["model_id"], config))
        if len(candidates) >= MAX_CANDIDATES:
            break
    return candidates


def active_and_declared(
    llm: dict[str, Any], declared: Sequence[dict[str, str]]
) -> list[dict[str, str]]:
    """Active model first, then the declared fallbacks, as plain selections."""
    entries: list[dict[str, str]] = []
    active_profile = str(llm.get("active_profile_id") or "").strip()
    active_model = str(llm.get("active_model_id") or "").strip()
    if active_profile and active_model:
        entries.append({"profile_id": active_profile, "model_id": active_model})
    entries.extend(declared)
    seen: set[tuple[str, str]] = set()
    unique: list[dict[str, str]] = []
    for entry in entries:
        key = (entry["profile_id"], entry["model_id"])
        if key in seen:
            continue
        seen.add(key)
        unique.append(entry)
    return unique


def non_cooling(candidates: Sequence[Candidate], owner_id: str) -> list[Candidate]:
    """Candidates worth trying now, primary first."""
    return [item for item in candidates if REGISTRY.is_available(owner_id, item)]


def drop_foreign_message_state(messages: Sequence[dict[str, Any]]) -> list[dict[str, Any]]:
    """Copy messages without provider-private replay state.

    `reasoning_content` (DeepSeek thinking) and `thinking_blocks` (Anthropic
    signatures) only mean something to the provider that produced them; a
    Responses-API gateway's `_provider_response_state` is even stricter.
    """
    private = {
        "thinking_blocks",
        "_provider_response_state",
        "_responses_output_items",
        "provider_specific_fields",
    }
    cleaned: list[dict[str, Any]] = []
    for message in messages:
        if not isinstance(message, dict):
            continue
        cleaned.append({key: value for key, value in message.items() if key not in private})
    return cleaned


async def call_with_failover(
    call: Callable[[Candidate], Awaitable[Any]],
    *,
    owner_id: str = "anonymous",
    on_switch: SwitchHook | None = None,
    candidates: Sequence[Candidate] | None = None,
) -> Any:
    """Run ``call`` against the first healthy candidate, switching on failure.

    The candidate that raised is cooled down; the next request starts from the
    primary again (that is the failback). Raises the last error when every
    candidate is exhausted, after reporting each switch.
    """
    chain = list(candidates) if candidates is not None else resolve_candidates(owner_id)
    if not chain:
        raise RuntimeError("No LLM candidate is configured")

    last_error: Exception | None = None
    attempted: list[str] = []
    for index, candidate in enumerate(chain):
        attempted.append(candidate.label)
        if not REGISTRY.is_available(owner_id, candidate):
            continue
        try:
            result = await call(candidate)
        except Exception as exc:  # noqa: BLE001 - re-raised below when fatal
            if not is_switchable(exc):
                raise
            last_error = exc
            reason = REGISTRY.record_failure(owner_id, candidate, exc)
            if on_switch is not None:
                await on_switch(
                    SwitchReport(
                        failed=candidate,
                        next_candidate=_next_candidate(chain, index + 1, owner_id),
                        reason=reason,
                        error=str(exc)[:300],
                    )
                )
            continue
        REGISTRY.record_success(owner_id, candidate)
        return result

    raise AllProvidersUnavailable(attempted, last_error)


def _next_candidate(candidates: Sequence[Candidate], start: int, owner_id: str) -> Candidate | None:
    for candidate in candidates[start:]:
        if REGISTRY.is_available(owner_id, candidate):
            return candidate
    return None


class AllProvidersUnavailable(RuntimeError):
    """Every candidate failed or is cooling down."""

    def __init__(self, attempted: Sequence[str], last_error: Exception | None) -> None:
        self.attempted = list(attempted)
        self.last_error = last_error
        detail = "; ".join(self.attempted) or "none"
        super().__init__(
            f"All model providers are unavailable (attempted: {detail}). "
            f"Last error: {last_error or 'cooling down'}"
        )


__all__ = [
    "AllProvidersUnavailable",
    "COOLDOWN_LADDER_S",
    "Candidate",
    "MAX_CANDIDATES",
    "ProviderHealthRegistry",
    "REGISTRY",
    "SwitchReport",
    "active_and_declared",
    "chain_from_config",
    "call_with_failover",
    "classify_error",
    "drop_foreign_message_state",
    "is_switchable",
    "non_cooling",
    "resolve_candidates",
]
