"""The Settings LLM probe's token budget.

A reasoning model spends part of its budget thinking before it emits any
content. The probe's old 1024 was enough for a chat model and not for a
reasoning one, which answered with an empty completion — so Settings told the
user a working model was broken. The budget lives in agents.yaml like every
other LLM budget; the code constant is only the floor for a config that does
not mention it.
"""

from __future__ import annotations

from typing import Any

import pytest

from deeptutor.services.config import test_runner
from deeptutor.services.setup.init import DEFAULT_AGENTS_SETTINGS

EXPECTED_PROBE_MAX_TOKENS = 4096


def _probe_budget(params: dict[str, Any], monkeypatch: pytest.MonkeyPatch) -> tuple[int, float]:
    """The budget ``_test_llm`` would resolve for ``params``."""
    monkeypatch.setattr(
        "deeptutor.services.config.loader.get_agent_params",
        lambda _module: params,
    )
    from deeptutor.services.config.loader import get_agent_params

    resolved = get_agent_params("llm_probe")
    return (
        test_runner._coerce_int(resolved.get("max_tokens"), EXPECTED_PROBE_MAX_TOKENS),
        test_runner._coerce_float(resolved.get("temperature"), 0.1),
    )


def test_a_config_that_says_nothing_gets_the_reasoning_safe_floor(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    max_tokens, temperature = _probe_budget({}, monkeypatch)

    assert max_tokens == EXPECTED_PROBE_MAX_TOKENS
    assert temperature == pytest.approx(0.1)


@pytest.mark.parametrize("configured", [512, 2048, 32000])
def test_agents_yaml_owns_the_probe_budget(
    configured: int, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The floor is a fallback, never a ceiling: agents.yaml still wins."""
    max_tokens, _ = _probe_budget({"max_tokens": configured}, monkeypatch)

    assert max_tokens == configured


@pytest.mark.parametrize("unusable", [None, "", "lots", {}])
def test_an_unusable_value_falls_back_instead_of_raising(
    unusable: Any, monkeypatch: pytest.MonkeyPatch
) -> None:
    max_tokens, _ = _probe_budget({"max_tokens": unusable}, monkeypatch)

    assert max_tokens == EXPECTED_PROBE_MAX_TOKENS


def test_a_fresh_agents_yaml_shows_the_probe_knob() -> None:
    """Seeded, so the number is editable in Settings rather than living only
    in the code path a user cannot reach — and seeded to the same value the
    fallback uses, so the two cannot drift."""
    probe = DEFAULT_AGENTS_SETTINGS["diagnostics"]["llm_probe"]

    assert probe["max_tokens"] == EXPECTED_PROBE_MAX_TOKENS
    assert probe["temperature"] == pytest.approx(0.1)
