"""Mastery path loop-capability hooks.

The pause/resume hooks commit against **the path's one open interaction**, not
against the question id printed on the ``ask_user`` card. The engine allows a
single open question per path, so that interaction is unambiguous — while the
card's id is only as trustworthy as the round it was built in: a model may emit
``mastery_quiz`` and ``ask_user`` in the *same* round, and every tool call in a
round has its arguments bound before any of them runs. In that case nothing is
persisted yet when ``ask_user`` is bound, so the card keeps the model's own id
and ``_bind_pending_ask_user_args`` has nothing to rebind it to. Treating that
id as authoritative used to abort the whole turn on a mismatch.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from importlib import resources
import logging
import re
from typing import Any

from deeptutor.capabilities.mastery.tools import MASTERY_TOOL_NAMES
from deeptutor.capabilities.protocol import PromptBlock
from deeptutor.core.context import UnifiedContext

logger = logging.getLogger(__name__)

# Tools that may move the turn onto a different path, and so need a handle on
# the live binding rather than just the path id it started with.
_PATH_BINDING_TOOLS = frozenset({"mastery_switch", "mastery_leave"})


# The generic ask_user contract asks the model to mark a suggested choice with
# a "(Recommended)" suffix — good for a preference card, disastrous on a quiz,
# where the model attaches it to the answer it wants picked. Mastery cards are
# assessments, so the marker is stripped structurally rather than merely
# forbidden in the prompt.
_RECOMMENDATION_SUFFIX = re.compile(
    r"[\s　]*[（(]\s*(?:推荐|建议|recommended|recommend)\s*[)）][\s　]*$",
    re.IGNORECASE,
)


def _without_recommendation(text: Any) -> Any:
    if not isinstance(text, str):
        return text
    return _RECOMMENDATION_SUFFIX.sub("", text).strip()


def _strip_answer_hints(kwargs: dict[str, Any]) -> dict[str, Any]:
    """Remove "recommended" markers from every option on an ask_user card."""
    questions = kwargs.get("questions")
    if not isinstance(questions, list):
        return kwargs
    cleaned_questions: list[Any] = []
    for question in questions:
        if not isinstance(question, dict):
            cleaned_questions.append(question)
            continue
        options = question.get("options")
        if not isinstance(options, list):
            cleaned_questions.append(question)
            continue
        cleaned_questions.append(
            {
                **question,
                "options": [
                    {
                        **option,
                        "label": _without_recommendation(option.get("label")),
                        "description": _without_recommendation(option.get("description")),
                    }
                    if isinstance(option, dict)
                    else _without_recommendation(option)
                    for option in options
                ],
            }
        )
    return {**kwargs, "questions": cleaned_questions}


def _bind_pending_ask_user_args(kwargs: dict[str, Any], path_id: str) -> dict[str, Any]:
    """Replace model-authored quiz display data with persisted public state.

    Binding at this adapter boundary prevents the model from changing question
    ids or reassigning A/B/C labels after a pause or on a later turn. Generic
    clarification cards remain untouched when no mastery question is pending.
    """
    if not path_id:
        return kwargs
    try:
        from deeptutor.learning.pending import public_pending_question
        from deeptutor.learning.storage import LearningStore

        progress = LearningStore().load(path_id)
        pending = progress.pending_question if progress is not None else None
    except Exception:
        logger.warning("Failed to load pending mastery question for ask_user", exc_info=True)
        return kwargs
    if pending is None:
        return kwargs

    updated = dict(kwargs)
    updated["questions"] = [public_pending_question(pending).to_ask_user_dict()]
    # Remove the accepted legacy shape so it cannot compete with the canonical
    # question list in ``build_ask_user_payload``.
    updated.pop("question", None)
    updated.pop("options", None)
    return updated


class MasteryLoopCapability:
    """Turn-scoped integration for mastery-path tutoring.

    Reuses the full chat tool surface (rag / read_source / ask_user / … under
    the same user toggles as chat) and adds the mastery engine tools on top.
    """

    name = "mastery"
    owned_tools = MASTERY_TOOL_NAMES

    def is_active(self, context: UnifiedContext) -> bool:
        return bool(context.metadata.get("mastery_mode"))

    def system_block(
        self,
        context: UnifiedContext,
        *,
        language: str,
        prompts: dict[str, Any],
    ) -> PromptBlock | None:
        if not self.is_active(context):
            return None
        override = _prompt_text(prompts, ("mastery", "system"))
        content = override or _load_system_prompt(language)
        return PromptBlock("mastery_tutor", content)

    def augment_kwargs(
        self,
        tool_name: str,
        kwargs: dict[str, Any],
        context: UnifiedContext,
    ) -> dict[str, Any]:
        if not self.is_active(context):
            return kwargs
        path_id = str(context.metadata.get("mastery_path_id") or "").strip()
        if tool_name == "ask_user":
            # Strip hints last, so a card rebound from persisted state is
            # cleaned too — the persisted options were model-authored as well.
            return _strip_answer_hints(_bind_pending_ask_user_args(kwargs, path_id))
        if tool_name in MASTERY_TOOL_NAMES:
            updated = dict(kwargs)
            updated["_mastery_path_id"] = path_id
            updated["_session_id"] = str(context.session_id or "").strip()
            updated["_turn_id"] = str(context.metadata.get("turn_id") or "").strip()
            if tool_name in _PATH_BINDING_TOOLS:
                # The narrowest possible handle on the turn: "point it at this
                # path". A tool that can switch paths has to change what the
                # rest of the turn operates on, and this keeps the tool from
                # needing to know a turn context exists.
                updated["_bind_active_path"] = _path_binder(context)
            return updated
        return kwargs

    def pre_loop_seed(self, context: UnifiedContext) -> str:
        _ = context
        return ""

    async def on_user_pause(
        self,
        context: UnifiedContext,
        ask_user: dict[str, Any],
    ) -> None:
        """Commit ``awaiting_input`` before the runtime begins waiting."""
        _ = ask_user
        path_id = str(context.metadata.get("mastery_path_id") or "").strip()
        if not path_id:
            return
        from deeptutor.learning.service import LearningService

        await asyncio.to_thread(
            LearningService().mark_question_awaiting,
            path_id,
            session_id=str(context.session_id or ""),
            turn_id=str(context.metadata.get("turn_id") or ""),
        )

    async def on_user_resume(
        self,
        context: UnifiedContext,
        ask_user: dict[str, Any],
        *,
        reply_text: str,
        answers: list[dict[str, str]] | None,
    ) -> None:
        """Commit the learner answer before giving it back to the LLM."""
        path_id = str(context.metadata.get("mastery_path_id") or "").strip()
        if not path_id:
            return
        from deeptutor.learning.service import LearningService

        await asyncio.to_thread(
            LearningService().record_question_answer,
            path_id,
            _answer_from_reply(ask_user, reply_text=reply_text, answers=answers),
            session_id=str(context.session_id or ""),
            turn_id=str(context.metadata.get("turn_id") or ""),
        )


def _path_binder(context: UnifiedContext) -> Callable[[str], None]:
    """Return the callback that repoints ``context`` at another path."""

    def bind(path_id: str) -> None:
        context.metadata["mastery_path_id"] = path_id

    return bind


def _answer_from_reply(
    ask_user: dict[str, Any],
    *,
    reply_text: str,
    answers: list[dict[str, str]] | None,
) -> str:
    """The learner's reply to the card, by the id the card was rendered with.

    That id is a *display* concern — the frontend echoes back whatever it was
    shown — and is deliberately not used to pick the interaction to commit
    against (see the module docstring).
    """
    card_question_id = _first_question_id(ask_user)
    for entry in answers or []:
        if entry.get("questionId") == card_question_id:
            return entry.get("text", "")
    return reply_text


def _first_question_id(ask_user: dict[str, Any]) -> str:
    questions = ask_user.get("questions") or []
    if not isinstance(questions, list):
        return ""
    for question in questions:
        if isinstance(question, dict):
            question_id = str(question.get("id") or "").strip()
            if question_id:
                return question_id
    return ""


def _prompt_text(prompts: dict[str, Any], path: tuple[str, ...]) -> str:
    value: Any = prompts
    for key in path:
        if not isinstance(value, dict):
            return ""
        value = value.get(key)
    return value if isinstance(value, str) and value else ""


def _load_system_prompt(language: str) -> str:
    lang = "zh" if language.lower().startswith("zh") else "en"
    prompt = resources.files(__package__).joinpath("prompts", lang, "system.md")
    return prompt.read_text(encoding="utf-8").strip()


__all__ = ["MasteryLoopCapability"]
