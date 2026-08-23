"""Fork-local, neutral extension point for optional Kids reward packages.

Core Kids emits only the learning facts declared by ``KidsRewardEvent``. A
provider owns its rules, copy, persistence, and idempotency; no provider ships
with the core application.
"""

from __future__ import annotations

from hashlib import sha256
import logging
import time
from typing import Any, Literal, Protocol

from pydantic import BaseModel, Field

from deeptutor.core.entry_points import load_entry_point_group

logger = logging.getLogger(__name__)

ENTRY_POINT_GROUP = "deeptutor.kids_reward_providers"
ENTRY_POINT_SCOPE = "fork-local"


class KidsRewardEvent(BaseModel):
    """The complete set of learning facts exposed to a reward provider."""

    event_id: str
    profile_id: str
    content_type: Literal["reading", "interactive_book"]
    content_id: str
    item_id: str
    kind: Literal["quiz_submitted", "section_completed"]
    score: int = Field(ge=0)
    total: int = Field(ge=0)
    completed: bool = False
    occurred_at: float = Field(default_factory=time.time)


class KidsRewardDisplayItem(BaseModel):
    provider_label: str
    value: str = ""
    detail: str = ""


class RewardSnapshot(BaseModel):
    provider: str
    title: str
    message: str
    items: list[KidsRewardDisplayItem] = Field(default_factory=list, max_length=20)


class KidsRewardProvider(Protocol):
    name: str
    version: str

    def record(self, event: KidsRewardEvent) -> RewardSnapshot | None:
        """Record an event using provider-owned persistence and idempotency."""
        ...

    def snapshot(self, profile_id: str) -> RewardSnapshot | None:
        """Return the child-safe display snapshot for a profile."""
        ...

    def content_totals(self, profile_id: str) -> dict[str, int] | None:
        """Optionally return provider-owned totals keyed by ``type:id``."""
        ...


def build_kids_reward_event(
    *,
    profile_id: str,
    content_type: Literal["reading", "interactive_book"],
    content_id: str,
    item_id: str,
    kind: Literal["quiz_submitted", "section_completed"],
    score: int,
    total: int,
    completed: bool,
) -> KidsRewardEvent:
    """Build a stable event id so identical submissions are replayable."""
    identity = "|".join(
        [
            profile_id,
            content_type,
            content_id,
            item_id,
            kind,
            str(score),
            str(total),
            str(completed),
        ]
    )
    return KidsRewardEvent(
        event_id=sha256(identity.encode()).hexdigest(),
        profile_id=profile_id,
        content_type=content_type,
        content_id=content_id,
        item_id=item_id,
        kind=kind,
        score=score,
        total=total,
        completed=completed,
    )


def _coerce_provider(name: str, loaded: Any) -> Any | None:
    candidate = loaded() if callable(loaded) else loaded
    required = ("name", "version", "record", "snapshot")
    if not all(hasattr(candidate, attr) for attr in required):
        logger.warning("Kids reward entry point %r does not implement the provider contract.", name)
        return None
    if not isinstance(candidate.name, str) or not candidate.name.strip():
        logger.warning("Kids reward entry point %r returned an invalid provider name.", name)
        return None
    if not isinstance(candidate.version, str) or not candidate.version.strip():
        logger.warning("Kids reward entry point %r returned an invalid provider version.", name)
        return None
    return candidate


def discover_kids_reward_providers() -> list[Any]:
    providers = load_entry_point_group(ENTRY_POINT_GROUP, _coerce_provider, log=logger)
    return sorted(providers, key=lambda provider: provider.name)


_provider_cache: list[Any] | None = None
_inactive_providers_logged = False


def get_kids_reward_providers(*, refresh: bool = False) -> list[Any]:
    global _provider_cache
    if _provider_cache is None or refresh:
        _provider_cache = discover_kids_reward_providers()
    return _provider_cache


def active_kids_reward_provider() -> Any | None:
    global _inactive_providers_logged
    providers = get_kids_reward_providers()
    if len(providers) > 1 and not _inactive_providers_logged:
        inactive = ", ".join(provider.name for provider in providers[1:])
        logger.info("Kids reward providers not enabled: %s", inactive)
        _inactive_providers_logged = True
    return providers[0] if providers else None


def _coerce_snapshot(value: Any) -> RewardSnapshot | None:
    if value is None:
        return None
    if isinstance(value, RewardSnapshot):
        return value
    if isinstance(value, dict):
        return RewardSnapshot.model_validate(value)
    raise TypeError("A reward provider must return RewardSnapshot, a mapping, or None")


def record_kids_reward_event(event: KidsRewardEvent) -> RewardSnapshot | None:
    provider = active_kids_reward_provider()
    if provider is None:
        return None
    try:
        return _coerce_snapshot(provider.record(event))
    except Exception:
        logger.warning(
            "Kids reward provider %r failed to record an event.", provider.name, exc_info=True
        )
        return None


def kids_reward_snapshot(profile_id: str) -> RewardSnapshot | None:
    provider = active_kids_reward_provider()
    if provider is None:
        return None
    try:
        return _coerce_snapshot(provider.snapshot(profile_id))
    except Exception:
        logger.warning(
            "Kids reward provider %r failed to load a snapshot.", provider.name, exc_info=True
        )
        return None


def kids_reward_content_totals(profile_id: str) -> dict[str, int]:
    """Return per-content reward totals for legacy library clients."""
    provider = active_kids_reward_provider()
    if provider is None:
        return {}
    content_totals = getattr(provider, "content_totals", None)
    if not callable(content_totals):
        return {}
    try:
        value = content_totals(profile_id)
    except Exception:
        logger.warning(
            "Kids reward provider %r failed to load content totals.",
            provider.name,
            exc_info=True,
        )
        return {}
    if not isinstance(value, dict):
        return {}

    totals: dict[str, int] = {}
    for content_key, stars in value.items():
        if not isinstance(content_key, str) or not content_key:
            continue
        try:
            normalized = int(stars)
        except (TypeError, ValueError):
            continue
        if normalized >= 0:
            totals[content_key] = normalized
    return totals


def reset_kids_reward_provider_cache_for_tests() -> None:
    global _inactive_providers_logged, _provider_cache
    _provider_cache = None
    _inactive_providers_logged = False
