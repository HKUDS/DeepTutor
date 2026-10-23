# Teaching-delivery provenance: focused TDD evidence

## Intent

An explanation record must refer to assistant text already published in its
runtime path, session and turn. A model's plan, private sources or reasoning
must not stand in for delivered teaching. A short explanation does not prove
that every part of a composite objective was taught or understood.

The task was planned from the existing Mastery runtime and storage contracts.
It introduces no database migration, extra model call or mastery-credit rule.

## RED and GREEN

Before implementation, running
`python -m pytest tests/capabilities/test_mastery_teaching_delivery.py -q --tb=short`
on the native v1.6.14 baseline executed the tests and produced **15 failed,
1 passed**. In particular, the existing tool successfully persisted a note
describing an explanation that had not yet been published.

After implementation, running
`python -m pytest tests/capabilities/test_mastery_teaching_delivery.py deeptutor/learning/tests/test_visual_learning_workflow.py tests/capabilities/test_mastery_loop_pipeline.py -q --tb=short`
produced **38 passed in 9.37s** in an isolated contribution worktree after
the independent visibility review. The added delivery suite has 18 cases
(13 test functions with parametrization).

The review found that optimistically streamed text can later be retracted by
the native loop. Two additional regression cases initially failed before
the snapshot was corrected. The final suite exercises the actual
`AgentLoop._discard_deferred_output` correction and rejects that prose as
teaching evidence, while preserving unrelated visible content.

The tests use temporary learning stores and emitted stream events; no real
learner path or inference provider is used.

## Guarantees

| Behavior | Proof |
| --- | --- |
| A future explanation cannot be recorded | The rejected call leaves isolated durable state unchanged |
| Public fragments can supply a contiguous exact excerpt | A successful note survives store reload with event-range and turn provenance |
| Thinking, tool results, sources and observations do not count | Each event type is independently rejected |
| Another source, stage, path, session or turn cannot supply evidence | Scoped rejection tests preserve the explanation state |
| Model-supplied private delivery arguments are overwritten | Capability and native-dispatch tests exercise server injection |
| Retracted optimistic prose cannot authorize teaching records | Actual loop-retraction and matching-call visibility tests |
| Snapshots do not expose mutable events or acquire future output | Snapshot-copy test |
| A delivered slice is not whole-objective completion | Partial stage and unchanged mastery/evidence assertions |
| Legacy self-reports are not retroactively certified | Legacy stage test |
| Source-based practice and assistance still work | Existing visual-learning workflow tests |

## Limits

This proves publication and bounded provenance, not whether the learner read
the text, understood it, or whether its semantic content fully teaches the
named objective. Such interpretation remains the tutor's responsibility.

Retrospective notes from an earlier turn are not supported without trusted
delivery references. Legacy notes are preserved without changing assessment
scores. Full-model evaluation, live UI testing and a global coverage run were
not performed for this narrowly scoped correction.
