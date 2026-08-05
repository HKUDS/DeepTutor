"""Production knowledge-card draft executor (KB-02 → ASM-01).

The worker's :class:`~deeptutor.learning.knowledge_cards.worker.DraftExecutor`
contract is implemented by :class:`FrozenModelDraftExecutor`, which lazily
resolves a provider config from the attempt's *frozen evaluator snapshot* and
the current server-side catalog/credentials, enforces the frozen
profile/model/protocol (never silent fallback), builds a strict draft prompt
from the existing secret-free generation input projection, and returns a
normalized :class:`DraftOutput`.

Nothing here persists the prompt, raw provider output or credentials — the
worker's blob store sanitizes/validates before any durable write.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any

from deeptutor.learning.evaluation import (
    EvaluatorUnavailableError,
    frozen_evaluator_llm_config,
)
from deeptutor.learning.knowledge_cards.worker import DraftOutput

logger = logging.getLogger(__name__)

DEFAULT_DRAFT_PROMPT_VERSION = "feynman-draft-v1"


def build_draft_prompt(
    input_projection: dict[str, Any],
    *,
    prompt_version: str = DEFAULT_DRAFT_PROMPT_VERSION,
) -> str:
    """Build a strict, secret-free draft prompt from the generation projection.

    The projection is the same secret-free input the worker hashes into
    ``input_hash`` (§7.9.1); no raw conversation beyond the evidence chain, no
    rubric/gap/provenance text, no credentials.
    """
    evidence = input_projection.get("evidence") or []
    sources = input_projection.get("sources") or []
    artifacts = input_projection.get("artifacts") or []
    evidence_lines = (
        "\n".join(f"- [{item.get('kind')}] {item.get('content')}" for item in evidence)
        or "- (no evidence)"
    )
    source_lines = (
        "\n".join(
            f"- {item.get('id')}: {item.get('title') or item.get('locator') or item.get('content_hash', '')[:8]}"
            for item in sources
        )
        or "- (no sources)"
    )
    artifact_ids = ", ".join(str(item.get("id")) for item in artifacts) or "none"
    title_hint = str(input_projection.get("title_hint") or "").strip()
    return (
        "You are the knowledge-card drafter. Write a concise, accurate "
        "knowledge-card draft from the learner's validated evidence and its "
        "source snapshots. Do not mention the learner, the rubric, gaps, or "
        "the evaluation. Do not include provider JSON, data URIs, or base64.\n"
        f"prompt_version={prompt_version}\n"
        "Respond with STRICT JSON only, no prose, no markdown fences:\n"
        '{"title":"...", "body":"..."}\n\n'
        f"TITLE HINT (may be empty): {title_hint or '(none)'}\n\n"
        f"EVIDENCE:\n{evidence_lines}\n\n"
        f"SOURCES:\n{source_lines}\n\n"
        f"ARTIFACT IDS (referenced only, not embedded): {artifact_ids}\n"
    )


def parse_draft_output(raw: str) -> tuple[str, str]:
    """Strictly parse ``{title, body}`` from the provider's JSON output.

    Truly strict JSON (§7.9.1): the provider response must be *exactly* one
    JSON object with no markdown fences, no prose prefix/suffix and no trailing
    content after outer whitespace. Unknown keys, missing/invalid values and
    multiple objects are all rejected — a prompt-injected or malformed provider
    response never lands on the card.
    """
    text = (raw or "").strip()
    if not text:
        raise ValueError("draft executor returned empty output")
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError("draft executor output is not strict JSON") from exc
    if not isinstance(parsed, dict):
        raise ValueError("draft executor output must be a JSON object")
    unknown = [key for key in parsed if key not in ("title", "body")]
    if unknown:
        raise ValueError("draft executor output has unexpected keys: " + ", ".join(sorted(unknown)))
    if "title" not in parsed or "body" not in parsed:
        raise ValueError("draft executor output missing title/body")
    title = parsed["title"]
    body = parsed["body"]
    if not isinstance(title, str) or not isinstance(body, str):
        raise ValueError("draft executor output title/body must be strings")
    title = title.strip()
    body = body.strip()
    if not title or not body:
        raise ValueError("draft executor output missing nonblank title/body")
    return title, body


class FrozenModelDraftExecutor:
    """Production :class:`DraftExecutor` bound to one frozen evaluator snapshot.

    ``provider`` is an injectable ``async callable(messages, config) -> response``
    for offline tests; the default routes through the unified LLM
    factory/adapters.
    """

    def __init__(
        self,
        snapshot: Any,
        *,
        catalog: Any | None = None,
        provider: Any = None,
        prompt_version: str = DEFAULT_DRAFT_PROMPT_VERSION,
        timeout_seconds: float = 120.0,
    ) -> None:
        self._snapshot = snapshot
        self._catalog = catalog
        self._provider = provider
        self._prompt_version = prompt_version
        self._timeout_seconds = timeout_seconds

    @property
    def snapshot(self) -> Any:
        return self._snapshot

    async def generate(self, input_projection: dict[str, Any]) -> DraftOutput:
        config = frozen_evaluator_llm_config(self._snapshot, catalog=self._catalog)
        prompt = build_draft_prompt(input_projection, prompt_version=self._prompt_version)
        messages = [
            {"role": "system", "content": "You are a strict knowledge-card drafter."},
            {"role": "user", "content": prompt},
        ]
        try:
            response = await self._call_provider(config, messages)
        except EvaluatorUnavailableError:
            raise
        except Exception as exc:  # noqa: BLE001 - any provider failure surfaces as unavailable
            logger.warning("draft executor invocation failed (%s)", type(exc).__name__)
            raise EvaluatorUnavailableError(sanitized_error=str(exc)) from exc
        if response is None:
            raise EvaluatorUnavailableError(sanitized_error="draft executor returned no response")
        content = getattr(response, "content", None) or ""
        finish_reason = getattr(response, "finish_reason", None)
        if finish_reason == "error" or not content.strip():
            raise EvaluatorUnavailableError(
                sanitized_error=content[:500] or "draft executor returned an error status"
            )
        try:
            title, body = parse_draft_output(content)
        except ValueError as exc:
            raise EvaluatorUnavailableError(sanitized_error=f"invalid draft output: {exc}") from exc
        return DraftOutput(
            title=title,
            body=body,
            reported_model=str(getattr(response, "model", "") or "") or None,
            reported_version=None,
            usage=getattr(response, "usage", None),
        )

    async def _call_provider(self, config, messages: list[dict[str, Any]]):
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
        # Real timeout enforcement: a hung draft provider surfaces as
        # unavailable and the worker fails the attempt without a second call.
        return await asyncio.wait_for(call, timeout=self._timeout_seconds)


__all__ = [
    "DEFAULT_DRAFT_PROMPT_VERSION",
    "FrozenModelDraftExecutor",
    "build_draft_prompt",
    "parse_draft_output",
]
