# -*- coding: utf-8 -*-
"""
LLM Stats Tracker
=================

Simple utility for tracking LLM token usage and costs across all modules.
Outputs summary via the unified logging system.

Usage:
    from src.logging import LLMStats

    stats = LLMStats("Solver")

    # After each LLM call:
    stats.add_call(
        model="gpt-4o-mini",
        prompt_tokens=100,
        completion_tokens=50
    )

    # At the end:
    stats.log_summary()  # Uses logging system
"""

from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Any, Optional

if TYPE_CHECKING:
    from ..logger import Logger

# Model pricing per 1K tokens (USD)
MODEL_PRICING = {
    "gpt-4o": {"input": 0.0025, "output": 0.010},
    "gpt-4o-mini": {"input": 0.00015, "output": 0.0006},
    "gpt-4-turbo": {"input": 0.01, "output": 0.03},
    "gpt-4": {"input": 0.03, "output": 0.06},
    "gpt-3.5-turbo": {"input": 0.0005, "output": 0.0015},
    "deepseek-chat": {"input": 0.00014, "output": 0.00028},
    "claude-3-5-sonnet": {"input": 0.003, "output": 0.015},
    "claude-3-opus": {"input": 0.015, "output": 0.075},
    "claude-3-haiku": {"input": 0.00025, "output": 0.00125},
}


def get_pricing(model: str) -> dict[str, float]:
    """Get pricing for a model (fuzzy match)."""
    model_lower = model.lower()
    for key, pricing in MODEL_PRICING.items():
        if key in model_lower or model_lower in key:
            return pricing
    return MODEL_PRICING.get("gpt-4o-mini", {"input": 0.00015, "output": 0.0006})


def estimate_tokens(text: str) -> int:
    """Rough estimate of tokens (1.3 tokens per word)."""
    return int(len(text.split()) * 1.3)


@dataclass
class LLMCall:
    """Single LLM call record."""

    model: str
    prompt_tokens: int
    completion_tokens: int
    cost: float
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())


class LLMStats:
    """
    LLM usage statistics tracker.
    Tracks token usage and costs, outputs summary to terminal.
    """

    def __init__(self, module_name: str = "Module"):
        """
        Initialize stats tracker.

        Args:
            module_name: Name of the module (for display)
        """
        self.module_name = module_name
        self.calls: list[LLMCall] = []
        self.total_prompt_tokens = 0
        self.total_completion_tokens = 0
        self.total_cost = 0.0
        self.model_used: Optional[str] = None

    def add_call(
        self,
        model: str,
        prompt_tokens: Optional[int] = None,
        completion_tokens: Optional[int] = None,
        # Alternative: estimate from text
        system_prompt: Optional[str] = None,
        user_prompt: Optional[str] = None,
        response: Optional[str] = None,
    ):
        """
        Add an LLM call to the stats.

        Args:
            model: Model name
            prompt_tokens: Number of prompt tokens (if known)
            completion_tokens: Number of completion tokens (if known)
            system_prompt: System prompt text (for estimation)
            user_prompt: User prompt text (for estimation)
            response: Response text (for estimation)
        """
        # Estimate tokens if not provided
        if prompt_tokens is None and (system_prompt or user_prompt):
            prompt_text = (system_prompt or "") + "\n" + (user_prompt or "")
            prompt_tokens = estimate_tokens(prompt_text)

        if completion_tokens is None and response:
            completion_tokens = estimate_tokens(response)

        prompt_tokens = prompt_tokens or 0
        completion_tokens = completion_tokens or 0

        # Calculate cost
        pricing = get_pricing(model)
        cost = (prompt_tokens / 1000.0) * pricing["input"] + (completion_tokens / 1000.0) * pricing[
            "output"
        ]

        # Record call
        call = LLMCall(
            model=model, prompt_tokens=prompt_tokens, completion_tokens=completion_tokens, cost=cost
        )
        self.calls.append(call)

        # Update totals
        self.total_prompt_tokens += prompt_tokens
        self.total_completion_tokens += completion_tokens
        self.total_cost += cost

        # Track primary model
        if self.model_used is None:
            self.model_used = model

    def get_summary(self) -> dict[str, Any]:
        """Get summary as dictionary."""
        return {
            "module": self.module_name,
            "model": self.model_used or "Unknown",
            "calls": len(self.calls),
            "prompt_tokens": self.total_prompt_tokens,
            "completion_tokens": self.total_completion_tokens,
            "total_tokens": self.total_prompt_tokens + self.total_completion_tokens,
            "cost_usd": self.total_cost,
        }

    def log_summary(self, logger: Optional["Logger"] = None):
        """
        Log summary using the unified logging system.

        Args:
            logger: Optional Logger instance. If None, creates one using module_name.
        """
        if len(self.calls) == 0:
            return

        # Import here to avoid circular imports
        from ..logger import get_logger

        if logger is None:
            logger = get_logger(self.module_name)

        total_tokens = self.total_prompt_tokens + self.total_completion_tokens

        logger.info("=" * 60)
        logger.info(f"LLM Usage Summary for {self.module_name}")
        logger.info("=" * 60)
        logger.info(f"Model       : {self.model_used or 'Unknown'}")
        logger.info(f"API Calls   : {len(self.calls)}")
        logger.info(
            f"Tokens      : {total_tokens:,} (Input: {self.total_prompt_tokens:,}, Output: {self.total_completion_tokens:,})"
        )
        logger.info(f"Cost        : ${self.total_cost:.6f} USD")
        logger.info("=" * 60)

    def print_summary(self):
        """
        Print summary to terminal.

        Deprecated: Use log_summary() instead for consistent logging.
        """
        self.log_summary()

    def reset(self):
        """Reset all statistics."""
        self.calls.clear()
        self.total_prompt_tokens = 0
        self.total_completion_tokens = 0
        self.total_cost = 0.0
        self.model_used = None
