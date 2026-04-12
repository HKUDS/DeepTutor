#!/usr/bin/env python
"""
Token Tracker - LLM Token usage and cost tracking system (DR-in-KG version)
References student_TA/solve_agents/utils/token_tracker.py, with minor trimming and added global singleton getter method.
"""

from dataclasses import asdict, dataclass, field
from datetime import datetime
import json
from typing import Any

# Try importing tiktoken (if available)
try:
    import tiktoken  # type: ignore

    TIKTOKEN_AVAILABLE = True
except ImportError:
    TIKTOKEN_AVAILABLE = False
    tiktoken = None  # type: ignore

# Try importing litellm (optional)
try:
    import litellm  # type: ignore
    from litellm import token_counter  # type: ignore

    LITELLM_AVAILABLE = True
except ImportError:
    LITELLM_AVAILABLE = False
    litellm = None  # type: ignore

# Model pricing table (USD per 1K tokens)
MODEL_PRICING = {
    "gpt-4o": {"input": 0.0025, "output": 0.010},
    "gpt-4o-mini": {"input": 0.00015, "output": 0.0006},
    "gpt-4-turbo": {"input": 0.01, "output": 0.03},
    "gpt-4": {"input": 0.03, "output": 0.06},
    "gpt-3.5-turbo": {"input": 0.0005, "output": 0.0015},
    "deepseek-chat": {"input": 0.00014, "output": 0.00028},
    "deepseek-coder": {"input": 0.00014, "output": 0.00028},
}


def get_tiktoken_encoding(model_name: str):
    if not TIKTOKEN_AVAILABLE:
        return None
    try:
        if "gpt-4" in model_name.lower() or "gpt-3.5" in model_name.lower():
            return tiktoken.encoding_for_model(model_name)
        if "gpt-4o" in model_name.lower():
            return tiktoken.encoding_for_model("gpt-4o")
        return tiktoken.get_encoding("cl100k_base")
    except Exception:
        return tiktoken.get_encoding("cl100k_base") if TIKTOKEN_AVAILABLE else None


def count_tokens_with_tiktoken(text: str, model_name: str) -> int:
    if not TIKTOKEN_AVAILABLE:
        return 0
    enc = get_tiktoken_encoding(model_name)
    if enc is None:
        return 0
    return len(enc.encode(text))


def count_tokens_with_litellm(messages: list[dict], model_name: str) -> dict[str, int]:
    if not LITELLM_AVAILABLE:
        return {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    try:
        token_count = token_counter(model=model_name, messages=messages)  # type: ignore
        return {"prompt_tokens": token_count, "completion_tokens": 0, "total_tokens": token_count}
    except Exception:
        return {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}


def get_model_pricing(model_name: str) -> dict[str, float]:
    if model_name in MODEL_PRICING:
        return MODEL_PRICING[model_name]
    # Fuzzy matching
    lower = model_name.lower()
    for key, val in MODEL_PRICING.items():
        if key in lower or lower in key:
            return val
    # litellm query
    if LITELLM_AVAILABLE:
        try:
            info = litellm.get_model_info(model=model_name)  # type: ignore
            if info and "input_cost_per_token" in info:
                return {
                    "input": info.get("input_cost_per_token", 0) * 1000,
                    "output": info.get("output_cost_per_token", 0) * 1000,
                }
        except Exception:
            pass
    return MODEL_PRICING["gpt-4o-mini"]


def calculate_cost(model_name: str, prompt_tokens: int, completion_tokens: int) -> float:
    pricing = get_model_pricing(model_name)
    return (prompt_tokens / 1000.0) * pricing["input"] + (completion_tokens / 1000.0) * pricing[
        "output"
    ]


@dataclass
class TokenUsage:
    agent_name: str
    stage: str
    model: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    total_tokens: int = 0
    cost_usd: float = 0.0
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())
    calculation_method: str = "api"  # "api"|"tiktoken"|"litellm"|"estimated"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class TokenTracker:
    def __init__(self, prefer_tiktoken: bool = True, prefer_litellm: bool = False):
        self.usage_records: list[TokenUsage] = []
        self.total_prompt_tokens = 0
        self.total_completion_tokens = 0
        self.total_tokens = 0
        self.total_cost_usd = 0.0
        self.prefer_tiktoken = prefer_tiktoken and TIKTOKEN_AVAILABLE
        self.prefer_litellm = prefer_litellm and LITELLM_AVAILABLE

    def add_usage(
        self,
        agent_name: str,
        stage: str,
        model: str,
        prompt_tokens: int = 0,
        completion_tokens: int = 0,
        token_counts: dict[str, int] | None = None,
        system_prompt: str | None = None,
        user_prompt: str | None = None,
        response_text: str | None = None,
        messages: list[dict] | None = None,
    ):
        method = "api"
        if token_counts:
            prompt_tokens = token_counts.get("prompt_tokens", prompt_tokens)
            completion_tokens = token_counts.get("completion_tokens", completion_tokens)
            method = "api"
        elif self.prefer_tiktoken and (system_prompt or user_prompt):
            prompt_text = (system_prompt or "") + "\n" + (user_prompt or "")
            prompt_tokens = count_tokens_with_tiktoken(prompt_text, model)
            completion_tokens = count_tokens_with_tiktoken(response_text or "", model)
            method = "tiktoken"
        elif self.prefer_litellm and messages:
            res = count_tokens_with_litellm(messages, model)
            prompt_tokens = res["prompt_tokens"]
            completion_tokens = res.get("completion_tokens", completion_tokens)
            method = "litellm"
        else:
            # Estimate: approximate by word count * 1.3
            est_prompt = int(
                (((system_prompt or "") + "\n" + (user_prompt or "")).split().__len__()) * 1.3
            )
            prompt_tokens = est_prompt
            completion_tokens = int(((response_text or "").split().__len__()) * 1.3)
            method = "estimated"

        total = prompt_tokens + completion_tokens
        cost = calculate_cost(model, prompt_tokens, completion_tokens)

        usage = TokenUsage(
            agent_name=agent_name,
            stage=stage,
            model=model,
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
            total_tokens=total,
            cost_usd=cost,
            calculation_method=method,
        )
        self.usage_records.append(usage)
        self.total_prompt_tokens += prompt_tokens
        self.total_completion_tokens += completion_tokens
        self.total_tokens += total
        self.total_cost_usd += cost

    def get_summary(self) -> dict[str, Any]:
        by_agent: dict[str, dict[str, Any]] = {}
        by_model: dict[str, dict[str, Any]] = {}
        by_method: dict[str, dict[str, Any]] = {}
        for u in self.usage_records:
            pa = by_agent.setdefault(
                u.agent_name,
                {
                    "prompt_tokens": 0,
                    "completion_tokens": 0,
                    "total_tokens": 0,
                    "cost_usd": 0.0,
                    "calls": 0,
                },
            )
            pm = by_model.setdefault(
                u.model,
                {
                    "prompt_tokens": 0,
                    "completion_tokens": 0,
                    "total_tokens": 0,
                    "cost_usd": 0.0,
                    "calls": 0,
                },
            )
            mm = by_method.setdefault(
                u.calculation_method,
                {
                    "prompt_tokens": 0,
                    "completion_tokens": 0,
                    "total_tokens": 0,
                    "cost_usd": 0.0,
                    "calls": 0,
                },
            )
            for bucket in (pa, pm, mm):
                bucket["prompt_tokens"] += u.prompt_tokens
                bucket["completion_tokens"] += u.completion_tokens
                bucket["total_tokens"] += u.total_tokens
                bucket["cost_usd"] += u.cost_usd
                bucket["calls"] += 1
        return {
            "total_prompt_tokens": self.total_prompt_tokens,
            "total_completion_tokens": self.total_completion_tokens,
            "total_tokens": self.total_tokens,
            "total_cost_usd": self.total_cost_usd,
            "total_calls": len(self.usage_records),
            "by_agent": by_agent,
            "by_model": by_model,
            "by_method": by_method,
            "tiktoken_available": TIKTOKEN_AVAILABLE,
            "litellm_available": LITELLM_AVAILABLE,
        }

    def format_summary(self) -> str:
        s = self.get_summary()
        lines = [
            "=" * 70,
            "📊 [DeepResearch] LLM Usage Summary",
            "=" * 70,
            f"Total API Calls: {s['total_calls']}",
            f"Total Tokens: {s['total_tokens']:,}",
            f"  - Input: {s['total_prompt_tokens']:,}",
            f"  - Output: {s['total_completion_tokens']:,}",
            f"Total Cost: ${s['total_cost_usd']:.6f} USD",
            "",
            "By Agent:",
            "-" * 70,
        ]
        for agent, stats in sorted(s["by_agent"].items()):
            lines += [
                f"  {agent}:",
                f"    Calls: {stats['calls']}",
                f"    Tokens: {stats['total_tokens']:,} (Input: {stats['prompt_tokens']:,}, Output: {stats['completion_tokens']:,})",
                f"    Cost: ${stats['cost_usd']:.6f} USD",
                "",
            ]
        lines += ["By Model:", "-" * 70]
        for model, stats in sorted(s["by_model"].items()):
            lines += [
                f"  {model}:",
                f"    Calls: {stats['calls']}",
                f"    Tokens: {stats['total_tokens']:,} (Input: {stats['prompt_tokens']:,}, Output: {stats['completion_tokens']:,})",
                f"    Cost: ${stats['cost_usd']:.6f} USD",
                "",
            ]
        lines.append("=" * 70)
        return "\n".join(lines)

    def reset(self):
        self.usage_records.clear()
        self.total_prompt_tokens = 0
        self.total_completion_tokens = 0
        self.total_tokens = 0
        self.total_cost_usd = 0.0

    def save(self, filepath: str):
        data = {"summary": self.get_summary(), "records": [u.to_dict() for u in self.usage_records]}
        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)


# Global singleton
_global_tracker: TokenTracker | None = None


def get_token_tracker() -> TokenTracker:
    global _global_tracker
    if _global_tracker is None:
        _global_tracker = TokenTracker()
    return _global_tracker
