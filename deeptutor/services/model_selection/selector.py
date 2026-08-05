"""Purpose-specific model selection and evaluator snapshot freezing (MOD-03).

Teaching selection follows the session/turn model selection (the existing
ModelSelector behaviour, FT-05). Evaluation uses the learning path's configured
evaluator profile/model, resolved once and frozen into an
:class:`~deeptutor.learning.models.EvaluatorSnapshot` at attempt start — with
no LLM call. ``api_protocol=auto`` is resolved exactly once and the actual
protocol plus the resolution reason are recorded (§9.3, §9.4).

Nothing here ever persists credentials: snapshots carry only IDs, names,
revision hashes and safe fingerprints.
"""

from __future__ import annotations

from dataclasses import dataclass
import time
from typing import Any

from deeptutor.learning.models import EvaluatorSnapshot, FeynmanAttempt, LearningProgress
from deeptutor.services.model_selection.fingerprint import base_url_fingerprint, profile_revision
from deeptutor.services.model_selection.llm import LLMSelection, apply_llm_selection_to_catalog


class EvaluatorSnapshotConflictError(Exception):
    """A re-freeze with a *different* evaluator selection was rejected.

    An attempt's evaluator snapshot is pinned at attempt start (§9.3). Calling
    ``freeze_evaluator_snapshot`` again with a selection that resolves to a
    different profile/model/protocol must never silently overwrite the frozen
    snapshot — it raises this stable conflict so the caller can surface the
    mismatch instead.
    """

    def __init__(
        self,
        *,
        attempt_id: str,
        existing_profile_id: str,
        existing_model: str,
        new_profile_id: str,
        new_model: str,
    ) -> None:
        self.attempt_id = attempt_id
        self.existing_profile_id = existing_profile_id
        self.existing_model = existing_model
        self.new_profile_id = new_profile_id
        self.new_model = new_model
        super().__init__(
            f"attempt {attempt_id!r} already has a frozen evaluator snapshot "
            f"({existing_profile_id!r}/{existing_model!r}); refusing to overwrite "
            f"with a different selection ({new_profile_id!r}/{new_model!r})"
        )


_EVALUATOR_EQUIVALENCE_FIELDS = (
    "profile_id",
    "profile_revision",
    "requested_provider",
    "requested_api_protocol",
    "requested_model",
    "resolved_provider",
    "resolved_api_protocol",
    "resolved_model",
    "auto_resolution_reason",
    "base_url_fingerprint",
    "strict_protocol",
    "prompt_version",
    "rubric_version",
)


def _evaluator_equivalence(snapshot: EvaluatorSnapshot) -> dict[str, Any]:
    """The selection-identity projection used to decide re-freeze idempotency.

    ``created_at`` is intentionally excluded — re-freezing an *equivalent*
    selection is idempotent and must not rewrite the timestamp.
    """
    return {field: getattr(snapshot, field) for field in _EVALUATOR_EQUIVALENCE_FIELDS}


def _selection_applied_catalog(
    catalog: dict[str, Any] | None,
    selection: Any,
) -> dict[str, Any] | None:
    """Catalog copy with *selection* made active (no mutation of the input)."""
    if catalog is None or selection is None:
        return catalog
    return apply_llm_selection_to_catalog(catalog, selection)


def _active_profile(catalog: dict[str, Any] | None) -> dict[str, Any] | None:
    if not isinstance(catalog, dict):
        return None
    service = catalog.get("services", {}).get("llm", {})
    profiles = service.get("profiles") or []
    if not profiles:
        return None
    active_id = service.get("active_profile_id")
    for profile in profiles:
        if isinstance(profile, dict) and profile.get("id") == active_id:
            return profile
    return profiles[0] if isinstance(profiles[0], dict) else None


def _active_model(catalog: dict[str, Any] | None) -> dict[str, Any] | None:
    profile = _active_profile(catalog)
    if not isinstance(profile, dict):
        return None
    service = catalog.get("services", {}).get("llm", {})
    models = profile.get("models") or []
    if not models:
        return None
    active_id = service.get("active_model_id")
    for model in models:
        if isinstance(model, dict) and model.get("id") == active_id:
            return model
    return models[0] if isinstance(models[0], dict) else None


@dataclass(frozen=True, slots=True)
class ResolvedModelSnapshot:
    """A resolved selection snapshot for one invocation purpose.

    Carries only IDs/names/revision hashes/fingerprints — never API keys, auth
    headers, or private URLs. Used to build a :class:`ModelInvocationRecord`
    and a frozen :class:`EvaluatorSnapshot`.
    """

    profile_id: str
    profile_name: str
    profile_revision: str
    requested_provider: str
    requested_protocol: str
    requested_model: str
    resolved_provider: str
    resolved_protocol: str
    resolved_model: str
    auto_resolution_reason: str
    base_url_fingerprint: str
    strict_protocol: bool = False
    prompt_version: str = ""
    tool_schema_version: str = ""

    def to_evaluator_snapshot(
        self,
        *,
        rubric_version: str = "",
        prompt_version: str | None = None,
        now: float | None = None,
    ) -> EvaluatorSnapshot:
        """Project this snapshot onto the frozen evaluator shape (§7.6)."""
        return EvaluatorSnapshot(
            profile_id=self.profile_id,
            profile_name=self.profile_name,
            profile_revision=self.profile_revision,
            requested_provider=self.requested_provider,
            requested_api_protocol=self.requested_protocol,
            requested_model=self.requested_model,
            resolved_provider=self.resolved_provider,
            resolved_api_protocol=self.resolved_protocol,
            resolved_model=self.resolved_model,
            auto_resolution_reason=self.auto_resolution_reason,
            base_url_fingerprint=self.base_url_fingerprint,
            strict_protocol=self.strict_protocol,
            prompt_version=prompt_version or self.prompt_version,
            rubric_version=rubric_version,
            created_at=now if now is not None else time.time(),
        )


class ModelSelector:
    """Resolve purpose-specific model selections without calling an LLM."""

    def __init__(self, catalog: dict[str, Any] | None = None) -> None:
        self._catalog = catalog

    def resolve_teaching(
        self,
        selection: Any = None,
        *,
        prompt_version: str = "",
        tool_schema_version: str = "",
    ) -> ResolvedModelSnapshot:
        """Resolve the teaching model for the current session/turn selection.

        ``selection`` is an :class:`LLMSelection` / dict, or ``None`` for the
        active session model (the existing ModelSelector behaviour).
        """
        return self._resolve(
            selection,
            prompt_version=prompt_version,
            tool_schema_version=tool_schema_version,
        )

    def resolve_evaluator(
        self,
        evaluator_selection: Any = None,
        *,
        prompt_version: str = "",
        tool_schema_version: str = "",
    ) -> ResolvedModelSnapshot:
        """Resolve the learning path's configured evaluator profile/model.

        ``evaluator_selection`` is the ``(profile_id, model_id)`` pinned on the
        learning path; ``None`` falls back to the active LLM profile.
        """
        return self._resolve(
            evaluator_selection,
            prompt_version=prompt_version,
            tool_schema_version=tool_schema_version,
        )

    def _resolve(
        self,
        selection: Any,
        *,
        prompt_version: str,
        tool_schema_version: str,
    ) -> ResolvedModelSnapshot:
        # Imported lazily: provider_runtime imports back into this package's
        # ``llm`` submodule, so a module-level import would create a cycle.
        from deeptutor.services.config.provider_runtime import resolve_llm_runtime_config

        catalog = self._catalog
        applied = _selection_applied_catalog(catalog, selection)
        resolved = resolve_llm_runtime_config(catalog, llm_selection=selection)
        profile = _active_profile(applied)
        model = _active_model(applied)

        requested_protocol = str((profile or {}).get("api_protocol") or "auto")
        requested_provider = str((profile or {}).get("binding") or resolved.binding_hint or "")
        requested_model = str((model or {}).get("model") or resolved.model)
        auto_reason = resolved.protocol_resolution_reason or (
            "auto:default" if requested_protocol == "auto" else ""
        )
        return ResolvedModelSnapshot(
            profile_id=str((profile or {}).get("id") or ""),
            profile_name=str((profile or {}).get("name") or ""),
            profile_revision=profile_revision(profile or {}),
            requested_provider=requested_provider,
            requested_protocol=requested_protocol,
            requested_model=requested_model,
            resolved_provider=resolved.provider_name or resolved.binding,
            resolved_protocol=resolved.resolved_api_protocol or requested_protocol,
            resolved_model=resolved.model,
            auto_resolution_reason=auto_reason,
            base_url_fingerprint=base_url_fingerprint(resolved.effective_url or resolved.base_url),
            strict_protocol=bool((profile or {}).get("strict_protocol")),
            prompt_version=prompt_version,
            tool_schema_version=tool_schema_version,
        )


def evaluator_selection_from_progress(
    progress: LearningProgress,
) -> LLMSelection | None:
    """Build the evaluator selection pinned on a learning path, if any.

    Returns ``None`` when the path has no evaluator configured yet, in which
    case callers fall back to the active LLM profile.
    """
    if not progress.evaluator_profile_id or not progress.evaluator_model_id:
        return None
    return LLMSelection(
        profile_id=progress.evaluator_profile_id,
        model_id=progress.evaluator_model_id,
    )


def freeze_evaluator_snapshot(
    attempt: FeynmanAttempt,
    *,
    evaluator_selection: Any = None,
    catalog: dict[str, Any] | None = None,
    prompt_version: str = "",
    rubric_version: str = "",
    now: float | None = None,
) -> EvaluatorSnapshot:
    """Resolve and freeze the evaluator snapshot at attempt start (§9.3).

    Makes no LLM call. The attempt's snapshot is pinned here and never changes
    when the teaching model is switched mid-attempt. Re-freezing an
    *equivalent* selection is idempotent (returns the existing snapshot); a
    *different* selection raises :class:`EvaluatorSnapshotConflictError` and
    never mutates the frozen snapshot.
    """
    selector = ModelSelector(catalog=catalog)
    resolved = selector.resolve_evaluator(evaluator_selection, prompt_version=prompt_version)
    snapshot = resolved.to_evaluator_snapshot(rubric_version=rubric_version, now=now)
    existing = attempt.evaluator_snapshot
    if existing is not None:
        if _evaluator_equivalence(existing) == _evaluator_equivalence(snapshot):
            return existing
        raise EvaluatorSnapshotConflictError(
            attempt_id=attempt.id,
            existing_profile_id=existing.profile_id,
            existing_model=existing.resolved_model,
            new_profile_id=snapshot.profile_id,
            new_model=snapshot.resolved_model,
        )
    attempt.evaluator_snapshot = snapshot
    return snapshot


def resolve_challenge_evaluator(
    *,
    challenge_evaluator_selection: Any,
    catalog: dict[str, Any] | None = None,
    prompt_version: str = "",
    rubric_version: str = "",
    now: float | None = None,
) -> tuple[ResolvedModelSnapshot, EvaluatorSnapshot]:
    """Resolve a *different* configured evaluator for an explicit cross-model
    challenge (§9.3, §7.3.1).

    Returns the resolved snapshot plus a frozen :class:`EvaluatorSnapshot`.
    The challenge links its resulting invocation/assessment through
    ``challenge_id`` / ``supersedes_assessment_id``; the original assessment
    and snapshot are never overwritten.
    """
    selector = ModelSelector(catalog=catalog)
    resolved = selector.resolve_evaluator(
        challenge_evaluator_selection, prompt_version=prompt_version
    )
    snapshot = resolved.to_evaluator_snapshot(rubric_version=rubric_version, now=now)
    return resolved, snapshot


__all__ = [
    "EvaluatorSnapshotConflictError",
    "ModelSelector",
    "ResolvedModelSnapshot",
    "evaluator_selection_from_progress",
    "freeze_evaluator_snapshot",
    "resolve_challenge_evaluator",
]
