"""How a mastery question is put in front of the learner.

A mastery question is not a clarifying question. It is a graded artefact: it
has an objective it is testing, a stable id the gate is keyed on, an expected
answer held server-side, a difficulty, and a place in a run of attempts on the
same objective. ``ask_user`` — the generic "I am blocked, decide this for me"
card — carries none of that, so posing a mastery question through it meant
translating the question into a shape that could not hold it, and asking the
model to keep the two in sync by hand.

The tutor now poses the question in one call and this module owns the shape it
travels in, which is the point: the card the learner sees is derived from the
persisted question rather than re-stated alongside it, so the two cannot drift.

That shape is this course's own, on its own event key
(:data:`QUESTION_CARD_KEY`). It used to *also* satisfy the ``ask_user``
structural contract, because the pause/resume machinery and the answer
substitution were written against it — but a posed question no longer pauses
its turn (the answer arrives as the next message, on ``mastery_answer``), so
nothing on the answer path reads that contract any more. What was left was a
card riding a channel meant for something else, marked with a ``kind`` every
reader had to branch on — and the one reader that forgot to branch left every
composer convinced the learner owed a same-turn reply. Cards posed before this
change still carry the old shape, so the surfaces that read them keep a path
for it.
"""

from __future__ import annotations

from typing import Any

from deeptutor.learning.models import LearningProgress, PendingQuestion
from deeptutor.learning.pending import public_pending_question

#: Tool-metadata key the posed card travels under. Also the discriminator on
#: the older ``ask_user``-shaped payload, for cards posed before the card got
#: its own channel.
QUESTION_CARD_KEY = "mastery_question"

#: Metadata key the graded result travels under, so the card that asked the
#: question can show the verdict instead of leaving it to prose scrollback.
GRADE_META_KEY = "mastery_grade"


def attempt_number(progress: LearningProgress, knowledge_point_id: str) -> int:
    """Which attempt on this objective the next answer will be (1-based).

    Counted from the durable attempt log rather than tracked separately: a
    question posed twice because a turn was interrupted must not inflate it.
    """
    kp_id = str(knowledge_point_id or "")
    if not kp_id:
        return 1
    return sum(1 for attempt in progress.quiz_attempts if attempt.knowledge_point_id == kp_id) + 1


def build_question_card(
    pending: PendingQuestion,
    *,
    objective_name: str = "",
    attempt: int = 1,
) -> dict[str, Any]:
    """The pause payload for one posed mastery question.

    Never carries ``expected_answer`` or ``explanation``: both are withheld
    until the answer is committed, and this payload is rendered to the learner.
    """
    public = public_pending_question(pending)
    return {
        "question_id": public.question_id,
        "prompt": public.prompt,
        "question_type": public.question_type,
        "objective": {
            "id": pending.knowledge_point_id,
            "name": str(objective_name or ""),
        },
        "difficulty": str(pending.difficulty or ""),
        "attempt": max(1, int(attempt)),
        "options": [{"label": option.label, "body": option.body} for option in public.options],
        # Every mastery question takes a typed answer: a learner who can only
        # tap a letter cannot say "I don't know" or show their work.
        "allow_free_text": True,
    }


def build_grade_result(
    *,
    question_id: str,
    is_correct: bool,
    learner_answer: str,
    correct_label: str,
    choice_options: dict[str, str],
    explanation: str,
) -> dict[str, Any]:
    """What the answered card shows once the gate has ruled on it.

    Safe to send now and only now: the expected answer and the explanation are
    the answer key, withheld while the question is open and released the moment
    it is graded — which is exactly when they are worth reading.
    """
    label = str(correct_label or "").strip()
    return {
        "question_id": str(question_id or ""),
        "is_correct": bool(is_correct),
        "learner_answer": str(learner_answer or ""),
        "correct_label": label,
        "correct_body": str(choice_options.get(label) or "") if label else "",
        "explanation": str(explanation or ""),
    }


__all__ = [
    "GRADE_META_KEY",
    "QUESTION_CARD_KEY",
    "attempt_number",
    "build_grade_result",
    "build_question_card",
]
