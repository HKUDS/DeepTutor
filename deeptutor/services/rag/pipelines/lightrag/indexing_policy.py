"""Immutable model identity for native LightRAG indexing writes."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field, replace
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
    return freeze_roles(selection_value, policy=POLICY_PENDING).persisted_policy()


def _active_catalog_selection() -> dict[str, str] | None:
    from deeptutor.services.config import get_model_catalog_service

    catalog = get_model_catalog_service().load()
    service = catalog.get("services", {}).get("llm", {})
    profile_id = str(service.get("active_profile_id") or "").strip()
    model_id = str(service.get("active_model_id") or "").strip()
    if not profile_id or not model_id:
        return None
    return {"profile_id": profile_id, "model_id": model_id}


def _freeze_legacy_default_snapshot() -> IndexingLLMSnapshot:
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


def _single_snapshot_from_persisted(policy: dict[str, Any]) -> IndexingLLMSnapshot:
    if type(policy.get("vision_available")) is not bool:
        raise IndexingModelChangedError(
            "The historical vision capability is unknown; run a full re-index."
        )
    selection = policy.get("selection")
    if not isinstance(selection, dict):
        raise IndexingPolicyError("Pinned LightRAG metadata has an invalid model selection.")
    snapshot = freeze_snapshot(selection, policy=POLICY_PINNED)
    expected = str(policy.get("fingerprint") or "")
    if not expected or snapshot.fingerprint != expected:
        raise IndexingModelChangedError(
            "The pinned LightRAG indexing model changed; run a full re-index to publish "
            "the new model identity."
        )
    return snapshot


@dataclass(frozen=True, slots=True)
class IndexingPolicySnapshot:
    """Freeze role identities, runtime limits, and accepted indexing target state."""

    extract: IndexingLLMSnapshot
    vlm: IndexingLLMSnapshot | None
    policy: str = POLICY_PINNED
    limits: dict[str, dict[str, int]] = field(default_factory=dict)
    legacy_policy: dict[str, Any] | None = None
    target_version: str | None = None
    target_bound: bool = False
    target_policy: str | None = None
    image_analysis: bool | None = None
    target_revision: str | None = None
    embedding_config: Any | None = field(default=None, repr=False, compare=False)

    @property
    def vision_available(self) -> bool:
        """Return whether the pinned vision model supports image inputs."""
        return self.vlm is not None and self.vlm.vision_available

    def persisted_policy(self) -> dict[str, Any]:
        """Serialize role identities while preserving an existing legacy policy."""
        if self.legacy_policy is not None:
            # Appending must not rewrite the old fingerprint as a v2 identity.
            return dict(self.legacy_policy)
        return {
            "schema_version": 2,
            "policy": self.policy,
            "extract": self.extract.persisted_policy(),
            "vlm": {
                "mode": "enabled" if self.vlm else "disabled",
                **({"snapshot": self.vlm.persisted_policy()} if self.vlm else {}),
            },
        }


def _role_identity(snapshot: IndexingLLMSnapshot, *, vision: bool) -> dict[str, Any]:
    config = snapshot.config
    return {
        **_canonical_identity(
            snapshot.selection,
            config,
            vision_available=snapshot.vision_available if vision else None,
        ),
        "wire_api": config.wire_api,
        "api_format": config.api_format,
        "context_window": config.context_window,
    }


def _with_role_identity(snapshot: IndexingLLMSnapshot, *, vision: bool) -> IndexingLLMSnapshot:
    snapshot = replace(
        snapshot,
        selection=replace(snapshot.selection, reasoning_effort=snapshot.config.reasoning_effort),
    )
    identity = _role_identity(snapshot, vision=vision)
    return replace(snapshot, descriptor=identity, fingerprint=_fingerprint(identity))


def _freeze_role(
    selection_value: Any, *, vision: bool = False, provider_default: bool = True
) -> IndexingLLMSnapshot:
    from deeptutor.services.config.lightrag_roles import LightRagModelSelection

    from .roles import resolve_selection

    if isinstance(selection_value, LLMSelection):
        selection_value = selection_value.to_dict()
    selected = LightRagModelSelection.model_validate(selection_value)
    selection = LLMSelection(**selected.model_dump())
    try:
        config = resolve_selection(selection, vision=vision, provider_default=provider_default)
    except (ValueError, PermissionError, LLMConfigError) as exc:
        raise IndexingPolicyError(str(exc)) from exc
    explicit_user = get_current_user_or_none()
    if config.binding in OWNER_BOUND_BINDINGS and explicit_user is None:
        raise IndexingPolicyError(
            "Owner-bound indexing models require an explicit initiating user scope."
        )
    snapshot = IndexingLLMSnapshot(
        config=config,
        owner=explicit_user or get_current_user(),
        policy=POLICY_PINNED,
        selection=replace(selection, reasoning_effort=config.reasoning_effort),
        descriptor={},
        fingerprint=None,
        vision_available=supports_vision(config.binding, config.model),
    )
    return _with_role_identity(snapshot, vision=vision)


def freeze_roles(
    selection_value: Any = None, *, policy: str = POLICY_PINNED
) -> IndexingPolicySnapshot:
    """Freeze create/rebuild choices; old request bodies still mean one model."""
    from deeptutor.services.config import load_lightrag_settings
    from deeptutor.services.config.lightrag_roles import LightRagIndexingSelection

    from .roles import runtime_limits, settings_models

    settings = load_lightrag_settings()
    models = settings_models(settings)
    limits = runtime_limits(settings)
    if selection_value is None and models is None and settings.get("version") == 2:
        raise IndexingPolicyError("Choose a LightRAG base model or explicit indexing models first.")
    if selection_value is None and models is not None:
        extract_selection = models.selection_for("extract").model_dump()
        vlm_selection = models.selection_for("vlm")
        value = {
            "extract": extract_selection,
            "vlm": {"mode": "enabled", "selection": vlm_selection.model_dump()}
            if vlm_selection
            else {"mode": "disabled"},
        }
    elif (
        selection_value is not None
        and isinstance(selection_value, dict)
        and "extract" in selection_value
    ):
        value = selection_value
    else:
        # Supported v1 settings and form producer: freeze the one known model,
        # including its known vision capability, before constructing v2 roles.
        single = (
            freeze_snapshot(selection_value, policy=POLICY_PINNED)
            if selection_value is not None
            else _freeze_legacy_default_snapshot()
        )
        if single.selection is None:
            raise IndexingPolicyError("Choose a catalog model before creating a LightRAG index.")
        selected = single.selection.to_dict()
        value = {
            "extract": selected,
            "vlm": {"mode": "enabled", "selection": selected}
            if single.vision_available and settings.get("version") != 2
            else {"mode": "disabled"},
        }
    parsed = LightRagIndexingSelection.model_validate(value)
    extract = _freeze_role(parsed.extract.model_dump())
    vlm = (
        _freeze_role(parsed.vlm.selection.model_dump(), vision=True)
        if parsed.vlm.selection
        else None
    )
    return IndexingPolicySnapshot(extract, vlm, policy=policy, limits=limits)


def freeze_default_snapshot() -> IndexingPolicySnapshot:
    return freeze_roles()


def snapshot_from_persisted(policy: dict[str, Any]) -> IndexingPolicySnapshot:
    from deeptutor.services.config import load_lightrag_settings

    from .roles import runtime_limits

    if not isinstance(policy, dict) or policy.get("policy") not in {POLICY_PINNED, POLICY_PENDING}:
        raise IndexingModelChangedError(
            "The index has no verified model policy; run a full re-index."
        )
    limits = runtime_limits(load_lightrag_settings())
    if "schema_version" not in policy:
        single = _single_snapshot_from_persisted(policy)
        if policy["policy"] == POLICY_PENDING:
            return IndexingPolicySnapshot(
                _with_role_identity(single, vision=False),
                _with_role_identity(single, vision=True) if single.vision_available else None,
                policy=POLICY_PENDING,
                limits=limits,
            )
        return IndexingPolicySnapshot(
            single,
            single if single.vision_available else None,
            policy=policy["policy"],
            limits=limits,
            legacy_policy=dict(policy),
        )
    if type(policy["schema_version"]) is not int or policy["schema_version"] != 2:
        raise IndexingPolicyError("Unsupported LightRAG indexing-policy version.")
    vision = policy.get("vlm")
    if not isinstance(vision, dict) or vision.get("mode") not in {"disabled", "enabled"}:
        raise IndexingPolicyError("Invalid LightRAG vision policy.")
    if vision["mode"] == "disabled" and "snapshot" in vision:
        raise IndexingPolicyError("A disabled VLM cannot have an indexing snapshot.")

    def restore(value: Any, *, vision: bool = False) -> IndexingLLMSnapshot:
        if not isinstance(value, dict) or not isinstance(value.get("selection"), dict):
            raise IndexingPolicyError("Invalid LightRAG role snapshot.")
        descriptor = value.get("descriptor")
        result = _freeze_role(
            value["selection"],
            vision=vision,
            provider_default=isinstance(descriptor, dict)
            and descriptor.get("reasoning_effort") == "",
        )
        if not value.get("fingerprint") or result.fingerprint != value["fingerprint"]:
            raise IndexingModelChangedError("The pinned role model changed; run a full re-index.")
        return result

    return IndexingPolicySnapshot(
        restore(policy.get("extract")),
        restore(vision.get("snapshot"), vision=True) if vision["mode"] == "enabled" else None,
        policy=policy["policy"],
        limits=limits,
    )


def revalidate_snapshot(snapshot: IndexingPolicySnapshot) -> IndexingPolicySnapshot:
    """Refresh credentials and permissions without changing frozen task settings."""
    from deeptutor.multi_user.paths import user_context

    with user_context(snapshot.extract.owner):
        fresh = snapshot_from_persisted(snapshot.persisted_policy())
    return replace(
        fresh,
        limits=snapshot.limits,
        target_version=snapshot.target_version,
        target_bound=snapshot.target_bound,
        target_policy=snapshot.target_policy,
        image_analysis=snapshot.image_analysis,
        target_revision=snapshot.target_revision,
        embedding_config=snapshot.embedding_config,
    )


def _target_policy_key(kb_dir: Path) -> str | None:
    policy = effective_policy(kb_dir, base_dir=str(kb_dir.parent), kb_name=kb_dir.name)
    return (
        _fingerprint({key: value for key, value in policy.items() if key != "vlm_used"})
        if policy is not None
        else None
    )


def _content_revision(root: Path | None) -> str:
    # Native document-status flushes are atomic. Track inode and nanosecond
    # timestamps as well as size so a same-version append invalidates a queued rebuild.
    from .storage import _store_root

    revisions = {}
    if root is not None:
        paths = {
            "meta.json": root / "meta.json",
            "kv_store_doc_status.json": _store_root(root) / "kv_store_doc_status.json",
        }
        for name, path in paths.items():
            try:
                stat = path.stat()
                revisions[name] = [stat.st_ino, stat.st_size, stat.st_mtime_ns, stat.st_ctime_ns]
            except FileNotFoundError:
                revisions[name] = None
    return _fingerprint(revisions)


def bind_target(
    snapshot: IndexingPolicySnapshot, kb_dir: Path, *, protect_contents: bool = False
) -> IndexingPolicySnapshot:
    """Bind a snapshot to the current index and optionally its content revision."""
    from .storage import latest_published_root

    target = latest_published_root(kb_dir)
    snapshot = with_embedding(snapshot)
    return replace(
        snapshot,
        target_version=str(target) if target else None,
        target_bound=True,
        target_policy=_target_policy_key(kb_dir),
        target_revision=_content_revision(target) if protect_contents else None,
    )


def validate_target(snapshot: IndexingPolicySnapshot, kb_dir: Path) -> None:
    """Reject a queued write if its bound index, policy, or revision changed."""
    from .storage import latest_published_root

    if not snapshot.target_bound:
        return
    target = latest_published_root(kb_dir)
    if (
        snapshot.target_version != (str(target) if target else None)
        or snapshot.target_policy != _target_policy_key(kb_dir)
        or (
            snapshot.target_revision is not None
            and snapshot.target_revision != _content_revision(target)
        )
    ):
        raise IndexingPolicyError(
            "The target index or pending policy changed while queued; resubmit this operation."
        )


def with_image_analysis(
    snapshot: IndexingPolicySnapshot, requested: bool | None
) -> IndexingPolicySnapshot:
    """Record the requested image mode, rejecting unavailable pinned vision."""
    if requested is True and not snapshot.vision_available:
        raise IndexingModelChangedError(
            "Image analysis is disabled for this index; run a full re-index with a VLM."
        )
    return replace(snapshot, image_analysis=requested)


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
    if pending is not None and not isinstance(pending, dict):
        raise IndexingPolicyError("Invalid pending LightRAG indexing policy.")
    return pending


def resolve_write_snapshot(
    kb_dir: Path,
    *,
    base_dir: str,
    kb_name: str,
    explicit: IndexingPolicySnapshot | None = None,
) -> IndexingPolicySnapshot:
    if explicit is not None:
        return explicit
    # Empty KBs (including old creation-time pending policies) follow defaults.
    # Published/partial versions still require verified historical identities.
    from deeptutor.services.rag.index_versioning import list_kb_versions

    from .storage import latest_published_root

    if latest_published_root(kb_dir) is None and not list_kb_versions(kb_dir):
        return freeze_default_snapshot()
    policy = effective_policy(kb_dir, base_dir=base_dir, kb_name=kb_name)
    if policy is None or policy.get("policy") == POLICY_LEGACY:
        raise IndexingModelChangedError(
            "This LightRAG index has no verified indexing model; run a full re-index "
            "before appending documents."
        )
    return snapshot_from_persisted(policy)


def with_embedding(snapshot: IndexingPolicySnapshot) -> IndexingPolicySnapshot:
    """Freeze embedding configuration once, before accepting an indexing task."""
    if snapshot.embedding_config is not None:
        return snapshot
    from deeptutor.services.embedding import get_embedding_config

    config = deepcopy(get_embedding_config())
    if not config.dim:
        raise IndexingPolicyError(
            "Configure an embedding model with a known dimension in Settings."
        )
    return replace(snapshot, embedding_config=config)


def public_rebuild_config(snapshot: IndexingPolicySnapshot) -> dict[str, Any]:
    """Bind the confirmation to resolved identities without exposing credentials."""
    from deeptutor.services.rag.embedding_signature import signature_from_config

    snapshot = with_embedding(snapshot)
    signature = signature_from_config(snapshot.embedding_config)
    policy = snapshot.persisted_policy()
    return {
        "fingerprint": _fingerprint({"indexing_policy": policy, "embedding": signature.hash()}),
        "indexing_policy": public_policy(policy),
        "embedding": {"model": signature.model, "dimension": signature.dimension},
    }


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
    return _fingerprint(
        {
            **_canonical_identity(None, config),
            "wire_api": config.wire_api,
            "api_format": config.api_format,
            "context_window": config.context_window,
        }
    )


def public_policy(policy: dict[str, Any]) -> dict[str, Any]:
    """Expose provenance without private endpoint or owner metadata."""
    result = {
        key: policy[key]
        for key in ("schema_version", "policy", "fingerprint", "vision_available", "vlm_used")
        if key in policy
    }
    selection = policy.get("selection")
    if isinstance(selection, dict):
        result["selection"] = {
            key: selection[key]
            for key in ("profile_id", "model_id", "reasoning_effort")
            if key in selection
        }
    descriptor = policy.get("descriptor")
    if isinstance(descriptor, dict):
        result["descriptor"] = {
            key: descriptor[key]
            for key in ("model", "binding", "provider_mode", "reasoning_effort", "vision_available")
            if key in descriptor
        }
    if isinstance(policy.get("extract"), dict):
        result["extract"] = public_policy(policy["extract"])
    vlm = policy.get("vlm")
    if isinstance(vlm, dict):
        result["vlm"] = {"mode": vlm.get("mode")}
        if isinstance(vlm.get("snapshot"), dict):
            result["vlm"]["snapshot"] = public_policy(vlm["snapshot"])
    return result


__all__ = [
    "IndexingLLMSnapshot",
    "IndexingPolicySnapshot",
    "freeze_roles",
    "bind_target",
    "revalidate_snapshot",
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
