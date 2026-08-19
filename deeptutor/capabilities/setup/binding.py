"""Decide whether a turn is a setup turn, and what is missing from the install.

Two questions live here.

**What is missing** (:func:`setup_gaps`) reads the same spec rows the tools
write, so "what would I offer to fix" and "what can I change" can never drift
apart. A gap is only reported when it costs the user a capability they would
otherwise expect — no embedding model means knowledge bases cannot be built, a
text-only parser means PDFs lose their tables — never as a nag about taste
(nobody needs to be told their theme is the default one).

**Whether to take part** (:func:`is_setup_turn`) deliberately does not ask the
model to sniff intent. An implicitly-mounted capability that activates whenever
an LLM *feels* configuration might be relevant is the failure mode that makes
such a feature obnoxious: it surfaces in unrelated conversations, and the tools
it mounts distract from what was actually asked. Activation here needs one of
three objective signals — the user picked the capability, the message pairs an
action word with a configuration object, or this is the user's first
conversation on an install that still has a real gap (once, ever).

Everything is cached on ``context.metadata`` so the several hooks that run per
turn share one filesystem pass, matching how the other capabilities bind.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any

from deeptutor.core.context import UnifiedContext

_GAPS_CACHE_KEY = "_setup_gaps"
_ACTIVE_CACHE_KEY = "_setup_active"

# Capability name the user can select explicitly (the settings-page entry point
# opens a chat with this preselected).
SETUP_CAPABILITY_NAME = "setup"

# Persisted per user in interface.json: the first-run offer is made once, not
# at the start of every new conversation.
INTRO_SHOWN_KEY = "setup_intro_shown"


@dataclass(frozen=True, slots=True)
class SetupGap:
    """One thing the install cannot currently do, and the row that fixes it."""

    key: str
    area: str
    summary: str
    remedy: str
    blocking: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "key": self.key,
            "area": self.area,
            "summary": self.summary,
            "remedy": self.remedy,
            "blocking": self.blocking,
        }


def setup_gaps() -> tuple[SetupGap, ...]:
    """Capabilities the current configuration cannot deliver.

    Failures are swallowed: a gap report is advisory, and a settings file that
    cannot be read should not take down the turn that was going to help fix it.
    """
    from deeptutor.services.config.settings_spec import setting_specs

    gaps: list[SetupGap] = []
    try:
        specs = setting_specs()
    except Exception:  # noqa: BLE001 - advisory only
        return ()

    def _has_selection(key: str) -> bool:
        spec = specs.get(key)
        if spec is None:
            return True
        try:
            current = spec.read()
            return bool(current) and any(
                choice.value == current and choice.available for choice in spec.choices()
            )
        except Exception:  # noqa: BLE001 - treat an unreadable row as configured
            return True

    if not _has_selection("catalog.embedding"):
        gaps.append(
            SetupGap(
                key="catalog.embedding",
                area="models",
                summary="No embedding model is selected.",
                remedy=("Knowledge bases cannot be built or searched until one is configured."),
                blocking=True,
            )
        )
    if not _has_selection("catalog.search"):
        gaps.append(
            SetupGap(
                key="catalog.search",
                area="models",
                summary="No web search provider is selected.",
                remedy="Web search is unavailable until one is configured.",
            )
        )

    try:
        parsing = specs.get("document_parsing.engine")
        if parsing is not None and parsing.read() == "text_only":
            better = [
                choice
                for choice in parsing.choices()
                if choice.value != "text_only" and choice.available
            ]
            gaps.append(
                SetupGap(
                    key="document_parsing.engine",
                    area="parsing",
                    summary="Documents are parsed with the built-in text-only extractor.",
                    remedy=(
                        "Tables, formulas and layout are lost. "
                        + (
                            f"{len(better)} better engine(s) are already installed and can be "
                            "selected."
                            if better
                            else "A stronger engine can be installed in one step."
                        )
                    ),
                )
            )
    except Exception:  # noqa: BLE001 - advisory only
        pass

    return tuple(gaps)


def cached_gaps(context: UnifiedContext) -> tuple[SetupGap, ...]:
    cached = context.metadata.get(_GAPS_CACHE_KEY)
    if cached is not None:
        return cached
    gaps = setup_gaps()
    context.metadata[_GAPS_CACHE_KEY] = gaps
    return gaps


# Intent detection requires an action AND an object, so "配置文件太大了" or
# "change the subject" cannot pull the capability into an unrelated turn.
_ACTION_PATTERN = re.compile(
    r"(设置|设定|配置|设好|设成|切换|切成|切到|换成|换到|换个|换掉|改成|改为|改用"
    r"|调整|调成|启用|开启|安装|下载|装上|配一下|连上)"
    r"|(\bconfigure\b|\bconfiguration\b|\bset\s?up\b|\bsetup\b|\bswitch\b|\bchange\b"
    r"|\benable\b|\binstall\b|\bdownload\b|\bset\s+the\b|\bsettings\b)",
    re.IGNORECASE,
)

_OBJECT_PATTERN = re.compile(
    r"(语言|界面|主题|皮肤|模型|嵌入|向量|解析引擎|解析器|引擎"
    r"|搜索引擎|搜索服务|联网搜索|偏好设置|设置项)"
    r"|(\blanguage\b|\btheme\b|\bmodel\b|\bembedding\b|\bparser\b|\bparsing\b|\bengine\b"
    r"|\bweb\s+search\b|\bsearch\s+provider\b|\bprovider\b|\bpreferences?\b)",
    re.IGNORECASE,
)

# Phrases that are unambiguous on their own — the user naming the act of
# configuring DeepTutor itself.
_DIRECT_PATTERN = re.compile(
    r"(帮我配置|帮我设置|自己配置|配置一下\s*deeptutor|设置一下\s*deeptutor|初始化配置)"
    r"|(\bconfigure\s+deeptutor\b|\bset\s?up\s+deeptutor\b|\bsetup\s+wizard\b)",
    re.IGNORECASE,
)


def message_signals_setup(message: str) -> bool:
    text = str(message or "")
    if not text.strip():
        return False
    if _DIRECT_PATTERN.search(text):
        return True
    return bool(_ACTION_PATTERN.search(text) and _OBJECT_PATTERN.search(text))


def _intro_pending(context: UnifiedContext) -> bool:
    """First-run offer: a real gap, a fresh conversation, and not yet offered."""
    if context.conversation_history:
        return False
    try:
        from deeptutor.services.settings.interface_settings import get_ui_settings

        if bool(get_ui_settings().get(INTRO_SHOWN_KEY)):
            return False
    except Exception:  # noqa: BLE001 - unreadable settings: do not nag
        return False
    return any(gap.blocking for gap in cached_gaps(context))


def mark_intro_shown() -> None:
    """Record that the first-run offer has been made, so it is not repeated."""
    try:
        from deeptutor.services.settings.interface_settings import set_ui_setting

        set_ui_setting(INTRO_SHOWN_KEY, True)
    except Exception:  # noqa: BLE001 - best effort
        pass


def setup_activation(context: UnifiedContext) -> str:
    """Why this turn is a setup turn: ``explicit`` / ``intent`` / ``intro`` / ``""``.

    The reason is carried, not just the boolean, because the three cases are not
    interchangeable. Only ``intro`` may spend the once-ever first-run offer: an
    earlier version marked it spent from ``system_block``, which meant the first
    time a user asked for anything at all ("change the theme") the offer was
    silently consumed and a genuinely unconfigured install was never proactively
    helped. ``intro`` also earns an extra prompt note, since opening a
    conversation the user did not start on this subject calls for a different
    tone than answering a direct request.

    The check order matters: the two cheap signals are evaluated before
    ``_intro_pending``, which reads settings and computes the install's gaps.
    """
    cached = context.metadata.get(_ACTIVE_CACHE_KEY)
    if cached is not None:
        return str(cached)
    if context.active_capability == SETUP_CAPABILITY_NAME:
        reason = "explicit"
    elif message_signals_setup(context.user_message):
        reason = "intent"
    elif _intro_pending(context):
        reason = "intro"
    else:
        reason = ""
    context.metadata[_ACTIVE_CACHE_KEY] = reason
    return reason


def is_setup_turn(context: UnifiedContext) -> bool:
    """Whether the setup capability takes part in this turn."""
    return bool(setup_activation(context))


__all__ = [
    "INTRO_SHOWN_KEY",
    "SETUP_CAPABILITY_NAME",
    "SetupGap",
    "cached_gaps",
    "is_setup_turn",
    "mark_intro_shown",
    "message_signals_setup",
    "setup_activation",
    "setup_gaps",
]
