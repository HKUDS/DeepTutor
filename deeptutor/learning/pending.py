"""Public, stable views of pending mastery questions.

The persisted :class:`~deeptutor.learning.models.PendingQuestion` contains the
server-only expected answer. This module projects it into the smaller contract
that is safe to give to the tutor model and interactive clients. It also owns
the pure multiple-choice translations shared by registration, presentation,
and grading, so all three boundaries use the same immutable label/body map.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
import re
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from deeptutor.learning.models import PendingQuestion


OPTION_PREFIX_RE = re.compile(r"^\s*([A-Z])\s*[.:：、)）-]\s*(.+)$", re.IGNORECASE | re.DOTALL)


def positional_label(index: int) -> str:
    """The label an option carries by its position: A, B, C, … then 27, 28, …"""
    return chr(ord("A") + index) if index < 26 else str(index + 1)


def _option_texts(options: list[str]) -> list[str]:
    return [text for text in (str(raw or "").strip() for raw in options) if text]


def _split_labelled(texts: list[str]) -> tuple[list[str], list[str]] | None:
    """``(labels, bodies)`` when every option carries a single-letter prefix."""
    labels: list[str] = []
    bodies: list[str] = []
    for text in texts:
        if len(text) == 1 and text.isalnum():
            # Legacy rows persisted the bare labels themselves.
            labels.append(text.upper())
            bodies.append(text)
            continue
        match = OPTION_PREFIX_RE.match(text)
        if match is None:
            return None
        labels.append(match.group(1).upper())
        bodies.append(match.group(2).strip())
    return labels, bodies


def option_label_intent(options: list[str]) -> list[str] | None:
    """The A/B/C labels the caller *meant* to give, or ``None`` if unlabelled.

    "Meant to" is decided by two things together: every option carries a
    single-letter prefix, and the first one is ``A``. A leading letter alone is
    not evidence — ``"x - 1 = 0"`` matches the prefix pattern and would
    otherwise register as option ``X`` with the body ``"1 = 0"``, which is how
    a maths question ended up with mislabelled and (once two options collided
    on one letter) duplicated choices.

    The returned labels may still be malformed — repeated or skipping a letter.
    :func:`parse_options` reads those positionally so nothing is lost, and
    registration rejects them so the model fixes the question instead.
    """
    split = _split_labelled(_option_texts(options))
    if split is None:
        return None
    labels, _ = split
    return labels if labels and labels[0] == "A" else None


def canonical_labels(count: int) -> set[str]:
    """The label set a well-formed *count*-option question must carry."""
    return {positional_label(index) for index in range(count)}


def parse_options(options: list[str]) -> dict[str, str]:
    """Map persisted option strings to their stable ``{label: body}`` form."""
    texts = _option_texts(options)
    split = _split_labelled(texts)
    if split is not None:
        labels, bodies = split
        if labels[:1] == ["A"] and set(labels) == canonical_labels(len(labels)):
            return dict(zip(labels, bodies, strict=True))
    return {positional_label(index): text for index, text in enumerate(texts)}


def has_option_bodies(options: dict[str, str]) -> bool:
    """Whether a choice map holds real answer text, not only A/B/C labels."""
    return len(options) >= 2 and all(
        value.strip() and value.strip().upper() != key.upper() for key, value in options.items()
    )


def format_options(options: dict[str, str]) -> list[str]:
    """Render a choice map as canonical, persistable ``"label: body"`` strings."""
    return [f"{label}: {body}" for label, body in options.items()]


def resolve_answer(answer: str, options: dict[str, str]) -> str:
    """Resolve a label, labelled option, or unique body to its stable label."""
    candidate = str(answer or "").strip()
    if not candidate:
        return ""

    key = candidate.upper()
    if key in options:
        return key

    prefix_match = OPTION_PREFIX_RE.match(candidate)
    if prefix_match and prefix_match.group(1).upper() in options:
        return prefix_match.group(1).upper()

    needle = candidate.casefold()
    exact = [label for label, text in options.items() if text.casefold() == needle]
    if len(exact) == 1:
        return exact[0]
    contained = [label for label, text in options.items() if needle in text.casefold()]
    return contained[0] if len(contained) == 1 else ""


def _squeezed(value: str) -> str:
    """Case-folded with all whitespace removed, for comparing formulas."""
    return "".join(str(value or "").split()).casefold()


def _mentioned_labels(text: str, labels: Iterable[str]) -> list[str]:
    """Labels named in *text* as standalone tokens, not inside another word.

    ``\\b`` is useless here: Chinese is word-character too, so ``"选C"`` has no
    word boundary before the ``C``. The guard is therefore "not glued to
    another latin letter or digit", which accepts ``选C`` / ``答案是 C`` /
    ``C。`` and rejects the ``C`` inside ``ABC``.
    """
    return [
        label
        for label in labels
        if re.search(rf"(?<![0-9A-Za-z]){re.escape(label)}(?![0-9A-Za-z])", text, re.IGNORECASE)
    ]


def resolve_choice_submission(answer: str, options: dict[str, str]) -> str:
    """Resolve a learner submission to the option label it picked, or ``""``.

    A learner typing into the composer instead of tapping the card writes
    ``"选C"``, ``"答案是 C"`` or the option body itself — none of which the
    label-only comparison could read, so a correct answer was graded wrong.
    Every form that identifies exactly ONE option is accepted; anything
    ambiguous (two labels named, a body fragment matching several) resolves to
    nothing, which the caller must treat as "unreadable", never as wrong.

    Registration stays separately forgiving of a model-supplied body fragment
    through :func:`resolve_answer`.
    """
    candidate = str(answer or "").strip()
    if not candidate:
        return ""
    key = candidate.upper()
    if key in options:
        return key
    prefix_match = OPTION_PREFIX_RE.match(candidate)
    if prefix_match and prefix_match.group(1).upper() in options:
        return prefix_match.group(1).upper()
    needle = _squeezed(candidate)
    exact = [label for label, body in options.items() if _squeezed(body) == needle]
    if len(exact) == 1:
        return exact[0]
    mentioned = _mentioned_labels(candidate, options)
    return mentioned[0] if len(mentioned) == 1 else ""


def is_readable_choice_answer(answer: str, options: list[str] | dict[str, str]) -> bool:
    """Whether *answer* identifies exactly one option on a choice question.

    Composer text that is a clarifying question (or otherwise unmappable) must
    not be treated as a committed pick — see mastery gate stall #1004.
    """
    option_map = parse_options(options) if isinstance(options, list) else options
    if not option_map:
        return False
    candidate = str(answer or "").strip()
    resolved = resolve_choice_submission(candidate, option_map)
    if not resolved:
        return False

    # Exact labels (optionally followed by declarative punctuation), labelled
    # answers, and exact option bodies are unambiguous without extra wording.
    if re.fullmatch(rf"{re.escape(resolved)}[。.!！]?", candidate, re.IGNORECASE):
        return True
    prefix_match = OPTION_PREFIX_RE.match(candidate)
    if prefix_match and prefix_match.group(1).upper() == resolved:
        return True
    if _squeezed(candidate) == _squeezed(option_map[resolved]):
        return True

    # Merely mentioning one label is not an answer. In particular, questions
    # such as "why is B wrong?" used to resolve to B and freeze the gate.
    if re.search(
        r"[?？]|\b(?:why|what|how|can|could|would|explain)\b|"
        r"(?:为什么|为何|怎么|如何|什么|解释一下|请解释)",
        candidate,
        re.IGNORECASE,
    ):
        return False

    label = re.escape(resolved)
    return bool(
        re.search(
            rf"(?:\b(?:answer(?:\s+is)?|choose|pick|select|"
            rf"think(?:\s+it(?:'s|\s+is))?|go\s+with)\s*(?:option\s*)?{label}\b|"
            rf"(?:答案(?:是|为)?|我?选(?:择)?|应该是|我觉得是)\s*{label})",
            candidate,
            re.IGNORECASE,
        )
    )


@dataclass(frozen=True, slots=True)
class PublicPendingOption:
    """One learner-visible option; ``id`` and ``label`` are intentionally stable."""

    id: str
    label: str
    body: str

    def to_dict(self) -> dict[str, str]:
        return {"id": self.id, "label": self.label, "body": self.body}

    def to_ask_user_dict(self) -> dict[str, str]:
        return {"label": self.label, "description": self.body}


@dataclass(frozen=True, slots=True)
class PublicPendingQuestion:
    """Learner-visible pending state, deliberately excluding the answer key."""

    question_id: str
    prompt: str
    question_type: str
    options: tuple[PublicPendingOption, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {
            "question_id": self.question_id,
            "prompt": self.prompt,
            "question_type": self.question_type,
            "options": [option.to_dict() for option in self.options],
        }

    def to_ask_user_dict(self) -> dict[str, Any]:
        return {
            "id": self.question_id,
            "prompt": self.prompt,
            "options": [option.to_ask_user_dict() for option in self.options],
            "multi_select": False,
            "allow_free_text": True,
        }


def public_pending_question(pending: PendingQuestion) -> PublicPendingQuestion:
    """Project persisted pending state without exposing ``expected_answer``."""
    choice_map = parse_options(list(pending.options or []))
    options = (
        tuple(
            PublicPendingOption(id=label, label=label, body=body)
            for label, body in choice_map.items()
        )
        if pending.question_type == "choice"
        else ()
    )
    return PublicPendingQuestion(
        question_id=pending.question_id,
        prompt=pending.prompt,
        question_type=pending.question_type,
        options=options,
    )


__all__ = [
    "OPTION_PREFIX_RE",
    "canonical_labels",
    "PublicPendingOption",
    "PublicPendingQuestion",
    "format_options",
    "has_option_bodies",
    "is_readable_choice_answer",
    "option_label_intent",
    "parse_options",
    "positional_label",
    "public_pending_question",
    "resolve_answer",
    "resolve_choice_submission",
]
