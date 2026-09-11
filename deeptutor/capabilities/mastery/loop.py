"""Mastery path loop-capability hooks.

A posed question ends its turn (see
:meth:`MasteryLoopCapability.final_text_override`), which is what removed this
module's most tangled machinery. A mastery question used to travel on the
generic ``ask_user`` pause channel, so every clarifying card the tutor raised
had to be inspected and rewritten in case it was really a quiz, and the
learner's reply to any card had to be considered as a possible answer to the
open question. Both were guesses about which card was which, made in the wrong
place. Now the engine poses its own card and answers arrive as ordinary
messages committed at turn start, so ``ask_user`` is left alone: in this mode
it is only ever a clarifying question.
"""

from __future__ import annotations

from collections.abc import Callable
import logging
import re
from typing import Any

from deeptutor.capabilities.mastery.tools import MASTERY_TOOL_NAMES
from deeptutor.capabilities.protocol import PromptBlock
from deeptutor.core.context import UnifiedContext
from deeptutor.services.prompt.lookup import prompt_text as _prompt_text

logger = logging.getLogger(__name__)

# Tools that may move the turn onto a different path, and so need a handle on
# the live binding rather than just the path id it started with.
_PATH_BINDING_TOOLS = frozenset({"mastery_switch", "mastery_leave"})

#: Set on the turn by :class:`~deeptutor.capabilities.mastery.pipeline.MasteryLoopPipeline`
#: so this extension knows the playbook is already the foundation of the
#: prompt and must not contribute a second copy of it. Declared here, next to
#: its only reader, so the tutor loop can import one string without this
#: module having to import the loop engine back.
NATIVE_LOOP_FLAG = "mastery_native_loop"


# Shapes that betray a question written into the reply as prose instead of
# posed through ``mastery_quiz`` — see ``finish_instruction``.
_PLAIN_CHOICE_OPTION_RE = re.compile(
    r"^(?:[-*+]\s*)?(?:\*\*)?([A-D])(?:\*\*)?\s*[.、):：-]\s*(\S.*)$",
    re.IGNORECASE,
)
_PLAIN_QUIZ_PROMPT_RE = re.compile(
    r"\b(?:which|choose|select|answer)\b|选择|选哪个|请选择|请回答|答案",
    re.IGNORECASE,
)
# A reply that announces a question without posing one. Matched against the
# tail of the reply only, where an announcement lands, so ordinary discussion
# of "this question" while reviewing an attempt does not trip it.
_QUESTION_PROMISE_RE = re.compile(
    # A bare "这道题" is how a *review* of the attempt just graded reads too,
    # so the Chinese branch needs a forward-looking verb alongside it.
    r"(?:来|下面|接下来|先|试试|做|回答)[^。！？\n]{0,12}(?:这道|一道|下一?道)题|"
    r"出一?道题|考考你|试试这|看看你(?:对|的|是否|能不能)|检验一下你|"
    # …and the same announcement with the noun left out: "再试一道，把这套
    # 判别规则用起来" never says 题 at all, which is exactly how two real
    # turns slipped past this guard and left the learner staring at a colon.
    r"再(?:试|来|做)一(?:道|个)|来实战|练一?练|上手试|"
    r"\bhere(?:\u2019s| is|'s) (?:a|the|this) question\b|"
    r"\btry (?:this|the following|a|another) (?:question|one)\b|"
    r"\blet(?:\u2019s|'s) (?:see|test|check) (?:if|whether|how|what) you\b",
    re.IGNORECASE,
)
_PROMISE_TAIL_CHARS = 160
# A reply that stops on a colon promised whatever was meant to follow it. The
# lead-in for a question is supposed to share its round with the
# ``mastery_quiz`` call that fills the space underneath, so a colon with
# nothing after it is the most reliable evidence that the call never happened —
# more reliable than recognising the wording, which varies every turn.
_DANGLING_LEAD_IN_CHARS = frozenset(":：")


def _looks_like_plain_choice_quiz(text: str) -> bool:
    """Recognise a rendered A-D option list with high precision.

    The model may discuss labelled options while teaching. Requiring both an
    assessment prompt and at least three distinct labelled answer bodies keeps
    ordinary prose, headings, and option-like vocabulary examples out of this
    protocol guard.
    """
    labels: set[str] = set()
    prompt_lines: list[str] = []
    for raw_line in text.splitlines():
        line = raw_line.strip()
        match = _PLAIN_CHOICE_OPTION_RE.match(line)
        if match:
            labels.add(match.group(1).upper())
        else:
            prompt_lines.append(line)
    return len(labels) >= 3 and any(_PLAIN_QUIZ_PROMPT_RE.search(line) for line in prompt_lines)


def _turn_has_graded(context: UnifiedContext) -> bool:
    """Whether a ruling was made this turn, by the model or by the runtime.

    Two things can grade: the tutor calling ``mastery_grade``, and the runtime
    ruling on a card answer before the turn starts. Only the first passes
    through ``augment_kwargs``, so reading the extension alone made the
    guard treat post-grade feedback — option-by-option prose, which is what
    reviewing an attempt looks like — as a question written out in text, and
    a rejected finish is discarded rather than shown.
    """
    if context.extension("mastery").get("quiz_graded"):
        return True
    return bool(context.metadata.get("mastery_card_grade"))


def _announces_an_unposed_question(text: str) -> bool:
    """Whether a reply promises a question it never put on a card."""
    body = (text or "").strip()
    if not body:
        return False
    if body[-1] in _DANGLING_LEAD_IN_CHARS:
        return True
    return bool(_QUESTION_PROMISE_RE.search(body[-_PROMISE_TAIL_CHARS:]))


class MasteryLoopCapability:
    """Turn-scoped integration for mastery-path tutoring.

    Reuses the full chat tool surface (rag / ask_user / … under the same user
    toggles as chat) and adds the mastery engine tools on top, plus its own
    ``read_source`` mount.

    ``read_source`` is owned here rather than left to chat's
    ``explore_context`` pre-pass on purpose: a topic's materials (see
    :mod:`deeptutor.learning.topic_materials`) are announced every turn as a
    plain-text manifest (``context.source_manifest``) — "here is what's
    attached" — but never force a read. The forced, bounded investigation
    explore_context runs before the model's first token is right for chat
    (where a referenced transcript must be read once, objectively, before
    answering) and wrong for tutoring, where the model should decide *itself*,
    knowledge point by knowledge point, whether the source text is worth
    reading this turn. Mounting ``read_source`` directly on the answer loop —
    fed from ``mastery_topic_source_index`` rather than the ``source_index``
    key explore_context watches — gives the tutor that choice without forcing
    it.
    """

    name = "mastery"
    owned_tools = (*MASTERY_TOOL_NAMES, "read_source")
    # Declared to the dispatcher so a call that repoints the turn runs first
    # and the rest of the round lands on the new target. Every call in a round
    # is bound before any of them runs, so without this a ``mastery_switch`` +
    # ``mastery_build`` round rebuilt the map of the path the conversation was
    # leaving.
    #
    # ``mastery_mode`` belongs here for the same reason and was missing it. It
    # repoints the turn's mode (``_bind_active_mode``, below), and every
    # mode-gated tool reads ``_mastery_session_mode`` from the bind — so in the
    # round the prompt explicitly asks for, "switch to study and get on with
    # it", ``mastery_quiz`` still saw ``outline`` and was refused. The tutor
    # had already written the lead-in, the card never appeared, and the turn
    # carried on: one of the ways a question ends up answered in prose.
    rebinding_tools = tuple(_PATH_BINDING_TOOLS | {"mastery_mode"})

    def is_active(self, context: UnifiedContext) -> bool:
        return bool(context.metadata.get("mastery_mode"))

    def system_block(
        self,
        context: UnifiedContext,
        *,
        language: str,
        prompts: dict[str, Any],
    ) -> PromptBlock | None:
        """The tutor playbook, for a mastery turn that is not on the tutor loop.

        :class:`~deeptutor.capabilities.mastery.pipeline.MasteryLoopPipeline`
        makes the playbook the *foundation* of its prompt, so contributing it
        again there would put two copies in the window. It is still needed on
        the chat pipeline: a mastery workspace can run another action (a quiz,
        a visualization) and that turn should still know it is inside a course
        rather than being silently untutored.
        """
        if not self.is_active(context):
            return None
        if context.metadata.get(NATIVE_LOOP_FLAG):
            return None
        override = _prompt_text(prompts, ("mastery", "system"))
        return PromptBlock("mastery_tutor", override or _load_playbook(language))

    def augment_kwargs(
        self,
        tool_name: str,
        kwargs: dict[str, Any],
        context: UnifiedContext,
    ) -> dict[str, Any]:
        if not self.is_active(context):
            return kwargs
        path_id = str(context.metadata.get("mastery_path_id") or "").strip()
        state = context.extension("mastery")
        # ``ask_user`` is deliberately untouched here. It carries clarifying
        # questions only; the graded ones are posed by ``mastery_quiz``.
        if tool_name == "read_source":
            # Deliberately a different key from chat's ``source_index``: that
            # one wakes the explore_context pre-pass (see the class docstring).
            # The tutor calls this tool on its own schedule instead.
            updated = dict(kwargs)
            updated["source_index"] = context.metadata.get("mastery_topic_source_index") or {}
            return updated
        if tool_name in MASTERY_TOOL_NAMES:
            updated = dict(kwargs)
            if tool_name == "mastery_quiz":
                state["quiz_awaiting_grade"] = True
                updated["_end_turn_on_card"] = _card_end_marker(context)
            elif tool_name == "mastery_grade":
                state["quiz_awaiting_grade"] = False
                state["quiz_graded"] = True
            updated["_mastery_path_id"] = path_id
            # Raw, not normalised: "this conversation never recorded a mode"
            # has to survive down to the tools, or every pre-modes conversation
            # (and every CLI / SDK turn, which pass none) would be enforced as
            # a study session and lose tools it has always been able to call.
            updated["_mastery_session_mode"] = context.metadata.get("mastery_session_mode")
            updated["_session_id"] = str(context.session_id or "").strip()
            updated["_turn_id"] = str(context.metadata.get("turn_id") or "").strip()
            if tool_name == "mastery_mode":
                # The narrowest handle on the turn for a tool that changes what
                # the rest of it may do — the same shape as ``_bind_active_path``
                # below, and for the same reason: the tool must not have to know
                # a turn context exists.
                updated["_bind_active_mode"] = _mode_binder(context)
            if tool_name in _PATH_BINDING_TOOLS:
                # The narrowest possible handle on the turn: "point it at this
                # path". A tool that can switch paths has to change what the
                # rest of the turn operates on, and this keeps the tool from
                # needing to know a turn context exists.
                updated["_bind_active_path"] = _path_binder(context)
            return updated
        return kwargs

    def finish_instruction(self, context: UnifiedContext, final_text: str) -> str | None:
        """Catch a finish that leaves the learner with nothing to answer.

        Only the *shape of the reply* can trigger this. Two states that read
        like unfinished protocol are not:

        ``mastery_quiz`` called without a grade no longer means the question
        went unasked — that call now poses it on its own card — so a learner
        who types a question instead of answering leaves the interaction open
        on purpose, and the tutor answering them is the right reply, not a
        skipped step.

        And once ``mastery_grade`` has run, reviewing the options one by one —
        "you picked C; A fails because…" — matches the plain-text-quiz
        heuristic exactly while being the whole point of the turn. Blocking
        that discarded the explanation and left the learner with a graded card
        and no reason for the verdict.

        That second exemption used to sit at the top of this method and so
        waived *every* check on a grading turn — including the unposed-question
        one. Grading turns are precisely where the tutor teaches the gap and
        then reaches for the next question, so the one turn shape most likely
        to end on an unkept promise was the one shape never examined. It now
        guards only the heuristic it was written for.
        """
        if not self.is_active(context):
            return None
        state = context.extension("mastery")
        if _announces_an_unposed_question(final_text):
            # "Let us see what you already know:" and then nothing. The learner
            # is left reading a promise with no card under it, and the turn is
            # over — this reply announced the question instead of posing it.
            return (
                "That reply announced a question but never posed one, so the "
                "learner is looking at a promise and an empty space. Write the "
                "lead-in and call mastery_quiz in the SAME round — the call is "
                "what puts the question on their card, and it ends the turn. If "
                "you did not mean to quiz them yet, say what you meant to say "
                "without announcing a question."
            )
        if _turn_has_graded(context) or not _looks_like_plain_choice_quiz(final_text):
            return None
        if state.get("quiz_awaiting_grade"):
            return (
                "That question is already on the learner's answer card — do not "
                "write it out again in prose. Either end the turn on what you "
                "have taught and let their answer arrive as the next message, or "
                "call mastery_grade with the answer they already gave you (the "
                "engine grades the question it is holding open)."
            )
        return (
            "The previous reply posed a mastery assessment as plain text. Do not "
            "write the question or its choices in prose: call mastery_quiz "
            "instead — that one call registers the expected answer and puts the "
            "question on its own answer card, and the turn stops there for the "
            "learner to answer."
        )

    def final_text_override(self, context: UnifiedContext, final_text: str) -> str | None:
        """End the turn on the card once a question has been posed.

        A posed question used to park the turn inside ``pause_for_user``: the
        runtime moved it to ``waiting_input`` and waited on a reply queue, so
        one conversation held a live turn — and the path's lease — for as long
        as the learner took, which could be forever. Everything they might do
        instead of answering (ask something, come back tomorrow, reload) had to
        be handled as an interruption of that parked turn, and the composer had
        no honest state to show while it was parked.

        Ending here inverts it. The card is this turn's artefact; answering it
        is the next message, exactly like typing one. So the learner may answer,
        ask something else, or walk away, and each is just the next turn —
        which is what makes the conversation feel continuous instead of gated.

        Returning ``""`` and not a sentence is deliberate: the tutor's own prose
        from this round is already published (mastery tool rounds keep their
        learner-facing text), and the question is on the card. There is nothing
        left for the turn to say.
        """
        if not self.is_active(context):
            return None
        state = context.extension("mastery")
        if not state.get("card_posted"):
            return None
        if final_text.strip():
            # A tool-less finish round already wrote the answer; the card was
            # posed earlier in the turn and has nothing to override.
            return None
        state["card_posted"] = False
        return ""

    def pre_loop_seed(self, context: UnifiedContext) -> str:
        """Hand over whatever this turn already settled on the open card.

        A card answer is graded when the turn starts, so by the time the tutor
        reads anything the gate has ruled and the learner can already see the
        verdict on their card. Without this the tutor would open the turn
        looking at a bare "C" with no open question to match it to — and the
        engine would have nothing left to grade, since it is already done.

        So the ruling is stated here as fact, and what is left for the tutor is
        the part only it can do: say what this attempt shows and carry on. A
        declined question is the same story with no verdict in it.
        """
        if not self.is_active(context):
            return ""
        skipped = self._skip_seed(context)
        graded = self._grade_seed(context)
        return "\n\n".join(part for part in (skipped, graded) if part)

    def _skip_seed(self, context: UnifiedContext) -> str:
        """State that the learner's declined question is already gone.

        Without this the tutor reads "let's skip this question" and reaches for
        ``mastery_skip_question`` — which now finds nothing open and reports so,
        costing a round to learn what the runtime already did. Worse, a tutor
        that does not know the question is gone tends to re-pose it.
        """
        skip = context.metadata.get("mastery_card_skip")
        if not isinstance(skip, dict) or not skip.get("skipped"):
            return ""
        return (
            "[Mastery] The learner declined the open question and the engine has "
            "already dropped it — do not call mastery_skip_question, and do not "
            "pose that same question again. Nothing was graded and no mastery "
            "credit was given, so the objective's gate is exactly where it was. "
            "Answer whatever they asked, then continue the objective from "
            "mastery_status.next — with a different question when you are ready "
            "to ask one."
        )

    def _grade_seed(self, context: UnifiedContext) -> str:
        grade = context.metadata.get("mastery_card_grade")
        if not isinstance(grade, dict) or not grade:
            return ""
        result = grade.get("result") if isinstance(grade.get("result"), dict) else {}
        verdict = "correct" if grade.get("is_correct") else "incorrect"
        learner_answer = str(result.get("learner_answer") or "").strip()
        lines = [
            "[Mastery] The learner answered the open question on its card and the "
            f"engine has already graded it: {verdict}"
            + (f' (they answered "{learner_answer}")' if learner_answer else "")
            + ".",
            "Their card already shows the verdict, the correct option and the "
            "explanation the question was registered with, so do not restate the "
            "answer key and do not call mastery_grade for it again.",
        ]
        if grade.get("mastered"):
            lines.append(
                "This cleared the objective's gate. Say what the attempt showed, "
                "then continue with mastery_status.next."
            )
        else:
            lines.append(
                "The gate is not cleared yet. Say what the attempt showed, teach "
                "the gap if there is one, and pose the next question with "
                "mastery_quiz when you are ready — that call ends the turn, so "
                "put it last."
            )
        return "\n".join(lines)


def _card_end_marker(context: UnifiedContext) -> Callable[[], None]:
    """Return the callback ``mastery_quiz`` calls once the card is posed."""

    def mark() -> None:
        context.extension("mastery")["card_posted"] = True

    return mark


def _path_binder(context: UnifiedContext) -> Callable[[str], None]:
    """Return the callback that repoints ``context`` at another path."""

    def bind(path_id: str) -> None:
        context.metadata["mastery_path_id"] = path_id

    return bind


def _mode_binder(context: UnifiedContext) -> Callable[[str], None]:
    """Return the callback that puts ``context`` into another mode.

    Only the rest of *this* turn is repointed. Persisting the change onto the
    conversation is the runtime's job — a tool cannot reach the session store,
    and a mode that survived only in memory would be forgotten on reload.
    """

    def bind(mode: str) -> None:
        context.metadata["mastery_session_mode"] = mode
        # Read back by the turn runtime after the turn, so the conversation
        # resumes in the mode it ended in rather than the one it began in.
        context.metadata["mastery_session_mode_changed"] = True

    return bind


def _load_playbook(language: str) -> str:
    """Render the tutor playbook from the mastery prompt pack, as one block.

    One source of truth with the tutor loop, which renders these very sections
    as separate foundation blocks: a rule fixed in one place is fixed for both.
    """
    from deeptutor.services.prompt import get_prompt_manager

    pack = (
        get_prompt_manager().load_prompts(
            module_name="mastery",
            agent_name="mastery_loop",
            language=language,
        )
        or {}
    )
    loop_section = pack.get("loop") if isinstance(pack.get("loop"), dict) else {}
    sections = (
        pack.get("general"),
        pack.get("runtime_policy"),
        loop_section.get("system"),
        pack.get("playbook"),
    )
    return "\n\n".join(text for section in sections if (text := str(section or "").strip()))


__all__ = ["MasteryLoopCapability"]
