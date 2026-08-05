"""Worker tests for knowledge-card generation (KB-02).

Covers the single-flight lease and invocation audit, the output-blob-before-apply
boundary, user-edit / stale-evidence races, deterministic restart recovery, and
crash/failure-injection at the pre-call-audit, post-call/pre-blob, post-blob/
pre-apply and expired-lease-takeover boundaries (§6.6, §7.9.1, requirement 4/5/8/9).
"""

from __future__ import annotations

import asyncio

import pytest

from deeptutor.learning.knowledge_cards.blobs import (
    KnowledgeCardBlobStore,
    validate_blob_payload,
)
from deeptutor.learning.knowledge_cards.config import KnowledgeCardLimits
from deeptutor.learning.knowledge_cards.errors import (
    KnowledgeCardLeaseError,
    OutputValidationError,
)
from deeptutor.learning.knowledge_cards.service import KnowledgeCardDraftService
from deeptutor.learning.knowledge_cards.worker import (
    DraftOutput,
    KnowledgeCardGenerationWorker,
)
from deeptutor.learning.models import (
    DraftGenerationStatus,
    GenerationAttemptStatus,
    KnowledgeCardStatus,
    MasteryState,
    ModelInvocationPurpose,
    ModelInvocationStatus,
)
from deeptutor.learning.storage import LearningStore
from deeptutor.learning.tests.knowledge_card_builders import (
    media_store_with_artifact,
    stable_mastery_progress,
)


class FakeDraftExecutor:
    """Stands in for an offline generation adapter."""

    def __init__(
        self,
        result: DraftOutput | None = None,
        error: Exception | None = None,
    ) -> None:
        self.result = result or DraftOutput(title="Generated title", body="Generated body")
        self.error = error
        self.inputs: list[dict] = []

    async def generate(self, input_projection: dict) -> DraftOutput:
        self.inputs.append(input_projection)
        if self.error is not None:
            raise self.error
        return self.result


def _run(coro):
    # Python 3.13: ``get_event_loop`` no longer auto-creates a loop in the main
    # thread, and an earlier pytest-asyncio test may leave no current loop. Fall
    # back to a fresh loop (same pattern as the publish/retraction suites).
    try:
        loop = asyncio.get_event_loop()
    except RuntimeError:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
    return loop.run_until_complete(coro)


@pytest.fixture
def store(tmp_path):
    return LearningStore(root=tmp_path)


@pytest.fixture
def media_store(tmp_path):
    return media_store_with_artifact(tmp_path)[0]


@pytest.fixture
def blob_store(tmp_path):
    return KnowledgeCardBlobStore(tmp_path / "blobs")


@pytest.fixture
def service(tmp_path, media_store, blob_store):
    return KnowledgeCardDraftService(
        LearningStore(root=tmp_path),
        media_store=media_store,
        blob_store=blob_store,
    )


def _worker(store, blob_store, media_store, *, executor=None, now=None):
    return KnowledgeCardGenerationWorker(
        store,
        blob_store=blob_store,
        executor=executor,
        media_store=media_store,
        now=now or (lambda: 2000.0),
    )


def _card_of(progress, card_id: str):
    return next(card for card in progress.knowledge_cards if card.id == card_id)


def _persist_blob(worker, title: str = "Generated title", body: str = "Generated body"):
    output = DraftOutput(title=title, body=body)
    return worker._persist_output_blob(output)


def _mark_running_with_blob(
    store, worker, *, attempt_id, blob_ref, blob_hash, owner="owner1", now=2000.0
):
    """Simulate a crash after lease claim + audit + blob persistence, before apply."""
    progress = store.load("b1")
    attempt = next(a for a in progress.knowledge_card_generation_attempts if a.id == attempt_id)
    attempt.status = GenerationAttemptStatus.RUNNING
    attempt.lease_owner = owner
    attempt.lease_expires_at = now + 300.0
    attempt.started_at = now
    attempt.output_blob_ref = blob_ref
    attempt.output_hash = blob_hash
    record_id = worker._append_pending_invocation(progress, attempt, now=now)
    progress.knowledge_cards[0].draft_generation_status = DraftGenerationStatus.RUNNING
    store.save(progress)
    return record_id


# ── happy path ─────────────────────────────────────────────────────────────


class TestRunAttemptSuccess:
    def test_success_applies_card_and_finishes_audit(self, store, service, blob_store, media_store):
        progress, _, _ = stable_mastery_progress()
        store.save(progress)
        result = service.ensure_draft(
            progress, user_id="owner", path_id="b1", knowledge_point_id="kp1"
        )
        attempt_id = result["attempt"].id
        executor = FakeDraftExecutor()
        worker = _worker(store, blob_store, media_store, executor=executor)

        outcome = _run(worker.run_attempt("b1", attempt_id))

        assert outcome["outcome"] == "succeeded"
        persisted = store.load("b1")
        card = persisted.knowledge_cards[0]
        attempt = persisted.knowledge_card_generation_attempts[0]

        # Executor was called exactly once with the frozen input projection.
        assert len(executor.inputs) == 1
        assert executor.inputs[0]["stable_assessment_id"] == "ra1"
        assert executor.inputs[0]["evidence"][0]["id"] == "ev1"
        assert executor.inputs[0]["sources"][0]["id"] == "s1"

        # Card applied: title/body set, content hash, revision bumped, ready.
        assert card.title == "Generated title"
        assert card.body == "Generated body"
        assert card.content_hash
        assert card.revision == 2
        assert card.draft_generation_status == DraftGenerationStatus.READY
        assert card.status == KnowledgeCardStatus.DRAFT

        # Attempt terminal with output blob ref/hash.
        assert attempt.status == GenerationAttemptStatus.SUCCEEDED
        assert attempt.output_blob_ref
        assert attempt.output_hash
        assert attempt.finished_at

        # Invocation audit: pending revision preserved + completed terminal appended.
        invocations = persisted.model_invocations
        assert len(invocations) == 2
        assert invocations[0].status == ModelInvocationStatus.PENDING
        assert invocations[1].status == ModelInvocationStatus.COMPLETED
        assert invocations[1].purpose == ModelInvocationPurpose.KNOWLEDGE_CARD_DRAFT
        assert invocations[1].knowledge_card_generation_attempt_id == attempt_id
        assert attempt.model_invocation_id == invocations[1].id
        assert invocations[1].resolved_model == "gpt-4o-mini"

    def test_pending_invocation_durably_saved_before_executor_call(
        self, store, service, blob_store, media_store
    ):
        """Pre-call audit crash: the pending record survives, linked to the attempt."""
        progress, _, _ = stable_mastery_progress()
        store.save(progress)
        result = service.ensure_draft(
            progress, user_id="owner", path_id="b1", knowledge_point_id="kp1"
        )
        attempt_id = result["attempt"].id
        executor = FakeDraftExecutor()
        worker = _worker(store, blob_store, media_store, executor=executor)

        # Manually run the pre-call phases exactly as run_attempt would.
        owner = "owner1"
        progress = store.load("b1")
        attempt = next(a for a in progress.knowledge_card_generation_attempts if a.id == attempt_id)
        worker._claim_lease(progress, attempt, owner, 2000.0)
        worker.save(progress)
        progress = store.load("b1")
        attempt = next(a for a in progress.knowledge_card_generation_attempts if a.id == attempt_id)
        record_id = worker._append_pending_invocation(progress, attempt, now=2000.0)
        worker.save(progress)

        # Crash here: executor never called. The pending audit record is durable.
        persisted = store.load("b1")
        assert persisted.model_invocations[0].status == ModelInvocationStatus.PENDING
        assert persisted.model_invocations[0].purpose == ModelInvocationPurpose.KNOWLEDGE_CARD_DRAFT
        assert persisted.model_invocations[0].knowledge_card_generation_attempt_id == attempt_id
        assert persisted.knowledge_card_generation_attempts[0].model_invocation_id == record_id
        assert (
            persisted.knowledge_card_generation_attempts[0].status
            == GenerationAttemptStatus.RUNNING
        )

    def test_audit_failure_never_creates_false_succeeded(
        self, store, service, blob_store, media_store
    ):
        """If the invocation cannot be finalized, the attempt is not succeeded."""
        progress, _, _ = stable_mastery_progress()
        store.save(progress)
        result = service.ensure_draft(
            progress, user_id="owner", path_id="b1", knowledge_point_id="kp1"
        )
        attempt_id = result["attempt"].id
        executor = FakeDraftExecutor()
        worker = _worker(store, blob_store, media_store, executor=executor)

        outcome = _run(worker.run_attempt("b1", attempt_id))
        assert outcome["outcome"] == "succeeded"

        # A duplicate terminalization must not create a second succeeded record.
        persisted = store.load("b1")
        succeeded = [
            a
            for a in persisted.knowledge_card_generation_attempts
            if a.status == GenerationAttemptStatus.SUCCEEDED
        ]
        assert len(succeeded) == 1

    def test_post_provider_cas_retry_commits_received_output_without_second_call(
        self, store, blob_store, media_store
    ):
        """A CAS conflict after the provider returns does not re-invoke the
        provider — the already-received output blob commits on the retry loop."""
        from deeptutor.learning.knowledge_cards.errors import KnowledgeCardStaleVersionError
        from deeptutor.learning.storage import VersionConflictError

        progress, _, _ = stable_mastery_progress()
        store.save(progress)
        service = KnowledgeCardDraftService(LearningStore(root=store._root))
        result = service.ensure_draft(
            progress, user_id="owner", path_id="b1", knowledge_point_id="kp1"
        )
        attempt_id = result["attempt"].id

        class _FailOnceOnBlobSave:
            """Fails the save that carries a blob (the post-provider completion
            save) once, as if a concurrent writer committed in the gap."""

            def __init__(self, store):
                self._store = store
                self._failed = False

            def load(self, book_id):
                return self._store.load(book_id)

            def save(self, progress):
                has_blob = any(
                    a.output_blob_ref for a in progress.knowledge_card_generation_attempts
                )
                if has_blob and not self._failed:
                    self._failed = True
                    concurrent = self._store.load(progress.book_id)
                    concurrent.version += 1
                    self._store.save(concurrent)
                    raise VersionConflictError(
                        book_id=progress.book_id,
                        expected_version=progress.version,
                        persisted_version=concurrent.version,
                    )
                self._store.save(progress)

        executor = FakeDraftExecutor()
        worker = KnowledgeCardGenerationWorker(
            _FailOnceOnBlobSave(store),
            blob_store=blob_store,
            executor=executor,
            media_store=media_store,
            now=lambda: 2000.0,
        )
        outcome = _run(worker.run_attempt("b1", attempt_id))
        assert outcome["outcome"] == "succeeded"
        # The provider was called exactly once — the CAS retry reused the blob.
        assert len(executor.inputs) == 1
        persisted = store.load("b1")
        card = persisted.knowledge_cards[0]
        assert card.title == "Generated title"
        assert card.draft_generation_status == DraftGenerationStatus.READY
        attempt = persisted.knowledge_card_generation_attempts[0]
        assert attempt.status == GenerationAttemptStatus.SUCCEEDED
        # The invocation was finished exactly once (no duplicate completion).
        completed = [
            r for r in persisted.model_invocations if r.status == ModelInvocationStatus.COMPLETED
        ]
        assert len(completed) == 1


# ── executor / output failures ─────────────────────────────────────────────


class TestFailures:
    def test_executor_failure_marks_failed_and_audits_failure(
        self, store, service, blob_store, media_store
    ):
        progress, _, _ = stable_mastery_progress()
        store.save(progress)
        result = service.ensure_draft(
            progress, user_id="owner", path_id="b1", knowledge_point_id="kp1"
        )
        attempt_id = result["attempt"].id
        worker = _worker(
            store,
            blob_store,
            media_store,
            executor=FakeDraftExecutor(error=RuntimeError("upstream boom")),
        )

        outcome = _run(worker.run_attempt("b1", attempt_id))
        assert outcome["outcome"] == "failed"
        persisted = store.load("b1")
        attempt = persisted.knowledge_card_generation_attempts[0]
        assert attempt.status == GenerationAttemptStatus.FAILED
        assert attempt.error_code
        assert attempt.sanitized_error
        assert persisted.knowledge_cards[0].draft_generation_status == DraftGenerationStatus.FAILED
        # Invocation finalized failed.
        latest = persisted.model_invocations[-1]
        assert latest.status == ModelInvocationStatus.FAILED
        assert "upstream" in latest.sanitized_error
        # Stable mastery untouched by the generation failure.
        assert persisted.projections["kp1"].mastery_state == MasteryState.STABLE_MASTERY

    def test_output_validation_failure_persists_no_blob(
        self, store, service, blob_store, media_store
    ):
        progress, _, _ = stable_mastery_progress()
        store.save(progress)
        result = service.ensure_draft(
            progress, user_id="owner", path_id="b1", knowledge_point_id="kp1"
        )
        attempt_id = result["attempt"].id
        executor = FakeDraftExecutor(
            result=DraftOutput(title="ok", body="b" * 100_000)  # exceeds body bound
        )
        worker = _worker(store, blob_store, media_store, executor=executor)

        outcome = _run(worker.run_attempt("b1", attempt_id))
        assert outcome["outcome"] == "failed"
        persisted = store.load("b1")
        attempt = persisted.knowledge_card_generation_attempts[0]
        assert attempt.status == GenerationAttemptStatus.FAILED
        assert attempt.output_blob_ref == ""
        assert persisted.knowledge_cards[0].title == ""
        # No blob files leaked.
        assert list(blob_store._blobs_dir.glob("*.json")) == []

    def test_base64_output_rejected(self, store, service, blob_store, media_store):
        progress, _, _ = stable_mastery_progress()
        store.save(progress)
        result = service.ensure_draft(
            progress, user_id="owner", path_id="b1", knowledge_point_id="kp1"
        )
        attempt_id = result["attempt"].id
        import base64

        b64 = base64.b64encode(b"fake-image-bytes").decode()
        executor = FakeDraftExecutor(
            result=DraftOutput(title="ok", body=f"data:image/png;base64,{b64}")
        )
        worker = _worker(store, blob_store, media_store, executor=executor)

        outcome = _run(worker.run_attempt("b1", attempt_id))
        assert outcome["outcome"] == "failed"
        assert store.load("b1").knowledge_cards[0].body == ""

    def test_private_url_never_persisted_in_blob_or_card(
        self, store, service, blob_store, media_store
    ):
        """A private URL in executor output is redacted before any durable write."""
        progress, _, _ = stable_mastery_progress()
        store.save(progress)
        result = service.ensure_draft(
            progress, user_id="owner", path_id="b1", knowledge_point_id="kp1"
        )
        attempt_id = result["attempt"].id
        executor = FakeDraftExecutor(
            result=DraftOutput(
                title="ok",
                body="See https://example.org/private-notes for details",
            )
        )
        worker = _worker(store, blob_store, media_store, executor=executor)

        outcome = _run(worker.run_attempt("b1", attempt_id))
        assert outcome["outcome"] == "succeeded"
        persisted = store.load("b1")
        card = persisted.knowledge_cards[0]
        assert "example.org" not in card.body
        assert "private-notes" not in card.body
        # The blob file itself is also scrubbed.
        for blob_file in blob_store._blobs_dir.glob("*.json"):
            text = blob_file.read_text(encoding="utf-8")
            assert "example.org" not in text
            assert "private-notes" not in text

    def test_educational_data_text_not_mistaken_for_envelope(
        self, store, service, blob_store, media_store
    ):
        """Prose that merely mentions ``data:`` / ``base64,`` is legitimate card
        content and must not be mistaken for a raw provider envelope."""
        progress, _, _ = stable_mastery_progress()
        store.save(progress)
        result = service.ensure_draft(
            progress, user_id="owner", path_id="b1", knowledge_point_id="kp1"
        )
        attempt_id = result["attempt"].id
        executor = FakeDraftExecutor(
            result=DraftOutput(
                title="Growth trends",
                body="The data: shows 42% growth over the quarter; base64, hex "
                "and other encodings are out of scope.",
            )
        )
        worker = _worker(store, blob_store, media_store, executor=executor)

        outcome = _run(worker.run_attempt("b1", attempt_id))
        assert outcome["outcome"] == "succeeded"
        card = store.load("b1").knowledge_cards[0]
        assert "data: shows 42% growth" in card.body
        assert card.draft_generation_status == DraftGenerationStatus.READY

    def test_raw_sse_envelope_rejected(self, store, service, blob_store, media_store):
        """A streaming provider chunk (``data: {``) is refused as raw output."""
        progress, _, _ = stable_mastery_progress()
        store.save(progress)
        result = service.ensure_draft(
            progress, user_id="owner", path_id="b1", knowledge_point_id="kp1"
        )
        attempt_id = result["attempt"].id
        executor = FakeDraftExecutor(
            result=DraftOutput(title="ok", body="stream chunk\ndata: {raw payload}")
        )
        worker = _worker(store, blob_store, media_store, executor=executor)

        outcome = _run(worker.run_attempt("b1", attempt_id))
        assert outcome["outcome"] == "failed"
        assert store.load("b1").knowledge_cards[0].body == ""
        assert list(blob_store._blobs_dir.glob("*.json")) == []

    def test_raw_data_uri_envelope_rejected(self, store, service, blob_store, media_store):
        """A non-base64 data URI (raw media/text) is still refused."""
        progress, _, _ = stable_mastery_progress()
        store.save(progress)
        result = service.ensure_draft(
            progress, user_id="owner", path_id="b1", knowledge_point_id="kp1"
        )
        attempt_id = result["attempt"].id
        executor = FakeDraftExecutor(
            result=DraftOutput(title="ok", body="attached data:text/plain,secret-material")
        )
        worker = _worker(store, blob_store, media_store, executor=executor)

        outcome = _run(worker.run_attempt("b1", attempt_id))
        assert outcome["outcome"] == "failed"
        assert store.load("b1").knowledge_cards[0].body == ""
        assert list(blob_store._blobs_dir.glob("*.json")) == []


# ── provider-envelope / raw-response rejection (KB-02 GLM residual) ────────


class TestProviderEnvelopeRejection:
    """Raw provider envelopes embedded in title/body must fail validation.

    Regression for the KB-02 GLM rereview: ``_PROVIDER_ENVELOPE_MARKERS`` were
    matched against ``json.dumps(payload)``, which escapes the quotes inside
    embedded JSON (``\\"model\\"``), so the quote-based markers never fired and a
    raw OpenAI/Anthropic response object passed straight through the validator.
    Envelope keys are now matched structurally (quoted key in JSON-key position)
    against the raw title/body strings.
    """

    def _validate(self, title: str, body: str) -> None:
        validate_blob_payload({"title": title, "body": body}, limits=KnowledgeCardLimits())

    @staticmethod
    def _openai_envelope() -> str:
        # Compact enough to sit in a title (<= 200 chars) so rejection is
        # attributable to envelope detection, not the title length bound.
        return (
            '{"id":"chatcmpl-abc123","model":"gpt-4o-mini","choices":[{"message":'
            '{"role":"assistant","content":"The derivative of x^2 is 2x."},'
            '"index":0,"finish_reason":"stop"}]}'
        )

    @staticmethod
    def _anthropic_envelope() -> str:
        return (
            '{"id":"msg_01VkX8p2c6nDfT3hQyLmZr9w","type":"message","role":"assistant",'
            '"model":"claude-sonnet-5","content":[{"type":"text",'
            '"text":"The derivative of x^2 is 2x."}]}'
        )

    def test_raw_provider_json_in_body_is_rejected(self):
        """Regression: an embedded provider JSON object must not pass validation."""
        with pytest.raises(OutputValidationError):
            self._validate("ok", self._openai_envelope())

    def test_raw_provider_json_in_title_is_rejected(self):
        with pytest.raises(OutputValidationError):
            self._validate(self._anthropic_envelope(), "ok")

    def test_openai_style_envelope_rejected_in_both_fields(self):
        envelope = self._openai_envelope()
        with pytest.raises(OutputValidationError):
            self._validate(envelope, "ok")
        with pytest.raises(OutputValidationError):
            self._validate("ok", envelope)

    def test_anthropic_style_envelope_rejected_in_both_fields(self):
        envelope = self._anthropic_envelope()
        with pytest.raises(OutputValidationError):
            self._validate(envelope, "ok")
        with pytest.raises(OutputValidationError):
            self._validate("ok", envelope)

    def test_educational_prose_with_provider_terms_is_accepted(self):
        """Prose that merely mentions a model/ID/choices/tokens/``data:``/
        ``base64`` is legitimate card content, not a provider envelope."""
        self._validate(
            "Growth trends and model choices",
            "The model and its choices over an ID column matter; tokens carry "
            "meaning. The data: shows 42% growth; base64, hex and other "
            "encodings are out of scope.",
        )

    def test_worker_rejects_provider_envelope_without_leaking_blob(
        self, store, service, blob_store, media_store
    ):
        progress, _, _ = stable_mastery_progress()
        store.save(progress)
        result = service.ensure_draft(
            progress, user_id="owner", path_id="b1", knowledge_point_id="kp1"
        )
        attempt_id = result["attempt"].id
        executor = FakeDraftExecutor(result=DraftOutput(title="ok", body=self._openai_envelope()))
        worker = _worker(store, blob_store, media_store, executor=executor)

        outcome = _run(worker.run_attempt("b1", attempt_id))
        assert outcome["outcome"] == "failed"
        assert store.load("b1").knowledge_cards[0].body == ""
        assert list(blob_store._blobs_dir.glob("*.json")) == []


# ── single-flight lease ────────────────────────────────────────────────────


class TestLease:
    def test_only_one_lease_holder_may_call_executor(self, store, service, blob_store, media_store):
        progress, _, _ = stable_mastery_progress()
        store.save(progress)
        result = service.ensure_draft(
            progress, user_id="owner", path_id="b1", knowledge_point_id="kp1"
        )
        attempt_id = result["attempt"].id
        executor = FakeDraftExecutor()
        worker = _worker(store, blob_store, media_store, executor=executor)

        # Worker A claims the lease first.
        progress = store.load("b1")
        attempt = next(a for a in progress.knowledge_card_generation_attempts if a.id == attempt_id)
        worker._claim_lease(progress, attempt, "ownerA", 2000.0)
        worker.save(progress)

        # Worker B tries to run the same attempt -> the lease is unexpired.
        with pytest.raises(KnowledgeCardLeaseError):
            progress = store.load("b1")
            attempt = next(
                a for a in progress.knowledge_card_generation_attempts if a.id == attempt_id
            )
            worker._claim_lease(progress, attempt, "ownerB", 2000.0)

        # Only A's executor call can have happened.
        assert len(executor.inputs) == 0

    def test_renew_and_finish_require_owner_token(self, store, service, blob_store, media_store):
        progress, _, _ = stable_mastery_progress()
        store.save(progress)
        result = service.ensure_draft(
            progress, user_id="owner", path_id="b1", knowledge_point_id="kp1"
        )
        attempt_id = result["attempt"].id
        worker = _worker(store, blob_store, media_store)

        progress = store.load("b1")
        attempt = next(a for a in progress.knowledge_card_generation_attempts if a.id == attempt_id)
        worker._claim_lease(progress, attempt, "ownerA", 2000.0)
        # Stale owner cannot renew.
        with pytest.raises(KnowledgeCardLeaseError):
            worker._renew_lease(attempt, "ownerB", 2100.0)
        # Real owner renews.
        worker._renew_lease(attempt, "ownerA", 2100.0)
        assert attempt.lease_expires_at == 2100.0 + 300.0

    def test_expired_lease_can_be_taken_over(self, store, service, blob_store, media_store):
        progress, _, _ = stable_mastery_progress()
        store.save(progress)
        result = service.ensure_draft(
            progress, user_id="owner", path_id="b1", knowledge_point_id="kp1"
        )
        attempt_id = result["attempt"].id
        worker = _worker(store, blob_store, media_store)

        progress = store.load("b1")
        attempt = next(a for a in progress.knowledge_card_generation_attempts if a.id == attempt_id)
        worker._claim_lease(progress, attempt, "ownerA", 2000.0)
        # Lease expires; a new holder may take over.
        progress = store.load("b1")
        attempt = next(a for a in progress.knowledge_card_generation_attempts if a.id == attempt_id)
        worker._claim_lease(progress, attempt, "ownerB", 3000.0)
        assert attempt.lease_owner == "ownerB"
        assert attempt.status == GenerationAttemptStatus.RUNNING


# ── apply / supersede races ────────────────────────────────────────────────


class TestApplyGuards:
    def test_user_edit_race_supersedes_and_preserves_user_content(
        self, store, service, blob_store, media_store
    ):
        progress, _, _ = stable_mastery_progress()
        store.save(progress)
        result = service.ensure_draft(
            progress, user_id="owner", path_id="b1", knowledge_point_id="kp1"
        )
        attempt_id = result["attempt"].id
        worker = _worker(store, blob_store, media_store)

        payload, blob_ref, blob_hash = _persist_blob(worker)
        _mark_running_with_blob(
            store, worker, attempt_id=attempt_id, blob_ref=blob_ref, blob_hash=blob_hash
        )

        # Concurrent user edit lands while the worker "runs".
        progress = store.load("b1")
        service.edit_draft(
            progress,
            card_id=result["card"].id,
            user_id="owner",
            request_id="edit1",
            expected_card_revision=1,
            title="User edited title",
        )

        # The worker reconciles the late model result.
        progress = store.load("b1")
        attempt = next(a for a in progress.knowledge_card_generation_attempts if a.id == attempt_id)
        worker._complete_with_blob(
            "b1",
            attempt_id,
            "owner1",
            attempt.model_invocation_id,
            payload,
            blob_ref,
            blob_hash,
            reported_model=None,
            reported_version=None,
            usage=None,
        )
        persisted = store.load("b1")
        card = persisted.knowledge_cards[0]
        attempt = persisted.knowledge_card_generation_attempts[0]
        # User content never overwritten.
        assert card.title == "User edited title"
        assert card.body == ""
        assert card.generation_locked_by_user_edit is True
        assert attempt.status == GenerationAttemptStatus.SUPERSEDED_BY_EDIT
        # Blob + audit preserved.
        assert attempt.output_blob_ref == blob_ref
        assert attempt.output_hash == blob_hash
        assert persisted.model_invocations[-1].status == ModelInvocationStatus.COMPLETED

    def test_stale_evidence_race_supersedes_without_overwrite(
        self, store, service, blob_store, media_store
    ):
        progress, _, _ = stable_mastery_progress()
        store.save(progress)
        result = service.ensure_draft(
            progress, user_id="owner", path_id="b1", knowledge_point_id="kp1"
        )
        attempt_id = result["attempt"].id
        worker = _worker(store, blob_store, media_store)

        payload, blob_ref, blob_hash = _persist_blob(worker)
        _mark_running_with_blob(
            store, worker, attempt_id=attempt_id, blob_ref=blob_ref, blob_hash=blob_hash
        )

        # Evidence overturned while the worker runs.
        progress = store.load("b1")
        progress.projections["kp1"].mastery_state = MasteryState.NEEDS_REVISION
        store.save(progress)

        worker._complete_with_blob(
            "b1",
            attempt_id,
            "owner1",
            "",
            payload,
            blob_ref,
            blob_hash,
            reported_model=None,
            reported_version=None,
            usage=None,
        )
        persisted = store.load("b1")
        attempt = persisted.knowledge_card_generation_attempts[0]
        assert attempt.status == GenerationAttemptStatus.SUPERSEDED_BY_EDIT
        assert attempt.output_blob_ref == blob_ref
        assert persisted.knowledge_cards[0].title == ""

    def test_late_result_on_discarded_card_supersedes(
        self, store, service, blob_store, media_store
    ):
        progress, _, _ = stable_mastery_progress()
        store.save(progress)
        result = service.ensure_draft(
            progress, user_id="owner", path_id="b1", knowledge_point_id="kp1"
        )
        attempt_id = result["attempt"].id
        worker = _worker(store, blob_store, media_store)

        payload, blob_ref, blob_hash = _persist_blob(worker)
        _mark_running_with_blob(
            store, worker, attempt_id=attempt_id, blob_ref=blob_ref, blob_hash=blob_hash
        )

        progress = store.load("b1")
        card = progress.knowledge_cards[0]
        card.status = KnowledgeCardStatus.DISCARDED
        store.save(progress)

        worker._complete_with_blob(
            "b1",
            attempt_id,
            "owner1",
            "",
            payload,
            blob_ref,
            blob_hash,
            reported_model=None,
            reported_version=None,
            usage=None,
        )
        persisted = store.load("b1")
        assert (
            persisted.knowledge_card_generation_attempts[0].status
            == GenerationAttemptStatus.SUPERSEDED_BY_EDIT
        )


# ── restart recovery ───────────────────────────────────────────────────────


class TestRestartRecovery:
    def test_queued_stays_runnable(self, store, service, blob_store, media_store):
        progress, _, _ = stable_mastery_progress()
        store.save(progress)
        result = service.ensure_draft(
            progress, user_id="owner", path_id="b1", knowledge_point_id="kp1"
        )
        attempt_id = result["attempt"].id
        worker = _worker(store, blob_store, media_store)
        outcomes = worker.recover()
        assert outcomes == []
        assert (
            store.load("b1").knowledge_card_generation_attempts[0].status
            == GenerationAttemptStatus.QUEUED
        )

    def test_queued_with_missing_frozen_model_fails_closed(
        self, store, service, blob_store, media_store
    ):
        progress, _, _ = stable_mastery_progress()
        store.save(progress)
        result = service.ensure_draft(
            progress, user_id="owner", path_id="b1", knowledge_point_id="kp1"
        )
        attempt_id = result["attempt"].id
        worker = _worker(store, blob_store, media_store)
        progress = store.load("b1")
        progress.knowledge_card_generation_attempts[0].frozen_model_snapshot = None
        store.save(progress)
        # A queued attempt with no frozen model is reconciled (never invoked).
        outcomes = worker.recover()
        persisted = store.load("b1")
        assert (
            persisted.knowledge_card_generation_attempts[0].status == GenerationAttemptStatus.FAILED
        )
        assert any(o["to"] == "failed" for o in outcomes)

    def test_running_with_blob_applies_on_restart(self, store, service, blob_store, media_store):
        progress, _, _ = stable_mastery_progress()
        store.save(progress)
        result = service.ensure_draft(
            progress, user_id="owner", path_id="b1", knowledge_point_id="kp1"
        )
        attempt_id = result["attempt"].id
        worker = _worker(store, blob_store, media_store)
        payload, blob_ref, blob_hash = _persist_blob(worker)
        _mark_running_with_blob(
            store, worker, attempt_id=attempt_id, blob_ref=blob_ref, blob_hash=blob_hash
        )

        outcomes = worker.recover()
        persisted = store.load("b1")
        assert persisted.knowledge_cards[0].title == "Generated title"
        assert persisted.knowledge_cards[0].draft_generation_status == DraftGenerationStatus.READY
        assert (
            persisted.knowledge_card_generation_attempts[0].status
            == GenerationAttemptStatus.SUCCEEDED
        )
        assert any(o["from"] == "running" and o["applied"] == "true" for o in outcomes)

    def test_running_with_blob_but_user_edited_supersedes_on_restart(
        self, store, service, blob_store, media_store
    ):
        progress, _, _ = stable_mastery_progress()
        store.save(progress)
        result = service.ensure_draft(
            progress, user_id="owner", path_id="b1", knowledge_point_id="kp1"
        )
        attempt_id = result["attempt"].id
        worker = _worker(store, blob_store, media_store)
        payload, blob_ref, blob_hash = _persist_blob(worker)
        _mark_running_with_blob(
            store, worker, attempt_id=attempt_id, blob_ref=blob_ref, blob_hash=blob_hash
        )

        progress = store.load("b1")
        service.edit_draft(
            progress,
            card_id=result["card"].id,
            user_id="owner",
            request_id="edit1",
            expected_card_revision=1,
            title="User wins",
        )

        worker.recover()
        persisted = store.load("b1")
        assert persisted.knowledge_cards[0].title == "User wins"
        assert (
            persisted.knowledge_card_generation_attempts[0].status
            == GenerationAttemptStatus.SUPERSEDED_BY_EDIT
        )

    def test_running_without_blob_becomes_unknown(self, store, service, blob_store, media_store):
        progress, _, _ = stable_mastery_progress()
        store.save(progress)
        result = service.ensure_draft(
            progress, user_id="owner", path_id="b1", knowledge_point_id="kp1"
        )
        attempt_id = result["attempt"].id
        worker = _worker(store, blob_store, media_store)

        # Crash right after the lease claim, before any output.
        progress = store.load("b1")
        attempt = next(a for a in progress.knowledge_card_generation_attempts if a.id == attempt_id)
        attempt.status = GenerationAttemptStatus.RUNNING
        attempt.lease_owner = "owner1"
        attempt.lease_expires_at = 2300.0
        attempt.started_at = 2000.0
        store.save(progress)

        outcomes = worker.recover()
        persisted = store.load("b1")
        assert (
            persisted.knowledge_card_generation_attempts[0].status
            == GenerationAttemptStatus.UNKNOWN
        )
        assert (
            persisted.knowledge_card_generation_attempts[0].error_code
            == "restart_no_confirmable_output"
        )
        assert any(o["to"] == "unknown" for o in outcomes)

    def test_terminal_attempts_never_auto_run(self, store, service, blob_store, media_store):
        progress, _, _ = stable_mastery_progress()
        store.save(progress)
        result = service.ensure_draft(
            progress, user_id="owner", path_id="b1", knowledge_point_id="kp1"
        )
        attempt_id = result["attempt"].id
        worker = _worker(store, blob_store, media_store)

        progress = store.load("b1")
        attempt = next(a for a in progress.knowledge_card_generation_attempts if a.id == attempt_id)
        attempt.status = GenerationAttemptStatus.UNKNOWN
        attempt.finished_at = 2000.0
        store.save(progress)

        executor = FakeDraftExecutor()
        worker.set_executor(executor)
        assert worker.recover() == []
        assert executor.inputs == []
        assert (
            store.load("b1").knowledge_card_generation_attempts[0].status
            == GenerationAttemptStatus.UNKNOWN
        )


# ── post-unknown explicit retry keeps history ──────────────────────────────


class TestRetryAfterUnknown:
    def test_retry_appends_and_preserves_old_attempt_and_invocation(
        self, store, service, blob_store, media_store
    ):
        progress, _, _ = stable_mastery_progress()
        store.save(progress)
        result = service.ensure_draft(
            progress, user_id="owner", path_id="b1", knowledge_point_id="kp1"
        )
        card_id = result["card"].id
        first_attempt = result["attempt"].id
        worker = _worker(store, blob_store, media_store)

        # First attempt ends unknown (crash with no confirmable output).
        progress = store.load("b1")
        attempt = progress.knowledge_card_generation_attempts[0]
        attempt.status = GenerationAttemptStatus.UNKNOWN
        attempt.finished_at = 2000.0
        store.save(progress)

        # Explicit retry creates a new append-only attempt.
        progress = store.load("b1")
        retry = service.retry_generation(
            progress,
            card_id=card_id,
            user_id="owner",
            request_id="retry1",
            expected_card_revision=1,
            latest_generation_attempt_id=first_attempt,
        )
        new_attempt = retry["attempt"]
        assert new_attempt.retry_of_generation_attempt_id == first_attempt
        assert new_attempt.status == GenerationAttemptStatus.QUEUED

        # The unknown attempt and its state are preserved, not rewritten.
        persisted = store.load("b1")
        assert (
            persisted.knowledge_card_generation_attempts[0].status
            == GenerationAttemptStatus.UNKNOWN
        )
        assert persisted.knowledge_card_generation_attempts[1].id == new_attempt.id
        # The old attempt is never claimed not to have existed / never auto-run.
        assert persisted.knowledge_card_generation_attempts[0].finished_at == 2000.0
        assert persisted.knowledge_card_generation_attempts[0].error_code == ""

    def test_retry_runs_with_same_frozen_model(self, store, service, blob_store, media_store):
        progress, _, _ = stable_mastery_progress()
        store.save(progress)
        result = service.ensure_draft(
            progress, user_id="owner", path_id="b1", knowledge_point_id="kp1"
        )
        card_id = result["card"].id
        first_attempt = result["attempt"].id
        executor = FakeDraftExecutor()
        worker = _worker(store, blob_store, media_store, executor=executor)

        progress = store.load("b1")
        attempt = progress.knowledge_card_generation_attempts[0]
        attempt.status = GenerationAttemptStatus.UNKNOWN
        attempt.finished_at = 2000.0
        store.save(progress)

        progress = store.load("b1")
        retry = service.retry_generation(
            progress,
            card_id=card_id,
            user_id="owner",
            request_id="retry1",
            expected_card_revision=1,
            latest_generation_attempt_id=first_attempt,
        )
        _run(worker.run_attempt("b1", retry["attempt"].id))

        persisted = store.load("b1")
        assert persisted.knowledge_cards[0].draft_generation_status == DraftGenerationStatus.READY
        assert persisted.knowledge_cards[0].title == "Generated title"
        assert (
            persisted.knowledge_card_generation_attempts[1].status
            == GenerationAttemptStatus.SUCCEEDED
        )
        # The original unknown attempt is untouched.
        assert (
            persisted.knowledge_card_generation_attempts[0].status
            == GenerationAttemptStatus.UNKNOWN
        )
