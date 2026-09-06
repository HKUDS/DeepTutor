"""Immutable model identity for native LightRAG indexing writes."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

from deeptutor.multi_user.context import get_current_user, get_current_user_or_none
from deeptutor.multi_user.model_access import (
    OWNER_BOUND_BINDINGS,
    apply_allowed_llm_selection,
)
from deeptutor.multi_user.models import CurrentUser
from deeptutor.services.llm.capabilities import supports_vision
from deeptutor.services.llm.config import LLMConfig
from deeptutor.services.llm.exceptions import LLMConfigError
from deeptutor.services.model_selection.llm import LLMSelection
from deeptutor.services.model_selection.runtime import resolve_llm_config_for_selection

POLICY_PINNED = "pinned"
POLICY_PENDING = "pending_pinned"
POLICY_LEGACY = "legacy_unpinned"


class IndexingPolicyError(RuntimeError):
    """A pinned model can no longer be used without changing index identity."""

    code = "indexing_model_unavailable"
    retryable = False


class IndexingModelChangedError(IndexingPolicyError):
    """The selected catalog entry no longer matches the published fingerprint."""

    code = "reindex_required"


def _endpoint_identity(value: str | None) -> str:
    if not value:
        return ""
    parsed = urlsplit(value)
    host = parsed.hostname or ""
    if parsed.port is not None:
        host = f"{host}:{parsed.port}"
    return urlunsplit((parsed.scheme.lower(), host.lower(), parsed.path.rstrip("/"), "", ""))


def _canonical_identity(
    selection: LLMSelection | None,
    config: LLMConfig,
    *,
    vision_available: bool | None = None,
) -> dict[str, Any]:
    identity = {
        "binding": config.binding,
        "provider_mode": config.provider_mode,
        "endpoint": _endpoint_identity(config.effective_url or config.base_url),
        "api_version": config.api_version or None,
        "model": config.model,
        "reasoning_effort": config.reasoning_effort,
    }
    if selection is not None:
        identity["profile_id"] = selection.profile_id
        identity["model_id"] = selection.model_id
    if vision_available is not None:
        identity["vision_available"] = vision_available
    return identity


def _fingerprint(identity: dict[str, Any]) -> str:
    encoded = json.dumps(identity, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


@dataclass(frozen=True, slots=True)
class IndexingLLMSnapshot:
    config: LLMConfig
    owner: CurrentUser
    policy: str
    selection: LLMSelection | None
    descriptor: dict[str, Any]
    fingerprint: str | None
    vision_available: bool

    def persisted_policy(self) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "policy": self.policy,
            "descriptor": self.descriptor,
            "fingerprint": self.fingerprint,
            "vision_available": self.vision_available,
        }
        if self.selection is not None:
            payload["selection"] = self.selection.to_dict()
        return payload


def freeze_snapshot(
    selection_value: Any = None,
    *,
    policy: str | None = None,
    require_explicit_user: bool = True,
) -> IndexingLLMSnapshot:
    """Resolve and freeze one access-checked indexing model in the caller scope."""
    selection = LLMSelection.from_payload(selection_value)
    explicit_user = get_current_user_or_none()
    if selection is not None and explicit_user is None and require_explicit_user:
        raise IndexingPolicyError(
            "Pinned indexing models require an explicit initiating user scope."
        )
    try:
        if selection is not None:
            apply_allowed_llm_selection(selection.to_dict())
        config = resolve_llm_config_for_selection(selection)
    except (LLMConfigError, PermissionError, ValueError) as exc:
        raise IndexingPolicyError(str(exc)) from exc

    if config.binding in OWNER_BOUND_BINDINGS and explicit_user is None:
        raise IndexingPolicyError(
            "Owner-bound indexing models require an explicit initiating user scope."
        )
    owner = explicit_user or get_current_user()
    resolved_policy = policy or (POLICY_PINNED if selection is not None else POLICY_LEGACY)
    vision_available = supports_vision(config.binding, config.model)
    if resolved_policy == POLICY_LEGACY:
        descriptor = {
            "model": config.model,
            "binding": config.binding,
            "reasoning_effort": config.reasoning_effort,
        }
        fingerprint = None
    else:
        identity = _canonical_identity(
            selection,
            config,
            vision_available=vision_available,
        )
        descriptor = identity
        fingerprint = _fingerprint(identity)
    return IndexingLLMSnapshot(
        config=config,
        owner=owner,
        policy=resolved_policy,
        selection=None if resolved_policy == POLICY_LEGACY else selection,
        descriptor=descriptor,
        fingerprint=fingerprint,
        vision_available=vision_available,
    )


def pending_policy_for_selection(selection_value: Any) -> dict[str, Any]:
    snapshot = freeze_snapshot(selection_value, policy=POLICY_PENDING)
    return snapshot.persisted_policy()


def _active_catalog_selection() -> dict[str, str] | None:
    from deeptutor.services.config import get_model_catalog_service

    catalog = get_model_catalog_service().load()
    service = catalog.get("services", {}).get("llm", {})
    profile_id = str(service.get("active_profile_id") or "").strip()
    model_id = str(service.get("active_model_id") or "").strip()
    if not profile_id or not model_id:
        return None
    return {"profile_id": profile_id, "model_id": model_id}


def freeze_default_snapshot() -> IndexingLLMSnapshot:
    """Freeze the released LightRAG model, or the active model when it is unset."""
    from .config import lightrag_indexing_selection_from_settings

    try:
        selection = lightrag_indexing_selection_from_settings()
    except Exception as exc:
        raise IndexingPolicyError(
            "The LightRAG indexing-model setting could not be resolved."
        ) from exc
    if selection is None:
        selection = _active_catalog_selection()
    return freeze_snapshot(
        selection,
        policy=POLICY_PINNED,
        require_explicit_user=False,
    )


def snapshot_from_persisted(policy: dict[str, Any]) -> IndexingLLMSnapshot:
    selection = policy.get("selection")
    if selection is not None and not isinstance(selection, dict):
        raise IndexingPolicyError("Pinned LightRAG metadata has an invalid model selection.")
    snapshot = freeze_snapshot(selection, policy=POLICY_PINNED)
    expected = str(policy.get("fingerprint") or "")
    if not expected or snapshot.fingerprint != expected:
        raise IndexingModelChangedError(
            "The pinned LightRAG indexing model changed; run a full re-index to publish "
            "the new model identity."
        )
    return snapshot


def effective_policy(kb_dir: Path, *, base_dir: str, kb_name: str) -> dict[str, Any] | None:
    """Return published policy first, then pre-publication pending policy."""
    from .storage import latest_published_root, read_published_policy

    root = latest_published_root(kb_dir)
    published = read_published_policy(root)
    if published is not None:
        return published

    from deeptutor.knowledge.manager import KnowledgeBaseManager

    manager = KnowledgeBaseManager(base_dir=base_dir)
    entry = manager.config.get("knowledge_bases", {}).get(kb_name) or {}
    pending = entry.get("pending_indexing_policy")
    return pending if isinstance(pending, dict) else None


def resolve_write_snapshot(
    kb_dir: Path,
    *,
    base_dir: str,
    kb_name: str,
    explicit: IndexingLLMSnapshot | None = None,
) -> IndexingLLMSnapshot:
    if explicit is not None:
        return explicit
    policy = effective_policy(kb_dir, base_dir=base_dir, kb_name=kb_name)
    if policy is None:
        return freeze_default_snapshot()
    if policy.get("policy") == POLICY_LEGACY:
        raise IndexingModelChangedError(
            "This LightRAG index has no verified indexing model; run a full re-index "
            "before appending documents."
        )
    return snapshot_from_persisted(policy)


def cache_identity(snapshot: IndexingLLMSnapshot) -> str:
    if snapshot.fingerprint:
        return snapshot.fingerprint
    identity = {
        "binding": snapshot.config.binding,
        "provider_mode": snapshot.config.provider_mode,
        "endpoint": _endpoint_identity(snapshot.config.effective_url or snapshot.config.base_url),
        "model": snapshot.config.model,
        "reasoning_effort": snapshot.config.reasoning_effort,
    }
    return _fingerprint(identity)


def cache_identity_for_config(config: LLMConfig) -> str:
    """Return a credential-free cache identity for a resolved query model."""
    return _fingerprint(_canonical_identity(None, config))


__all__ = [
    "IndexingLLMSnapshot",
    "IndexingModelChangedError",
    "IndexingPolicyError",
    "POLICY_LEGACY",
    "POLICY_PENDING",
    "POLICY_PINNED",
    "cache_identity",
    "cache_identity_for_config",
    "effective_policy",
    "freeze_default_snapshot",
    "freeze_snapshot",
    "pending_policy_for_selection",
    "resolve_write_snapshot",
    "snapshot_from_persisted",
]
