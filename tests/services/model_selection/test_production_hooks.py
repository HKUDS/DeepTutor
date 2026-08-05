"""Production-boundary offline integration tests (MOD-03, §7.8 / §9.4).

These prove the shared LLM boundary and the audit seam actually wire
``ModelInvocationRecorder`` into real call paths: a ``pending`` record is
persisted *before* the provider request and finalized after success/failure.
No real endpoint is ever touched — providers are scripted in-memory.
"""

from __future__ import annotations

import pytest

from deeptutor.learning.models import (
    LearningProgress,
    ModelInvocationPurpose,
    ModelInvocationStatus,
)
from deeptutor.learning.storage import LearningStore, find_model_invocation
from deeptutor.services.llm import factory
from deeptutor.services.llm.types import TutorResponse
from deeptutor.services.model_selection import (
    ModelInvocationAuditContext,
    ModelSelector,
    finish_audited_invocation,
    run_audited_completion,
    start_audited_invocation,
    to_audit_view,
)
from deeptutor.services.model_selection.llm import LLMSelection

from . import _fixtures as fx


@pytest.fixture
def store(tmp_path):
    return LearningStore(root=tmp_path)


def _snapshot():
    return ModelSelector(catalog=fx.catalog()).resolve_evaluator(
        LLMSelection(profile_id="p1", model_id="m1")
    )


def _ctx(
    store, *, purpose=ModelInvocationPurpose.CHAT, book_id="b1"
) -> ModelInvocationAuditContext:
    return ModelInvocationAuditContext(
        purpose=purpose,
        book_id=book_id,
        store=store,
        snapshot=_snapshot(),
        session_id="s1",
        turn_id="t1",
    )


# ── the audit seam: persist-before-call ───────────────────────────────────


class TestAuditSeam:
    def test_start_persists_pending_before_provider_call(self, store):
        progress = LearningProgress(book_id="b1")
        store.save(progress)
        ctx = _ctx(store)

        record_id = start_audited_invocation(ctx, ctx.snapshot)

        # The pending record is on disk before any provider call.
        loaded = store.load("b1")
        record = find_model_invocation(loaded, record_id)
        assert record.status == ModelInvocationStatus.PENDING
        assert record.started_at is not None
        assert record.purpose == ModelInvocationPurpose.CHAT
        assert record.session_id == "s1"
        assert record.turn_id == "t1"

        finish_audited_invocation(
            ctx,
            record_id,
            status=ModelInvocationStatus.COMPLETED,
            reported_model="gpt-4o-mini",
        )
        loaded = store.load("b1")
        latest = find_model_invocation(loaded, record_id)
        assert latest.status == ModelInvocationStatus.COMPLETED
        assert latest.provider_reported_model == "gpt-4o-mini"
        # Append-only: pending revision preserved.
        assert loaded.model_invocations[0].status == ModelInvocationStatus.PENDING

    def test_disabled_context_is_legacy_noop(self, store):
        ctx = ModelInvocationAuditContext(
            purpose=ModelInvocationPurpose.CHAT,
            book_id="b1",
            store=None,
            snapshot=_snapshot(),
        )
        assert start_audited_invocation(ctx) is None

    def test_run_audited_completion_success_and_failure(self, store):
        progress = LearningProgress(book_id="b1")
        store.save(progress)
        ctx = _ctx(store)

        async def _ok():
            loaded = store.load("b1")
            assert any(r.status == ModelInvocationStatus.PENDING for r in loaded.model_invocations)
            return "result"

        result = asyncio_run(run_audited_completion(ctx, _ok))
        assert result == "result"
        loaded = store.load("b1")
        assert find_model_invocation(loaded, loaded.model_invocations[0].id).status == (
            ModelInvocationStatus.COMPLETED
        )

        async def _boom():
            raise RuntimeError("upstream timeout")

        with pytest.raises(RuntimeError):
            asyncio_run(run_audited_completion(ctx, _boom))
        loaded = store.load("b1")
        # The failure finalized a second invocation as failed with a sanitized
        # error and a stable error code.
        latest_by_id = {r.id: find_model_invocation(loaded, r.id) for r in loaded.model_invocations}
        assert any(r.status == ModelInvocationStatus.FAILED for r in latest_by_id.values())
        failed = next(r for r in latest_by_id.values() if r.status == ModelInvocationStatus.FAILED)
        assert failed.error_code == "runtime"
        assert "upstream timeout" in failed.sanitized_error

    def test_to_audit_view_projects_latest_revision(self, store):
        progress = LearningProgress(book_id="b1")
        store.save(progress)
        ctx = _ctx(store)
        record_id = start_audited_invocation(ctx, ctx.snapshot)
        finish_audited_invocation(
            ctx,
            record_id,
            status=ModelInvocationStatus.COMPLETED,
            reported_model="gpt-4o-mini",
        )
        loaded = store.load("b1")
        view = to_audit_view(loaded, record_id)
        assert view["revision"] == 2
        assert view["status"] == "completed"
        assert view["provider_reported_model"] == "gpt-4o-mini"


# ── the shared LLM boundary (factory.complete / stream) ───────────────────


class _FakeProvider:
    """Scripted provider that asserts persist-before-call on every call."""

    def __init__(self, store, *, fail: bool = False) -> None:
        self.store = store
        self.fail = fail

    async def chat_with_retry(self, **kwargs: object) -> TutorResponse:
        loaded = self.store.load("b1")
        assert loaded is not None
        assert any(r.status == ModelInvocationStatus.PENDING for r in loaded.model_invocations), (
            "pending record must be persisted before the provider request"
        )
        if self.fail:
            raise RuntimeError("provider exploded")
        return TutorResponse(
            content="hello",
            model="gpt-4o-mini",
            usage={"prompt_tokens": 3, "completion_tokens": 2, "total_tokens": 5},
        )


@pytest.mark.asyncio
async def test_factory_complete_audits_persist_before_call(monkeypatch, store):
    progress = LearningProgress(book_id="b1")
    store.save(progress)
    fake = _FakeProvider(store)
    monkeypatch.setattr(factory, "get_runtime_provider", lambda config: fake)

    out = await factory.complete(
        "hi",
        model="gpt-4o-mini",
        api_key="sk-test",
        base_url="https://api.example.com/v1",
        binding="openai",
        messages=[{"role": "user", "content": "hi"}],
        model_invocation_audit=_ctx(store),
    )
    assert out == "hello"

    loaded = store.load("b1")
    record = find_model_invocation(loaded, loaded.model_invocations[0].id)
    assert record.status == ModelInvocationStatus.COMPLETED
    assert record.provider_reported_model == "gpt-4o-mini"
    assert record.usage.total_tokens == 5
    assert record.started_at is not None and record.finished_at is not None
    assert record.finished_at >= record.started_at


@pytest.mark.asyncio
async def test_factory_complete_finalizes_failed_on_exception(monkeypatch, store):
    progress = LearningProgress(book_id="b1")
    store.save(progress)
    fake = _FakeProvider(store, fail=True)
    monkeypatch.setattr(factory, "get_runtime_provider", lambda config: fake)

    with pytest.raises(Exception):
        await factory.complete(
            "hi",
            model="gpt-4o-mini",
            api_key="sk-test",
            base_url="https://api.example.com/v1",
            binding="openai",
            messages=[{"role": "user", "content": "hi"}],
            model_invocation_audit=_ctx(store),
        )

    loaded = store.load("b1")
    record = find_model_invocation(loaded, loaded.model_invocations[0].id)
    assert record.status == ModelInvocationStatus.FAILED
    assert record.error_code == "runtime"
    assert "provider exploded" in record.sanitized_error
    # No secret from the snapshot ever leaks.
    assert "sk-test" not in record.sanitized_error


@pytest.mark.asyncio
async def test_factory_complete_legacy_no_audit_preserves_behavior(monkeypatch, store):
    progress = LearningProgress(book_id="b1")
    store.save(progress)

    class _PlainProvider:
        async def chat_with_retry(self, **kwargs: object) -> TutorResponse:
            return TutorResponse(content="hello")

    monkeypatch.setattr(factory, "get_runtime_provider", lambda config: _PlainProvider())

    out = await factory.complete(
        "hi",
        model="gpt-4o-mini",
        api_key="sk-test",
        base_url="https://api.example.com/v1",
        binding="openai",
        messages=[{"role": "user", "content": "hi"}],
    )
    assert out == "hello"
    # No audit context → no audit record is created.
    loaded = store.load("b1")
    assert loaded.model_invocations == []


@pytest.mark.asyncio
async def test_factory_stream_audits_and_finalizes(monkeypatch, store):
    progress = LearningProgress(book_id="b1")
    store.save(progress)

    class _FakeStreamProvider:
        def __init__(self, s):
            self.store = s

        async def chat_stream_with_retry(self, *, on_content_delta, on_reasoning_delta, **kwargs):
            loaded = self.store.load("b1")
            assert any(
                r.status == ModelInvocationStatus.PENDING for r in loaded.model_invocations
            ), "pending record must be persisted before the stream request"
            await on_content_delta("he")
            await on_content_delta("llo")
            return TutorResponse(content="hello", finish_reason="stop")

    monkeypatch.setattr(factory, "get_runtime_provider", lambda config: _FakeStreamProvider(store))

    chunks: list[str] = []
    async for chunk in factory.stream(
        "hi",
        model="gpt-4o-mini",
        api_key="sk-test",
        base_url="https://api.example.com/v1",
        binding="openai",
        messages=[{"role": "user", "content": "hi"}],
        model_invocation_audit=_ctx(store),
    ):
        chunks.append(chunk)

    assert "".join(chunks) == "hello"
    loaded = store.load("b1")
    record = find_model_invocation(loaded, loaded.model_invocations[0].id)
    assert record.status == ModelInvocationStatus.COMPLETED
    assert record.finished_at is not None


def asyncio_run(coro):
    import asyncio

    return asyncio.run(coro)
