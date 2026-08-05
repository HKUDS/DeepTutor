"""LRN-03 mastery tool contract tests (spec §17.2).

These drive the actual tools the chat loop mounts: ``mastery_cycle_start`` /
``mastery_record_evidence`` / ``mastery_finalize``. They assert the server
identity contract (model spoofing is ignored), the idempotency/version
contract, the read-only evidence boundary, the server-computed gate (no
``passed``), the WebSocket refresh-hint metadata, the production evaluator
freeze at attempt start, and the frozen-evaluator finalize flow — all without
any real LLM or network call (the evaluator is scripted in-memory).
"""

from __future__ import annotations

import json
from types import SimpleNamespace

import pytest

from deeptutor.capabilities.mastery import tools as mastery_tools
from deeptutor.learning.models import SourceCitation
from deeptutor.learning.storage import LearningStore
from deeptutor.tools.mastery_tool import (
    MasteryBuildTool,
    MasteryCycleStartTool,
    MasteryFinalizeTool,
    MasteryRecordEvidenceTool,
    MasteryStatusTool,
)


@pytest.fixture
def path_id(tmp_path, monkeypatch, evaluator_catalog, fake_evaluator):
    monkeypatch.setattr(LearningStore, "__init__", _store_init_factory(tmp_path))
    return "test_path"


@pytest.fixture
def evaluator_catalog(tmp_path, monkeypatch):
    """Patch the model catalog so the production evaluator resolver resolves.

    The fixture catalog (``tests.services.model_selection._fixtures``) carries
    an active OpenAI Responses profile and an Anthropic evaluator profile. A
    real :class:`ModelCatalogService` is used so ``resolve_llm_runtime_config``
    can call ``get_active_profile``/``get_active_model``.
    """
    import deeptutor.services.config as config_module
    import deeptutor.services.config.model_catalog as config_model_catalog
    from deeptutor.services.config.model_catalog import ModelCatalogService
    from tests.services.model_selection import _fixtures as fx

    data = fx.catalog()
    service = ModelCatalogService(path=tmp_path / "model_catalog.json")
    monkeypatch.setattr(service, "load", lambda: data)
    monkeypatch.setattr(config_module, "get_model_catalog_service", lambda: service)
    monkeypatch.setattr(config_model_catalog, "get_model_catalog_service", lambda: service)
    return data


class _FakeEvaluator:
    """A scripted RubricEvaluator double that appends a real pending record.

    The pending invocation projects the *frozen* evaluator snapshot (exactly
    like the production :class:`RubricEvaluator`), so tests can assert the
    frozen profile/model/protocol lands on the audit record. ``invoke`` can be
    scripted to raise (evaluator unavailable) and counts provider calls.
    """

    def __init__(
        self,
        rubric=None,
        *,
        critical_errors=None,
        strengths=None,
        gaps=None,
        citations=None,
        reported_model=None,
    ):
        self._rubric = rubric or {
            "correctness": 2,
            "completeness": 1,
            "causal_clarity": 1,
            "transfer": 2,
        }
        self._critical_errors = list(critical_errors or [])
        self._strengths = list(strengths or [])
        self._gaps = list(gaps or [])
        self._citations = list(citations or [])
        self.reported_model = reported_model
        #: Number of provider invocations this double was asked to make.
        self.call_count = 0
        #: When set, ``invoke`` raises this error (evaluator unavailable).
        self.invoke_error: BaseException | None = None

    def append_pending(
        self, progress, attempt, *, snapshot=None, session_id="", turn_id="", now=None
    ):
        from deeptutor.learning.evaluation import (
            EvaluatorUnavailableError,
            resolved_snapshot_from_evaluator,
        )
        from deeptutor.services.model_selection.audit import ModelInvocationRecorder

        frozen = snapshot or attempt.evaluator_snapshot
        if frozen is None or not (frozen.profile_id and frozen.resolved_model):
            raise EvaluatorUnavailableError(
                sanitized_error="attempt has no frozen evaluator snapshot"
            )
        resolved = resolved_snapshot_from_evaluator(frozen)
        recorder = ModelInvocationRecorder()
        record = recorder.start(
            progress,
            purpose="evaluation",
            snapshot=resolved,
            session_id=session_id,
            turn_id=turn_id,
            attempt_id=attempt.id,
            now=now,
        )
        return SimpleNamespace(record_id=record.id, snapshot=resolved)

    async def invoke(self, progress, attempt, *, snapshot=None, prompt=None, timeout_seconds=120.0):
        self.call_count += 1
        if self.invoke_error is not None:
            raise self.invoke_error
        from deeptutor.learning.evaluation import EvaluatorOutput
        from deeptutor.learning.models import RubricScores

        citations = [
            SourceCitation(
                source_snapshot_id=str(c["source_snapshot_id"]),
                anchor=str(c.get("anchor") or ""),
            )
            for c in self._citations
        ]
        return (
            EvaluatorOutput(
                rubric=RubricScores(**self._rubric),
                critical_errors=self._critical_errors,
                strengths=self._strengths,
                gap_candidates=self._gaps,
                source_citations=citations,
                reported_model=self.reported_model,
            ),
            self.reported_model,
            None,
        )


@pytest.fixture
def fake_evaluator(monkeypatch):
    """Patch the tool's evaluator client factory with a shared scripted double.

    Tests that need a specific evaluator output mutate the returned instance
    (``fake._citations = [...]``, ``fake._rubric = {...}``) before finalize.
    """
    fake = _FakeEvaluator()
    monkeypatch.setattr(mastery_tools, "_new_evaluator_client", lambda: fake)
    return fake


def _store_init_factory(root):
    def _init(self, root_arg=None):  # mirrors LearningStore.__init__ signature
        from pathlib import Path

        self._root = Path(root) / "learning"
        self._root.mkdir(parents=True, exist_ok=True)

    return _init


async def _build_concept_path(path_id):
    result = await MasteryBuildTool().execute(
        _mastery_path_id=path_id,
        modules=[{"name": "M1", "knowledge_points": [{"name": "Voltage", "type": "concept"}]}],
    )
    assert result.success
    kp_id = json.loads(result.content)["map"]["modules"][0]["knowledge_points"][0]["id"]
    # LRN-03 requires a frozen map/source basis before an attempt can start;
    # a freshly built path has modules but no confirmed map yet.
    _register_map_and_sources(path_id)
    return kp_id


def _register_map_and_sources(path_id):
    """Give the path a confirmed map version freezing source snapshots s1/s2."""
    from deeptutor.learning.cycles import FeynmanCycleService
    from deeptutor.learning.models import KnowledgeMapVersion, SourceSnapshot

    service = FeynmanCycleService(LearningStore())
    progress = service.load(path_id)
    if any(version.version == 1 for version in progress.map_versions):
        return
    progress.source_snapshots.extend(
        [
            SourceSnapshot(id="s1", citation_anchors=["p.3"]),
            SourceSnapshot(id="s2", citation_anchors=["fig.2"]),
        ]
    )
    progress.map_versions.append(
        KnowledgeMapVersion(
            id=f"{path_id}:map:1",
            path_id=path_id,
            version=1,
            source_snapshot_ids=["s1", "s2"],
        )
    )
    service.save(progress)


async def _start_cycle(path_id, kp_id, **injected):
    kwargs = {
        "_mastery_path_id": path_id,
        "knowledge_point_id": kp_id,
        "cycle_type": injected.get("cycle_type", "initial"),
        **_injected_identity(),
    }
    kwargs.update(injected)
    result = await MasteryCycleStartTool().execute(**kwargs)
    return result


def _injected_identity(**overrides):
    identity = {
        "_session_id": "trusted-session",
        "_turn_id": "trusted-turn",
        "_message_id": "trusted-msg",
        "_user_id": "trusted-user",
    }
    identity.update(overrides)
    return identity


def _current_attempt_version(path_id) -> int:
    from deeptutor.learning.cycles import FeynmanCycleService

    progress = FeynmanCycleService(LearningStore()).load(path_id)
    return progress.aggregate_versions.attempt


async def _record(
    path_id, attempt_id, *, kind, event_id, content, question_evidence_id="", **injected
):
    kwargs = {
        "_mastery_path_id": path_id,
        "attempt_id": attempt_id,
        "kind": kind,
        "event_id": event_id,
        "content": content,
        "question_evidence_id": question_evidence_id,
        # §8.3: the concurrency token is required; a test may override it (e.g.
        # with 0) to exercise the stale-version guard.
        "expected_attempt_version": injected.pop(
            "expected_attempt_version", _current_attempt_version(path_id)
        ),
        **_injected_identity(),
    }
    kwargs.update(injected)
    return await MasteryRecordEvidenceTool().execute(**kwargs)


async def _finalize(
    path_id,
    attempt_id,
    *,
    rubric,
    evidence_ids,
    source_citations=None,
    event_id="fin-default",
    **injected,
):
    kwargs = {
        "_mastery_path_id": path_id,
        "attempt_id": attempt_id,
        "rubric": rubric,
        "evidence_ids": evidence_ids,
        "source_citations": source_citations or [],
        "event_id": event_id,
        "expected_attempt_version": injected.pop(
            "expected_attempt_version", _current_attempt_version(path_id)
        ),
        **injected,
    }
    return await MasteryFinalizeTool().execute(**kwargs)


async def _complete_chain(path_id, attempt_id):
    ids: list[str] = []
    r = await _record(
        path_id, attempt_id, kind="explanation", event_id="e-expl", content="My explanation"
    )
    ids.append(json.loads(r.content)["evidence_id"])
    for i, content in enumerate(["Q1?", "Q2?"], start=1):
        q = await _record(
            path_id, attempt_id, kind="probe_question", event_id=f"e-q{i}", content=content
        )
        qid = json.loads(q.content)["evidence_id"]
        a = await _record(
            path_id,
            attempt_id,
            kind="probe_answer",
            event_id=f"e-a{i}",
            content=f"A{i}",
            question_evidence_id=qid,
        )
        ids.append(qid)
        ids.append(json.loads(a.content)["evidence_id"])
    qt = await _record(path_id, attempt_id, kind="transfer_question", event_id="e-qt", content="T?")
    qtid = json.loads(qt.content)["evidence_id"]
    at = await _record(
        path_id,
        attempt_id,
        kind="transfer_answer",
        event_id="e-at",
        content="TA",
        question_evidence_id=qtid,
    )
    ids.append(qtid)
    ids.append(json.loads(at.content)["evidence_id"])
    return ids


# ── identity spoofing ─────────────────────────────────────────────────────


class TestIdentitySpoofing:
    @pytest.mark.asyncio
    async def test_model_supplied_identity_is_ignored(self, path_id):
        kp_id = await _build_concept_path(path_id)
        start = await _start_cycle(path_id, kp_id)
        attempt_id = json.loads(start.content)["attempt_id"]

        # The model tries to spoof session/turn/message ids in its args.
        result = await _record(
            path_id,
            attempt_id,
            kind="explanation",
            event_id="e1",
            content="hello",
            session_id="spoofed-session",
            turn_id="spoofed-turn",
            message_id="spoofed-msg",
            user_id="spoofed-user",
        )
        assert result.success
        payload = json.loads(result.content)
        assert payload["recorded"] is True

        # Read the persisted progress and assert trusted identity was bound.
        from deeptutor.learning.cycles import FeynmanCycleService

        progress = FeynmanCycleService(LearningStore()).load(path_id)
        item = progress.evidence_items[0]
        assert item.session_id == "trusted-session"
        assert item.turn_id == "trusted-turn"
        assert item.message_id == "trusted-msg"

    @pytest.mark.asyncio
    async def test_tool_schema_has_no_identity_parameter(self, path_id):
        definition = MasteryRecordEvidenceTool().get_definition()
        param_names = {p.name for p in definition.parameters}
        assert "session_id" not in param_names
        assert "turn_id" not in param_names
        assert "message_id" not in param_names
        assert "user_id" not in param_names
        # But the server-injected underscore keys are expected via kwargs only.
        assert "attempt_id" in param_names


# ── idempotency / version conflicts ───────────────────────────────────────


class TestEvidenceIdempotency:
    @pytest.mark.asyncio
    async def test_duplicate_event_key_same_payload_replays(self, path_id):
        kp_id = await _build_concept_path(path_id)
        attempt_id = json.loads((await _start_cycle(path_id, kp_id)).content)["attempt_id"]
        first = await _record(
            path_id, attempt_id, kind="explanation", event_id="e1", content="same"
        )
        second = await _record(
            path_id, attempt_id, kind="explanation", event_id="e1", content="same"
        )
        assert json.loads(second.content)["replay"] is True

    @pytest.mark.asyncio
    async def test_duplicate_event_key_different_payload_conflicts(self, path_id):
        kp_id = await _build_concept_path(path_id)
        attempt_id = json.loads((await _start_cycle(path_id, kp_id)).content)["attempt_id"]
        await _record(path_id, attempt_id, kind="explanation", event_id="e1", content="same")
        second = await _record(
            path_id, attempt_id, kind="explanation", event_id="e1", content="different"
        )
        assert second.success is False
        payload = json.loads(second.content)
        assert payload["error_type"] == "EvidenceConflictError"

    @pytest.mark.asyncio
    async def test_stale_expected_attempt_version_conflicts(self, path_id):
        kp_id = await _build_concept_path(path_id)
        start = await _start_cycle(path_id, kp_id)
        attempt_id = json.loads(start.content)["attempt_id"]
        result = await _record(
            path_id,
            attempt_id,
            kind="explanation",
            event_id="e1",
            content="x",
            expected_attempt_version=0,  # stale
        )
        assert result.success is False
        assert json.loads(result.content)["error_type"] == "StaleVersionError"


# ── attempt state boundaries ──────────────────────────────────────────────


class TestAttemptState:
    @pytest.mark.asyncio
    async def test_record_on_invalidated_attempt_rejected(self, path_id):
        kp_id = await _build_concept_path(path_id)
        attempt_id = json.loads((await _start_cycle(path_id, kp_id)).content)["attempt_id"]
        from deeptutor.learning.cycles import FeynmanCycleService

        service = FeynmanCycleService(LearningStore())
        progress = service.load(path_id)
        attempt = next(a for a in progress.attempts if a.id == attempt_id)
        attempt.status = "invalidated"
        service.save(progress)

        result = await _record(path_id, attempt_id, kind="explanation", event_id="e1", content="x")
        assert result.success is False
        assert json.loads(result.content)["error_type"] == "InvalidAttemptStateError"

    @pytest.mark.asyncio
    async def test_finalize_on_invalidated_attempt_rejected(self, path_id):
        kp_id = await _build_concept_path(path_id)
        attempt_id = json.loads((await _start_cycle(path_id, kp_id)).content)["attempt_id"]
        from deeptutor.learning.cycles import FeynmanCycleService

        service = FeynmanCycleService(LearningStore())
        progress = service.load(path_id)
        attempt = next(a for a in progress.attempts if a.id == attempt_id)
        attempt.status = "invalidated"
        service.save(progress)

        result = await MasteryFinalizeTool().execute(
            _mastery_path_id=path_id,
            attempt_id=attempt_id,
            rubric={"correctness": 2, "completeness": 1, "causal_clarity": 1, "transfer": 2},
            evidence_ids=[],
            event_id="fin-invalidated",
            expected_attempt_version=_current_attempt_version(path_id),
        )
        assert result.success is False
        assert json.loads(result.content)["error_type"] == "InvalidAttemptStateError"

    @pytest.mark.asyncio
    async def test_voice_transcript_unconfirmed_rejected(self, path_id):
        kp_id = await _build_concept_path(path_id)
        attempt_id = json.loads((await _start_cycle(path_id, kp_id)).content)["attempt_id"]
        result = await _record(
            path_id,
            attempt_id,
            kind="explanation",
            event_id="e1",
            content="voice",
            input_mode="voice_transcript",
        )
        assert result.success is False


# ── finalize: no passed, server gate ──────────────────────────────────────


class TestFinalizeTool:
    @pytest.mark.asyncio
    async def test_rejects_passed_argument(self, path_id):
        kp_id = await _build_concept_path(path_id)
        attempt_id = json.loads((await _start_cycle(path_id, kp_id)).content)["attempt_id"]
        result = await MasteryFinalizeTool().execute(
            _mastery_path_id=path_id,
            attempt_id=attempt_id,
            rubric={"correctness": 2, "completeness": 1, "causal_clarity": 1, "transfer": 2},
            evidence_ids=[],
            event_id="fin-passed",
            expected_attempt_version=_current_attempt_version(path_id),
            passed=True,
        )
        assert result.success is False
        assert "does not accept 'passed'" in result.content

    @pytest.mark.asyncio
    async def test_full_cycle_provisional_and_refresh_metadata(self, path_id):
        kp_id = await _build_concept_path(path_id)
        _register_map_and_sources(path_id)
        start = await _start_cycle(path_id, kp_id)
        attempt_id = json.loads(start.content)["attempt_id"]
        assert json.loads(start.content)["required_steps"]

        evidence_ids = await _complete_chain(path_id, attempt_id)
        final = await _finalize(
            path_id,
            attempt_id,
            rubric={"correctness": 2, "completeness": 1, "causal_clarity": 1, "transfer": 2},
            evidence_ids=evidence_ids,
            source_citations=[{"source_snapshot_id": "s1", "anchor": "p.3"}],
        )
        assert final.success
        payload = json.loads(final.content)
        assert payload["passed"] is True
        assert payload["mastery_state"] == "provisional_mastery"
        # Tool metadata carries stable refresh hints + trusted ids (no user id).
        metadata = final.metadata
        assert metadata["refresh"]["kind"] == ["map", "attempt", "reviews"]
        assert metadata["refresh"]["path_id"] == path_id
        assert metadata["refresh"]["attempt_id"] == attempt_id
        assert "session_id" not in metadata["refresh"]
        assert "user_id" not in metadata["refresh"]

    @pytest.mark.asyncio
    async def test_citation_outside_frozen_snapshot_fails_gate(self, path_id, fake_evaluator):
        """The evaluator's citation to a non-frozen snapshot fails the gate."""
        kp_id = await _build_concept_path(path_id)
        _register_map_and_sources(path_id)
        attempt_id = json.loads((await _start_cycle(path_id, kp_id)).content)["attempt_id"]
        evidence_ids = await _complete_chain(path_id, attempt_id)
        # The frozen evaluator cites snapshot s99, which is NOT frozen on the
        # attempt (only s1/s2 are); the server gate fails the assessment.
        fake_evaluator._citations = [{"source_snapshot_id": "s99", "anchor": "p.9"}]
        final = await _finalize(
            path_id,
            attempt_id,
            rubric={"correctness": 2, "completeness": 1, "causal_clarity": 1, "transfer": 2},
            evidence_ids=evidence_ids,
        )
        assert final.success
        assert json.loads(final.content)["passed"] is False

    @pytest.mark.asyncio
    async def test_cycle_start_refresh_metadata(self, path_id):
        kp_id = await _build_concept_path(path_id)
        start = await _start_cycle(path_id, kp_id)
        assert start.metadata["refresh"]["kind"] == ["map", "attempt"]
        assert start.metadata["refresh"]["attempt_id"]
        assert "session_id" not in start.metadata["refresh"]


# ── finalize event_id idempotency (finding 8) ─────────────────────────────


class TestFinalizeIdempotencyTool:
    @pytest.mark.asyncio
    async def test_finalize_event_id_replay_after_restart(self, path_id):
        kp_id = await _build_concept_path(path_id)
        attempt_id = json.loads((await _start_cycle(path_id, kp_id)).content)["attempt_id"]
        evidence_ids = await _complete_chain(path_id, attempt_id)
        kwargs = {
            "_mastery_path_id": path_id,
            "attempt_id": attempt_id,
            "rubric": {"correctness": 2, "completeness": 1, "causal_clarity": 1, "transfer": 2},
            "evidence_ids": evidence_ids,
            "source_citations": [{"source_snapshot_id": "s1", "anchor": "p.3"}],
            "event_id": "fin-1",
            "expected_attempt_version": _current_attempt_version(path_id),
        }
        first = await MasteryFinalizeTool().execute(**kwargs)
        assert first.success
        # A fresh service instance reloads from the same store (restart).
        second = await MasteryFinalizeTool().execute(**kwargs)
        assert second.success
        payload = json.loads(second.content)
        assert payload["replayed"] is True
        assert payload["assessment_id"] == json.loads(first.content)["assessment_id"]
        from deeptutor.learning.cycles import FeynmanCycleService

        progress = FeynmanCycleService(LearningStore()).load(path_id)
        assert len(progress.rubric_assessments) == 1

    @pytest.mark.asyncio
    async def test_finalize_event_id_different_payload_conflicts(self, path_id):
        kp_id = await _build_concept_path(path_id)
        attempt_id = json.loads((await _start_cycle(path_id, kp_id)).content)["attempt_id"]
        evidence_ids = await _complete_chain(path_id, attempt_id)
        base = {
            "_mastery_path_id": path_id,
            "attempt_id": attempt_id,
            "rubric": {"correctness": 2, "completeness": 1, "causal_clarity": 1, "transfer": 2},
            "evidence_ids": evidence_ids,
            "source_citations": [{"source_snapshot_id": "s1", "anchor": "p.3"}],
            "event_id": "fin-2",
            "expected_attempt_version": _current_attempt_version(path_id),
        }
        first = await MasteryFinalizeTool().execute(**base)
        assert first.success
        second = await MasteryFinalizeTool().execute(
            **{
                **base,
                "rubric": {"correctness": 1, "completeness": 1, "causal_clarity": 1, "transfer": 2},
            }
        )
        assert second.success is False
        assert json.loads(second.content)["error_type"] == "IdempotencyConflictError"


# ── WebSocket refresh-hint metadata (§8.4) ────────────────────────────────


class _MasteryRegistry:
    """Registry that executes the real mastery tools (for dispatch tests)."""

    _TOOLS = {
        "mastery_cycle_start": MasteryCycleStartTool(),
        "mastery_record_evidence": MasteryRecordEvidenceTool(),
        "mastery_finalize": MasteryFinalizeTool(),
    }

    async def execute(self, name: str, **kwargs):
        tool = self._TOOLS[name]
        return await tool.execute(**kwargs)


class TestWebSocketRefreshMetadata:
    @pytest.mark.asyncio
    async def test_tool_result_event_carries_refresh_hints(self, path_id):
        """The dispatched tool_result event's ``tool_metadata`` exposes stable
        refresh hints + trusted attempt/path ids, never user identity (§8.4)."""
        import asyncio
        import json

        from deeptutor.core.agentic.tool_dispatch import dispatch_tool_calls
        from deeptutor.core.context import UnifiedContext
        from deeptutor.core.stream import StreamEventType
        from deeptutor.core.stream_bus import StreamBus

        kp_id = await _build_concept_path(path_id)
        bus = StreamBus()
        events: list = []

        async def _consume():
            async for event in bus.subscribe():
                events.append(event)

        consumer = asyncio.create_task(_consume())
        await asyncio.sleep(0)

        await dispatch_tool_calls(
            tool_calls=[
                {
                    "id": "tc1",
                    "name": "mastery_cycle_start",
                    "arguments": json.dumps({"knowledge_point_id": kp_id, "cycle_type": "initial"}),
                }
            ],
            context=UnifiedContext(session_id="s1", user_message="teach"),
            stream=bus,
            source="chat",
            stage="responding",
            iteration_index=0,
            registry=_MasteryRegistry(),
            kwarg_augmenter=lambda name, args, ctx: {
                **args,
                "_mastery_path_id": path_id,
                "_session_id": "trusted-session",
                "_turn_id": "trusted-turn",
                "_message_id": "trusted-msg",
                "_user_id": "trusted-user",
            },
        )
        await bus.close()
        await consumer

        tool_results = [e for e in events if e.type == StreamEventType.TOOL_RESULT]
        assert tool_results, "a tool_result event must be emitted"
        meta = tool_results[0].metadata.get("tool_metadata") or {}
        refresh = meta.get("refresh") or {}
        assert refresh.get("kind") == ["map", "attempt"]
        assert refresh.get("path_id") == path_id
        assert refresh.get("attempt_id")
        # User-supplied identity never leaks into the refresh metadata.
        assert "session_id" not in refresh
        assert "user_id" not in refresh
        assert "turn_id" not in refresh


# ── full journey through the tools ────────────────────────────────────────


class TestToolJourney:
    @pytest.mark.asyncio
    async def test_status_reports_active_attempt(self, path_id):
        kp_id = await _build_concept_path(path_id)
        await _start_cycle(path_id, kp_id)
        status = json.loads((await MasteryStatusTool().execute(_mastery_path_id=path_id)).content)
        assert status["status"] == "active"

    @pytest.mark.asyncio
    async def test_status_reports_active_attempt_and_required_steps(self, path_id):
        kp_id = await _build_concept_path(path_id)
        attempt_id = json.loads((await _start_cycle(path_id, kp_id)).content)["attempt_id"]
        status = json.loads((await MasteryStatusTool().execute(_mastery_path_id=path_id)).content)
        active = status["active_attempt"]
        assert active is not None
        assert active["attempt_id"] == attempt_id
        assert "explanation" in active["next_required_steps"]

    @pytest.mark.asyncio
    async def test_provisional_pass_moves_map_cursor(self, path_id):
        """After a Feynman provisional pass the mastered kp is skipped."""
        kp_id = await _build_concept_path(path_id)
        _register_map_and_sources(path_id)
        attempt_id = json.loads((await _start_cycle(path_id, kp_id)).content)["attempt_id"]
        evidence_ids = await _complete_chain(path_id, attempt_id)
        final = await _finalize(
            path_id,
            attempt_id,
            rubric={"correctness": 2, "completeness": 1, "causal_clarity": 1, "transfer": 2},
            evidence_ids=evidence_ids,
            source_citations=[{"source_snapshot_id": "s1", "anchor": "p.3"}],
        )
        assert json.loads(final.content)["passed"] is True
        status = json.loads((await MasteryStatusTool().execute(_mastery_path_id=path_id)).content)
        assert status["next"]["action"] == "complete"
        assert status["map"]["counts"]["mastered"] == 1


# ── Final correction: required idempotency keys + trusted invocation id ────


class TestRequiredIdempotencyKeysTool:
    @pytest.mark.asyncio
    async def test_record_evidence_missing_event_id_rejected(self, path_id):
        kp_id = await _build_concept_path(path_id)
        attempt_id = json.loads((await _start_cycle(path_id, kp_id)).content)["attempt_id"]
        result = await MasteryRecordEvidenceTool().execute(
            _mastery_path_id=path_id,
            attempt_id=attempt_id,
            kind="explanation",
            event_id="",
            content="x",
            expected_attempt_version=1,
            **_injected_identity(),
        )
        assert result.success is False
        assert "event_id" in result.content

    @pytest.mark.asyncio
    async def test_record_evidence_missing_expected_version_rejected(self, path_id):
        kp_id = await _build_concept_path(path_id)
        attempt_id = json.loads((await _start_cycle(path_id, kp_id)).content)["attempt_id"]
        result = await MasteryRecordEvidenceTool().execute(
            _mastery_path_id=path_id,
            attempt_id=attempt_id,
            kind="explanation",
            event_id="e1",
            content="x",
            **_injected_identity(),
        )
        assert result.success is False
        assert "expected_attempt_version" in result.content

    @pytest.mark.asyncio
    async def test_finalize_missing_event_id_rejected(self, path_id):
        kp_id = await _build_concept_path(path_id)
        attempt_id = json.loads((await _start_cycle(path_id, kp_id)).content)["attempt_id"]
        result = await MasteryFinalizeTool().execute(
            _mastery_path_id=path_id,
            attempt_id=attempt_id,
            rubric={"correctness": 2, "completeness": 1, "causal_clarity": 1, "transfer": 2},
            evidence_ids=[],
            expected_attempt_version=1,
        )
        assert result.success is False
        assert "event_id" in result.content

    @pytest.mark.asyncio
    async def test_finalize_missing_expected_version_rejected(self, path_id):
        kp_id = await _build_concept_path(path_id)
        attempt_id = json.loads((await _start_cycle(path_id, kp_id)).content)["attempt_id"]
        result = await MasteryFinalizeTool().execute(
            _mastery_path_id=path_id,
            attempt_id=attempt_id,
            rubric={"correctness": 2, "completeness": 1, "causal_clarity": 1, "transfer": 2},
            evidence_ids=[],
            event_id="fin-x",
        )
        assert result.success is False
        assert "expected_attempt_version" in result.content

    @pytest.mark.asyncio
    async def test_tool_schemas_expose_required_keys(self, path_id):
        record_params = {
            p.name: p.required for p in MasteryRecordEvidenceTool().get_definition().parameters
        }
        assert record_params["event_id"] is True
        assert record_params["expected_attempt_version"] is True
        finalize_params = {
            p.name: p.required for p in MasteryFinalizeTool().get_definition().parameters
        }
        assert finalize_params["event_id"] is True
        assert finalize_params["expected_attempt_version"] is True
        # The invocation id is private: it must not appear as a public parameter.
        assert "model_invocation_id" not in finalize_params


class TestTrustedInvocationIdTool:
    @pytest.mark.asyncio
    async def test_model_supplied_invocation_id_is_ignored(self, path_id):
        """A model-forged invocation id is never promoted; the evaluator's
        pending/terminal invocation record is the only id attached (§7.8)."""
        from deeptutor.learning.cycles import FeynmanCycleService

        kp_id = await _build_concept_path(path_id)
        attempt_id = json.loads((await _start_cycle(path_id, kp_id)).content)["attempt_id"]
        evidence_ids = await _complete_chain(path_id, attempt_id)
        final = await _finalize(
            path_id,
            attempt_id,
            rubric={"correctness": 2, "completeness": 1, "causal_clarity": 1, "transfer": 2},
            evidence_ids=evidence_ids,
            source_citations=[{"source_snapshot_id": "s1", "anchor": "p.3"}],
            model_invocation_id="forged",  # model-supplied public key, never promoted
            _model_invocation_id="forged-server",  # spoofed private key, never promoted
        )
        assert final.success
        progress = FeynmanCycleService(LearningStore()).load(path_id)
        assessment = progress.rubric_assessments[0]
        assert assessment.model_invocation_id != ""
        assert assessment.model_invocation_id != "forged"
        assert assessment.model_invocation_id != "forged-server"
        # The attached id resolves to an evaluation invocation record.
        record = next(
            (r for r in progress.model_invocations if r.id == assessment.model_invocation_id),
            None,
        )
        assert record is not None
        assert record.purpose.value == "evaluation"
        assert record.attempt_id == attempt_id

    @pytest.mark.asyncio
    async def test_evaluator_invocation_id_is_attached(self, path_id):
        """The frozen evaluator's exact evaluation invocation id lands on the
        assessment alongside the frozen snapshot (finding 3)."""
        from deeptutor.learning.cycles import FeynmanCycleService

        kp_id = await _build_concept_path(path_id)
        attempt_id = json.loads((await _start_cycle(path_id, kp_id)).content)["attempt_id"]
        evidence_ids = await _complete_chain(path_id, attempt_id)
        final = await _finalize(
            path_id,
            attempt_id,
            rubric={"correctness": 2, "completeness": 1, "causal_clarity": 1, "transfer": 2},
            evidence_ids=evidence_ids,
            source_citations=[{"source_snapshot_id": "s1", "anchor": "p.3"}],
        )
        assert final.success
        progress = FeynmanCycleService(LearningStore()).load(path_id)
        assessment = progress.rubric_assessments[0]
        assert assessment.model_invocation_id
        # The frozen evaluator snapshot is attached (not empty).
        assert assessment.evaluator_snapshot is not None
        assert assessment.evaluator_snapshot.profile_id
        assert assessment.evaluator_snapshot.resolved_model

    @pytest.mark.asyncio
    async def test_evaluator_audit_has_pending_and_terminal_revisions(
        self, path_id, fake_evaluator
    ):
        """The evaluator call writes a pending (pre-call) + terminal (post-call)
        invocation revision with the frozen protocol/model, and the server
        computes ``passed`` — never the model (§7.8, requirement 2)."""
        from deeptutor.learning.cycles import FeynmanCycleService
        from deeptutor.learning.models import ModelInvocationStatus

        kp_id = await _build_concept_path(path_id)
        _register_map_and_sources(path_id)
        attempt_id = json.loads((await _start_cycle(path_id, kp_id)).content)["attempt_id"]
        evidence_ids = await _complete_chain(path_id, attempt_id)
        final = await _finalize(
            path_id,
            attempt_id,
            rubric={"correctness": 2, "completeness": 1, "causal_clarity": 1, "transfer": 2},
            evidence_ids=evidence_ids,
            source_citations=[{"source_snapshot_id": "s1", "anchor": "p.3"}],
        )
        assert final.success
        progress = FeynmanCycleService(LearningStore()).load(path_id)
        assessment = progress.rubric_assessments[0]
        # Both the pending (rev 1) and terminal (rev 2) revisions are stored.
        records = [r for r in progress.model_invocations if r.id == assessment.model_invocation_id]
        assert len(records) == 2
        assert records[0].status == ModelInvocationStatus.PENDING
        assert records[1].status == ModelInvocationStatus.COMPLETED
        assert records[1].revision == records[0].revision + 1
        # The audit carries the frozen evaluator identity — never the teaching model.
        assert records[1].purpose.value == "evaluation"
        assert records[1].attempt_id == attempt_id
        assert records[1].resolved_model == "gpt-4o-mini"
        assert records[1].resolved_protocol == "openai_responses"
        assert records[1].strict_protocol is True
        # Server computes the gate from evidence + rubric; the model never passes.
        assert assessment.server_gate_result.passed is True
        # The evaluator output carries no ``passed`` verdict for the server to trust.
        assert "passed" not in fake_evaluator._rubric


class TestStaleDifferentEventTool:
    @pytest.mark.asyncio
    async def test_stale_token_cannot_be_reused_for_different_evidence(self, path_id):
        kp_id = await _build_concept_path(path_id)
        attempt_id = json.loads((await _start_cycle(path_id, kp_id)).content)["attempt_id"]
        start_version = _current_attempt_version(path_id)
        first = await _record(path_id, attempt_id, kind="explanation", event_id="e1", content="x")
        assert json.loads(first.content)["attempt_version"] > start_version
        # Reusing the pre-mutation token for a different event is stale.
        second = await _record(
            path_id,
            attempt_id,
            kind="probe_question",
            event_id="e2",
            content="Q?",
            expected_attempt_version=start_version,
        )
        assert second.success is False
        assert json.loads(second.content)["error_type"] == "StaleVersionError"


# ── production evaluator freeze at attempt start (§9.3) ───────────────────


class TestEvaluatorFreezeTool:
    @pytest.mark.asyncio
    async def test_attempt_start_freezes_real_configured_evaluator(self, path_id):
        """The production resolver freezes the active LLM profile at attempt
        start — the attempt's snapshot is nonempty and carries the configured
        profile/model/protocol/strictness (no empty ``EvaluatorSnapshot``)."""
        from deeptutor.learning.cycles import FeynmanCycleService

        kp_id = await _build_concept_path(path_id)
        _register_map_and_sources(path_id)
        attempt_id = json.loads((await _start_cycle(path_id, kp_id)).content)["attempt_id"]
        progress = FeynmanCycleService(LearningStore()).load(path_id)
        attempt = next(a for a in progress.attempts if a.id == attempt_id)
        snapshot = attempt.evaluator_snapshot
        assert snapshot is not None
        assert snapshot.profile_id == "p1"
        assert snapshot.resolved_model == "gpt-4o-mini"
        assert snapshot.resolved_api_protocol == "openai_responses"
        assert snapshot.strict_protocol is True
        assert snapshot.profile_revision
        assert snapshot.base_url_fingerprint

    @pytest.mark.asyncio
    async def test_teaching_model_switch_does_not_mutate_frozen_evaluator(
        self, path_id, evaluator_catalog
    ):
        """Switching the teaching (active) model after start never rewrites the
        attempt's frozen evaluator snapshot (§9.3)."""
        from deeptutor.learning.cycles import FeynmanCycleService

        kp_id = await _build_concept_path(path_id)
        _register_map_and_sources(path_id)
        attempt_id = json.loads((await _start_cycle(path_id, kp_id)).content)["attempt_id"]
        progress = FeynmanCycleService(LearningStore()).load(path_id)
        attempt = next(a for a in progress.attempts if a.id == attempt_id)
        frozen_before = attempt.evaluator_snapshot.model_dump()

        # Simulate a teaching-model switch by moving the active profile.
        evaluator_catalog["services"]["llm"]["active_profile_id"] = "p2"
        evaluator_catalog["services"]["llm"]["active_model_id"] = "m3"

        progress = FeynmanCycleService(LearningStore()).load(path_id)
        attempt = next(a for a in progress.attempts if a.id == attempt_id)
        assert attempt.evaluator_snapshot.model_dump() == frozen_before
        assert attempt.evaluator_snapshot.resolved_model == "gpt-4o-mini"

    @pytest.mark.asyncio
    async def test_path_configured_evaluator_is_frozen(self, path_id):
        """A learning path that pins its own evaluator profile/model freezes that
        exact identity instead of the active profile default."""
        from deeptutor.learning.cycles import FeynmanCycleService

        kp_id = await _build_concept_path(path_id)
        _register_map_and_sources(path_id)
        service = FeynmanCycleService(LearningStore())
        progress = service.load(path_id)
        progress.evaluator_profile_id = "p2"
        progress.evaluator_model_id = "m3"
        service.save(progress)

        attempt_id = json.loads((await _start_cycle(path_id, kp_id)).content)["attempt_id"]
        progress = FeynmanCycleService(LearningStore()).load(path_id)
        attempt = next(a for a in progress.attempts if a.id == attempt_id)
        snapshot = attempt.evaluator_snapshot
        assert snapshot.profile_id == "p2"
        assert snapshot.resolved_model == "claude-3-7-sonnet"
        assert snapshot.resolved_api_protocol == "anthropic_messages"
        assert snapshot.strict_protocol is True

    def test_forged_challenge_snapshot_fails_closed(self, evaluator_catalog):
        """A challenge request that merely names a configured profile/model but
        forges the rest of the frozen snapshot is rejected by the evaluator
        boundary (protocol/strictness/revision/fingerprint verified) (§9.3)."""
        from deeptutor.learning.evaluation import (
            EvaluatorUnavailableError,
            frozen_evaluator_llm_config,
        )
        from deeptutor.learning.models import EvaluatorSnapshot

        forged = EvaluatorSnapshot(
            profile_id="p1",  # configured profile
            resolved_model="gpt-4o-mini",  # configured model
            resolved_api_protocol="openai_chat_completions",  # forged: real is responses
            base_url_fingerprint="forged-fp",
            strict_protocol=False,  # forged: real profile is strict
            profile_revision="forged-rev",
        )
        with pytest.raises(EvaluatorUnavailableError):
            frozen_evaluator_llm_config(
                forged, catalog=evaluator_catalog, verify_against_catalog=True
            )


# ── evaluator unavailable pauses finalize (§9.3) ──────────────────────────


class TestEvaluatorUnavailableTool:
    @pytest.mark.asyncio
    async def test_evaluator_unavailable_pauses_without_assessment_or_mastery(
        self, path_id, fake_evaluator
    ):
        """An unavailable/timeout evaluator pauses finalize with a stable
        sanitized outcome: no assessment is written, mastery never advances, the
        pending invocation is finalized paused, and no fallback model is used."""
        from deeptutor.learning.cycles import FeynmanCycleService
        from deeptutor.learning.evaluation import EvaluatorUnavailableError
        from deeptutor.learning.models import MasteryState, ModelInvocationStatus

        kp_id = await _build_concept_path(path_id)
        _register_map_and_sources(path_id)
        attempt_id = json.loads((await _start_cycle(path_id, kp_id)).content)["attempt_id"]
        evidence_ids = await _complete_chain(path_id, attempt_id)
        fake_evaluator.invoke_error = EvaluatorUnavailableError(
            sanitized_error="provider timed out"
        )

        final = await _finalize(
            path_id,
            attempt_id,
            rubric={"correctness": 2, "completeness": 1, "causal_clarity": 1, "transfer": 2},
            evidence_ids=evidence_ids,
            source_citations=[{"source_snapshot_id": "s1", "anchor": "p.3"}],
        )
        assert final.success is False
        payload = json.loads(final.content)
        assert payload["status"] == "paused"
        assert payload["reason"] == "evaluator_unavailable"
        assert payload["sanitized_error"]

        progress = FeynmanCycleService(LearningStore()).load(path_id)
        # No assessment was written and mastery never advanced to provisional/
        # stable — the attempt stays live and retryable.
        assert progress.rubric_assessments == []
        attempt = next(a for a in progress.attempts if a.id == attempt_id)
        assert attempt.status.value in ("collecting", "ready_to_assess", "draft")
        projection = progress.projections.get(kp_id)
        if projection is not None:
            assert projection.mastery_state not in (
                MasteryState.PROVISIONAL_MASTERY,
                MasteryState.STABLE_MASTERY,
            )
        # The pending invocation was finalized paused (no provider identity guess).
        terminal = [
            r
            for r in progress.model_invocations
            if r.status == ModelInvocationStatus.PAUSED and r.purpose.value == "evaluation"
        ]
        assert terminal, "an evaluation invocation must be finalized paused"
        assert fake_evaluator.call_count == 1

    @pytest.mark.asyncio
    async def test_committed_finalize_replay_does_not_double_call_evaluator(
        self, path_id, fake_evaluator
    ):
        """A committed finalize replays its stored result on retry — the
        evaluator provider is never called a second time (§8.3, requirement 2)."""
        from deeptutor.learning.cycles import FeynmanCycleService

        kp_id = await _build_concept_path(path_id)
        _register_map_and_sources(path_id)
        attempt_id = json.loads((await _start_cycle(path_id, kp_id)).content)["attempt_id"]
        evidence_ids = await _complete_chain(path_id, attempt_id)
        kwargs = {
            "_mastery_path_id": path_id,
            "attempt_id": attempt_id,
            "rubric": {"correctness": 2, "completeness": 1, "causal_clarity": 1, "transfer": 2},
            "evidence_ids": evidence_ids,
            "source_citations": [{"source_snapshot_id": "s1", "anchor": "p.3"}],
            "event_id": "fin-replay-no-double",
            "expected_attempt_version": _current_attempt_version(path_id),
        }
        first = await MasteryFinalizeTool().execute(**kwargs)
        assert first.success
        assert fake_evaluator.call_count == 1

        second = await MasteryFinalizeTool().execute(**kwargs)
        assert second.success
        assert json.loads(second.content)["replayed"] is True
        # The provider was NOT invoked again for the replay.
        assert fake_evaluator.call_count == 1

        progress = FeynmanCycleService(LearningStore()).load(path_id)
        assert len(progress.rubric_assessments) == 1


# ── §6.6 automatic stable-mastery knowledge card ──────────────────────────


class TestStableMasteryAutoCardTool:
    @pytest.mark.asyncio
    async def test_stable_mastery_atomically_creates_one_card_and_queued_attempt(self, path_id):
        """A newly reached ``stable_mastery`` creates exactly one empty eligible
        draft shell plus its first queued generation attempt in the same CAS save
        as the finalize; provisional mastery creates none (§6.6)."""
        from deeptutor.learning.cycles import FeynmanCycleService
        from deeptutor.learning.models import (
            DraftGenerationStatus,
            GenerationAttemptStatus,
            KnowledgeCardStatus,
        )

        kp_id = await _build_concept_path(path_id)
        _register_map_and_sources(path_id)
        identity = {"_user_id": "trusted-user"}

        # Initial pass -> provisional_mastery: no card.
        attempt1 = json.loads((await _start_cycle(path_id, kp_id)).content)["attempt_id"]
        ev1 = await _complete_chain(path_id, attempt1)
        first = await _finalize(
            path_id,
            attempt1,
            rubric={"correctness": 2, "completeness": 1, "causal_clarity": 1, "transfer": 2},
            evidence_ids=ev1,
            source_citations=[{"source_snapshot_id": "s1", "anchor": "p.3"}],
            **identity,
        )
        assert json.loads(first.content)["mastery_state"] == "provisional_mastery"

        # Delayed reteach pass -> stable_mastery: card auto-created.
        attempt2 = json.loads(
            (await _start_cycle(path_id, kp_id, cycle_type="delayed_reteach")).content
        )["attempt_id"]
        ev2 = await _complete_chain(path_id, attempt2)
        second = await _finalize(
            path_id,
            attempt2,
            rubric={"correctness": 2, "completeness": 1, "causal_clarity": 1, "transfer": 2},
            evidence_ids=ev2,
            source_citations=[{"source_snapshot_id": "s1", "anchor": "p.3"}],
            event_id="fin-stable",
            **identity,
        )
        payload = json.loads(second.content)
        assert payload["passed"] is True
        assert payload["mastery_state"] == "stable_mastery"

        progress = FeynmanCycleService(LearningStore()).load(path_id)
        cards = progress.knowledge_cards
        assert len(cards) == 1
        card = cards[0]
        assert card.status == KnowledgeCardStatus.DRAFT
        assert card.draft_generation_status == DraftGenerationStatus.QUEUED
        assert card.user_id == "trusted-user"
        assert card.path_id == path_id
        # Bound to the current latest valid stable assessment.
        assert card.stable_assessment_id == progress.projections[kp_id].latest_assessment_id
        assert card.stable_attempt_id == attempt2
        attempts = progress.knowledge_card_generation_attempts
        assert len(attempts) == 1
        queued = attempts[0]
        assert queued.card_id == card.id
        assert queued.status == GenerationAttemptStatus.QUEUED
        assert queued.frozen_model_snapshot is not None
        assert queued.frozen_model_snapshot.resolved_model

    @pytest.mark.asyncio
    async def test_provisional_mastery_creates_no_card(self, path_id):
        from deeptutor.learning.cycles import FeynmanCycleService

        kp_id = await _build_concept_path(path_id)
        _register_map_and_sources(path_id)
        attempt_id = json.loads((await _start_cycle(path_id, kp_id)).content)["attempt_id"]
        evidence_ids = await _complete_chain(path_id, attempt_id)
        final = await _finalize(
            path_id,
            attempt_id,
            rubric={"correctness": 2, "completeness": 1, "causal_clarity": 1, "transfer": 2},
            evidence_ids=evidence_ids,
            source_citations=[{"source_snapshot_id": "s1", "anchor": "p.3"}],
            _user_id="trusted-user",
        )
        assert json.loads(final.content)["mastery_state"] == "provisional_mastery"
        progress = FeynmanCycleService(LearningStore()).load(path_id)
        assert progress.knowledge_cards == []
        assert progress.knowledge_card_generation_attempts == []

    @pytest.mark.asyncio
    async def test_stable_mastery_card_failure_prevents_commit(self, path_id, monkeypatch):
        """A card-transition failure prevents the aggregate mutation from
        committing: the persisted progress stays pre-finalize (no assessment,
        mastery still provisional, no card, no generation attempt) and the tool
        returns a stable sanitized paused outcome instead of swallowing the
        failure (finding 2)."""
        from deeptutor.learning.cycles import FeynmanCycleService
        from deeptutor.learning.knowledge_cards.errors import KnowledgeCardStateError
        from deeptutor.learning.models import MasteryState

        kp_id = await _build_concept_path(path_id)
        _register_map_and_sources(path_id)
        identity = {"_user_id": "trusted-user"}

        attempt1 = json.loads((await _start_cycle(path_id, kp_id)).content)["attempt_id"]
        ev1 = await _complete_chain(path_id, attempt1)
        await _finalize(
            path_id,
            attempt1,
            rubric={"correctness": 2, "completeness": 1, "causal_clarity": 1, "transfer": 2},
            evidence_ids=ev1,
            source_citations=[{"source_snapshot_id": "s1", "anchor": "p.3"}],
            **identity,
        )

        attempt2 = json.loads(
            (await _start_cycle(path_id, kp_id, cycle_type="delayed_reteach")).content
        )["attempt_id"]
        ev2 = await _complete_chain(path_id, attempt2)

        def _fail_card(*args, **kwargs):
            raise KnowledgeCardStateError("card slot occupied by a publishing card")

        monkeypatch.setattr(mastery_tools, "_auto_create_stable_card", _fail_card)
        second = await _finalize(
            path_id,
            attempt2,
            rubric={"correctness": 2, "completeness": 1, "causal_clarity": 1, "transfer": 2},
            evidence_ids=ev2,
            source_citations=[{"source_snapshot_id": "s1", "anchor": "p.3"}],
            event_id="fin-stable-fail",
            **identity,
        )
        assert second.success is False
        payload = json.loads(second.content)
        assert payload["status"] == "paused"
        assert payload["reason"] == "auto_card_unavailable"
        assert payload["sanitized_error"]

        progress = FeynmanCycleService(LearningStore()).load(path_id)
        # The delayed-reteach assessment never persisted; mastery is still
        # provisional and no card/attempt exists.
        assert all(a.attempt_id != attempt2 for a in progress.rubric_assessments)
        assert progress.projections[kp_id].mastery_state == MasteryState.PROVISIONAL_MASTERY
        assert progress.knowledge_cards == []
        assert progress.knowledge_card_generation_attempts == []

    @pytest.mark.asyncio
    async def test_stable_mastery_auto_card_replay_does_not_duplicate(self, path_id):
        """Replaying a committed stable finalize returns the prior result and
        never creates a second card or generation attempt (§6.6, §8.3)."""
        from deeptutor.learning.cycles import FeynmanCycleService

        kp_id = await _build_concept_path(path_id)
        _register_map_and_sources(path_id)
        identity = {"_user_id": "trusted-user"}

        attempt1 = json.loads((await _start_cycle(path_id, kp_id)).content)["attempt_id"]
        ev1 = await _complete_chain(path_id, attempt1)
        await _finalize(
            path_id,
            attempt1,
            rubric={"correctness": 2, "completeness": 1, "causal_clarity": 1, "transfer": 2},
            evidence_ids=ev1,
            source_citations=[{"source_snapshot_id": "s1", "anchor": "p.3"}],
            **identity,
        )

        attempt2 = json.loads(
            (await _start_cycle(path_id, kp_id, cycle_type="delayed_reteach")).content
        )["attempt_id"]
        ev2 = await _complete_chain(path_id, attempt2)
        kwargs = {
            "_mastery_path_id": path_id,
            "attempt_id": attempt2,
            "rubric": {"correctness": 2, "completeness": 1, "causal_clarity": 1, "transfer": 2},
            "evidence_ids": ev2,
            "source_citations": [{"source_snapshot_id": "s1", "anchor": "p.3"}],
            "event_id": "fin-stable-idem",
            "expected_attempt_version": _current_attempt_version(path_id),
            **identity,
        }
        first = await MasteryFinalizeTool().execute(**kwargs)
        assert json.loads(first.content)["mastery_state"] == "stable_mastery"

        second = await MasteryFinalizeTool().execute(**kwargs)
        assert second.success
        assert json.loads(second.content)["replayed"] is True

        progress = FeynmanCycleService(LearningStore()).load(path_id)
        assert len(progress.knowledge_cards) == 1
        assert len(progress.knowledge_card_generation_attempts) == 1


class TestFinalizePostProviderCASRetryTool:
    @pytest.mark.asyncio
    async def test_version_conflict_after_provider_commits_same_output_once(
        self, path_id, fake_evaluator, monkeypatch
    ):
        """A version conflict injected *after* the evaluator returns commits the
        same already-received output on retry without a second provider call and
        without a second pending invocation record (finding 3)."""
        from deeptutor.learning.cycles import FeynmanCycleService, StaleVersionError

        kp_id = await _build_concept_path(path_id)
        _register_map_and_sources(path_id)
        attempt_id = json.loads((await _start_cycle(path_id, kp_id)).content)["attempt_id"]
        evidence_ids = await _complete_chain(path_id, attempt_id)

        real_save = FeynmanCycleService.save
        state = {"injected": False}

        def patched_save(self, progress):
            # Inject the conflict on the first save that happens AFTER the
            # provider call (the pending-invocation save precedes it).
            if fake_evaluator.call_count >= 1 and not state["injected"]:
                state["injected"] = True
                store = self._store
                persisted = store.load(progress.book_id)
                if persisted is not None:
                    # ``store.save`` bumps the persisted version, simulating a
                    # concurrent writer landing between our reload and our save.
                    store.save(persisted)
                raise StaleVersionError(
                    f"stale save rejected: expected {progress.version}, "
                    "persisted bumped by a concurrent writer"
                )
            return real_save(self, progress)

        monkeypatch.setattr(FeynmanCycleService, "save", patched_save)

        final = await _finalize(
            path_id,
            attempt_id,
            rubric={"correctness": 2, "completeness": 1, "causal_clarity": 1, "transfer": 2},
            evidence_ids=evidence_ids,
            source_citations=[{"source_snapshot_id": "s1", "anchor": "p.3"}],
            event_id="fin-cas-retry",
        )
        assert final.success
        payload = json.loads(final.content)
        assert payload["passed"] is True
        assert payload["mastery_state"] == "provisional_mastery"
        # The provider was invoked exactly once despite the injected conflict.
        assert fake_evaluator.call_count == 1

        progress = FeynmanCycleService(LearningStore()).load(path_id)
        assert len(progress.rubric_assessments) == 1
        assessment = progress.rubric_assessments[0]
        records = [r for r in progress.model_invocations if r.id == assessment.model_invocation_id]
        # Pending (rev 1) + terminal (rev 2); never a second pending record.
        assert len(records) == 2
        assert records[0].status.value == "pending"
        assert records[1].status.value == "completed"

    @pytest.mark.asyncio
    async def test_conflicting_event_payload_still_fails_closed(self, path_id, fake_evaluator):
        """A different client payload under the same event_id is a stable
        conflict even when the evaluator already ran — never silently applied."""
        from deeptutor.learning.cycles import FeynmanCycleService

        kp_id = await _build_concept_path(path_id)
        _register_map_and_sources(path_id)
        attempt_id = json.loads((await _start_cycle(path_id, kp_id)).content)["attempt_id"]
        evidence_ids = await _complete_chain(path_id, attempt_id)
        base = {
            "_mastery_path_id": path_id,
            "attempt_id": attempt_id,
            "rubric": {"correctness": 2, "completeness": 1, "causal_clarity": 1, "transfer": 2},
            "evidence_ids": evidence_ids,
            "source_citations": [{"source_snapshot_id": "s1", "anchor": "p.3"}],
            "event_id": "fin-cas-conflict",
            "expected_attempt_version": _current_attempt_version(path_id),
        }
        first = await MasteryFinalizeTool().execute(**base)
        assert first.success
        second = await MasteryFinalizeTool().execute(
            **{
                **base,
                "rubric": {"correctness": 1, "completeness": 1, "causal_clarity": 1, "transfer": 2},
            }
        )
        assert second.success is False
        assert json.loads(second.content)["error_type"] == "IdempotencyConflictError"
        # The conflicting payload did not produce a second assessment.
        progress = FeynmanCycleService(LearningStore()).load(path_id)
        assert len(progress.rubric_assessments) == 1
