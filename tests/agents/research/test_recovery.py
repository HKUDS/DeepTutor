from deeptutor.agents.research.recovery import (
    BLOCK_EVIDENCE_MIN_CHARS,
    REPORT_BODY_MIN_CHARS,
    block_is_substantive,
    report_is_substantive,
    seal_checkpoint,
    verify_checkpoint,
    retry_budget,
    backoff_delays,
    retry_parameters_hash,
    safe_research_config,
)


def test_research_content_gates_are_exact_boundaries() -> None:
    assert not block_is_substantive("x" * (BLOCK_EVIDENCE_MIN_CHARS - 1))
    assert block_is_substantive("x" * BLOCK_EVIDENCE_MIN_CHARS)
    assert not report_is_substantive("# Title\n\n" + "x" * (REPORT_BODY_MIN_CHARS - 1))
    assert report_is_substantive("# Title\n\n" + "x" * REPORT_BODY_MIN_CHARS)
    assert not report_is_substantive("# Title\n\n[1]\n[2]")


def test_checkpoint_hash_detects_tampering() -> None:
    checkpoint = seal_checkpoint({"schema_version": 1, "attempt_id": "attempt_a", "blocks": []})
    assert verify_checkpoint(checkpoint)
    checkpoint["attempt_id"] = "attempt_b"
    assert not verify_checkpoint(checkpoint)


def test_retry_policy_has_one_bounded_escalation_and_backoff() -> None:
    assert retry_budget(100, 200) == 200
    assert retry_budget(100, 100) is None
    assert retry_budget(100, 0) is None
    assert backoff_delays(10) == (1.0, 2.0, 4.0)


def test_retry_identity_is_canonical_and_secret_free() -> None:
    first = retry_parameters_hash(
        parent_attempt_id="attempt_a",
        strategy="failed_blocks",
        llm_selection={"profile_id": "profile_a", "model_id": "model_a", "api_key": "not-hashed"},
    )
    assert first == retry_parameters_hash(
        parent_attempt_id="attempt_a",
        strategy="failed_blocks",
        llm_selection={"model_id": "model_a", "profile_id": "profile_a"},
    )
    assert first != retry_parameters_hash(
        parent_attempt_id="attempt_a",
        strategy="failed_blocks",
        llm_selection={"profile_id": "profile_a", "model_id": "model_b"},
    )


def test_checkpoint_config_is_shallow_allowlisted() -> None:
    saved = safe_research_config({
        "research_depth": "deep", "confirmed_outline": [{"title": "A"}],
        "_research_retry": {"checkpoint": {"api_key": "secret"}},
        "api_key": "secret", "continuation_items": [{"opaque": "secret"}],
    })
    assert saved == {"research_depth": "deep", "confirmed_outline": [{"title": "A"}]}


def test_opaque_continuation_sentinel_is_excluded_from_checkpoint_config() -> None:
    saved = safe_research_config({"_research_retry": {"continuation_items": ["opaque-SENTINEL"]}, "continuation_items": ["opaque-SENTINEL"], "research_depth": "deep"})
    assert "opaque-SENTINEL" not in repr(saved)
