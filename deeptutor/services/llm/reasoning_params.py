"""Reasoning/thinking parameters for OpenAI-compatible provider calls."""

from __future__ import annotations

from typing import Any

#: Reasoning level to ask for on a second attempt, after a first one spent its
#: whole ``max_tokens`` budget thinking and returned no answer. ``"low"``
#: rather than ``"minimal"``: local/Qwen models served via vLLM reject
#: ``"minimal"``, and it disables thinking outright rather than trimming it.
RETRY_REASONING_EFFORT = "low"

_THINKING_STYLE_MAP = {
    "thinking_type": lambda enabled: {"thinking": {"type": "enabled" if enabled else "disabled"}},
    "enable_thinking": lambda enabled: {"enable_thinking": enabled},
    "reasoning_split": lambda enabled: {"reasoning_split": enabled},
}
# These values are used by callers that need a guaranteed reader-facing
# response.  ``minimal``/``minimum`` are retained as off sentinels for
# provider-native thinking controls for backwards compatibility; OpenRouter
# receives the canonical ``none`` value below.
_THINKING_OFF_EFFORTS = frozenset({"none", "minimal", "minimum"})
_PROVIDER_THINKING_STYLES = {
    "deepseek": "thinking_type",
    "volcengine": "thinking_type",
    "volcengine_coding_plan": "thinking_type",
    "byteplus": "thinking_type",
    "byteplus_coding_plan": "thinking_type",
    "dashscope": "enable_thinking",
    "minimax": "reasoning_split",
}
_PROVIDER_REASONING_PATTERNS = {
    "deepseek": ("deepseek-v4-pro", "deepseek-reasoner"),
    "dashscope": ("qwen3", "qwen-3", "qwq", "qwen-plus"),
}
# Models that ship with thinking enabled by default and burn the entire
# `max_tokens` budget on reasoning unless we explicitly turn it off via the
# top-level ``reasoning_effort`` field. Substring match — also catches the
# ``models/<id>`` prefix some clients use.
_PROVIDER_DEFAULT_OFF_PATTERNS: dict[str, tuple[str, ...]] = {
    "gemini": ("gemini-2.5", "gemini-3"),
}
# Models matched above that cannot turn thinking off at all: they reject
# ``reasoning_effort="none"`` with a 400, and "minimal" is the lowest level
# they accept (#734). Kept beside the patterns it narrows so adding a family
# to one table is an obvious prompt to check the other.
_MINIMAL_NOT_OFF_PATTERNS: dict[str, tuple[str, ...]] = {
    "gemini": ("gemini-3", "gemini-2.5-pro"),
}
_CUSTOM_MODEL_THINKING_STYLES: tuple[tuple[tuple[str, ...], str], ...] = (
    (("qwen3", "qwen-3", "qwq", "qwen-plus"), "enable_thinking"),
    (("deepseek-v4-pro", "deepseek-reasoner", "deepseek-r1"), "thinking_type"),
)
# Models we send an explicit "thinking off" to, by model substring and by
# (provider, model) pair. Both are deliberately EMPTY.
#
# ``deepseek-v4-flash`` used to be listed here to dodge the mid-conversation
# ``reasoning_content must be passed back`` 400 (#1058). That is not what fixes
# it — echoing the previous round's reasoning on the assistant turn that issued
# the tool calls is, and that landed in the same change (see
# ``assistant_message_with_tool_calls``). Keeping the switch off as well bought
# nothing and cost every flash user their entire reasoning stream: the model
# emits reasoning happily, and we were the ones suppressing it.
#
# Add a model here only when the provider itself cannot be made to work with
# thinking on — not to work around a payload we control.
_THINKING_DISABLED_BY_DEFAULT_MODELS: tuple[str, ...] = ()
_THINKING_DISABLED_BY_DEFAULT: tuple[tuple[str, str], ...] = ()


def _spec_name(spec: Any, binding: str | None) -> str:
    return str(getattr(spec, "name", None) or binding or "").strip().lower()


def _matches(model_name: str, patterns: tuple[str, ...]) -> bool:
    model_lower = model_name.lower()
    return any(pattern.lower() in model_lower for pattern in patterns)


def _custom_thinking_style(model_name: str) -> tuple[str, tuple[str, ...]]:
    for patterns, style in _CUSTOM_MODEL_THINKING_STYLES:
        if _matches(model_name, patterns):
            return style, patterns
    # A model listed as thinking-off needs a style to express that in, but it
    # must NOT inherit the high-effort patterns used by pro/reasoner.
    if any(pattern in model_name.lower() for pattern in _THINKING_DISABLED_BY_DEFAULT_MODELS):
        return "thinking_type", ()
    return "", ()


def _disable_thinking_by_default(provider_name: str, model_name: str) -> bool:
    normalized = model_name.strip().lower()
    if any(pattern in normalized for pattern in _THINKING_DISABLED_BY_DEFAULT_MODELS):
        return True
    return any(
        provider_name == provider and pattern in normalized
        for provider, pattern in _THINKING_DISABLED_BY_DEFAULT
    )


def default_reasoning_effort_for(provider: str | None, model: str | None) -> str | None:
    """Return the implicit ``reasoning_effort`` for ``provider``/``model``, if any.

    Used by callers that don't go through :func:`build_openai_compatible_reasoning_kwargs`.
    Returns ``None`` when no default applies — the caller should leave the field
    unset in that case.

    The single source of truth is :data:`_PROVIDER_DEFAULT_OFF_PATTERNS` so every
    execution path agrees on which models need thinking disabled by default.
    """
    provider_name = (provider or "").strip().lower()
    off_patterns = _PROVIDER_DEFAULT_OFF_PATTERNS.get(provider_name)
    if off_patterns and _matches(model or "", off_patterns):
        if _matches(model or "", _MINIMAL_NOT_OFF_PATTERNS.get(provider_name, ())):
            return "minimal"
        return "none"
    return None


def thinking_off_effort_for(provider: str | None, model: str | None) -> str:
    """The lowest effort *model* actually accepts as "thinking off".

    ``"none"`` for almost everything, ``"minimal"`` for the families that
    answer HTTP 400 to it (#734). The rule already existed inside
    :func:`default_reasoning_effort_for`, but that function is consulted only
    when the caller says nothing — so a caller that asks for ``"none"``
    itself, as the reader-facing book blocks do, skipped the narrowing and got
    the 400 the table exists to prevent. Naming it here keeps it beside
    :data:`_MINIMAL_NOT_OFF_PATTERNS`, so adding a family to that table is
    still an obvious prompt to check this one.
    """
    provider_name = (provider or "").strip().lower()
    if _matches(model or "", _MINIMAL_NOT_OFF_PATTERNS.get(provider_name, ())):
        return "minimal"
    return "none"


def build_openai_compatible_reasoning_kwargs(
    *,
    spec: Any,
    binding: str | None,
    model: str | None,
    reasoning_effort: str | None,
) -> dict[str, Any]:
    """Return reasoning kwargs for OpenAI-compatible Chat Completions calls.

    Some OpenAI-compatible providers expose thinking controls through
    ``extra_body`` instead of the top-level ``reasoning_effort`` field.  Direct
    ``custom`` bindings need model-family inference because their endpoint is
    user supplied and therefore cannot be identified by provider name alone.
    """
    provider_name = _spec_name(spec, binding)
    model_name = model or ""
    thinking_style = str(getattr(spec, "thinking_style", "") or "")
    patterns = tuple(getattr(spec, "reasoning_model_patterns", ()) or ())

    if not thinking_style:
        thinking_style = _PROVIDER_THINKING_STYLES.get(provider_name, "")
    if not patterns:
        patterns = _PROVIDER_REASONING_PATTERNS.get(provider_name, ())
    # Infer style from the model id when the binding has none of its own —
    # covers ``custom`` endpoints and ``openai`` bindings aimed at DeepSeek /
    # Qwen gateways (#1058).
    if not thinking_style:
        custom_style, custom_patterns = _custom_thinking_style(model_name)
        if custom_style:
            thinking_style = custom_style
            if not patterns:
                patterns = custom_patterns

    resolved_effort = reasoning_effort
    if resolved_effort is None:
        if patterns and _matches(model_name, patterns):
            resolved_effort = "high"
        else:
            resolved_effort = default_reasoning_effort_for(provider_name, model_name)
    elif str(resolved_effort).strip().lower() == "none":
        # An explicit "off" is subject to the same vendor limit as an inferred
        # one — see ``thinking_off_effort_for``.
        resolved_effort = thinking_off_effort_for(provider_name, model_name)

    semantic_effort: str | None = None
    if isinstance(resolved_effort, str):
        semantic_effort = resolved_effort.lower()
        if semantic_effort == "minimum":
            semantic_effort = "minimal"

    kwargs: dict[str, Any] = {}
    # OpenRouter exposes a provider-neutral reasoning object.  Keep the
    # explicit off request and exclude any reasoning trace from the response;
    # this is important for models whose gateway response otherwise uses the
    # ``reasoning`` field alongside ``content``.
    if provider_name == "openrouter" and semantic_effort == "none":
        kwargs["extra_body"] = {
            "reasoning": {"effort": "none", "exclude": True},
        }
    if resolved_effort:
        suppress_top_level = bool(
            thinking_style
            and (semantic_effort in _THINKING_OFF_EFFORTS or thinking_style == "enable_thinking")
        )
        if not suppress_top_level and not (
            provider_name == "openrouter" and semantic_effort == "none"
        ):
            kwargs["reasoning_effort"] = resolved_effort

    if (
        thinking_style
        and resolved_effort is not None
        and not (provider_name == "openrouter" and semantic_effort == "none")
    ):
        thinking_enabled = semantic_effort not in _THINKING_OFF_EFFORTS
        extra = _THINKING_STYLE_MAP.get(thinking_style, lambda _enabled: None)(thinking_enabled)
        if extra:
            kwargs.setdefault("extra_body", {}).update(extra)
    elif thinking_style and _disable_thinking_by_default(provider_name, model_name):
        extra = _THINKING_STYLE_MAP.get(thinking_style, lambda _enabled: None)(False)
        if extra:
            kwargs.setdefault("extra_body", {}).update(extra)

    return kwargs


__all__ = [
    "RETRY_REASONING_EFFORT",
    "build_openai_compatible_reasoning_kwargs",
    "default_reasoning_effort_for",
]
