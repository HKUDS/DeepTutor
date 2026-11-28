"""Reasoning/thinking parameters for OpenAI-compatible provider calls."""

from __future__ import annotations

import re
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
    "siliconflow": "enable_thinking",
    "zhipu": "thinking_type",
    "moonshot": "thinking_type",
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


def minimax_reasoning_kwargs(
    model: str, effort: str, *, anthropic: bool = False
) -> dict[str, Any] | None:
    """Map current MiniMax models without changing saved legacy/custom requests.

    See https://platform.minimax.io/docs/api-reference/text-openai-api and
    https://platform.minimax.io/docs/api-reference/text-anthropic-api.
    """
    name = model.lower()
    if name not in {"minimax-m3.1-flash", "minimax-m3"}:
        return None
    if name == "minimax-m3":
        if not effort and not anthropic:
            # Omission retains each protocol's own default, including when an
            # agentic OpenAI facade forwards this request to Anthropic Messages.
            return {}
        enabled = effort not in {"none", "minimal", "minimum"} if effort else not anthropic
        thinking = {"type": "adaptive" if enabled else "disabled"}
        return {"thinking": thinking} if anthropic else {"extra_body": {"thinking": thinking}}
    # Flash always uses adaptive reasoning. Saved off/binary values fall back
    # to the vendor default effort rather than sending an unsupported mode.
    thinking = {"type": "adaptive"}
    result: dict[str, Any] = (
        {"thinking": thinking}
        if anthropic
        else {"extra_body": {"thinking": thinking, "reasoning_split": True}}
    )
    if effort in {"low", "medium", "high", "xhigh", "max"}:
        if anthropic:
            result["output_config"] = {"effort": effort}
        else:
            result["reasoning_effort"] = effort
    return result


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
    if provider_name == "minimax":
        minimax = minimax_reasoning_kwargs(model_name, (reasoning_effort or "").strip().lower())
        if minimax is not None:
            return minimax
    if provider_name == "zhipu" and (
        model_name.lower() == "glm-5.3" or model_name.lower().endswith("/glm-5.3")
    ):
        # GLM-5.3 always thinks and uses multi-level reasoning_effort (low/high/max);
        # sending thinking.type=disabled is rejected with HTTP 400.
        effort = (reasoning_effort or "").strip().lower()
        return {"reasoning_effort": effort} if effort in {"low", "high", "max"} else {}
    if (
        provider_name == "openrouter"
        and model_name.lower() == "minimax/minimax-m3.1-flash:free"
        and reasoning_effort in {"none", "minimal", "minimum"}
    ):
        return {}
    if reasoning_effort == "":
        return {}
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

    # Qwen Instruct variants do not implement thinking controls, even when a
    # caller explicitly requests an effort. Do not replace the unsupported
    # native parameter with the equally unsupported top-level effort field.
    model_tokens = model_name.lower().replace("_", "-").split("-")
    if thinking_style == "enable_thinking" and "instruct" in model_tokens:
        return {}

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


_REASONING_CONTROL_ALIASES = {
    "azure": "azure_openai",
    "azureopenai": "azure_openai",
    "google": "gemini",
    "google_genai": "gemini",
    "claude": "anthropic",
    "openai_compatible": "custom",
    "anthropic_compatible": "custom_anthropic",
}
_OPENAI_MULTI_LEVEL_PROVIDERS = frozenset(
    {"openai", "azure_openai", "openai_codex", "github_copilot"}
)
_TOGGLE_ONLY_PROVIDERS = frozenset(
    {
        "deepseek",
        "dashscope",
        "volcengine",
        "volcengine_coding_plan",
        "byteplus",
        "byteplus_coding_plan",
        "siliconflow",
        "zhipu",
        "moonshot",
        "custom",
    }
)
_BINARY_MINIMAL_OFF_PROVIDERS = frozenset(
    {
        "deepseek",
        "dashscope",
        "volcengine",
        "volcengine_coding_plan",
        "byteplus",
        "byteplus_coding_plan",
        "siliconflow",
        "zhipu",
        "moonshot",
        "minimax",
    }
)
_VALID_WIRE_EFFORTS = frozenset({"none", "minimal", "low", "medium", "high", "xhigh", "max"})
_R1_TOKEN_RE = re.compile(r"(?:^|[^a-z0-9])r1(?:$|[^a-z0-9])")


def _is_qwen_instruct(model_name: str) -> bool:
    """Whether *model_name* is a Qwen Instruct variant without thinking controls."""
    if "qwen" not in model_name:
        return False
    tokens = re.split(r"[-_/]", model_name)
    return "instruct" in tokens


def _default_toggle_on(
    resolved_provider: str,
    model_name: str,
    configured_effort: str | None,
) -> bool:
    """Infer whether a binary-toggle model thinks by default when no turn override is set."""
    configured = (configured_effort or "").strip().lower()
    if configured:
        return configured not in _THINKING_OFF_EFFORTS
    if _is_qwen_instruct(model_name):
        return False
    patterns = _PROVIDER_REASONING_PATTERNS.get(resolved_provider, ())
    if patterns and _matches(model_name, patterns):
        return True
    if resolved_provider in {"custom", "siliconflow"}:
        custom_style, custom_patterns = _custom_thinking_style(model_name)
        if custom_style and custom_patterns and _matches(model_name, custom_patterns):
            return True
    return False


def resolve_reasoning_control(
    provider: str | None,
    model: str | None,
    *,
    supported_reasoning_efforts: list[str] | tuple[str, ...] | None = None,
    declared_reasoning: bool | None = None,
    configured_effort: str | None = None,
) -> dict[str, Any]:
    """Single source of truth for how the UI controls reasoning for a model.

    Returns one of:
      - ``{"mode": "none"}``
      - ``{"mode": "toggle", "off_value": "minimal"|"none", "on_value": "high", "default_on": bool}``
      - ``{"mode": "levels", "levels": [...]}``
    """
    if declared_reasoning is False:
        return {"mode": "none"}

    # 1. Live provider-advertised levels (e.g. OpenAI Codex OAuth) always win.
    if supported_reasoning_efforts is not None:
        levels: list[str] = []
        for raw in supported_reasoning_efforts:
            val = str(raw).strip().lower()
            if val in _VALID_WIRE_EFFORTS and val not in levels:
                levels.append(val)
        if not levels:
            return {"mode": "none"}
        return {"mode": "levels", "levels": levels}

    canonical = (provider or "").strip().lower().replace("-", "_")
    resolved_provider = _REASONING_CONTROL_ALIASES.get(canonical, canonical)
    model_name = (model or "").strip().lower()

    # Qwen Instruct variants never emit thinking controls on OpenAI-compatible
    # paths; hide the toggle unless the user explicitly declared reasoning=True.
    if declared_reasoning is not True and _is_qwen_instruct(model_name):
        return {"mode": "none"}

    # 2. Known multi-level model families.
    if resolved_provider in {"minimax", "minimax_anthropic"}:
        if model_name == "minimax-m3.1-flash":
            return {"mode": "levels", "levels": ["low", "medium", "high", "xhigh", "max"]}
        if model_name == "minimax-m3":
            return {
                "mode": "toggle",
                "off_value": "minimal",
                "on_value": "high",
                "default_on": _default_toggle_on(resolved_provider, model_name, configured_effort),
            }

    if resolved_provider == "gemini" or "gemini" in model_name:
        if "gemini-3" in model_name or "gemini-2.5-pro" in model_name:
            return {"mode": "levels", "levels": ["minimal", "low", "medium", "high"]}
        if "gemini-2.5" in model_name:
            return {"mode": "levels", "levels": ["none", "low", "medium", "high"]}
        return {"mode": "levels", "levels": ["low", "medium", "high"]}

    if resolved_provider in {"anthropic", "custom_anthropic"} or "claude" in model_name:
        if any(
            token in model_name
            for token in ("opus-4-7", "opus-4-8", "opus-5", "sonnet-5", "fable-5", "mythos-5")
        ):
            return {"mode": "levels", "levels": ["none"]}
        if any(
            token in model_name
            for token in (
                "claude-3-7",
                "claude-4",
                "claude-sonnet-4",
                "claude-opus-4",
                "claude-haiku-4",
            )
        ):
            return {"mode": "levels", "levels": ["none", "low", "medium", "high"]}
        return {"mode": "none"}

    if (
        resolved_provider in _OPENAI_MULTI_LEVEL_PROVIDERS
        or resolved_provider in {"custom", "zhipu"}
    ) and (model_name == "glm-5.3" or model_name.endswith("/glm-5.3")):
        return {"mode": "levels", "levels": ["low", "high", "max"]}

    if resolved_provider in _OPENAI_MULTI_LEVEL_PROVIDERS:
        if "gpt-5.6-sol" in model_name:
            return {
                "mode": "levels",
                "levels": ["none", "low", "medium", "high", "xhigh", "max"],
            }
        if "gpt-5" in model_name or "codex" in model_name:
            return {
                "mode": "levels",
                "levels": ["minimal", "low", "medium", "high", "xhigh"],
            }
        if any(token in model_name for token in ("o1", "o3", "o4")):
            return {"mode": "levels", "levels": ["low", "medium", "high"]}
        if declared_reasoning is True:
            return {
                "mode": "toggle",
                "off_value": "none",
                "on_value": "high",
                "default_on": _default_toggle_on(resolved_provider, model_name, configured_effort),
            }
        return {"mode": "none"}

    # 3. Binary thinking vendors and general/custom endpoints default to a simple toggle.
    if (
        resolved_provider in _TOGGLE_ONLY_PROVIDERS
        or resolved_provider == "minimax"
        or declared_reasoning is True
    ):
        is_binary_model = (
            resolved_provider == "custom"
            or declared_reasoning is True
            or resolved_provider == "minimax"
            or _R1_TOKEN_RE.search(model_name) is not None
            or any(
                token in model_name
                for token in (
                    "deepseek",
                    "qwen3",
                    "qwen-3",
                    "qwq",
                    "qwen-plus",
                    "doubao",
                    "thinking",
                    "reasoner",
                    "glm-4",
                    "glm-5",
                    "kimi",
                )
            )
        )
        if is_binary_model:
            off_value = "minimal" if resolved_provider in _BINARY_MINIMAL_OFF_PROVIDERS else "none"
            return {
                "mode": "toggle",
                "off_value": off_value,
                "on_value": "high",
                "default_on": _default_toggle_on(resolved_provider, model_name, configured_effort),
            }

    return {"mode": "none"}


_REASONING_EXTRA_BODY_KEYS = frozenset(
    {"thinking", "enable_thinking", "reasoning_split", "reasoning"}
)


def has_reasoning_kwargs(request_kwargs: dict[str, Any]) -> bool:
    """Whether *request_kwargs* carries any reasoning/thinking request parameter."""
    if "reasoning_effort" in request_kwargs or "reasoning" in request_kwargs:
        return True
    extra_body = request_kwargs.get("extra_body")
    if isinstance(extra_body, dict) and any(
        key in extra_body for key in _REASONING_EXTRA_BODY_KEYS
    ):
        return True
    return False


def strip_reasoning_kwargs(request_kwargs: dict[str, Any]) -> dict[str, Any]:
    """Return a shallow copy of *request_kwargs* without reasoning parameters."""
    cleaned = dict(request_kwargs)
    cleaned.pop("reasoning_effort", None)
    cleaned.pop("reasoning", None)
    extra_body = cleaned.get("extra_body")
    if isinstance(extra_body, dict):
        next_extra = {k: v for k, v in extra_body.items() if k not in _REASONING_EXTRA_BODY_KEYS}
        if next_extra:
            cleaned["extra_body"] = next_extra
        else:
            cleaned.pop("extra_body", None)
    return cleaned


__all__ = [
    "RETRY_REASONING_EFFORT",
    "build_openai_compatible_reasoning_kwargs",
    "default_reasoning_effort_for",
    "has_reasoning_kwargs",
    "resolve_reasoning_control",
    "strip_reasoning_kwargs",
]
