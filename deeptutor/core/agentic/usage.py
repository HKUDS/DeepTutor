"""Token-usage accumulator shared across LLM calls within a single turn."""

from __future__ import annotations

from typing import Any


class UsageTracker:
    """Accumulate prompt/completion tokens across many streaming LLM calls.

    Two ingestion paths:

    * :meth:`add_from_response` — read OpenAI ``CompletionUsage`` (or the
      streaming ``usage`` chunk) when the provider returns it.
    * :meth:`add_estimated` — fall back to a coarse ``chars / 3.5`` estimate
      for providers that don't emit ``usage`` (used by chat's answer-now path).

    Construct with ``model=<name>`` so :meth:`summary` can resolve a
    ``total_cost_usd`` via the pricing table in ``deeptutor.logging.stats``.
    """

    def __init__(self, *, model: str | None = None) -> None:
        self.prompt_tokens: int = 0
        self.completion_tokens: int = 0
        self.total_tokens: int = 0
        self.calls: int = 0
        self.model: str | None = model

    def add_from_response(self, response_or_usage: Any) -> None:
        usage = getattr(response_or_usage, "usage", None) or response_or_usage
        prompt = int(getattr(usage, "prompt_tokens", 0) or 0)
        completion = int(getattr(usage, "completion_tokens", 0) or 0)
        total = int(getattr(usage, "total_tokens", prompt + completion) or 0)
        if prompt or completion or total:
            self.prompt_tokens += prompt
            self.completion_tokens += completion
            self.total_tokens += total
            self.calls += 1

    def add_estimated(self, *, input_chars: int, output_chars: int) -> None:
        est_input = int(input_chars / 3.5)
        est_output = int(output_chars / 3.5)
        self.prompt_tokens += est_input
        self.completion_tokens += est_output
        self.total_tokens += est_input + est_output
        self.calls += 1

    def add_usage(
        self,
        *,
        agent_name: str = "",
        stage: str = "",
        model: str = "",
        system_prompt: str = "",
        user_prompt: str = "",
        response_text: str = "",
    ) -> None:
        """Adapter for :class:`~deeptutor.agents.base_agent.BaseAgent`.

        ``BaseAgent._track_tokens`` looks for an external tracker exposing
        ``add_usage(...)``; this method lets a :class:`UsageTracker` be
        passed as the ``token_tracker`` constructor argument so a
        capability pipeline can aggregate cost across all of its
        BaseAgent-derived sub-agents in one place.

        We fall back to a character-based estimate because BaseAgent
        only hands us the prompt/response text (the raw provider usage
        object is not available at that layer).
        """
        if model and not self.model:
            self.model = model
        input_chars = len(system_prompt or "") + len(user_prompt or "")
        output_chars = len(response_text or "")
        if input_chars or output_chars:
            self.add_estimated(input_chars=input_chars, output_chars=output_chars)

    def summary(self) -> dict[str, Any] | None:
        if self.calls == 0:
            return None
        cost_usd = 0.0
        if self.model:
            # Local import keeps ``core.agentic`` import-light at module load.
            from deeptutor.logging.stats.llm_stats import get_pricing

            pricing = get_pricing(self.model)
            cost_usd = (self.prompt_tokens / 1000.0) * pricing.get("input", 0.0) + (
                self.completion_tokens / 1000.0
            ) * pricing.get("output", 0.0)
        return {
            "total_cost_usd": cost_usd,
            "total_tokens": self.total_tokens,
            "total_calls": self.calls,
            "prompt_tokens": self.prompt_tokens,
            "completion_tokens": self.completion_tokens,
        }
