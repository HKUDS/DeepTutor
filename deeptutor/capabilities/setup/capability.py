"""Setup loop capability — DeepTutor configuring its own install.

A *plain* :class:`~deeptutor.capabilities.protocol.LoopExtension`, not a
:class:`~deeptutor.capabilities.protocol.KnowledgeCapability`: configuring the
app is something the user asks for in the middle of ordinary work ("switch to
Chinese and use a better PDF parser"), so the turn keeps its normal tool
surface — knowledge bases, web search, the lot — and these four tools are added
on top. An exclusive capability would strip exactly the abilities a
configuration conversation is often about.

Activation is decided by :func:`~deeptutor.capabilities.setup.binding.setup_activation`
on objective signals rather than by the model's sense of relevance; see that
module for why.

How the four tools reach the model depends on why the turn is a setup turn.
``intent`` (the message pairs "switch" with "model") and ``intro`` (first
conversation on an install with a blocking gap) are message heuristics: when
the loop can defer tools (:mod:`deeptutor.capabilities.disclosure`) they no
longer mount anything. The tools stay listed under Extended Tools on every
turn, their usage protocol is returned by ``load_tools`` (see
:meth:`SetupCapability.deferred_tool_guide`), and the turn gets a short note at
the end of the user message instead (:meth:`SetupCapability.turn_note`). The
note carries the install's current gaps — what lets the model open with
something useful ("your knowledge bases can't be built yet — no embedding model
is selected") instead of a menu. ``tools[]`` and the system prompt therefore
stay byte-identical whether or not a message happens to mention configuration.

``explicit`` (the user opened setup mode) is a mode switch: the capability is
active and the pipeline records the tools as loaded, so they join ``tools[]``
on that turn and stay there after the user leaves the mode. The protocol is put
in that turn's user message once, the way ``load_tools`` would have returned
it; the system prompt is never touched.
"""

from __future__ import annotations

from importlib import resources
import logging
from typing import Any

import yaml

from deeptutor.capabilities.disclosure import deferral_available
from deeptutor.capabilities.protocol import PromptBlock
from deeptutor.capabilities.setup.binding import (
    SETUP_CAPABILITY_NAME,
    cached_gaps,
    mark_intro_shown,
    setup_activation,
)
from deeptutor.capabilities.setup.tools import SETUP_TOOL_NAMES
from deeptutor.core.context import UnifiedContext
from deeptutor.services.prompt.lookup import prompt_text as _prompt_text

logger = logging.getLogger(__name__)


class SetupCapability:
    """Turn-scoped ability to inspect and change DeepTutor's own configuration."""

    name = SETUP_CAPABILITY_NAME
    owned_tools = SETUP_TOOL_NAMES
    #: Offered through ``load_tools`` on every turn that can defer tools.
    deferred_tools = SETUP_TOOL_NAMES

    def is_active(self, context: UnifiedContext) -> bool:
        reason = setup_activation(context)
        if reason == "explicit":
            return True
        # A message heuristic must not change the turn's tool surface or system
        # prompt; where deferral is available the tools are one ``load_tools``
        # away and :meth:`turn_note` tells the model so.
        return bool(reason) and not deferral_available(context)

    def system_block(
        self,
        context: UnifiedContext,
        *,
        language: str,
        prompts: dict[str, Any],
    ) -> PromptBlock | None:
        reason = setup_activation(context)
        if not reason:
            return None
        if deferral_available(context):
            # Nothing in the system prompt: the protocol travels with the tools
            # (``load_tools`` result, or this turn's user message when an opened
            # mode loads them) and the gaps ride in :meth:`turn_note`. Entering
            # or leaving setup mode therefore never rewrites the system prompt.
            return None
        content = _protocol(language, prompts)
        content = f"{content}\n\n{_gaps_section(context, language, prompts)}"
        if reason == "intro":
            intro = _note(language, prompts, "intro")
            if intro:
                content = f"{content}\n\n{intro}"
            # Spent only here: an explicit or intent-driven turn must not consume
            # the one proactive offer an unconfigured install gets.
            mark_intro_shown()
        return PromptBlock(SETUP_CAPABILITY_NAME, content)

    def deferred_tool_guide(self, *, language: str, prompts: dict[str, Any]) -> str:
        """The protocol for the four tools, returned when ``load_tools`` loads them."""
        return _protocol(language, prompts)

    def turn_note(
        self,
        context: UnifiedContext,
        *,
        language: str,
        prompts: dict[str, Any] | None = None,
    ) -> str:
        """Per-turn setup facts for the end of the user message.

        Only emitted where deferral is available — otherwise the legacy system
        block carries the same facts. The wording lives in
        ``prompts/<lang>/notes.yaml``.
        """
        reason = setup_activation(context)
        if not reason or not deferral_available(context):
            return ""
        prompts = prompts or {}
        tools = ", ".join(f"`{name}`" for name in SETUP_TOOL_NAMES)
        if reason == "intro":
            lead = "\n".join(
                part
                for part in (
                    _note(language, prompts, "intro"),
                    _note(language, prompts, "intro_load", tools=tools),
                )
                if part
            )
            # Spent only here, as in the legacy system block.
            mark_intro_shown()
        else:  # explicit / intent
            lead = _note(language, prompts, reason, tools=tools)
        parts = [
            _note(language, prompts, "header"),
            _gaps_section(context, language, prompts),
            lead,
        ]
        return "\n".join(part for part in parts if part)

    def augment_kwargs(
        self,
        tool_name: str,
        kwargs: dict[str, Any],
        context: UnifiedContext,
    ) -> dict[str, Any]:
        # Nothing server-owned to inject: these tools address settings by key
        # and resolve scope from the caller's own identity, so there is no
        # turn-scoped handle the model could otherwise forge.
        _ = (tool_name, context)
        return kwargs

    def pre_loop_seed(self, context: UnifiedContext) -> str:
        _ = context
        return ""


def _lang(language: str) -> str:
    return "zh" if str(language or "en").lower().startswith("zh") else "en"


def _load_system_prompt(language: str) -> str:
    prompt = resources.files(__package__).joinpath("prompts", _lang(language), "system.md")
    return prompt.read_text(encoding="utf-8").strip()


def _protocol(language: str, prompts: dict[str, Any]) -> str:
    override = _prompt_text(prompts, ("setup", "system"))
    return override or _load_system_prompt(language)


_NOTES_CACHE: dict[str, dict[str, Any]] = {}


def _load_notes(language: str) -> dict[str, Any]:
    lang = _lang(language)
    cached = _NOTES_CACHE.get(lang)
    if cached is not None:
        return cached
    try:
        text = resources.files(__package__).joinpath("prompts", lang, "notes.yaml")
        data = yaml.safe_load(text.read_text(encoding="utf-8"))
    except Exception:
        logger.warning("failed to load setup notes (%s)", lang, exc_info=True)
        data = None
    result = data if isinstance(data, dict) else {}
    _NOTES_CACHE[lang] = result
    return result


def _note(language: str, prompts: dict[str, Any], key: str, **values: str) -> str:
    """One entry of ``notes.yaml``, a prompt-pack override winning, placeholders filled."""
    template = _prompt_text(prompts, ("setup", "notes", key)) or _prompt_text(
        _load_notes(language), (key,)
    )
    template = template.strip()
    if not values or not template:
        return template
    try:
        return template.format(**values)
    except (KeyError, IndexError, ValueError):
        # An override with stray braces still says something useful.
        return template


def _gaps_section(context: UnifiedContext, language: str, prompts: dict[str, Any]) -> str:
    gaps = cached_gaps(context)
    if gaps:
        lines = "\n".join(f"- {gap.summary} {gap.remedy}".strip() for gap in gaps)
    else:
        lines = _note(language, prompts, "gaps_none")
    heading = _note(language, prompts, "gaps_heading")
    return "\n".join(part for part in (heading, lines) if part)


__all__ = ["SetupCapability"]
