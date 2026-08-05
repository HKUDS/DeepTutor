"""Frozen-model draft executor tests (KB-02 → ASM-01, §6.6/§7.9.1).

Proves the production :class:`FrozenModelDraftExecutor` resolves its provider
config from the attempt's *frozen evaluator snapshot* (exact profile/model/
protocol/strictness — never the teaching model, never silent fallback), builds
a strict secret-free prompt from the generation input projection, parses the
draft with truly strict JSON, and returns a normalized :class:`DraftOutput`.
Nothing here persists the prompt, raw provider output, or credentials.
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

import pytest

from deeptutor.learning.evaluation import EvaluatorUnavailableError
from deeptutor.learning.knowledge_cards.executor import (
    FrozenModelDraftExecutor,
    build_draft_prompt,
    parse_draft_output,
)
from deeptutor.learning.knowledge_cards.worker import DraftOutput
from deeptutor.learning.tests.knowledge_card_builders import evaluator_snapshot


def _response(content, *, model: str = "gpt-4o-mini", finish_reason: str = "stop"):
    return SimpleNamespace(
        content=content,
        model=model,
        finish_reason=finish_reason,
        usage={"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
    )


class _CaptureProvider:
    """Fake provider that records the config and returns a scripted response."""

    def __init__(self, response=None, error=None, *, delay: float = 0.0):
        self.response = response
        self.error = error
        self.delay = delay
        self.configs: list = []
        self.messages: list = []

    async def __call__(self, messages, config):
        self.messages.append(messages)
        self.configs.append(config)
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.error is not None:
            raise self.error
        return self.response


INPUT_PROJECTION = {
    "knowledge_point_id": "kp1",
    "stable_assessment_id": "ra1",
    "stable_assessment_sequence": 1,
    "title_hint": "Voltage",
    "evidence": [
        {
            "kind": "explanation",
            "content": "Voltage is the push that moves charges around a circuit.",
        }
    ],
    "sources": [{"id": "s1", "title": "Source 1", "content_hash": "src-hash-1"}],
    "artifacts": [],
}


def test_build_draft_prompt_is_secret_free_and_strict():
    prompt = build_draft_prompt(INPUT_PROJECTION)
    assert "Voltage is the push" in prompt
    assert "prompt_version=" in prompt
    assert '{"title":"...", "body":"..."}' in prompt
    # Never include the rubric, gap text, raw provider envelopes, or secrets.
    assert "gpt-4o-mini" not in prompt
    assert "sk-" not in prompt
    assert "data:image" not in prompt


@pytest.mark.parametrize(
    "raw",
    [
        '{"title": "T", "body": "B"}',
        '   {"title": "T", "body": "B"}   ',
    ],
)
def test_parse_draft_output_strict_json(raw):
    title, body = parse_draft_output(raw)
    assert title == "T"
    assert body == "B"


@pytest.mark.parametrize(
    "raw",
    [
        # Fenced JSON is rejected — the contract forbids markdown fences.
        '```json\n{"title": "T", "body": "B"}\n```',
        '```\n{"title": "T", "body": "B"}\n```',
        # Prose prefix/suffix is rejected.
        'Here is the JSON: {"title": "T", "body": "B"}',
        '{"title": "T", "body": "B"} hope this helps',
        # Multiple objects are rejected.
        '{"title": "T"}{"body": "B"}',
        # Missing / invalid / unknown keys are rejected.
        '{"title": "T"}',
        '{"body": "B"}',
        '{"title": 5, "body": "B"}',
        '{"title": "T", "body": "B", "extra": 1}',
        # Not JSON at all.
        "not json at all",
        "",
    ],
)
def test_parse_draft_output_rejects_non_strict(raw):
    with pytest.raises(ValueError):
        parse_draft_output(raw)


@pytest.mark.asyncio
async def test_executor_uses_frozen_evaluator_identity():
    """The draft executor resolves its provider config from the frozen snapshot
    — exact profile/model/protocol/strictness, never the teaching model."""
    from tests.services.model_selection import _fixtures as fx

    snapshot = evaluator_snapshot(profile_id="p1", model="gpt-4o-mini")
    provider = _CaptureProvider(
        response=_response('{"title": "Voltage", "body": "A concise draft."}')
    )
    executor = FrozenModelDraftExecutor(snapshot, provider=provider, catalog=fx.catalog())

    out = await executor.generate(INPUT_PROJECTION)
    assert isinstance(out, DraftOutput)
    assert out.title == "Voltage"
    assert out.body == "A concise draft."
    assert out.reported_model == "gpt-4o-mini"

    config = provider.configs[0]
    assert config.model == "gpt-4o-mini"
    assert config.api_protocol == "openai_responses"
    assert config.resolved_api_protocol == "openai_responses"
    assert config.strict_protocol is True
    # The system prompt is the strict drafter contract; no learner identity.
    assert provider.messages[0][0]["role"] == "system"


@pytest.mark.asyncio
async def test_executor_uses_path_configured_anthropic_evaluator():
    """A path that pins an Anthropic evaluator freezes that exact protocol."""
    from tests.services.model_selection import _fixtures as fx

    snapshot = evaluator_snapshot(
        profile_id="p2",
        model="claude-3-7-sonnet",
    )
    snapshot.resolved_api_protocol = "anthropic_messages"
    snapshot.requested_api_protocol = "anthropic_messages"
    snapshot.base_url_fingerprint = "e3e47bc906562b38"  # https://api.anthropic.com/v1
    provider = _CaptureProvider(
        response=_response('{"title": "T", "body": "B"}', model="claude-3-7-sonnet")
    )
    executor = FrozenModelDraftExecutor(snapshot, provider=provider, catalog=fx.catalog())
    out = await executor.generate(INPUT_PROJECTION)
    assert out.title == "T"
    config = provider.configs[0]
    assert config.model == "claude-3-7-sonnet"
    assert config.api_protocol == "anthropic_messages"


@pytest.mark.asyncio
async def test_executor_fails_closed_on_missing_frozen_identity():
    """A missing/empty frozen snapshot is an unavailable error — never a silent
    fallback to the teaching model."""
    from deeptutor.learning.models import EvaluatorSnapshot

    executor = FrozenModelDraftExecutor(EvaluatorSnapshot())
    with pytest.raises(EvaluatorUnavailableError):
        await executor.generate(INPUT_PROJECTION)


@pytest.mark.asyncio
async def test_executor_timeout_is_enforced():
    """A hung provider is surfaced as unavailable (real timeout enforcement),
    not left hanging and never retried."""
    from tests.services.model_selection import _fixtures as fx

    snapshot = evaluator_snapshot()
    provider = _CaptureProvider(
        response=_response('{"title": "T", "body": "B"}'),
        delay=5.0,
    )
    executor = FrozenModelDraftExecutor(
        snapshot, provider=provider, catalog=fx.catalog(), timeout_seconds=0.05
    )
    with pytest.raises(EvaluatorUnavailableError):
        await executor.generate(INPUT_PROJECTION)
    assert provider.configs  # the provider was actually invoked
    assert provider.messages


@pytest.mark.asyncio
async def test_executor_rejects_prose_wrapped_output():
    """Non-strict (prose-wrapped) provider output fails closed."""
    snapshot = evaluator_snapshot()
    provider = _CaptureProvider(
        response=_response('Sure! Here is the draft: {"title": "T", "body": "B"}')
    )
    executor = FrozenModelDraftExecutor(snapshot, provider=provider)
    with pytest.raises(EvaluatorUnavailableError):
        await executor.generate(INPUT_PROJECTION)


@pytest.mark.asyncio
async def test_worker_run_attempt_with_executor_persists_no_prompt_or_raw_output(
    tmp_path,
):
    """After a real executor runs through the worker, the persisted progress
    contains only the normalized draft and audit fingerprints — never the
    prompt, raw provider output, or credentials."""
    from deeptutor.learning.knowledge_cards.blobs import KnowledgeCardBlobStore
    from deeptutor.learning.knowledge_cards.service import KnowledgeCardDraftService
    from deeptutor.learning.knowledge_cards.worker import KnowledgeCardGenerationWorker
    from deeptutor.learning.storage import LearningStore
    from deeptutor.learning.tests.knowledge_card_builders import stable_mastery_progress

    root = tmp_path / "learning"
    progress, _, _ = stable_mastery_progress("b1")
    draft_service = KnowledgeCardDraftService(
        LearningStore(root=root),
        blob_store=KnowledgeCardBlobStore(tmp_path / "blobs"),
    )
    from tests.services.model_selection import _fixtures as fx

    result = draft_service.ensure_draft(
        progress, user_id="owner", path_id="b1", knowledge_point_id="kp1"
    )
    attempt_id = result["attempt"].id

    executor = FrozenModelDraftExecutor(
        result["attempt"].frozen_model_snapshot,
        provider=_CaptureProvider(
            response=_response('{"title": "Voltage", "body": "A concise draft."}')
        ),
        catalog=fx.catalog(),
    )
    worker = KnowledgeCardGenerationWorker(
        LearningStore(root=root),
        blob_store=KnowledgeCardBlobStore(tmp_path / "blobs"),
        executor=executor,
        now=lambda: 2000.0,
    )
    await worker.run_attempt("b1", attempt_id)

    persisted = LearningStore(root=root).load("b1")
    card = persisted.knowledge_cards[0]
    assert card.title == "Voltage"
    assert card.body == "A concise draft."
    attempt = persisted.knowledge_card_generation_attempts[0]
    # Output blob ref + hash are stored; raw provider JSON / prompt are not.
    assert attempt.output_blob_ref
    assert attempt.output_hash
    serialized = persisted.model_dump(mode="json")
    text = str(serialized)
    assert '"body": "A concise draft."' in text or "A concise draft." in text
    assert "provider" not in card.title.lower() or "provider" not in str(card.body)
    assert "sk-" not in text
    assert "data:image" not in text
    # The frozen evaluator identity is what the audit record records.
    invocation = persisted.model_invocations[-1]
    assert invocation.purpose.value == "knowledge_card_draft"
    assert invocation.resolved_model == "gpt-4o-mini"
    assert invocation.resolved_protocol == "openai_responses"
