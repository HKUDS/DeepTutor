"""Domain errors for knowledge-card drafts and generation (KB-02).

Every error carries a stable ``code`` so API/worker callers can surface a
recoverable, secret-free outcome without leaking the underlying exception text.
"""

from __future__ import annotations


class KnowledgeCardError(RuntimeError):
    """Base class for knowledge-card failures."""

    code = "knowledge_card_error"


class KnowledgeCardEligibilityError(KnowledgeCardError):
    """No server-eligible stable assessment could be derived (fail closed).

    Raised when the create/ensure operation cannot find a *current* latest
    valid stable assessment for the knowledge point, or its sequence is not
    strictly greater than every historical retracted card's sequence (§6.6).
    """

    code = "new_stable_evidence_required"


class KnowledgeCardOwnershipError(KnowledgeCardError):
    """A card was addressed by a different user/path than it belongs to."""

    code = "card_ownership"


class KnowledgeCardNotFoundError(KnowledgeCardError):
    """No card/attempt matched the requested id."""

    code = "card_not_found"


class KnowledgeCardStateError(KnowledgeCardError):
    """The card is not in a state that supports the requested operation
    (publishing/published/retracting/stale/discarded, ...)."""

    code = "card_state"


class KnowledgeCardStaleVersionError(KnowledgeCardError):
    """An ``expected_card_revision``/``expected_*`` token no longer matches.

    The caller holds a stale snapshot; reload the card and retry. Never
    overwrites newer progress (§8.3).
    """

    code = "card_version_conflict"


class KnowledgeCardIdempotencyConflictError(KnowledgeCardError):
    """The same idempotency key was reused with a different payload."""

    code = "idempotency_conflict"


class GenerationLockedByUserEditError(KnowledgeCardError):
    """Generation/retry refused because the user has edited title/body.

    Once the user owns the content, a model retry must never overwrite it
    (§7.9, §8.5).
    """

    code = "generation_locked_by_user_edit"


class KnowledgeCardLeaseError(KnowledgeCardError):
    """A lease claim/renew/finish was rejected (stale owner or state)."""

    code = "generation_lease"


class OutputValidationError(KnowledgeCardError):
    """Executor output failed normalization/bounds/sanitization checks.

    The output is rejected before any blob is persisted or any card is touched,
    so a malformed or unsafe provider result can never produce a draft.
    """

    code = "output_validation"


class KnowledgeCardInputValidationError(KnowledgeCardError):
    """A reference or identity supplied to a card operation was invalid.

    Covers client-injected remote ids, cross-path/cross-user references and
    missing/unowned artifacts/evidence/sources (§6.6, §14).
    """

    code = "input_validation"


class KnowledgeCardKbNotWritableError(KnowledgeCardError):
    """The target knowledge base cannot accept knowledge-card publication.

    The writable-KB policy failed: the target is not an existing ordinary local
    indexed KB that is ``ready``, accessible to the current user, has a local
    raw document set and a ready provider index, and has neither
    ``needs_reindex`` nor a connected/external type (§7.9.2 requirement 4).
    """

    code = "kb_not_writable"


class KnowledgeCardPublicationConflictError(KnowledgeCardError):
    """The same publication key was reused with different content.

    Idempotency contract (§7.9.2 requirement 5): same ``publication_key`` +
    same content hash replays/reuses the existing publication; same key with a
    different content hash is a stable conflict that requires a new revision.
    """

    code = "publication_conflict"


class KnowledgeCardPublicationUnavailableError(KnowledgeCardError):
    """The target KB is busy or the publication state is not actionable.

    ``kb_busy`` is recoverable: retry after the current operation completes or
    is reconciled. A crashed/expired publication cannot permit a second
    mutation until explicit reconciliation (§7.9.2 requirement 12).
    """

    code = "publication_unavailable"


class KnowledgeCardReconcileRequiredError(KnowledgeCardError):
    """A publication/retraction cannot proceed until it is explicitly reconciled.

    The card is in ``reconcile_required`` / ``retract_reconcile_required``
    (interrupted / ambiguous provider mutation) and must be reconciled
    conservatively before any further publication or retraction attempt
    (§7.9.2 requirement 9/11, §7.11 requirement 8).
    """

    code = "reconcile_required"


class KnowledgeCardRetractionConflictError(KnowledgeCardError):
    """The same retraction ``request_id`` was reused with different facts.

    Idempotency contract (§7.11 requirement 1): the same ``request_id`` for one
    card revision replays the existing result when the payload (target KB,
    original path, quarantine path, content hash) is identical; reusing it with
    different facts is a stable conflict.
    """

    code = "retraction_conflict"


class KnowledgeCardRetractionUnavailableError(KnowledgeCardError):
    """The target KB is busy or the retraction state is not actionable.

    ``kb_busy`` is recoverable: retry after the current operation completes or
    is reconciled. A crashed/expired retraction cannot permit a second mutation
    until explicit reconciliation (§7.11 requirement 4/8).
    """

    code = "retraction_unavailable"


__all__ = [
    "GenerationLockedByUserEditError",
    "KnowledgeCardEligibilityError",
    "KnowledgeCardError",
    "KnowledgeCardIdempotencyConflictError",
    "KnowledgeCardInputValidationError",
    "KnowledgeCardKbNotWritableError",
    "KnowledgeCardLeaseError",
    "KnowledgeCardNotFoundError",
    "KnowledgeCardOwnershipError",
    "KnowledgeCardPublicationConflictError",
    "KnowledgeCardPublicationUnavailableError",
    "KnowledgeCardReconcileRequiredError",
    "KnowledgeCardRetractionConflictError",
    "KnowledgeCardRetractionUnavailableError",
    "KnowledgeCardStaleVersionError",
    "KnowledgeCardStateError",
    "OutputValidationError",
]
