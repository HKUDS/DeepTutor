"""Output-token budgets are capped to what the model can actually return.

A budget above a model's output limit is rejected with HTTP 400 (gpt-4o and
gpt-4o-mini stop at 16384), and on a local server the prompt plus the budget
must fit inside the context window. The configured budget is a ceiling: the
request carries min(budget, model limit, half the configured window).
"""

from __future__ import annotations

import pytest

from deeptutor.runtime.agentic.client import build_completion_kwargs
from deeptutor.services.llm.config import get_token_limit_kwargs
from deeptutor.services.llm.output_limits import cap_output_tokens, known_output_limit


@pytest.mark.parametrize(
    ("model", "limit"),
    [
        ("gpt-4o", 16384),
        ("GPT-4o-mini", 16384),
        ("openai/gpt-4o", 16384),
        ("gpt-4o-2024-08-06", 16384),
        ("gpt-4o-2024-05-13", 4096),
        ("qwen-max", 8192),
        ("deepseek-flash", None),
        ("my-local-model", None),
    ],
)
def test_known_output_limit(model: str, limit: int | None) -> None:
    assert known_output_limit(model) == limit


def test_a_budget_above_the_model_limit_is_lowered_to_it() -> None:
    assert cap_output_tokens(32768, model="gpt-4o") == 16384


def test_a_budget_within_the_model_limit_is_kept() -> None:
    assert cap_output_tokens(8000, model="gpt-4o") == 8000
    assert cap_output_tokens(32768, model="deepseek-flash") == 32768


def test_a_configured_context_window_leaves_room_for_the_prompt() -> None:
    # A 32k local server cannot take a 32k answer on top of the prompt.
    assert cap_output_tokens(32768, model="my-local-model", context_window=32768) == 16384
    assert cap_output_tokens(8000, model="my-local-model", context_window=32768) == 8000
    assert cap_output_tokens(32768, model="gpt-4o", context_window=128000) == 16384


def test_token_limit_kwargs_carry_the_capped_value() -> None:
    assert get_token_limit_kwargs("gpt-4o", 32768) == {"max_completion_tokens": 16384}
    assert get_token_limit_kwargs("deepseek-flash", 32768) == {"max_tokens": 32768}
    assert get_token_limit_kwargs("my-local-model", 32768, context_window=32768) == {
        "max_tokens": 16384
    }


def test_completion_kwargs_carry_the_capped_value() -> None:
    kwargs = build_completion_kwargs(
        temperature=0.2, model="my-local-model", max_tokens=32768, context_window=32768
    )
    assert kwargs["max_tokens"] == 16384
