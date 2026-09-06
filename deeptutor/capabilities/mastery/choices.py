"""The data contract for multiple-choice mastery questions.

A choice question crosses four boundaries with different shapes for the same
data: the model registers option *bodies* through ``mastery_quiz``, the learner
answers a *label* (``"C"``) on an interactive ``ask_user`` card, deterministic
grading must compare like with like, and the Question Bank persists the full
option text. This module owns the translation between those shapes so the tool
layer (:mod:`deeptutor.capabilities.mastery.tools`) reads as orchestration:

* :func:`read_option_objects` — options the model sent as objects → the
  ``{label, body}`` options this contract stores.
* :func:`parse_options` — legacy option strings → a ``{label: body}`` map.
* :func:`option_label_intent` / :func:`canonical_labels` — were the options
  meant to be labelled A/B/C, and do those labels form a well-formed set?
* :func:`has_option_bodies` — did the model send real bodies, not bare labels?
* :func:`resolve_answer` — a model-supplied answer → its stable option label.
* :func:`recover_options_from_turn` — bodies recovered from a legacy turn's
  ``ask_user`` event, for paths registered before the contract was enforced.

Everything here is pure except :func:`recover_options_from_turn`, which takes a
session store by dependency injection rather than importing one, keeping this
module free of infrastructure wiring.
"""

from __future__ import annotations

from collections.abc import Mapping
import logging
import re
from typing import Any

from deeptutor.learning.pending import (
    OPTION_PREFIX_RE,
    canonical_labels,
    has_option_bodies,
    is_readable_choice_answer,
    option_label_intent,
    parse_options,
    positional_label,
    resolve_answer,
    resolve_choice_submission,
)

logger = logging.getLogger(__name__)


#: Where an option object keeps its answer text. ``description`` leads because
#: it is ``ask_user``'s own key (see :mod:`deeptutor.tools.ask_user`), which is
#: where a model picks that shape up in the first place.
_OPTION_BODY_KEYS = ("body", "description", "text", "content", "answer", "value", "option")
#: Where it keeps the label.
_OPTION_LABEL_KEYS = ("label", "key", "letter", "id")
#: A label carrying no answer text of its own: ``"A"``, ``"A."``, ``"B)"``.
_BARE_LABEL_RE = re.compile(r"^\s*([A-Za-z0-9])\s*[.、):：-]?\s*$")


def _scalar_text(value: Any) -> str:
    """*value* as trimmed text, when it is a scalar an option can be made of."""
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        return ""
    return str(value).strip()


def _first_text(entry: Mapping[Any, Any], keys: tuple[str, ...]) -> str:
    """The first of *keys* holding scalar text in *entry*."""
    for key in keys:
        text = _scalar_text(entry.get(key))
        if text:
            return text
    return ""


def split_label_and_body(text: str) -> tuple[str, str]:
    """``"A: body"`` → ``("A", "body")``; text with no label → ``("", text)``."""
    match = OPTION_PREFIX_RE.match(text)
    if match is None:
        return "", text
    return match.group(1).upper(), match.group(2).strip()


def _option_object(entry: Any) -> dict[str, str] | None:
    """One option the model sent as ``{label, body}``, or ``None`` if unreadable.

    A bare label with its text elsewhere is rejoined (``{"label": "A",
    "description": "…"}``). A label that already carries the answer text is
    split apart, and the description sent beside it is dropped: that describes
    what picking the option *means*, which belongs in ``explanation`` and not
    on a card still being answered. An option with a label and no text at all
    keeps the empty body so the caller can reject it as a bare label, which is
    a different mistake with its own message.
    """
    if isinstance(entry, Mapping):
        label = _first_text(entry, _OPTION_LABEL_KEYS)
        body = _first_text(entry, _OPTION_BODY_KEYS)
        bare = _BARE_LABEL_RE.match(label) if label else None
        if bare is not None:
            return {"label": bare.group(1).upper(), "body": body}
        if label:
            split_label, split_body = split_label_and_body(label)
            return {"label": split_label, "body": split_body}
        return {"label": "", "body": body} if body else None
    text = _scalar_text(entry)
    if not text:
        return None
    label, body = split_label_and_body(text)
    return {"label": label, "body": body}


def read_option_objects(raw: Any) -> tuple[list[dict[str, str]], list[Any]] | None:
    """Read options the model shaped as objects, or ``None`` for plain strings.

    ``mastery_quiz`` asks for ``{label, body}`` options, but a model working
    inside one turn also sees ``ask_user`` — a different tool, with a
    ``{label, description}`` parameter of the same name — and reaches for that
    shape here readily. Both are read, because the object it sends carries
    exactly the label and the body this contract wants; rejecting it cost the
    learner the question outright, since a model that reached for the shape
    once reached for it again on every retry until the turn's round budget was
    gone and no card was ever posed.

    Returns the options read and the entries it could not read — passed back
    untouched so the caller's rejection can name the shape actually sent — or
    ``None`` when every entry is a plain string, which the legacy path
    (:func:`parse_options`) infers labels for as a group instead.
    """
    if isinstance(raw, Mapping):
        # ``{"A": "first answer", …}`` — the internal map, sent as is.
        mapped = [
            {"label": label, "body": body}
            for label, body in (
                (_scalar_text(key), _scalar_text(value)) for key, value in raw.items()
            )
            if label and body
        ]
        return (mapped, []) if len(mapped) == len(raw) and mapped else None
    if not isinstance(raw, (list, tuple)):
        return None
    if all(isinstance(entry, str) for entry in raw):
        return None

    read: list[dict[str, str]] = []
    unreadable: list[Any] = []
    for entry in raw:
        option = _option_object(entry)
        if option is None:
            unreadable.append(entry)
            continue
        read.append(option)
    return read, unreadable


def labelled_options(options: list[dict[str, str]]) -> list[dict[str, str]]:
    """Give every option that came without a label the one its position implies."""
    return [
        {"label": option["label"] or positional_label(index), "body": option["body"]}
        for index, option in enumerate(options)
    ]


# How a restated option reads inside prose: an optional bullet, the label, a
# separator, then the body. Built per option so the label and its own body must
# appear together — a stem that merely reuses an option's words does not match.
_OPTION_ECHO_TEMPLATE = r"(?:[-*+]\s*)?(?:\*\*)?{label}(?:\*\*)?\s*[.、):：）]\s*{body}"


def strip_echoed_options(question: str, options: dict[str, str]) -> tuple[str, bool]:
    """Remove an option list the model also spelled out inside the question.

    The card renders ``options`` as its own labelled, clickable list, so a stem
    that restates them shows every choice twice — once as dead prose, once as
    the buttons. Models do this readily, and nothing in the contract told them
    otherwise: it asks for the stem and the options separately without ever
    saying the stem must not contain them.

    Repaired rather than rejected, unlike the other checks in this contract.
    Those reject a payload that is missing or self-contradictory, where the
    intended question cannot be recovered; this one is pure redundancy — the
    bodies are already held in ``options`` — and bouncing the call would cost
    the learner another round while they wait for the card.

    Only a *list* is stripped, never a lone mention: a stem may legitimately
    quote one option ("why does ``int`` fail here?"), so two or more
    label-and-body pairs are required. A stem that is *nothing but* its options
    is left intact for the caller's own validation to rule on, rather than
    being emptied here.
    """
    stem = str(question or "")
    if len(options) < 2 or not stem.strip():
        return stem, False

    echo_starts: list[int] = []
    for label, body in options.items():
        needle = str(body or "").strip()
        if not needle:
            continue
        pattern = _OPTION_ECHO_TEMPLATE.format(
            label=re.escape(str(label).strip()),
            body=re.escape(needle),
        )
        match = re.search(pattern, stem, re.IGNORECASE)
        if match is not None:
            echo_starts.append(match.start())

    if len(echo_starts) < 2:
        return stem, False
    head = stem[: min(echo_starts)].rstrip().rstrip("-*+").rstrip()
    if not head:
        return stem, False
    return head, True


def _normalized_prompt(value: str) -> str:
    """Alphanumeric-only, case-folded form for tolerant prompt matching."""
    return "".join(char.casefold() for char in str(value or "") if char.isalnum())


async def recover_options_from_turn(store: Any, turn_id: str, question: str) -> dict[str, str]:
    """Recover choice bodies from the most recent matching ``ask_user`` card.

    A compatibility fallback for questions registered by older versions, where
    ``mastery_quiz`` persisted only ``["A", "B", ...]`` even though the full
    descriptions were present in the turn's ``ask_user`` event. ``store`` is
    injected so this stays decoupled from the session layer.
    """
    if not turn_id or not hasattr(store, "get_turn_events"):
        return {}
    try:
        events = await store.get_turn_events(turn_id)
    except Exception:
        logger.warning("Failed to load turn events for mastery option recovery", exc_info=True)
        return {}

    target = _normalized_prompt(question)
    for event in reversed(events):
        if event.get("type") != "tool_call":
            continue
        metadata = event.get("metadata") or {}
        if metadata.get("tool_name") != "ask_user":
            continue
        for item in reversed((metadata.get("args") or {}).get("questions") or []):
            if not isinstance(item, dict):
                continue
            recovered = {
                str(option.get("label") or "").strip().upper(): str(
                    option.get("description") or ""
                ).strip()
                for option in (item.get("options") or [])
                if isinstance(option, dict)
                and str(option.get("label") or "").strip()
                and str(option.get("description") or "").strip()
            }
            if not has_option_bodies(recovered):
                continue
            prompt = _normalized_prompt(str(item.get("prompt") or ""))
            if prompt == target or prompt.startswith(target) or target.startswith(prompt):
                return recovered
    return {}


__all__ = [
    "canonical_labels",
    "has_option_bodies",
    "is_readable_choice_answer",
    "option_label_intent",
    "labelled_options",
    "parse_options",
    "read_option_objects",
    "recover_options_from_turn",
    "resolve_answer",
    "resolve_choice_submission",
    "split_label_and_body",
    "strip_echoed_options",
]
