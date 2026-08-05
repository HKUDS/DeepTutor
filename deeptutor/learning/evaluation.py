"""Production evaluator boundary (MOD-03 → ASM-01, spec §9.3/§7.8).

The frozen evaluator pinned at attempt start performs the rubric evaluation that
supplies the assessment fields (rubric, critical errors, strengths, gaps,
citations); the server still computes ``passed``. This module is the
provider-neutral seam:

* builds a strict request only from the active attempt's validated
  evidence/source snapshot projection and the fixed rubric contract;
* resolves the exact frozen profile/model/protocol — never silent fallback and
  never switching to the teaching model;
* the caller appends a ``pending`` ``ModelInvocationRecord(purpose=evaluation,
  attempt_id=...)`` *before* the provider request and appends the terminal
  revision after success/failure, attaching that exact id and the frozen
  evaluator snapshot to the resulting :class:`RubricAssessment`;
* evaluator unavailable/timeout/protocol failure raises
  :class:`EvaluatorUnavailableError` so finalize pauses with a stable sanitized
  error and never writes an assessment or advances mastery.

Nothing here ever persists credentials or raw provider responses — errors are
sanitized and only fingerprints/usage reach the invocation record.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
import json
import logging
import time
from typing import Any

from deeptutor.learning.grading import RUBRIC_DOMAIN
from deeptutor.learning.models import (
    EvaluatorSnapshot,
    FeynmanAttempt,
    LearningProgress,
    ModelInvocationPurpose,
    ModelInvocationUsage,
    RubricScores,
    SourceCitation,
)
from deeptutor.services.model_selection.fingerprint import sanitize_error
from deeptutor.services.model_selection.selector import ResolvedModelSnapshot

logger = logging.getLogger(__name__)

#: The exact evaluator output key set the boundary requires; unknown keys are
#: rejected and every listed key must be present.
_ALLOWED_EVALUATION_KEYS = (
    "rubric",
    "critical_errors",
    "strengths",
    "gaps",
    "source_citations",
)


class EvaluatorUnavailableError(Exception):
    """The frozen evaluator could not resolve/invoke; finalize pauses (§9.3).

    Carries a stable, sanitized error code/message. No assessment is written
    and no mastery is advanced.
    """

    def __init__(
        self,
        *,
        code: str = "evaluator_unavailable",
        sanitized_error: str = "",
    ) -> None:
        self.code = code
        self.sanitized_error = sanitize_error(sanitized_error or code)
        super().__init__(self.sanitized_error)


@dataclass(frozen=True, slots=True)
class EvaluatorOutput:
    """Strictly parsed/validated evaluator output for one assessment pass."""

    rubric: RubricScores
    critical_errors: list[str]
    strengths: list[str]
    gap_candidates: list[dict[str, str]]
    source_citations: list[SourceCitation]
    #: Reported identity is an audit fact only — never copied into the request.
    reported_model: str | None = None
    reported_version: str | None = None
    usage: ModelInvocationUsage | dict[str, Any] | None = None


@dataclass(slots=True)
class PendingEvaluation:
    """A persisted ``pending`` evaluation invocation awaiting the provider call."""

    record_id: str
    snapshot: ResolvedModelSnapshot


def _evidence_projection(
    progress: LearningProgress, attempt: FeynmanAttempt
) -> list[dict[str, Any]]:
    """The active chain's validated evidence, projected secret-free."""
    chain = [
        item
        for item in progress.evidence_items
        if item.attempt_id == attempt.id and item.chain_id == attempt.active_chain_id
    ]
    chain.sort(key=lambda item: (item.created_at, item.event_seq))
    return [
        {
            "kind": item.kind.value,
            "content": item.content_snapshot or "",
            "input_mode": item.input_mode.value,
            "transcript_confirmed": item.transcript_confirmed,
            "citations": [c.model_dump() for c in item.source_citations],
        }
        for item in chain
    ]


def _source_projection(progress: LearningProgress, attempt: FeynmanAttempt) -> list[dict[str, Any]]:
    """The attempt's frozen source snapshots, projected secret-free."""
    by_id = {snapshot.id: snapshot for snapshot in progress.source_snapshots}
    return [
        {
            "id": snapshot.id,
            "source_type": snapshot.source_type.value,
            "title": snapshot.title,
            "locator": snapshot.locator,
            "content_hash": snapshot.content_hash,
            "citation_anchors": list(snapshot.citation_anchors),
        }
        for snapshot in (by_id.get(sid) for sid in attempt.source_snapshot_ids)
        if snapshot is not None
    ]


def build_evaluation_prompt(
    progress: LearningProgress,
    attempt: FeynmanAttempt,
    *,
    rubric_version: str = "feynman-rubric-v1",
    language: str = "en",
) -> str:
    """Build the strict, secret-free rubric-evaluation prompt.

    The request contains only the active attempt's validated evidence and its
    frozen source snapshots — never raw conversation beyond the evidence chain,
    never credentials, never private URLs.
    """
    evidence = _evidence_projection(progress, attempt)
    sources = _source_projection(progress, attempt)
    evidence_lines = (
        "\n".join(f"- [{item['kind']}] {item['content']}" for item in evidence) or "- (no evidence)"
    )
    source_lines = (
        "\n".join(
            f"- {item['id']}: {item['title'] or item['locator'] or item['content_hash'][:8]}"
            for item in sources
        )
        or "- (no sources)"
    )
    return (
        "You are the evaluator for a Feynman teach-back cycle. Grade ONLY the "
        "learner's evidence below against the fixed rubric. You have no "
        "publishing or mastery power.\n"
        f"rubric_version={rubric_version}\n"
        "Scores are 0|1|2 for each of correctness, completeness, "
        "causal_clarity, transfer. A pass requires correctness=2, transfer=2, "
        "completeness>=1, causal_clarity>=1, and no critical errors.\n"
        "Respond with STRICT JSON only, no prose, no markdown fences:\n"
        '{"rubric":{"correctness":0,"completeness":0,"causal_clarity":0,'
        '"transfer":0},"critical_errors":[],"strengths":[],'
        '"gaps":[{"label":"","description":""}],'
        '"source_citations":[{"source_snapshot_id":"","anchor":""}]}\n'
        "source_citations must reference only the source snapshot ids listed "
        "below.\n\n"
        f"LEARNER EVIDENCE:\n{evidence_lines}\n\n"
        f"AVAILABLE SOURCE SNAPSHOTS:\n{source_lines}\n"
    )


def _extract_json_object(raw: str) -> dict[str, Any]:
    text = (raw or "").strip()
    if not text:
        raise ValueError("evaluator returned empty output")
    # Truly strict JSON parsing: the response must be *exactly* one JSON object
    # with no markdown fences, no prose prefix/suffix and no trailing content.
    # Prose with an embedded ``{...}`` and multiple objects are rejected, never
    # "salvaged", so a prompt-injected or malformed evaluator response fails
    # closed (finding 4).
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError("evaluator output is not strict JSON") from exc
    if not isinstance(parsed, dict):
        raise ValueError("evaluator output must be a JSON object")
    return parsed


def _coerce_rubric(value: Any) -> RubricScores:
    if not isinstance(value, dict):
        raise ValueError("rubric must be an object")
    scores: dict[str, int] = {}
    for name in ("correctness", "completeness", "causal_clarity", "transfer"):
        raw = value.get(name)
        if isinstance(raw, bool) or not isinstance(raw, (int, float)):
            raise ValueError(f"rubric.{name} must be 0|1|2")
        number = float(raw)
        if not number.is_integer() or int(number) not in RUBRIC_DOMAIN:
            raise ValueError(f"rubric.{name} must be 0|1|2")
        scores[name] = int(number)
    return RubricScores(
        correctness=scores["correctness"],
        completeness=scores["completeness"],
        causal_clarity=scores["causal_clarity"],
        transfer=scores["transfer"],
    )


def _coerce_string_list(value: Any, name: str, *, max_items: int = 20) -> list[str]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError(f"{name} must be a list")
    out: list[str] = []
    for entry in value:
        if not isinstance(entry, str):
            raise ValueError(f"{name} entries must be strings")
        out.append(entry[:500])
    if len(out) > max_items:
        raise ValueError(f"{name} exceeds {max_items} items")
    return out


def _coerce_gaps(value: Any) -> list[dict[str, str]]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError("gaps must be a list")
    out: list[dict[str, str]] = []
    for entry in value:
        if not isinstance(entry, dict):
            raise ValueError("gap entries must be objects")
        label = str(entry.get("label") or "").strip()[:200]
        description = str(entry.get("description") or "").strip()[:1000]
        if label or description:
            out.append({"label": label, "description": description})
    return out[:20]


def _coerce_citations(value: Any, *, allowed_snapshot_ids: frozenset[str]) -> list[SourceCitation]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError("source_citations must be a list")
    out: list[SourceCitation] = []
    for entry in value:
        if not isinstance(entry, dict):
            continue
        snapshot_id = str(entry.get("source_snapshot_id") or "").strip()
        if not snapshot_id:
            continue
        if snapshot_id not in allowed_snapshot_ids:
            raise ValueError(f"source_citation {snapshot_id!r} is not a frozen source snapshot")
        out.append(
            SourceCitation(
                source_snapshot_id=snapshot_id,
                anchor=str(entry.get("anchor") or "").strip()[:200],
            )
        )
    return out


def parse_evaluator_output(
    raw: str,
    *,
    allowed_snapshot_ids: frozenset[str],
) -> EvaluatorOutput:
    """Strictly parse and validate the evaluator's structured output.

    Any structural violation raises :class:`ValueError` — the caller finalizes
    the invocation as failed and pauses finalize; nothing is trusted.
    """
    parsed = _extract_json_object(raw)
    unknown = [k for k in parsed if k not in _ALLOWED_EVALUATION_KEYS]
    if unknown:
        raise ValueError(f"unexpected evaluator output keys: {', '.join(sorted(unknown))}")
    # The exact key set is required before coercion — omitting any contract key
    # (including a collection key) must fail closed, never silently become an
    # empty collection. Explicit ``[]`` values remain valid.
    missing = [k for k in _ALLOWED_EVALUATION_KEYS if k not in parsed]
    if missing:
        raise ValueError(f"missing required evaluator output keys: {', '.join(sorted(missing))}")
    rubric = _coerce_rubric(parsed["rubric"])
    critical_errors = _coerce_string_list(parsed["critical_errors"], "critical_errors")
    strengths = _coerce_string_list(parsed["strengths"], "strengths")
    gaps = _coerce_gaps(parsed["gaps"])
    citations = _coerce_citations(
        parsed["source_citations"], allowed_snapshot_ids=allowed_snapshot_ids
    )
    return EvaluatorOutput(
        rubric=rubric,
        critical_errors=critical_errors,
        strengths=strengths,
        gap_candidates=gaps,
        source_citations=citations,
    )


def resolved_snapshot_from_evaluator(snapshot: EvaluatorSnapshot | None) -> ResolvedModelSnapshot:
    """Project a frozen evaluator snapshot onto the MOD-03 resolved shape.

    The frozen identity is never re-resolved — evaluation reuses the exact
    profile/model/protocol pinned at attempt start.
    """
    if snapshot is None:
        return ResolvedModelSnapshot(
            profile_id="",
            profile_name="",
            profile_revision="",
            requested_provider="",
            requested_protocol="",
            requested_model="",
            resolved_provider="",
            resolved_protocol="",
            resolved_model="",
            auto_resolution_reason="",
            base_url_fingerprint="",
        )
    return ResolvedModelSnapshot(
        profile_id=snapshot.profile_id,
        profile_name=snapshot.profile_name,
        profile_revision=snapshot.profile_revision,
        requested_provider=snapshot.requested_provider,
        requested_protocol=snapshot.requested_api_protocol,
        requested_model=snapshot.requested_model,
        resolved_provider=snapshot.resolved_provider,
        resolved_protocol=snapshot.resolved_api_protocol,
        resolved_model=snapshot.resolved_model,
        auto_resolution_reason=snapshot.auto_resolution_reason,
        base_url_fingerprint=snapshot.base_url_fingerprint,
        strict_protocol=snapshot.strict_protocol,
        prompt_version=snapshot.prompt_version,
        tool_schema_version="",
    )


def frozen_evaluator_llm_config(
    snapshot: EvaluatorSnapshot | None,
    catalog: Any | None = None,
    *,
    verify_against_catalog: bool = False,
):
    """Build an :class:`LLMConfig` honoring the frozen profile/model/protocol.

    Shared by the evaluator boundary and the knowledge-card draft executor so
    both reuse the exact frozen identity (never silent fallback, never the
    teaching model). Raises :class:`EvaluatorUnavailableError` when the frozen
    profile/model is no longer configured.

    With ``verify_against_catalog=True`` (a *client-supplied* challenge
    alternative evaluator) the frozen snapshot must match the currently
    configured profile's resolved protocol, strictness and profile revision —
    a request that merely names a configured profile/model but forges the rest
    of the frozen snapshot fails closed. The original attempt's server-frozen
    snapshot (``verify_against_catalog=False``) keeps its frozen contract even
    if the profile later migrates, but its endpoint fingerprint is still
    verified so a moved base URL never silently redirects the evaluation.
    """
    if snapshot is None or not snapshot.profile_id or not snapshot.resolved_model:
        raise EvaluatorUnavailableError(sanitized_error="no frozen evaluator identity is available")
    if catalog is None:
        from deeptutor.services.config import get_model_catalog_service

        catalog = get_model_catalog_service().load()
    from deeptutor.services.llm.config import LLMConfig
    from deeptutor.services.provider_registry import (
        canonical_provider_name,
        find_by_name,
    )

    service = (catalog or {}).get("services", {}).get("llm", {})
    profile = next(
        (
            profile
            for profile in service.get("profiles", []) or []
            if isinstance(profile, dict) and profile.get("id") == snapshot.profile_id
        ),
        None,
    )
    if profile is None:
        raise EvaluatorUnavailableError(
            sanitized_error=(
                "frozen evaluator profile is no longer configured; explicit "
                "migration is required (no fallback)"
            )
        )
    model = next(
        (
            model
            for model in profile.get("models", []) or []
            if isinstance(model, dict)
            and model.get("model")
            and model.get("model") == snapshot.resolved_model
        ),
        None,
    )
    if model is None:
        raise EvaluatorUnavailableError(
            sanitized_error=(
                "frozen evaluator model is no longer configured; explicit "
                "migration is required (no fallback)"
            )
        )
    binding_raw = str(profile.get("binding") or "")
    spec = find_by_name(canonical_provider_name(binding_raw)) or find_by_name(binding_raw)
    provider_name = (
        spec.name if spec is not None else canonical_provider_name(binding_raw) or "openai"
    )
    base_url = str(profile.get("base_url") or "")
    # The frozen *resolved* protocol is authoritative; a profile that migrated
    # later does not silently change the frozen contract.
    protocol = snapshot.resolved_api_protocol or str(profile.get("api_protocol") or "auto")
    if verify_against_catalog:
        from deeptutor.services.config.provider_runtime import resolve_api_protocol
        from deeptutor.services.model_selection.fingerprint import (
            base_url_fingerprint,
            profile_revision,
        )

        catalog_protocol, _ = resolve_api_protocol(
            binding_raw, str(profile.get("api_protocol") or "auto")
        )
        catalog_strict = bool(profile.get("strict_protocol"))
        catalog_revision = profile_revision(profile)
        catalog_fingerprint = base_url_fingerprint(base_url)
        # Every frozen identity field is required and verified exactly — a
        # client-authored challenge snapshot that omits or forges any of them
        # fails closed before any provider call (finding 5). Omission never
        # falls back to a catalog default and never skips a conditional check.
        if not str(snapshot.resolved_api_protocol or ""):
            raise EvaluatorUnavailableError(
                sanitized_error=(
                    "requested challenge evaluator omits resolved_api_protocol; "
                    "a complete server-canonical snapshot is required"
                )
            )
        if protocol != catalog_protocol:
            raise EvaluatorUnavailableError(
                sanitized_error=(
                    "requested challenge evaluator protocol does not match the "
                    "configured profile; a forged snapshot never selects a "
                    "different protocol"
                )
            )
        if "strict_protocol" not in snapshot.model_fields_set:
            raise EvaluatorUnavailableError(
                sanitized_error=(
                    "requested challenge evaluator omits strict_protocol; the "
                    "explicit flag is required (including an explicit false)"
                )
            )
        if bool(snapshot.strict_protocol) != catalog_strict:
            raise EvaluatorUnavailableError(
                sanitized_error=(
                    "requested challenge evaluator strictness does not match the configured profile"
                )
            )
        if not str(snapshot.profile_revision or ""):
            raise EvaluatorUnavailableError(
                sanitized_error=(
                    "requested challenge evaluator omits profile_revision; the "
                    "exact configured revision is required"
                )
            )
        if str(snapshot.profile_revision) != catalog_revision:
            raise EvaluatorUnavailableError(
                sanitized_error=(
                    "requested challenge evaluator profile revision does not match "
                    "the configured profile"
                )
            )
        if not str(snapshot.base_url_fingerprint or ""):
            raise EvaluatorUnavailableError(
                sanitized_error=(
                    "requested challenge evaluator omits base_url_fingerprint; the "
                    "exact non-secret endpoint fingerprint is required"
                )
            )
        if snapshot.base_url_fingerprint != catalog_fingerprint:
            raise EvaluatorUnavailableError(
                sanitized_error=(
                    "requested challenge evaluator endpoint fingerprint does not "
                    "match the configured profile"
                )
            )
    # The frozen strictness flag is authoritative too — a profile toggling
    # ``strict_protocol`` after the attempt started must not change the frozen
    # contract, and a forged challenge snapshot that renames a configured
    # profile/model but omits the real strictness fails closed below.
    frozen_fingerprint = str(snapshot.base_url_fingerprint or "")
    if frozen_fingerprint:
        from deeptutor.services.model_selection.fingerprint import base_url_fingerprint

        if base_url_fingerprint(base_url) != frozen_fingerprint:
            raise EvaluatorUnavailableError(
                sanitized_error=(
                    "frozen evaluator endpoint moved; explicit migration is required (no fallback)"
                )
            )
    return LLMConfig(
        model=snapshot.resolved_model,
        api_key=str(profile.get("api_key") or ""),
        base_url=base_url or None,
        effective_url=base_url or None,
        binding=provider_name,
        provider_name=provider_name,
        provider_mode=spec.mode if spec is not None else "standard",
        api_version=str(profile.get("api_version") or "") or None,
        extra_headers=profile.get("extra_headers") or None,
        reasoning_effort=str(model.get("reasoning_effort") or "") or None,
        api_protocol=protocol,
        strict_protocol=bool(snapshot.strict_protocol),
        resolved_api_protocol=protocol,
        temperature=0.0,
        max_tokens=2048,
    )


class RubricEvaluator:
    """Provider-neutral rubric evaluation using the frozen evaluator identity.

    ``provider`` is an injectable ``async callable(messages, config) -> response``
    used by offline tests; the default routes through the unified LLM
    factory/adapters (``deeptutor.services.llm.provider_factory``).
    """

    def __init__(
        self,
        *,
        catalog: Any | None = None,
        provider: Any = None,
        prompt_version: str = "feynman-eval-v1",
        rubric_version: str = "feynman-rubric-v1",
        now: Any | None = None,
    ) -> None:
        self._catalog = catalog
        self._provider = provider
        self._prompt_version = prompt_version
        self._rubric_version = rubric_version
        self._now = now or time.time

    # ── config resolution ──────────────────────────────────────────────────

    def llm_config(self, snapshot: EvaluatorSnapshot, *, verify_against_catalog: bool = False):
        """Build an :class:`LLMConfig` honoring the frozen profile/model/protocol.

        ``verify_against_catalog=True`` is set for a *client-supplied* challenge
        alternative evaluator so a forged snapshot fails closed.
        """
        return frozen_evaluator_llm_config(
            snapshot, catalog=self._catalog, verify_against_catalog=verify_against_catalog
        )

    # ── invocation audit (caller persists the pending record) ──────────────

    def append_pending(
        self,
        progress: LearningProgress,
        attempt: FeynmanAttempt,
        *,
        snapshot: EvaluatorSnapshot | None = None,
        session_id: str = "",
        turn_id: str = "",
        now: float | None = None,
    ) -> PendingEvaluation:
        """Append a durable ``pending`` evaluation invocation (§7.8).

        The caller saves ``progress`` before invoking the provider, so a crash
        between here and the request still leaves an audit trail. The frozen
        snapshot (or an explicitly selected challenge alternative) is the only
        evaluator identity used.
        """
        from deeptutor.services.model_selection.audit import ModelInvocationRecorder

        frozen = snapshot or attempt.evaluator_snapshot
        if frozen is None or not (frozen.profile_id and frozen.resolved_model):
            raise EvaluatorUnavailableError(
                sanitized_error=(
                    "attempt has no frozen evaluator snapshot; finalize pauses "
                    "until the evaluator is configured"
                )
            )
        recorder = ModelInvocationRecorder()
        resolved = resolved_snapshot_from_evaluator(frozen)
        record = recorder.start(
            progress,
            purpose=ModelInvocationPurpose.EVALUATION,
            snapshot=resolved,
            session_id=session_id,
            turn_id=turn_id,
            attempt_id=attempt.id,
            prompt_version=frozen.prompt_version or self._prompt_version,
            now=now if now is not None else self._now(),
        )
        return PendingEvaluation(record_id=record.id, snapshot=resolved)

    # ── provider call ──────────────────────────────────────────────────────

    async def invoke(
        self,
        progress: LearningProgress,
        attempt: FeynmanAttempt,
        *,
        snapshot: EvaluatorSnapshot | None = None,
        prompt: str | None = None,
        timeout_seconds: float = 120.0,
    ) -> tuple[EvaluatorOutput, str, Any | None]:
        """Call the frozen evaluator once and return ``(output, reported_model, response)``.

        The caller is responsible for finishing the pending invocation on the
        same progress. A provider/timeout/protocol failure raises
        :class:`EvaluatorUnavailableError` (the caller finalizes the invocation
        as failed/paused and never writes an assessment).
        """
        frozen = snapshot or attempt.evaluator_snapshot
        if frozen is None:
            raise EvaluatorUnavailableError(
                sanitized_error="attempt has no frozen evaluator snapshot"
            )
        # A client-supplied challenge alternative must match the configured
        # profile exactly; the server-frozen original keeps its frozen contract.
        config = self.llm_config(frozen, verify_against_catalog=snapshot is not None)
        request_prompt = prompt or build_evaluation_prompt(
            progress, attempt, rubric_version=self._rubric_version
        )
        messages = [
            {"role": "system", "content": "You are a strict rubric evaluator."},
            {"role": "user", "content": request_prompt},
        ]
        try:
            response = await self._call_provider(config, messages, timeout_seconds)
        except EvaluatorUnavailableError:
            raise
        except Exception as exc:  # noqa: BLE001 - any provider failure pauses
            logger.warning("evaluator invocation failed (%s)", type(exc).__name__)
            raise EvaluatorUnavailableError(
                sanitized_error=str(exc),
            ) from exc

        if response is None:
            raise EvaluatorUnavailableError(sanitized_error="evaluator returned no response")
        finish_reason = getattr(response, "finish_reason", None)
        content = getattr(response, "content", None) or ""
        if finish_reason == "error" or not content.strip():
            raise EvaluatorUnavailableError(
                sanitized_error=content[:500] or "evaluator returned an error status"
            )
        allowed = frozenset(attempt.source_snapshot_ids)
        try:
            output = parse_evaluator_output(content, allowed_snapshot_ids=allowed)
        except ValueError as exc:
            raise EvaluatorUnavailableError(
                sanitized_error=f"invalid evaluator output: {exc}",
            ) from exc
        reported_model = str(getattr(response, "model", "") or "") or None
        reported_version = None
        usage = getattr(response, "usage", None)
        return (
            EvaluatorOutput(
                rubric=output.rubric,
                critical_errors=output.critical_errors,
                strengths=output.strengths,
                gap_candidates=output.gap_candidates,
                source_citations=output.source_citations,
                reported_model=reported_model,
                reported_version=reported_version,
                usage=usage,
            ),
            reported_model,
            response,
        )

    async def _call_provider(self, config, messages: list[dict[str, Any]], timeout_seconds: float):
        if self._provider is not None:
            call = self._provider(messages, config)
        else:
            from deeptutor.services.llm.provider_factory import get_runtime_provider

            provider = get_runtime_provider(config)
            call = provider.chat_with_retry(
                messages=messages,
                model=config.model,
                max_tokens=config.max_tokens,
                temperature=config.temperature,
                reasoning_effort=config.reasoning_effort,
            )
        # Real timeout enforcement: a provider that hangs (or retries through a
        # transient storm) beyond the deadline is surfaced as unavailable and the
        # pending invocation is finalized paused — the attempt stays retryable.
        return await asyncio.wait_for(call, timeout=timeout_seconds)


__all__ = [
    "EvaluatorOutput",
    "EvaluatorUnavailableError",
    "PendingEvaluation",
    "RubricEvaluator",
    "build_evaluation_prompt",
    "frozen_evaluator_llm_config",
    "parse_evaluator_output",
    "resolved_snapshot_from_evaluator",
]
