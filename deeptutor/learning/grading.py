"""Deterministic answer grading + coarse error classification for Mastery Path."""

from __future__ import annotations

from dataclasses import dataclass
from difflib import SequenceMatcher
from fractions import Fraction
import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from deeptutor.learning.models import ErrorType


def grade_answer(user_answer: str, expected_answer: str, question_type: str = "short") -> bool:
    """Grade user answer against expected answer.

    Args:
        user_answer: The user's submitted answer.
        expected_answer: The stored expected answer.
        question_type: One of "choice", "short", "open".

    Returns:
        True if answer is correct.
    """
    user = user_answer.strip().lower()
    expected = expected_answer.strip().lower()

    if not expected:
        return False

    if question_type == "choice":
        user_norm = user.replace(" ", "")
        expected_norm = expected.replace(" ", "")
        return user_norm == expected_norm

    if question_type == "short":
        if user == expected:
            return True
        # A numeric key is never fuzzy-matched: "1250.60" is not "1250.50".
        # Without a verdict, ambiguous readings fail closed like every miss.
        if _numeric_parts(expected) is not None:
            return numeric_equivalent(user, expected).correct
        if len(expected) <= 30:
            return SequenceMatcher(None, user, expected).ratio() >= 0.85
        return False

    if question_type == "open":
        keywords = [k.strip() for k in re.split(r"[,;，；。\n]+", expected) if k.strip()]
        if not keywords:
            return False
        matched = sum(1 for kw in keywords if kw in user)
        return matched / len(keywords) >= 0.6

    return False


# Numeric answer equivalence. Shared vectors with the web port
# (web/lib/numeric-answer.ts) live in tests/fixtures/numeric_answers.json.
_TEXT_FOLD = str.maketrans(
    {"\u2212": "-", "\u2013": "-", "\u00a0": " ", "\u202f": " ", "\u2009": " ", "\u2019": "'"}
)
_LABEL = re.compile(
    r"(?<![^\s,;])\s*(?:\(?(?P<item>[a-z]{1,3}|[0-9]{1,2})\)|(?P<name>[^\W\d_][\w'\[\]]{0,15})\s*[=:])",
    re.IGNORECASE,
)
_NUMBER = re.compile(
    r"(?P<pre>[^0-9]*?)(?P<num>[0-9](?:[0-9.,' ]*[0-9])?)"
    r"(?:\s*/\s*(?P<den>[0-9]{1,15})|[eE](?P<exp>[+-]?[0-9]{1,2}))?(?P<post>.*)",
    re.DOTALL,
)
_PREFIX = re.compile(
    r"(?:≈|~|ca\.?|approx\.?)?\s*[+-]?\s*(?:€|\$|£|eur|usd|gbp|chf)?\s*[+-]?", re.I
)
_CURRENCY = {"€": "eur", "euro": "eur", "$": "usd", "£": "gbp", "eur": "eur", "usd": "usd"}
_CURRENCY |= {"gbp": "gbp", "chf": "chf"}
# Words that change the magnitude or meaning and so may never be dropped.
_FIXED_UNITS = {"tsd", "tsd.", "teur", "mio", "mio.", "mrd", "mrd.", "bn", "pi", "dozen", "dutzend"}
_FIXED_UNITS |= {"hundred", "hundert", "thousand", "tausend", "million", "millionen"}
_FIXED_UNITS |= {"milliarde", "milliarden", "billion", "billionen"}
# A part outcome that matches only once the key is rounded to the answer's
# coarser precision: never a final verdict in either direction.
_ROUNDED = "rounded"
_MAX_DIGITS = 30


@dataclass(frozen=True)
class _Number:
    readings: dict[str, tuple[Fraction, int | None]]  # decimal mark -> (value, decimals)
    implied: str | None  # decimal mark this token proves, if any
    percent: bool
    currency: str
    unit: str
    text: str


@dataclass(frozen=True)
class NumericPart:
    label: str | None
    expected: str
    given: str
    correct: bool


@dataclass(frozen=True)
class NumericResult:
    """``comparable`` is False when either side is not a plain numeric answer.

    ``ambiguous`` marks an answer that matches under some reading but not
    under the decisive one (separator, rounding or percent); callers issuing
    final verdicts must treat it as neither correct nor incorrect.
    """

    comparable: bool
    correct: bool
    ambiguous: bool = False
    parts: tuple[NumericPart, ...] = ()


def _is_unit(word: str) -> bool:
    """Letters with an optional abbreviation dot and one ``/``: ``Stk.``, ``m/s``."""
    shape = re.fullmatch(r"[^\W\d_]+\.?(?:/[^\W\d_]+)?", word)
    return bool(shape) and word.replace(".", "").replace("/", "").isalpha()  # no "²"


def _value(groups: list[str], frac: str) -> tuple[Fraction, int]:
    if len(groups) > 1 and not (len(groups[0]) <= 3 and all(len(g) == 3 for g in groups[1:])):
        raise ValueError("invalid digit grouping")
    if sum(map(len, groups)) + len(frac) > _MAX_DIGITS:
        raise ValueError("not an answer-sized number")
    return Fraction(int("".join(groups) + frac), 10 ** len(frac)), len(frac)


def _readings(raw: str) -> tuple[dict[str, tuple[Fraction, int]], str | None]:
    seps, groups = re.findall(r"[.,' ]", raw), re.split(r"[.,' ]", raw)
    other = {".": ",", ",": "."}
    if seps and seps[-1] in other and seps.count(seps[-1]) == 1:
        mark, head = seps[-1], groups[0]
        if len(seps) == 1 and len(groups[1]) == 3 and len(head) <= 3 and head[0] != "0":
            # "125.000" / "1,250": decimal under one convention, grouping under the other.
            return {mark: _value(groups[:1], groups[1]), other[mark]: _value(groups, "")}, None
        if len(set(seps[:-1])) > 1:
            raise ValueError("mixed grouping")
        value = _value(groups[:-1], groups[-1])
        return {".": value, ",": value}, mark
    if len(set(seps)) > 1:
        raise ValueError("mixed separators")
    value = _value(groups, "")
    return {".": value, ",": value}, other.get(seps[0]) if seps else None


def _parse_number(text: str) -> _Number | None:
    match = _NUMBER.fullmatch(text.translate(_TEXT_FOLD).strip())
    if not match or _PREFIX.fullmatch(match["pre"].strip()) is None:
        return None
    if len(re.findall(r"[+-]", match["pre"])) > 1 or match["post"][:1].isalpha():
        return None  # "--5"; "3x" is algebra, not a unit
    post = match["post"].strip()
    percent = post.startswith("%") or post.lower().split(" ")[0] in {"prozent", "percent"}
    if percent:
        post = post[1:] if post.startswith("%") else post.partition(" ")[2]
    words = post.lower().replace("€", " € ").split()
    currency = re.search(r"[€$£]|eur|usd|gbp|chf", match["pre"], re.IGNORECASE)
    currencies = {_CURRENCY[w] for w in words if w in _CURRENCY}
    currencies |= {_CURRENCY[currency[0].lower()]} if currency else set()
    units = [w for w in words if w not in _CURRENCY]
    if len(currencies) > 1 or len(units) > 1 or not all(_is_unit(w) for w in units):
        return None  # prose such as "5 or six", or symbols such as "3²"
    try:
        readings, implied = _readings(match["num"])
    except ValueError:
        return None
    if match["den"] is not None:
        if int(match["den"]) == 0:
            return None
        readings = {k: (v / int(match["den"]), None) for k, (v, _) in readings.items()}
    if match["exp"] is not None:
        e = int(match["exp"])
        readings = {
            k: (v * Fraction(10) ** e, None if d is None else max(0, d - e))
            for k, (v, d) in readings.items()
        }
    sign = -1 if "-" in match["pre"] else 1
    scale = Fraction(1, 100) if percent else 1
    readings = {k: (sign * v * scale, d) for k, (v, d) in readings.items()}
    return _Number(readings, implied, percent, "".join(currencies), "".join(units), text.strip())


def _numeric_parts(text: str) -> list[tuple[str | None, _Number]] | None:
    """Split an answer into numeric parts, or None if any part is not numeric."""
    parts: list[tuple[str | None, _Number]] = []
    for chunk in re.split(r"[;\n]+", str(text or "")):
        labels = list(_LABEL.finditer(chunk))
        if labels and chunk[: labels[0].start()].strip():
            return None
        bodies = (
            [(None, chunk)]
            if not labels
            else [
                ((m["item"] or m["name"]).lower(), chunk[m.end() : n.start() if n else None])
                for m, n in zip(labels, [*labels[1:], None])
            ]
        )
        for label, body in bodies:
            body = body.strip().rstrip(",").strip()
            if not body and label is None:
                continue
            number = _parse_number(body)
            if number is None:
                return None
            parts.append((label, number))
    return parts or None


def _convention(numbers: list[_Number]) -> str | None:
    implied = {n.implied for n in numbers} - {None}
    return implied.pop() if len(implied) == 1 else None


def _rounds_to(value: Fraction, target: Fraction, decimals: int) -> bool:
    """Whether ``value`` rounded half away from zero to ``decimals`` places is ``target``."""
    half, diff = Fraction(1, 2 * 10**decimals), abs(value - target)
    return diff < half or (diff == half and abs(value) < abs(target))


def _shift(decimals: int | None, by: int) -> int | None:
    return None if decimals is None else max(0, decimals + by)


def _close(value: Fraction, key: Fraction, decimals: int | None, key_decimals: int | None):
    if value == key:
        return True
    # A key with two or more places accepts answers that round to it; a
    # fraction key must round to the answer's two or more places ("0,13" for 1/8).
    if key_decimals is None:
        if decimals is not None and decimals >= 2 and _rounds_to(key, value, decimals):
            return True
    elif key_decimals >= 2 and _rounds_to(value, key, key_decimals):
        return True
    # "3,48" for "3,4833": the question may ask for two decimals. A key with
    # fewer than two places ("12.5" stored from 12.50, "417") cannot settle a
    # finer answer that rounds to it.
    coarser = decimals is not None and (key_decimals is None or decimals < key_decimals)
    finer = decimals is not None and key_decimals is not None and decimals > key_decimals
    if (coarser and _rounds_to(key, value, decimals)) or (
        finer and _rounds_to(value, key, key_decimals)
    ):
        return _ROUNDED
    # "1250" for "-1250": the question may ask for the amount of a loss.
    if value and (value < 0) != (key < 0) and _close(-value, key, decimals, key_decimals):
        return _ROUNDED
    return False


def _matches(given: _Number, key: _Number, mark_given: str, mark_key: str):
    lone = given.unit or key.unit
    if (given.currency and key.currency and given.currency != key.currency) or (
        given.unit != key.unit
        and (
            (given.unit and key.unit)
            or len(lone) < 2
            or lone in _FIXED_UNITS
            or given.currency
            or key.currency
        )
    ):
        return None
    key_value, key_decimals = key.readings[mark_key]
    value, decimals = given.readings[mark_given]
    # Compare in the key's written units; a bare "12.5" answers a "12.5%" key.
    scale = 100 if key.percent else 1
    shifted = _shift(decimals, 2 * given.percent - 2 * key.percent)
    outcome = _close(value * scale, key_value * scale, shifted, key_decimals)
    if outcome is not False:
        return outcome
    if key.percent and not given.percent:
        outcome = _close(value, key_value * scale, decimals, key_decimals)
        # "0.5" for "0.5%" may also be the rate written as a fraction (50 %).
        return _ROUNDED if outcome and abs(value) < 1 else outcome
    if given.percent and not key.percent and _close(value * 100, key_value, decimals, key_decimals):
        return None  # "50%" for "50" may be right; leave it to the caller
    # "42" for "0,42" (or the reverse) may be the same rate in percent points.
    if not (given.percent or key.percent) and (
        (
            0 < abs(key_value) < 1
            and _close(value, key_value * 100, decimals, _shift(key_decimals, -2))
        )
        or (
            0 < abs(value) < 1
            and _close(value * 100, key_value, _shift(decimals, -2), key_decimals)
        )
    ):
        return _ROUNDED
    return False


def _conventions(given: list[_Number], keys: list[_Number]):
    """Decisive (given, key) decimal marks, then every other reading.

    Only the key's own notation fixes how the key is read. The answer borrows
    the key's convention, never the reverse: "12.5" must not turn a German
    "12.500 €" into 12.5.
    """
    own_given, own_key = _convention(given), _convention(keys)
    marks_given = [own_given] if own_given else [".", ","]
    marks_key = [own_key] if own_key else [".", ","]
    decisive = [(own_given or mark, mark) for mark in marks_key]
    others = [(g, k) for g in marks_given for k in marks_key if (g, k) not in decisive]
    return decisive, decisive + others


def numeric_equivalent(user_answer: str, expected_answer: str) -> NumericResult:
    """Compare numeric answers deterministically.

    - Formats: ``1250.5``, ``1250,5``, ``1.250,50``, ``1,250.50``, ``1 250,50``,
      ``1'250.50``, one sign, ``≈``/``~``/``ca.``, currencies, ``%``, ``a/b``,
      ``1e3``. Prose, ``3x`` or ``3²`` are not comparable.
    - A single ``.``/``,`` before exactly three digits (``12.500``) is read in
      the convention the key proves (``1.234,57``); without proof the answer
      must match under both readings. The answer may borrow the key's
      convention, never the reverse.
    - A key with two or more places sets the precision, rounding half away
      from zero (``3.48`` accepts ``[3.475, 3.485)``). Keys with fewer places
      are correct only when equal; a fraction key accepts its own rounding to
      the answer's two or more places (``0.13`` for ``1/8``).
    - ``12.5%`` equals ``0.125``; a bare ``12.5`` answers a ``12.5%`` key.
    - One trailing unit word may be dropped if the other side has none, except
      single letters, magnitude words (``Mio.``, ``TEUR``) or next to a currency.
    - Multi-part answers (``a) 12; b) 3,5``, ``x=3, y=4``) compare by label or
      position and are correct only if every part is.

    ``ambiguous`` is set when some other reading would match: a separator, a
    rounding the key cannot settle (``3,48`` for ``3,4833``, ``416,67`` for
    ``417``), only the sign (``1250`` for ``-1250``), or a rate in the other
    unit (``0.5`` for ``0.5%``, ``42`` for ``0,42``).
    """
    keys, given = _numeric_parts(expected_answer), _numeric_parts(user_answer)
    if keys is None or given is None:
        return NumericResult(False, False)
    if len(keys) != len(given):
        return NumericResult(True, False)
    key_labels, given_labels = [k for k, _ in keys], [g for g, _ in given]
    labelled = None not in key_labels + given_labels and len(set(key_labels)) == len(keys)
    if labelled and set(key_labels) != set(given_labels):
        return NumericResult(False, False)
    by_label = dict(given)
    pairs = [
        (label or given[i][0], by_label[label] if labelled else given[i][1], key)
        for i, (label, key) in enumerate(keys)
    ]
    decisive, options = _conventions([g for _, g, _ in pairs], [k for _, _, k in pairs])
    outcomes = []
    for mg, mk in options:
        outcome = tuple(_matches(g, k, mg, mk) for _, g, k in pairs)
        if None in outcome:
            return NumericResult(False, False)
        outcomes.append(outcome)
    part_ok = [all(o is True for o in column) for column in zip(*outcomes[: len(decisive)])]
    correct = all(part_ok)
    ambiguous = not correct and any(all(outcome) for outcome in outcomes)
    parts = tuple(
        NumericPart(label, k.text, g.text, ok) for (label, g, k), ok in zip(pairs, part_ok)
    )
    return NumericResult(True, correct, ambiguous, parts)


def classify_error(user_answer: str) -> ErrorType:
    """Coarse error classification for a wrong answer.

    A blank answer signals the student did not know (metacognitive); anything
    else is treated as a wrong application. The richer four-type taxonomy is
    assigned later by the LLM in the error-diagnosis stage.
    """
    from deeptutor.learning.models import ErrorType

    return ErrorType.METACOGNITIVE if not user_answer.strip() else ErrorType.APPLICATION_ERROR


__all__ = ["NumericPart", "NumericResult", "classify_error", "grade_answer", "numeric_equivalent"]
