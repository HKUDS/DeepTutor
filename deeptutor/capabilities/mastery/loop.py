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
import json
import logging
import re
from typing import Any

from deeptutor.capabilities.mastery.tools import MASTERY_TOOL_NAMES
from deeptutor.capabilities.protocol import PromptBlock
from deeptutor.core.context import UnifiedContext
from deeptutor.core.tool_protocol import TOOL_EVENT_PROJECTION, ToolEventProjection
from deeptutor.services.prompt.lookup import prompt_text as _prompt_text
from deeptutor.tools.mastery_nav import MASTERY_NAV_TOOL_NAMES

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
# Defense in depth for explicit numbered assessments. Merely asking questions
# while explaining is valid; require both answer/assessment intent and multiple
# numbered question stems. This fallback does not replace registered groups.
_MULTIPART_INTENT_RE = re.compile(
    r"\b(?:answer these|practice questions|will grade (?:both|your|the) answers)\b|"
    r"\b(?:válaszolj|gyakorló kérdés|ellenőrző kérdés)\w*\b|"
    r"请回答|回答下面|练习题|检查题",
    re.IGNORECASE,
)
_NUMBERED_QUESTION_RE = re.compile(
    r"^\s*(?:#{1,6}\s+)?(?:\*\*)?\d{1,2}[.)、](?:\*\*)?\s+", re.MULTILINE
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

# A bare instruction to pick from unseen choices is also a promise of a card.
# #1508 ended with "四个选项，选一个。" after describing the objective, but
# never called mastery_quiz, so no choices were available to the learner.
_UNPOSTED_CHOICE_LEAD_IN_RE = re.compile(
    r"(?:[两三四五六七八九十]|\d+)个选项[，,、:\s]*(?:请|你)?(?:选|挑)(?:一|1)个[。！？.!?]?\s*$|"
    r"\b(?:three|four|\d+) (?:choices|options)[,:;\s]+(?:choose|pick|select) one[.!?]?\s*$",
    re.IGNORECASE,
)

# Delivery claims can precede a long explanation, unlike the vague question
# announcements above. Check clauses across the reply, but require both a
# concrete card/question and a delivery verb rather than the word "card" alone.
_CARD_DELIVERY_RE = re.compile(
    r"(?:卡片|题卡|(?:这|那|一|下一)道题|题目)[^。！？\n，,；;]{0,24}"
    r"(?:重开|开出来|(?:放|挂|贴|发)(?:上来|上去|出来|上了|好了)|"
    r"(?:生成|展示)(?:了|好|出来)|(?:就)?在(?:下面|下方))|"
    r"先探一题|"
    r"\bI(?:['’]ve| have)? (?:just |now )?(?:posted|reopened|displayed) "
    r"(?:the|a|this) (?:(?:question|quiz|answer) )?card\b|"
    r"\b(?:the|this) (?:(?:question|quiz|answer) )?card "
    r"(?:is|has been) (?:ready|posted|displayed|reopened|below)\b",
    re.IGNORECASE,
)
_NON_DELIVERY_CLAUSE_RE = re.compile(
    r"没有|没能|未能|尚未|还没|不会|不再|不要|不能|并未|无法|失败|"
    r"上次|上一轮|刚才|之前|如果|假如|是否|你说|[吗？?]|^\s*等|"
    r"\b(?:not|never|if|earlier|previously|yesterday)\b",
    re.IGNORECASE,
)
_QUOTED_CARD_TEXT_RE = re.compile(
    r"```.*?```|~~~.*?~~~|`[^`\n]*`|“[^”]*”|「[^」]*」|\"[^\"\n]*\"|^\s*>[^\n]*",
    re.DOTALL | re.MULTILINE,
)
_CONDITIONAL_DELIVERY_RE = re.compile(
    r"^\s*(?:等|如果|假如|(?:学|讲|看)完.{0,12}(?:以后|之后)|稍后|下一轮|"
    r"if\b|when\b|after\b)",
    re.IGNORECASE,
)


def _claims_card_delivery(text: str) -> bool:
    """Recognise current delivery claims without treating quoted reports as actions."""
    prose = _QUOTED_CARD_TEXT_RE.sub(" ", text)
    for sentence in re.split(r"[。！\n]|(?<=[.!?])\s+", prose):
        if _CONDITIONAL_DELIVERY_RE.search(sentence):
            continue
        for clause in re.split(r"[，,；;]", sentence):
            if _CARD_DELIVERY_RE.search(clause) and not _NON_DELIVERY_CLAUSE_RE.search(clause):
                return True
    return False


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


def _looks_like_multipart_assessment(text: str) -> bool:
    prose = _QUOTED_CARD_TEXT_RE.sub(" ", text)
    if not _MULTIPART_INTENT_RE.search(prose):
        return False
    # Markdown frequently puts the title on the numbered line and the actual
    # question in the following paragraph. Count question-bearing blocks, not
    # only same-line stems; quoted/code examples were removed above.
    starts = list(_NUMBERED_QUESTION_RE.finditer(prose))
    questions = 0
    for index, start in enumerate(starts):
        end = starts[index + 1].start() if index + 1 < len(starts) else len(prose)
        if re.search(r"[?？]", prose[start.end() : end]):
            questions += 1
    return questions >= 2


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
        if tool_name == "rag":
            import asyncio

            from deeptutor.learning.service import LearningService

            session_id = str(context.session_id or "").strip()
            turn_id = str(context.metadata.get("turn_id") or "").strip()

            async def present_sources(sources, purpose):
                if (
                    context.metadata.get("mastery_path_id") != path_id
                    or context.session_id != session_id
                    or str(context.metadata.get("turn_id") or "").strip() != turn_id
                ):
                    raise ValueError("The mastery source presentation context changed.")
                return await asyncio.to_thread(
                    LearningService().present_sources,
                    path_id,
                    sources,
                    purpose,
                    session_id=session_id,
                    turn_id=turn_id,
                )

            return {
                **kwargs,
                "_mastery_source_context": True,
                TOOL_EVENT_PROJECTION: ToolEventProjection(
                    arguments={"presentation": kwargs.get("presentation") or "inspect"}
                ),
                "_present_mastery_sources": present_sources,
            }
        # ``ask_user`` is deliberately untouched here. It carries clarifying
        # questions only; the graded ones are posed by ``mastery_quiz``.
        if tool_name == "read_source":
            # Deliberately a different key from chat's ``source_index``: that
            # one wakes the explore_context pre-pass (see the class docstring).
            # The tutor calls this tool on its own schedule instead.
            updated = dict(kwargs)
            updated["source_index"] = context.metadata.get("mastery_topic_source_index") or {}
            updated["_mastery_source_context"] = True
            updated[TOOL_EVENT_PROJECTION] = ToolEventProjection()
            return updated
        if tool_name in MASTERY_TOOL_NAMES:
            updated = dict(kwargs)
            if tool_name == "mastery_quiz":
                state["quiz_requested"] = True
                state["quiz_awaiting_grade"] = True
                # Only preparation after the latest failed attempt can earn a
                # final delivery round; an old packet must not reopen the loop.
                state.pop("quiz_recovery_receipt", None)
                updated["_end_turn_on_card"] = _card_end_marker(context)
            elif tool_name == "mastery_grade":
                state["quiz_awaiting_grade"] = False
                state["quiz_graded"] = True
            updated["_mastery_path_id"] = path_id
            updated["_attached_kb_names"] = list(context.knowledge_bases)
            updated["_inspected_image_hashes"] = list(
                context.extension("source_visual_evidence").get("image_hashes", [])
            )
            # Raw, not normalised: "this conversation never recorded a mode"
            # has to survive down to the tools, or every pre-modes conversation
            # (and every CLI / SDK turn, which pass none) would be enforced as
            # a study session and lose tools it has always been able to call.
            updated["_mastery_session_mode"] = context.metadata.get("mastery_session_mode")
            updated["_session_id"] = str(context.session_id or "").strip()
            updated["_turn_id"] = str(context.metadata.get("turn_id") or "").strip()
            if tool_name == "mastery_profile":
                updated["_learner_message"] = context.user_message or ""
                selection = int(state.get("profile_selection", 0)) + 1
                state["profile_selection"] = selection
                state["profile_write_pending"] = True

                def profile_recorded(receipt):
                    if (
                        state.get("profile_selection") == selection
                        and context.metadata.get("mastery_path_id") == path_id
                    ):
                        state["profile_write_pending"] = False
                        state["profile_receipt"] = receipt

                updated["_profile_recorded"] = profile_recorded

            if tool_name == "mastery_note_explained":
                session_id = str(context.session_id or "").strip()
                turn_id = str(context.metadata.get("turn_id") or "").strip()

                def teaching_delivery():
                    # A rebind must not let an earlier tool record teaching on
                    # the new path or under another session/turn's provenance.
                    if (
                        str(context.metadata.get("mastery_path_id") or "").strip() != path_id
                        or str(context.session_id or "").strip() != session_id
                        or str(context.metadata.get("turn_id") or "").strip() != turn_id
                    ):
                        return None
                    snapshot = context.extension("published_assistant_content").get("snapshot")
                    return {
                        "path_id": path_id,
                        "session_id": session_id,
                        "turn_id": turn_id,
                        "segments": snapshot() if callable(snapshot) else (),
                    }

                # Always override model-supplied private kwargs.
                updated["_teaching_delivery"] = teaching_delivery

            if tool_name == "mastery_revise":
                updated["_revision_request_id"] = str(
                    context.extension("agent_loop").get("model_call_id") or ""
                )

            if tool_name in {
                "mastery_quiz",
                "mastery_grade",
                "mastery_assess",
                "mastery_prepare_lesson",
            }:
                # A replacement needs a quote from the actual current learner
                # request, not a model-supplied claim about their intention.
                updated["_learner_message"] = context.user_message or ""
            if tool_name == "mastery_prepare_lesson":
                updated["_language"] = context.language
                from deeptutor.learning.policy import next_objective
                from deeptutor.learning.storage import LearningStore

                def bind_lesson(kp_id):
                    progress = LearningStore().load(path_id)
                    context.metadata["mastery_lesson_objective"] = {
                        "path_id": path_id,
                        "kp_id": kp_id,
                        "policy_id": next_objective(progress).knowledge_point_id
                        if progress
                        else "",
                    }
                    if (
                        progress is not None
                        and context.metadata.get("mastery_path_id") == path_id
                        and state.get("quiz_requested")
                        and not state.get("card_posted")
                    ):
                        state["quiz_recovery_receipt"] = {
                            **context.metadata["mastery_lesson_objective"],
                            "revision": progress.version,
                        }

                updated["_bind_lesson_objective"] = bind_lesson
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
        if tool_name in MASTERY_NAV_TOOL_NAMES:
            # The navigation tools stay mounted inside a mastery session —
            # sending the learner to a *different* topic is a real thing to
            # want mid-course. What they could not see is which topic this
            # turn is already tutoring, so a hand-off card could point back at
            # this very conversation's topic (#1412).
            updated = dict(kwargs)
            updated["_tutoring_path_id"] = path_id
            return updated
        return kwargs

    def settlement_recovery(self, context: UnifiedContext) -> tuple[str, tuple[str, ...]] | None:
        """Spend one final card-only round when a failed quiz's source was repaired."""
        if not self.is_active(context):
            return None
        state = context.extension("mastery")
        receipt = state.pop("quiz_recovery_receipt", None)
        if (
            not receipt
            or not state.get("quiz_requested")
            or state.get("card_posted")
            or state.get("quiz_recovery_used")
        ):
            return None
        from deeptutor.learning.policy import next_objective
        from deeptutor.learning.storage import LearningStore

        path_id = context.metadata.get("mastery_path_id")
        binding = context.metadata.get("mastery_lesson_objective") or {}
        if receipt["path_id"] != path_id or any(
            receipt[key] != binding.get(key) for key in ("path_id", "kp_id", "policy_id")
        ):
            return None
        progress = LearningStore().load(path_id)
        if (
            progress is None
            or progress.version != receipt["revision"]
            or next_objective(progress).knowledge_point_id != receipt["policy_id"]
        ):
            return None
        state["quiz_recovery_used"] = True
        return (
            "Source preparation for the quiz selected in this turn has now succeeded. "
            "Use this single final delivery round to call mastery_quiz with a supported question "
            "contract from the prepared evidence. Preserve the current pending question and "
            "replacement rules. Do not search, prepare again, grade, or claim a card was delivered "
            "in prose. If verification still fails, this turn cannot complete the delivery.",
            ("mastery_quiz",),
        )

    def finish_instruction(self, context: UnifiedContext, final_text: str) -> str | None:
        """Catch a finish that leaves the learner with nothing to answer.

        A quiz selected in this turn must reach its success callback before
        the turn can finish, regardless of reply wording or later grading.
        Text heuristics are only a fallback for replies that never selected
        the tool. Two other states are not an outstanding delivery:

        A pending question from an earlier turn does not mean it went
        unasked — it was already posed on its own card — so a learner
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
        if state.get("profile_write_pending") and not state.get("profile_repair_requested"):
            state["profile_repair_requested"] = True
            return (
                "The selected mastery_profile update has no successful storage receipt. "
                "If repairable, retry once with the current revision and only the requested "
                "changed fields. Blank optional fields keep existing values. Otherwise continue "
                "the useful teaching, apply the request for this turn, and explain that it was "
                "not saved for future sessions. Do not claim durable persistence without a "
                "successful receipt. Do not delay teaching with repeated optional profile retries."
            )
        if state.get("quiz_requested") and not state.get("card_posted"):
            return (
                "This turn selected mastery_quiz, but no question card was successfully "
                "posted. Inspect the tool error and retry mastery_quiz with corrected "
                "arguments. A prose reply or a grading call cannot complete the selected "
                "question delivery. If delivery remains unsuccessful, this turn must "
                "fail rather than report successful completion."
            )
        if not state.get("card_posted") and (
            _announces_an_unposed_question(final_text)
            or _claims_card_delivery(final_text)
            or (
                not state.get("quiz_awaiting_grade")
                and _UNPOSTED_CHOICE_LEAD_IN_RE.search(final_text)
            )
        ):
            # Argument binding sets quiz_awaiting_grade even when registration
            # fails. Only the tool's success callback marks a card as posted.
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
        if not state.get("card_posted") and _looks_like_multipart_assessment(final_text):
            return (
                "That reply presented a numbered assessment as unregistered prose. "
                "For practice across all objective types, call mastery_quiz with a questions group "
                "so each answer has its own stored contract and result. CONCEPT / DESIGN cards "
                "do not open their qualitative gate; use mastery_assess for the learner's own "
                "explanation when assessing that gate. If an older question "
                "is pending and you want to show it again, call mastery_quiz with "
                "pending_action='resume' and its exact parent resume_question_id, without "
                "new questions or answer keys. Preserve it unless the learner explicitly requested replacement; "
                "then use its current question ID and a literal replacement_request quote. "
                "Do not concatenate expected answers or claim that a prose list is a card. "
                "If this is teaching rather than assessment, explain directly without "
                "instructing the learner to answer an unregistered practice set."
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
        notice = ""
        if state.get("profile_write_pending"):
            if not final_text.strip() and not state.get("card_posted"):
                # This hook also runs after every tool batch. An optional
                # storage notice cannot end work still in progress; append it
                # only to a real final answer or an accepted question card.
                return None
            # Optional memory failure must not deadlock otherwise valid tutoring.
            # The native status corrects any unsupported persistence promise;
            # it does not classify or discard the learner-facing explanation.
            state["profile_write_pending"] = False
            state["profile_receipt"] = {"status": "not_saved"}
            from deeptutor.services.prompt import get_prompt_manager
            from deeptutor.services.prompt.lookup import prompt_text

            pack = get_prompt_manager().load_prompts("mastery", "mastery_loop", context.language)
            notice = prompt_text(pack, ("notices", "profile_not_saved"))

        def with_notice(override):
            if not notice:
                return override
            content = final_text if override is None else override
            return notice + ("\n\n" + content if content.strip() else "")

        if not state.get("card_posted"):
            return with_notice(None)
        if final_text.strip():
            # A tool-less finish round already wrote the answer; the card was
            # posed earlier in the turn and has nothing to override.
            return with_notice(None)
        state["card_posted"] = False
        return with_notice("")

    async def pre_loop(
        self, context: UnifiedContext, stream: Any, *, usage: Any = None
    ) -> PromptBlock | None:
        """Read current state once before the first model call, without an LLM.

        This is a fresh read for this turn, never a session cache. Reuse the
        status tool so objective gates and pending answers have one authority.
        The loop's pre-pass wrapper falls back to the tool on read failure.
        """
        context.extension("mastery").pop("status_snapshot", None)
        if not self.is_active(context) or not context.metadata.get("mastery_path_id"):
            return None
        from deeptutor.capabilities.mastery.mode import normalize_mode
        from deeptutor.capabilities.mastery.tools import MasteryStatusTool

        binding = (
            context.metadata.get("mastery_path_id"),
            context.metadata.get("mastery_session_mode"),
        )
        result = await MasteryStatusTool().execute(
            **self.augment_kwargs("mastery_status", {}, context),
            _working_brief=normalize_mode(context.metadata.get("mastery_session_mode"))
            != "outline",
        )
        if not result.success:
            return None
        # A rebind during the read must not seed the new path with old state.
        current = (
            context.metadata.get("mastery_path_id"),
            context.metadata.get("mastery_session_mode"),
        )
        if (
            binding != current
            or json.loads(result.content).get("path_id") != str(binding[0]).strip()
        ):
            return None
        block = PromptBlock(
            "mastery_status_snapshot",
            "[Current-turn mastery_status snapshot]\n"
            "The runtime has already read mastery_status for this turn and active path. "
            "Use this result directly; do not call mastery_status again just to begin. "
            "Refresh with mastery_status after changing the path, mode, outline, or progress "
            "when updated state is needed. Earlier turns' snapshots are historical only.\n"
            + result.content,
        )
        context.extension("mastery")["status_snapshot"] = block.content
        return block

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

    def skip_kb_seed(self, context: UnifiedContext) -> bool:
        """Don't pre-search the knowledge base with a card answer.

        The message of a card turn is the learner's pick ("A", "True") or a
        declined question, not a question to look up. The engine grades it
        against the stored key, and the tutor can still call ``rag`` with the
        actual question if it needs the material.
        """
        if not self.is_active(context):
            return False
        meta = context.metadata
        grade = meta.get("mastery_card_grade")
        skip = meta.get("mastery_card_skip")
        return bool(
            meta.get("mastery_card_answered")
            or (isinstance(grade, dict) and grade)
            or (isinstance(skip, dict) and skip.get("skipped"))
        )

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

        def verdict(item):
            typed = item.get("result")
            return (
                typed
                if isinstance(typed, str)
                and typed in {"correct", "partial", "incorrect", "ungraded"}
                else (
                    "ungraded"
                    if item.get("is_correct") is None
                    else "correct"
                    if item.get("is_correct")
                    else "incorrect"
                )
            )

        results = result.get("results")
        if isinstance(results, list) and results:
            parts = [
                f"{item.get('question_id', '')}: "
                f"{verdict(item)}; final={item.get('final', True)}; "
                f"objective {item.get('knowledge_point_id', '')}; "
                f"mastered={bool(item.get('mastered'))}; feedback={item.get('feedback', '')}"
                for item in results
                if isinstance(item, dict)
            ]
            complete = result.get("complete", grade.get("complete", True)) is not False
            status = (
                "The question group was already graded by the engine. "
                if complete
                else "Only the submitted group replies were graded by the engine. "
                "These children still need an answer or clarification: "
                + ", ".join(result.get("remaining_question_ids", []))
                + ". "
                "Preserve final siblings. Clarify nonfinal replies and then assess the learner's explicit revision. "
                "Explain reported gaps, but never infer confusion from an unanswered "
                "item or invent its reply. "
            )
            return (
                "[Mastery] "
                + status
                + "Do not regrade final replies or repeat their answer keys. Each result belongs "
                "only to its own objective; the parent group gives no extra credit. "
                "Address the specific gap, then use the fresh status for the next step.\n"
                + "\n".join(parts)
            )
        outcome = verdict(
            {**result, "is_correct": result.get("is_correct", grade.get("is_correct"))}
        )
        learner_answer = str(result.get("learner_answer") or "").strip()
        lines = [
            "[Mastery] The learner answered the open question on its card and the "
            f"engine reports: {outcome}"
            + (f' (they answered "{learner_answer}")' if learner_answer else "")
            + ".",
            str(result.get("feedback") or ""),
        ]
        if result.get("final") is False or outcome == "ungraded":
            lines.append(
                "This is not a final grade and created no mastery penalty. Ask for the needed clarification, preserve the same question, and assess an explicit revised learner answer. Do not infer a wrong answer or replace this question automatically."
            )
            return "\n".join(line for line in lines if line)
        lines.append(
            "The engine already graded this reply; do not call mastery_grade. The card shows the saved final result. Do not repeat the answer key or grade this reply again."
        )
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
