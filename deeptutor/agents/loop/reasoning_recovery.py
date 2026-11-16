"""Explicit policy for the existing single reasoning-budget recovery round."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class ReasoningBudgetRecovery:
    """Keep the retry count fixed while choosing its output budget."""

    strategy: str = "prompt"
    max_tokens: int = 0

    @classmethod
    def from_config(cls, value: Any, *, base_max_tokens: int) -> ReasoningBudgetRecovery:
        """Reject invalid opt-ins instead of silently choosing a cost policy."""
        if value is None:
            return cls()
        if not isinstance(value, dict):
            raise ValueError("chat.reasoning_budget_recovery must be a mapping")
        strategy = value.get("strategy", "prompt")
        if not isinstance(strategy, str) or strategy not in {
            "prompt",
            "stop",
            "increase_output_budget",
        }:
            raise ValueError("Unknown chat.reasoning_budget_recovery.strategy")
        maximum = value.get("max_tokens", 0)
        if strategy == "increase_output_budget" and (
            type(maximum) is not int or not base_max_tokens < maximum <= 131072
        ):
            raise ValueError(
                "Reasoning recovery max_tokens must exceed the normal output budget "
                "and be at most 131072"
            )
        return cls(
            strategy=strategy, max_tokens=maximum if strategy == "increase_output_budget" else 0
        )
