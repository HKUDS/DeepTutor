#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Token Tracker - LLM Token usage and cost tracking system (Advanced)
Uses tiktoken for precise token counting, supports multiple models and more accurate cost calculation
"""

from dataclasses import asdict, dataclass, field
from datetime import datetime
import json
from typing import Any

# Try importing tiktoken (if available)
try:
    import tiktoken

    TIKTOKEN_AVAILABLE = True
except ImportError:
    TIKTOKEN_AVAILABLE = False
    tiktoken = None

# Try importing litellm (optional advanced library)
try:
    import litellm
    from litellm import token_counter

    LITELLM_AVAILABLE = True
except ImportError:
    LITELLM_AVAILABLE = False
    litellm = None


# Model pricing table (price per 1K tokens, unit: USD)
# Data source: Official pricing from various vendors (November 2024)
MODEL_PRICING = {
    # OpenAI GPT Series
    "gpt-4o": {"input": 0.0025, "output": 0.010},
    "gpt-4o-mini": {"input": 0.00015, "output": 0.0006},
    "gpt-4-turbo": {"input": 0.01, "output": 0.03},
    "gpt-4": {"input": 0.03, "output": 0.06},
    "gpt-4-32k": {"input": 0.06, "output": 0.12},
    "gpt-3.5-turbo": {"input": 0.0005, "output": 0.0015},
    "gpt-3.5-turbo-16k": {"input": 0.003, "output": 0.004},
    # DeepSeek Series
    "deepseek-chat": {"input": 0.00014, "output": 0.00028},
    "deepseek-coder": {"input": 0.00014, "output": 0.00028},
    # Anthropic Claude Series
    "claude-3-opus": {"input": 0.015, "output": 0.075},
    "claude-3-sonnet": {"input": 0.003, "output": 0.015},
    "claude-3-haiku": {"input": 0.00025, "output": 0.00125},
    "claude-3-5-sonnet": {"input": 0.003, "output": 0.015},
    # Google Gemini Series
    "gemini-pro": {"input": 0.0005, "output": 0.0015},
    "gemini-1.5-pro": {"input": 0.00125, "output": 0.005},
    "gemini-1.5-flash": {"input": 0.000075, "output": 0.0003},
}


def get_tiktoken_encoding(model_name: str):
    """
    Get tiktoken encoder (for precise token counting)

    Args:
        model_name: Model name

    Returns:
        tiktoken.Encoding object, returns None if not available
    """
    if not TIKTOKEN_AVAILABLE:
        return None

    try:
        # Try getting encoding based on model name
        if "gpt-4" in model_name.lower() or "gpt-3.5" in model_name.lower():
            return tiktoken.encoding_for_model(model_name)
        if "gpt-4o" in model_name.lower():
            return tiktoken.encoding_for_model("gpt-4o")
        # Default to cl100k_base (encoding for GPT-3.5/GPT-4)
        return tiktoken.get_encoding("cl100k_base")
    except Exception:
        # If fails, use default encoding
        return tiktoken.get_encoding("cl100k_base")


def count_tokens_with_tiktoken(text: str, model_name: str) -> int:
    """
    Precisely calculate token count using tiktoken

    Args:
        text: Text to calculate
        model_name: Model name (for selecting correct encoding)

    Returns:
        Token count
    """
    if not TIKTOKEN_AVAILABLE:
        return 0

    encoding = get_tiktoken_encoding(model_name)
    if encoding is None:
        return 0

    return len(encoding.encode(text))


def count_tokens_with_litellm(messages: list[dict], model_name: str) -> dict[str, int]:
    """
    Calculate token count using litellm (if available)

    Args:
        messages: Message list
        model_name: Model name

    Returns:
        {'prompt_tokens': int, 'completion_tokens': int, 'total_tokens': int}
    """
    if not LITELLM_AVAILABLE:
        return {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}

    try:
        # Use litellm's token_counter
        token_count = token_counter(model=model_name, messages=messages)
        return {
            "prompt_tokens": token_count,
            "completion_tokens": 0,  # litellm only counts prompt tokens
            "total_tokens": token_count,
        }
    except Exception:
        return {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}


def calculate_cost_with_litellm(model: str, prompt_tokens: int, completion_tokens: int) -> float:
    """
    Calculate cost using litellm (more accurate if available)

    Args:
        model: Model name
        prompt_tokens: Input tokens
        completion_tokens: Output tokens

    Returns:
        Cost (USD)
    """
    if not LITELLM_AVAILABLE:
        # Fall back to manual calculation
        return calculate_cost(model, prompt_tokens, completion_tokens)

    try:
        # Use litellm's completion_cost function
        cost = litellm.completion_cost(
            model=model, prompt_tokens=prompt_tokens, completion_tokens=completion_tokens
        )
        return cost
    except Exception:
        # If failed, fall back to manual calculation
        return calculate_cost(model, prompt_tokens, completion_tokens)


def get_model_pricing(model_name: str) -> dict[str, float]:
    """
    Get model pricing information

    Args:
        model_name: Model name

    Returns:
        {'input': float, 'output': float} Price per 1K tokens (USD)
    """
    # Try exact match
    if model_name in MODEL_PRICING:
        return MODEL_PRICING[model_name]

    # Try fuzzy match (handle model names with version numbers)
    model_lower = model_name.lower()
    for key, pricing in MODEL_PRICING.items():
        if key.lower() in model_lower or model_lower in key.lower():
            return pricing

    # If using litellm, try to get price from litellm
    if LITELLM_AVAILABLE:
        try:
            # litellm has built-in pricing table
            model_info = litellm.get_model_info(model=model_name)
            if model_info and "input_cost_per_token" in model_info:
                return {
                    "input": model_info.get("input_cost_per_token", 0) * 1000,
                    "output": model_info.get("output_cost_per_token", 0) * 1000,
                }
        except Exception:
            pass

    # Default price (use gpt-4o-mini as conservative estimate)
    return MODEL_PRICING.get("gpt-4o-mini", {"input": 0.00015, "output": 0.0006})


def calculate_cost(model_name: str, prompt_tokens: int, completion_tokens: int) -> float:
    """
    Calculate LLM call cost (backward compatibility function)

    Args:
        model_name: Model name
        prompt_tokens: Number of input tokens
        completion_tokens: Number of output tokens

    Returns:
        Cost (USD)
    """
    pricing = get_model_pricing(model_name)

    input_cost = (prompt_tokens / 1000.0) * pricing["input"]
    output_cost = (completion_tokens / 1000.0) * pricing["output"]

    return input_cost + output_cost


@dataclass
class TokenUsage:
    """Token usage record for a single LLM call"""

    agent_name: str
    stage: str
    model: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    cost_usd: float = 0.0
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    # New field
    calculation_method: str = "api"  # "api", "tiktoken", "litellm", "estimated"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class TokenTracker:
    """
    Token Tracker (Advanced Version)
    Supports multiple token counting methods: API response > tiktoken > litellm > estimation
    """

    def __init__(self, prefer_tiktoken: bool = True, prefer_litellm: bool = False):
        """
        Initialize tracker.

        Args:
            prefer_tiktoken: If API doesn't return usage, prefer tiktoken calculation (default True)
            prefer_litellm: Whether to prefer litellm (requires litellm installation, default False)
        """
        self.usage_records: list[TokenUsage] = []
        self.total_prompt_tokens = 0
        self.total_completion_tokens = 0
        self.total_tokens = 0
        self.total_cost_usd = 0.0
        self.prefer_tiktoken = prefer_tiktoken and TIKTOKEN_AVAILABLE
        self.prefer_litellm = prefer_litellm and LITELLM_AVAILABLE

        # Callback for real-time updates (e.g., to display_manager)
        self._on_usage_added_callback = None

    def set_on_usage_added_callback(self, callback):
        """
        Set a callback to be called whenever usage is added.
        The callback receives the summary dict.

        Args:
            callback: Function that takes summary dict as argument
        """
        self._on_usage_added_callback = callback

    def add_usage(
        self,
        agent_name: str,
        stage: str,
        model: str,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        token_counts: dict[str, int] | None = None,
        # New parameters: for precise calculation
        system_prompt: str | None = None,
        user_prompt: str | None = None,
        response_text: str | None = None,
        messages: list[dict] | None = None,
    ):
        """
        Add token usage record (supports multiple calculation methods)

        Args:
            agent_name: Agent name
            stage: Stage name
            model: Model name
            prompt_tokens: Input tokens (will be overridden if token_counts is provided)
            completion_tokens: Output tokens (will be overridden if token_counts is provided)
            token_counts: Optional token count dictionary (from API response, most accurate)
            system_prompt: System prompt (for tiktoken calculation)
            user_prompt: User prompt (for tiktoken calculation)
            response_text: Response text (for tiktoken calculation)
            messages: Message list (for litellm calculation)
        """
        calculation_method = "api"

        # If token_counts is provided (from API response), prioritize using it
        if token_counts:
            prompt_tokens = token_counts.get("prompt_tokens", prompt_tokens)
            completion_tokens = token_counts.get("completion_tokens", completion_tokens)
            calculation_method = "api"
        # If no API data, try using tiktoken for precise calculation
        elif self.prefer_tiktoken and system_prompt and user_prompt:
            prompt_tokens = count_tokens_with_tiktoken(system_prompt + "\n" + user_prompt, model)
            if response_text:
                completion_tokens = count_tokens_with_tiktoken(response_text, model)
            calculation_method = "tiktoken"
        # If litellm is available and messages are provided
        elif self.prefer_litellm and messages:
            result = count_tokens_with_litellm(messages, model)
            prompt_tokens = result["prompt_tokens"]
            completion_tokens = result.get("completion_tokens", completion_tokens)
            calculation_method = "litellm"
        # If none available, use estimation (fallback)
        elif system_prompt and user_prompt:
            # Simple estimation
            estimated_prompt_tokens = int(
                (len(system_prompt.split()) + len(user_prompt.split())) * 1.3
            )
            prompt_tokens = estimated_prompt_tokens
            if response_text:
                completion_tokens = int(len(response_text.split()) * 1.3)
            calculation_method = "estimated"

        total_tokens = prompt_tokens + completion_tokens

        # Calculate cost (prefer litellm, otherwise manual calculation)
        if self.prefer_litellm and LITELLM_AVAILABLE:
            cost_usd = calculate_cost_with_litellm(model, prompt_tokens, completion_tokens)
        else:
            cost_usd = calculate_cost(model, prompt_tokens, completion_tokens)

        # Create usage record
        usage = TokenUsage(
            agent_name=agent_name,
            stage=stage,
            model=model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total_tokens,
            cost_usd=cost_usd,
            calculation_method=calculation_method,
        )

        self.usage_records.append(usage)

        # Update totals
        self.total_prompt_tokens += prompt_tokens
        self.total_completion_tokens += completion_tokens
        self.total_tokens += total_tokens
        self.total_cost_usd += cost_usd

        # Invoke callback for real-time updates
        if self._on_usage_added_callback:
            try:
                self._on_usage_added_callback(self.get_summary())
            except Exception:
                pass  # Don't let callback errors affect main flow

    def get_summary(self) -> dict[str, Any]:
        """
        Get usage summary

        Returns:
            {
                'total_prompt_tokens': int,
                'total_completion_tokens': int,
                'total_tokens': int,
                'total_cost_usd': float,
                'total_calls': int,
                'by_agent': Dict[str, Dict],
                'by_model': Dict[str, Dict],
                'by_method': Dict[str, Dict],  # New: statistics by calculation method
                'tiktoken_available': bool,
                'litellm_available': bool
            }
        """
        by_agent: dict[str, dict[str, Any]] = {}
        by_model: dict[str, dict[str, Any]] = {}
        by_method: dict[str, dict[str, Any]] = {}

        for usage in self.usage_records:
            # Statistics by Agent
            if usage.agent_name not in by_agent:
                by_agent[usage.agent_name] = {
                    "prompt_tokens": 0,
                    "completion_tokens": 0,
                    "total_tokens": 0,
                    "cost_usd": 0.0,
                    "calls": 0,
                }
            by_agent[usage.agent_name]["prompt_tokens"] += usage.prompt_tokens
            by_agent[usage.agent_name]["completion_tokens"] += usage.completion_tokens
            by_agent[usage.agent_name]["total_tokens"] += usage.total_tokens
            by_agent[usage.agent_name]["cost_usd"] += usage.cost_usd
            by_agent[usage.agent_name]["calls"] += 1

            # Statistics by model
            if usage.model not in by_model:
                by_model[usage.model] = {
                    "prompt_tokens": 0,
                    "completion_tokens": 0,
                    "total_tokens": 0,
                    "cost_usd": 0.0,
                    "calls": 0,
                }
            by_model[usage.model]["prompt_tokens"] += usage.prompt_tokens
            by_model[usage.model]["completion_tokens"] += usage.completion_tokens
            by_model[usage.model]["total_tokens"] += usage.total_tokens
            by_model[usage.model]["cost_usd"] += usage.cost_usd
            by_model[usage.model]["calls"] += 1

            # Statistics by calculation method
            method = usage.calculation_method
            if method not in by_method:
                by_method[method] = {
                    "prompt_tokens": 0,
                    "completion_tokens": 0,
                    "total_tokens": 0,
                    "cost_usd": 0.0,
                    "calls": 0,
                }
            by_method[method]["prompt_tokens"] += usage.prompt_tokens
            by_method[method]["completion_tokens"] += usage.completion_tokens
            by_method[method]["total_tokens"] += usage.total_tokens
            by_method[method]["cost_usd"] += usage.cost_usd
            by_method[method]["calls"] += 1

        return {
            "total_prompt_tokens": self.total_prompt_tokens,
            "total_completion_tokens": self.total_completion_tokens,
            "total_tokens": self.total_tokens,
            "total_cost_usd": self.total_cost_usd,
            "total_calls": len(self.usage_records),
            "by_agent": by_agent,
            "by_model": by_model,
            "by_method": by_method,  # New: statistics by calculation method
            "tiktoken_available": TIKTOKEN_AVAILABLE,
            "litellm_available": LITELLM_AVAILABLE,
        }

    def format_summary(self) -> str:
        """
        Format usage summary as readable string

        Returns:
            Formatted summary string
        """
        summary = self.get_summary()

        lines = [
            "=" * 70,
            "💰 LLM Cost Statistics",
            "=" * 70,
            f"Total calls: {summary['total_calls']}",
            f"Total Tokens: {summary['total_tokens']:,}",
            f"  - Input: {summary['total_prompt_tokens']:,}",
            f"  - Output: {summary['total_completion_tokens']:,}",
            f"Total cost: ${summary['total_cost_usd']:.6f} USD",
        ]

        # If advanced features are used, show tool status and calculation method statistics
        if summary.get("tiktoken_available") or summary.get("litellm_available"):
            lines.append("")
            lines.append("Calculation Tool Status:")
            lines.append(
                f"  - tiktoken: {'✓ Available' if summary['tiktoken_available'] else '✗ Unavailable'}"
            )
            lines.append(
                f"  - litellm: {'✓ Available' if summary['litellm_available'] else '✗ Unavailable'}"
            )

            if summary.get("by_method"):
                lines.append("")
                lines.append("Statistics by Calculation Method:")
                lines.append("-" * 70)
                for method, stats in sorted(summary["by_method"].items()):
                    method_name = {
                        "api": "API Response",
                        "tiktoken": "tiktoken Precise Calculation",
                        "litellm": "litellm Calculation",
                        "estimated": "Estimation",
                    }.get(method, method)
                    lines.append(f"  {method_name}:")
                    lines.append(f"    Calls: {stats['calls']}")
                    lines.append(f"    Tokens: {stats['total_tokens']:,}")
                    lines.append(f"    Cost: ${stats['cost_usd']:.6f} USD")
                    lines.append("")

        lines.append("Statistics by Agent:")
        lines.append("-" * 70)
        for agent_name, stats in sorted(summary["by_agent"].items()):
            lines.append(f"  {agent_name}:")
            lines.append(f"    Calls: {stats['calls']}")
            lines.append(
                f"    Tokens: {stats['total_tokens']:,} (Input: {stats['prompt_tokens']:,}, Output: {stats['completion_tokens']:,})"
            )
            lines.append(f"    Cost: ${stats['cost_usd']:.6f} USD")
            lines.append("")

        lines.append("Statistics by Model:")
        lines.append("-" * 70)
        for model, stats in sorted(summary["by_model"].items()):
            lines.append(f"  {model}:")
            lines.append(f"    Calls: {stats['calls']}")
            lines.append(
                f"    Tokens: {stats['total_tokens']:,} (Input: {stats['prompt_tokens']:,}, Output: {stats['completion_tokens']:,})"
            )
            lines.append(f"    Cost: ${stats['cost_usd']:.6f} USD")
            lines.append("")

        lines.append("=" * 70)

        return "\n".join(lines)

    def reset(self):
        """Reset all statistics"""
        self.usage_records.clear()
        self.total_prompt_tokens = 0
        self.total_completion_tokens = 0
        self.total_tokens = 0
        self.total_cost_usd = 0.0

    def save(self, filepath: str):
        """
        Save usage records to file

        Args:
            filepath: Save path
        """
        data = {
            "summary": self.get_summary(),
            "records": [usage.to_dict() for usage in self.usage_records],
        }

        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
