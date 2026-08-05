"""Model selection services for request-scoped runtime switching and audit.

- ``llm`` — legacy chat selection helpers (``LLMSelection``, catalog apply).
- ``selector`` — purpose-specific ModelSelector + evaluator snapshot freezing.
- ``audit`` — append-only ModelInvocationRecorder used by chat/teaching/
  evaluation/challenge/knowledge-card-draft callers.
- ``fingerprint`` — deterministic secret-safe profile revision / URL / error
  fingerprints.
"""

from .audit import (
    EvaluatorUnavailableResult,
    ModelInvocationAuditContext,
    ModelInvocationRecorder,
    attach_evaluation_identity,
    finalize_evaluator_unavailable,
    finish_audited_invocation,
    run_audited_completion,
    start_audited_invocation,
    to_audit_view,
)
from .fingerprint import (
    base_url_fingerprint,
    invocation_request_fingerprint,
    invocation_response_fingerprint,
    profile_revision,
    sanitize_error,
)
from .llm import LLMSelection, apply_llm_selection_to_catalog, list_llm_options
from .selector import (
    EvaluatorSnapshotConflictError,
    ModelSelector,
    ResolvedModelSnapshot,
    evaluator_selection_from_progress,
    freeze_evaluator_snapshot,
    resolve_challenge_evaluator,
)

__all__ = [
    "EvaluatorSnapshotConflictError",
    "EvaluatorUnavailableResult",
    "LLMSelection",
    "ModelInvocationAuditContext",
    "ModelInvocationRecorder",
    "ModelSelector",
    "ResolvedModelSnapshot",
    "apply_llm_selection_to_catalog",
    "attach_evaluation_identity",
    "base_url_fingerprint",
    "evaluator_selection_from_progress",
    "finalize_evaluator_unavailable",
    "finish_audited_invocation",
    "freeze_evaluator_snapshot",
    "invocation_request_fingerprint",
    "invocation_response_fingerprint",
    "list_llm_options",
    "profile_revision",
    "resolve_challenge_evaluator",
    "run_audited_completion",
    "sanitize_error",
    "start_audited_invocation",
    "to_audit_view",
]
