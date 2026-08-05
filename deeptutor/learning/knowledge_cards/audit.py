"""Model-invocation audit helpers for knowledge-card generation (KB-02).

Before invoking the executor the worker appends a ``pending``
:class:`ModelInvocationRecord` with purpose ``knowledge_card_draft`` and the
frozen evaluator identity converted to the MOD-03 resolved snapshot shape
(:class:`ResolvedModelSnapshot`), links the invocation id onto the generation
attempt, and only then calls the executor (§7.8/§9.4, requirement 4).
"""

from __future__ import annotations

from deeptutor.learning.models import EvaluatorSnapshot
from deeptutor.services.model_selection.selector import ResolvedModelSnapshot


def resolved_snapshot_from_evaluator(
    snapshot: EvaluatorSnapshot | None,
) -> ResolvedModelSnapshot:
    """Project a frozen :class:`EvaluatorSnapshot` onto the MOD-03 resolved shape.

    The frozen evaluator identity (pinned at attempt start) is never
    re-resolved — generation and every explicit retry reuse this exact shape.
    ``tool_schema_version`` is not part of the evaluator snapshot; it defaults
    to empty, exactly like a pre-resolution snapshot.
    """
    if snapshot is None:
        return ResolvedModelSnapshot(
            profile_id="",
            profile_name="",
            profile_revision="",
            requested_provider="",
            requested_protocol="",
            requested_model="",
            resolved_provider="",
            resolved_protocol="",
            resolved_model="",
            auto_resolution_reason="",
            base_url_fingerprint="",
        )
    return ResolvedModelSnapshot(
        profile_id=snapshot.profile_id,
        profile_name=snapshot.profile_name,
        profile_revision=snapshot.profile_revision,
        requested_provider=snapshot.requested_provider,
        requested_protocol=snapshot.requested_api_protocol,
        requested_model=snapshot.requested_model,
        resolved_provider=snapshot.resolved_provider,
        resolved_protocol=snapshot.resolved_api_protocol,
        resolved_model=snapshot.resolved_model,
        auto_resolution_reason=snapshot.auto_resolution_reason,
        base_url_fingerprint=snapshot.base_url_fingerprint,
        strict_protocol=snapshot.strict_protocol,
        prompt_version=snapshot.prompt_version,
        tool_schema_version="",
    )


__all__ = ["resolved_snapshot_from_evaluator"]
