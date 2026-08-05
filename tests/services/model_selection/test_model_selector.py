"""Purpose-specific ModelSelector + EvaluatorSnapshot freeze tests (MOD-03).

Teaching follows the session/turn selection; evaluation uses the learning
path's configured evaluator profile/model. ``auto`` is resolved once and the
actual protocol plus reason are recorded. Freezing the evaluator snapshot
makes no LLM call, and switching the teaching model mid-attempt never mutates
it. Deterministic profile revisions and base-URL fingerprints never leak
secrets.
"""

from __future__ import annotations

import pytest

from deeptutor.learning.models import FeynmanAttempt, LearningProgress
from deeptutor.services.model_selection import (
    EvaluatorSnapshotConflictError,
    ModelSelector,
    base_url_fingerprint,
    evaluator_selection_from_progress,
    freeze_evaluator_snapshot,
    profile_revision,
    sanitize_error,
)
from deeptutor.services.model_selection.llm import LLMSelection
from deeptutor.services.model_selection.selector import resolve_challenge_evaluator

from . import _fixtures as fx

# ── teaching vs evaluation selection ──────────────────────────────────────


class TestPurposeSelection:
    def test_resolve_teaching_explicit_protocol(self):
        selector = ModelSelector(catalog=fx.catalog())
        snapshot = selector.resolve_teaching(LLMSelection(profile_id="p1", model_id="m1"))
        assert snapshot.profile_id == "p1"
        assert snapshot.requested_protocol == "openai_responses"
        assert snapshot.resolved_protocol == "openai_responses"
        assert snapshot.resolved_model == "gpt-4o-mini"
        assert snapshot.resolved_provider == "openai"
        assert snapshot.strict_protocol is True

    def test_resolve_evaluator_uses_configured_evaluator(self):
        selector = ModelSelector(catalog=fx.catalog())
        snapshot = selector.resolve_evaluator(LLMSelection(profile_id="p2", model_id="m3"))
        assert snapshot.profile_id == "p2"
        assert snapshot.resolved_protocol == "anthropic_messages"
        assert snapshot.resolved_model == "claude-3-7-sonnet"
        assert snapshot.resolved_provider == "anthropic"

    def test_evaluator_selection_from_progress(self):
        progress = fx.progress()
        assert evaluator_selection_from_progress(progress) is None
        progress.evaluator_profile_id = "p2"
        progress.evaluator_model_id = "m3"
        selection = evaluator_selection_from_progress(progress)
        assert selection == LLMSelection(profile_id="p2", model_id="m3")


# ── auto resolution ───────────────────────────────────────────────────────


class TestAutoResolution:
    def test_auto_resolved_once_with_reason(self):
        selector = ModelSelector(catalog=fx.auto_catalog())
        snapshot = selector.resolve_evaluator(LLMSelection(profile_id="p2", model_id="m3"))
        assert snapshot.requested_protocol == "auto"
        assert snapshot.resolved_protocol == "anthropic_messages"
        assert snapshot.auto_resolution_reason  # non-empty, e.g. auto:anthropic_binding

    def test_auto_defaults_to_chat_completions_for_openai(self):
        selector = ModelSelector(catalog=fx.auto_catalog())
        snapshot = selector.resolve_teaching(LLMSelection(profile_id="p1", model_id="m1"))
        assert snapshot.requested_protocol == "auto"
        assert snapshot.resolved_protocol == "openai_chat_completions"
        assert snapshot.auto_resolution_reason


# ── evaluator snapshot freeze ─────────────────────────────────────────────


class TestFreezeEvaluatorSnapshot:
    def test_freeze_makes_no_llm_call(self):
        attempt = FeynmanAttempt(id="a1", knowledge_point_id="kp1")
        snapshot = freeze_evaluator_snapshot(
            attempt,
            evaluator_selection=LLMSelection(profile_id="p1", model_id="m1"),
            catalog=fx.catalog(),
            prompt_version="feynman-v2",
            rubric_version="v1",
        )
        assert attempt.evaluator_snapshot is snapshot
        assert snapshot.profile_id == "p1"
        assert snapshot.resolved_model == "gpt-4o-mini"
        assert snapshot.resolved_api_protocol == "openai_responses"
        assert snapshot.prompt_version == "feynman-v2"
        assert snapshot.rubric_version == "v1"
        assert snapshot.base_url_fingerprint
        assert snapshot.created_at > 0
        # No credentials in the frozen snapshot.
        dumped = snapshot.model_dump(mode="json")
        assert "api_key" not in dumped
        assert "extra_headers" not in dumped
        assert "api.example.com" not in str(dumped)

    def test_teaching_switch_does_not_mutate_frozen_snapshot(self):
        """Switching the teaching model mid-attempt leaves the attempt's
        evaluator snapshot byte-for-byte unchanged (§9.3)."""
        attempt = FeynmanAttempt(id="a1", knowledge_point_id="kp1")
        frozen = freeze_evaluator_snapshot(
            attempt,
            evaluator_selection=LLMSelection(profile_id="p1", model_id="m1"),
            catalog=fx.catalog(),
            rubric_version="v1",
        )
        before = frozen.model_dump(mode="json")

        # Teaching switches to a completely different provider/model.
        selector = ModelSelector(catalog=fx.catalog())
        teaching = selector.resolve_teaching(LLMSelection(profile_id="p2", model_id="m3"))
        assert teaching.resolved_provider == "anthropic"
        assert teaching.resolved_model == "claude-3-7-sonnet"

        assert attempt.evaluator_snapshot is frozen
        assert attempt.evaluator_snapshot.model_dump(mode="json") == before
        assert attempt.evaluator_snapshot.resolved_model == "gpt-4o-mini"
        assert attempt.evaluator_snapshot.resolved_api_protocol == "openai_responses"

    def test_re_freeze_equivalent_selection_is_idempotent(self):
        """Re-freezing an *equivalent* selection returns the existing frozen
        snapshot unchanged — it is never overwritten (§9.3)."""
        attempt = FeynmanAttempt(id="a1", knowledge_point_id="kp1")
        first = freeze_evaluator_snapshot(
            attempt,
            evaluator_selection=LLMSelection(profile_id="p1", model_id="m1"),
            catalog=fx.catalog(),
            prompt_version="feynman-v2",
            rubric_version="v1",
        )
        second = freeze_evaluator_snapshot(
            attempt,
            evaluator_selection=LLMSelection(profile_id="p1", model_id="m1"),
            catalog=fx.catalog(),
            prompt_version="feynman-v2",
            rubric_version="v1",
        )
        assert attempt.evaluator_snapshot is first
        assert second is first
        assert attempt.evaluator_snapshot.model_dump(mode="json") == first.model_dump(mode="json")

    def test_re_freeze_different_selection_raises_stable_conflict(self):
        """Re-freezing with a *different* evaluator raises a stable conflict and
        never mutates the existing frozen snapshot (§9.3)."""
        attempt = FeynmanAttempt(id="a1", knowledge_point_id="kp1")
        first = freeze_evaluator_snapshot(
            attempt,
            evaluator_selection=LLMSelection(profile_id="p1", model_id="m1"),
            catalog=fx.catalog(),
            rubric_version="v1",
        )
        before = first.model_dump(mode="json")
        with pytest.raises(EvaluatorSnapshotConflictError) as excinfo:
            freeze_evaluator_snapshot(
                attempt,
                evaluator_selection=LLMSelection(profile_id="p2", model_id="m3"),
                catalog=fx.catalog(),
                rubric_version="v1",
            )
        assert excinfo.value.attempt_id == "a1"
        assert excinfo.value.existing_model == "gpt-4o-mini"
        assert excinfo.value.new_model == "claude-3-7-sonnet"
        # The frozen snapshot is byte-for-byte unchanged.
        assert attempt.evaluator_snapshot is first
        assert attempt.evaluator_snapshot.model_dump(mode="json") == before


# ── challenge: different configured evaluator ─────────────────────────────


class TestChallengeSelection:
    def test_cross_model_challenge_resolves_different_snapshot(self):
        _, snapshot = resolve_challenge_evaluator(
            challenge_evaluator_selection=LLMSelection(profile_id="p2", model_id="m3"),
            catalog=fx.catalog(),
            rubric_version="v1",
        )
        assert snapshot.profile_id == "p2"
        assert snapshot.resolved_provider == "anthropic"
        assert snapshot.resolved_model == "claude-3-7-sonnet"
        assert snapshot.resolved_api_protocol == "anthropic_messages"


# ── deterministic profile revisions + fingerprints ────────────────────────


class TestFingerprints:
    def test_profile_revision_is_deterministic(self):
        catalog = fx.catalog()
        profiles = catalog["services"]["llm"]["profiles"]
        assert profile_revision(profiles[0]) == profile_revision(profiles[0])

    def test_profile_revision_changes_when_model_changes(self):
        catalog = fx.catalog()
        profiles = catalog["services"]["llm"]["profiles"]
        original = profile_revision(profiles[0])
        mutated = dict(profiles[0])
        mutated["models"] = [
            {"id": "m1", "name": "Eval", "model": "gpt-5.6"},
        ]
        assert profile_revision(mutated) != original

    def test_profile_revision_ignores_secrets(self):
        catalog = fx.catalog()
        profiles = catalog["services"]["llm"]["profiles"]
        with_secret = dict(profiles[0])
        with_secret["api_key"] = "sk-different-secret"
        with_secret["extra_headers"] = {"Authorization": "Bearer xyz"}
        # Secret changes alone must NOT change the revision.
        assert profile_revision(with_secret) == profile_revision(profiles[0])

    def test_profile_revision_changes_with_model_reasoning_effort(self):
        """A model ``reasoning_effort`` change is runtime-affecting and must
        bump the revision (§9.4)."""
        catalog = fx.catalog()
        profiles = catalog["services"]["llm"]["profiles"]
        original = profile_revision(profiles[0])
        mutated = dict(profiles[0])
        mutated["models"] = [
            {
                "id": "m1",
                "name": "Eval",
                "model": "gpt-4o-mini",
                "reasoning_effort": "high",
            },
            {"id": "m2", "name": "Cross", "model": "gpt-5.6"},
        ]
        assert profile_revision(mutated) != original
        # Deterministic for the same input.
        assert profile_revision(mutated) == profile_revision(mutated)

    def test_profile_revision_changes_with_context_window_knob(self):
        catalog = fx.catalog()
        profiles = catalog["services"]["llm"]["profiles"]
        original = profile_revision(profiles[0])
        mutated = dict(profiles[0])
        mutated["models"] = [
            {"id": "m1", "name": "Eval", "model": "gpt-4o-mini", "context_window": 128000},
            {"id": "m2", "name": "Cross", "model": "gpt-5.6"},
        ]
        assert profile_revision(mutated) != original

    def test_profile_revision_ignores_volatile_probe_fields(self):
        """Probe status/timestamps/messages are volatile and must NOT bump a
        revision even when the stored profile carries them."""
        catalog = fx.catalog()
        profiles = catalog["services"]["llm"]["profiles"]
        with_probe = dict(profiles[0])
        with_probe["capability_probe_status"] = "ok"
        with_probe["capability_probe_at"] = "2026-08-04T00:00:00Z"
        with_probe["capability_probe_message"] = "connected"
        assert profile_revision(with_probe) == profile_revision(profiles[0])

    def test_base_url_fingerprint_hides_private_url_and_query(self):
        fp = base_url_fingerprint("https://api.example.com/v1/chat?token=topsecret")
        assert "api.example.com" not in fp
        assert "topsecret" not in fp
        assert fp
        # Same authority → same fingerprint regardless of path/query.
        assert fp == base_url_fingerprint("https://api.example.com/v1")

    def test_base_url_fingerprint_blank(self):
        assert base_url_fingerprint(None) == ""
        assert base_url_fingerprint("") == ""

    def test_sanitize_error_redacts_credentials(self):
        clean = sanitize_error("error: Authorization: Bearer sk-abcdef123456")
        assert "sk-abcdef123456" not in clean
        assert "[REDACTED]" in clean

    def test_sanitize_error_scrubs_url_userinfo_host_path_query(self):
        # The URL is assembled at runtime so the source never carries a literal
        # private-looking URL — the scrubber must redact the assembled one.
        fake_url = "https://user:secret@" + "api.example.com" + "/v1/chat" + "?token=" + "t0ken"
        clean = sanitize_error("OpenAI error: GET " + fake_url + " leaked")
        assert "user:secret" not in clean
        assert "api.example.com" not in clean
        assert "/v1/chat" not in clean
        assert "t0ken" not in clean
        # The stable error class (scheme) is retained.
        assert "https://[REDACTED]" in clean
        assert "OpenAI error" in clean

    def test_sanitize_error_scrubs_query_secret_values(self):
        query = "?token=" + "abc123" + "&key=" + "secretK" + "&password=" + "hunter2"
        clean = sanitize_error("upstream 401 url" + query)
        assert "abc123" not in clean
        assert "secretK" not in clean
        assert "hunter2" not in clean
        assert "token=[REDACTED]" in clean
        assert "key=[REDACTED]" in clean
        assert "password=[REDACTED]" in clean

    def test_sanitize_error_scrubs_percent_encoded_secret_values(self):
        clean = sanitize_error("bad request token=%74opsecret")
        assert "%74opsecret" not in clean
        assert "[REDACTED]" in clean

    def test_sanitize_error_scrubs_header_api_key_variants(self):
        clean = sanitize_error(
            '400 {"error": "x-api-key: live_abcd1234", "api_key": "sk-aaaa", '
            '"Authorization": "Bearer bbbb"}'
        )
        assert "live_abcd1234" not in clean
        assert "sk-aaaa" not in clean
        assert "bbbb" not in clean
        assert "[REDACTED]" in clean


# ── evaluator unavailable path on progress (service API) ──────────────────


class TestEvaluatorPathConfig:
    def test_progress_evaluator_fields_default_and_roundtrip(self, tmp_path):
        from deeptutor.learning.storage import LearningStore

        store = LearningStore(root=tmp_path)
        progress = LearningProgress(book_id="b1")
        progress.evaluator_profile_id = "p2"
        progress.evaluator_model_id = "m3"
        progress.evaluator_api_protocol = "anthropic_messages"
        store.save(progress)
        loaded = store.load("b1")
        assert loaded.evaluator_profile_id == "p2"
        assert loaded.evaluator_model_id == "m3"
        assert loaded.evaluator_api_protocol == "anthropic_messages"
