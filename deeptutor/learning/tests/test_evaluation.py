"""Evaluator boundary tests (MOD-03 → ASM-01, §9.3/§7.6).

Covers the truly-strict evaluator JSON contract (no markdown fences, no prose
prefix/suffix, exactly one object, missing/unknown keys rejected) and the
server-canonical challenge evaluator identity verification. Nothing here
persists raw provider output or credentials.
"""

from __future__ import annotations

import json

import pytest

from deeptutor.learning.evaluation import (
    EvaluatorUnavailableError,
    frozen_evaluator_llm_config,
    parse_evaluator_output,
)

ALLOWED = frozenset({"s1", "s2"})


def _valid() -> str:
    return (
        '{"rubric":{"correctness":2,"completeness":1,"causal_clarity":1,'
        '"transfer":2},"critical_errors":[],"strengths":["clear"],'
        '"gaps":[],"source_citations":[{"source_snapshot_id":"s1","anchor":"p.3"}]}'
    )


# ── truly strict JSON (finding 4) ─────────────────────────────────────────


@pytest.mark.parametrize(
    "raw",
    [
        _valid(),
        f"   {_valid()}   ",
    ],
)
def test_parse_evaluator_output_accepts_exact_object(raw):
    output = parse_evaluator_output(raw, allowed_snapshot_ids=ALLOWED)
    assert output.rubric.correctness == 2
    assert output.source_citations[0].source_snapshot_id == "s1"


@pytest.mark.parametrize(
    "raw",
    [
        # Markdown fences are forbidden by the strict contract.
        f"```json\n{_valid()}\n```",
        f"```\n{_valid()}\n```",
        # Prose prefix / suffix.
        f"Here is the JSON: {_valid()}",
        f"{_valid()} hope this helps",
        # Multiple objects.
        f"{_valid()}{_valid()}",
        '{"rubric":{"correctness":2,"completeness":1,"causal_clarity":1,'
        '"transfer":2},"critical_errors":[],"strengths":[],"gaps":[],'
        '"source_citations":[]}{"rubric":{"correctness":2,"completeness":1,'
        '"causal_clarity":1,"transfer":2},"critical_errors":[],"strengths":[],'
        '"gaps":[],"source_citations":[]}',
        # Missing required key.
        '{"critical_errors":[],"strengths":[],"gaps":[],"source_citations":[]}',
        # Unknown key.
        '{"rubric":{"correctness":2,"completeness":1,"causal_clarity":1,'
        '"transfer":2},"critical_errors":[],"strengths":[],"gaps":[],'
        '"source_citations":[],"passed":true}',
        # Invalid type.
        '{"rubric":"pass","critical_errors":[],"strengths":[],"gaps":[],"source_citations":[]}',
        # Not JSON at all / empty.
        "not json at all",
        "",
    ],
)
def test_parse_evaluator_output_rejects_non_strict(raw):
    with pytest.raises(ValueError):
        parse_evaluator_output(raw, allowed_snapshot_ids=ALLOWED)


# ── complete exact key set (round-3 strict output) ─────────────────────────


_CONTRACT_KEYS = (
    "rubric",
    "critical_errors",
    "strengths",
    "gaps",
    "source_citations",
)


def _valid_with_empty_arrays() -> str:
    return (
        '{"rubric":{"correctness":2,"completeness":1,"causal_clarity":1,'
        '"transfer":2},"critical_errors":[],"strengths":[],"gaps":[],'
        '"source_citations":[]}'
    )


@pytest.mark.parametrize("omitted", _CONTRACT_KEYS)
def test_parse_evaluator_output_rejects_each_missing_contract_key(omitted):
    """Every contract key is individually required — omitting any one of them,
    including each of the four collection keys, must fail closed instead of
    silently coercing to an empty collection."""
    data = json.loads(_valid())
    del data[omitted]
    with pytest.raises(ValueError):
        parse_evaluator_output(json.dumps(data), allowed_snapshot_ids=ALLOWED)


def test_parse_evaluator_output_accepts_explicit_empty_arrays():
    """Explicit empty arrays stay valid — only key *omission* is rejected."""
    output = parse_evaluator_output(_valid_with_empty_arrays(), allowed_snapshot_ids=ALLOWED)
    assert output.rubric.correctness == 2
    assert output.critical_errors == []
    assert output.strengths == []
    assert output.gap_candidates == []
    assert output.source_citations == []


# ── server-canonical challenge evaluator identity (finding 5) ─────────────


def _catalog():
    from tests.services.model_selection import _fixtures as fx

    return fx.catalog()


def _complete_snapshot():
    from deeptutor.learning.tests.knowledge_card_builders import evaluator_snapshot

    # The builder's values match the fixture catalog's p1 profile exactly
    # (profile_revision is recomputed against the real catalog below).
    snap = evaluator_snapshot(profile_id="p1", model="gpt-4o-mini")
    from deeptutor.services.model_selection.fingerprint import profile_revision

    service = _catalog()["services"]["llm"]
    profile = next(p for p in service["profiles"] if p["id"] == "p1")
    snap.profile_revision = profile_revision(profile)
    return snap


def test_complete_valid_challenge_snapshot_passes_boundary():
    """A complete server-canonical snapshot (all identity fields present and
    matching the configured profile) passes the evaluator boundary."""
    config = frozen_evaluator_llm_config(
        _complete_snapshot(), catalog=_catalog(), verify_against_catalog=True
    )
    assert config.resolved_api_protocol == "openai_responses"
    assert config.strict_protocol is True


@pytest.mark.parametrize(
    "mutate,reason",
    [
        (lambda s: setattr(s, "resolved_api_protocol", ""), "omitted resolved_api_protocol"),
        (
            lambda s: setattr(s, "resolved_api_protocol", "openai_chat_completions"),
            "forged resolved_api_protocol",
        ),
        (lambda s: setattr(s, "strict_protocol", not s.strict_protocol), "forged strict_protocol"),
        (lambda s: setattr(s, "profile_revision", ""), "omitted profile_revision"),
        (lambda s: setattr(s, "profile_revision", "forged-rev"), "forged profile_revision"),
        (lambda s: setattr(s, "base_url_fingerprint", ""), "omitted base_url_fingerprint"),
        (lambda s: setattr(s, "base_url_fingerprint", "forged-fp"), "forged base_url_fingerprint"),
    ],
)
def test_evaluator_boundary_rejects_incomplete_or_forged_snapshot(mutate, reason):
    snap = _complete_snapshot()
    mutate(snap)
    with pytest.raises(EvaluatorUnavailableError):
        frozen_evaluator_llm_config(snap, catalog=_catalog(), verify_against_catalog=True)


def test_evaluator_boundary_rejects_omitted_strict_protocol_explicitly():
    """An omitted strict_protocol is rejected even though the configured profile
    is non-strict — omission must never silently default to the catalog value."""
    snap = _complete_snapshot()
    snap.model_fields_set.discard("strict_protocol")
    snap.strict_protocol = False
    # Force omission semantics: pydantic treats assignment as "set", so rebuild
    # the snapshot without the field instead.
    data = snap.model_dump()
    data.pop("strict_protocol", None)
    from deeptutor.learning.models import EvaluatorSnapshot

    omitted = EvaluatorSnapshot(**data)
    with pytest.raises(EvaluatorUnavailableError):
        frozen_evaluator_llm_config(omitted, catalog=_catalog(), verify_against_catalog=True)
