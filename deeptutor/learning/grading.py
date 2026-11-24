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
_EPS = Fraction(1, 10**9)


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

    ``ambiguous`` marks an answer that is correct under one separator reading
    but not under the preferred one; callers issuing final verdicts must not
    treat it as incorrect.
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


def _tolerance(value: Fraction, decimals: int | None, rel_tol, abs_tol) -> Fraction:
    if rel_tol is not None or abs_tol is not None:
        explicit = max(Fraction(str(abs_tol or 0)), Fraction(str(rel_tol or 0)) * abs(value))
        return explicit + _EPS
    # The key's own precision: "3.48" covers [3.475, 3.485]; integers are exact.
    return (Fraction(1, 2 * 10**decimals) if decimals else 0) + _EPS


def _matches(given: _Number, key: _Number, mark_given: str, mark_key: str, rel_tol, abs_tol):
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
    key_value, decimals = key.readings[mark_key]
    value, given_decimals = given.readings[mark_given]
    if decimals is None and (given_decimals or 0) >= 2:
        # "0.33" (or "33.33%") rounds "1/3" correctly.
        decimals = given_decimals + (2 if given.percent else 0)
    # Compare in the key's written units; a bare "12.5" answers a "12.5%" key.
    scale = 100 if key.percent else 1
    tol = _tolerance(key_value * scale, decimals, rel_tol, abs_tol)
    if abs(value * scale - key_value * scale) <= tol:
        return True
    if key.percent and not given.percent:
        return abs(value - key_value * scale) <= tol
    if given.percent and not key.percent and abs(value * 100 - key_value) <= tol:
        return None  # "50%" for "50" may be right; leave it to the caller
    return False


def _conventions(given: list[_Number], keys: list[_Number]):
    """Preferred (given, key) decimal marks first, then the other readings."""
    own_given, own_key = _convention(given), _convention(keys)
    if not (own_given or own_key):
        # Same-convention readings decide; cross readings can only make it ambiguous.
        return None, [(".", "."), (",", ","), (".", ","), (",", ".")]
    preferred = (own_given or own_key, own_key or own_given)
    marks_given = [own_given] if own_given else [".", ","]
    marks_key = [own_key] if own_key else [".", ","]
    others = [(g, k) for g in marks_given for k in marks_key if (g, k) != preferred]
    return preferred, [preferred, *others]


def numeric_equivalent(
    user_answer: str,
    expected_answer: str,
    *,
    rel_tol: float | None = None,
    abs_tol: float | None = None,
) -> NumericResult:
    """Compare numeric answers deterministically.

    Accepted formats: ``1250.5``, ``1250,5``, ``1.250,50``, ``1,250.50``,
    ``1 250,50``, ``1'250.50``, one leading sign (incl. U+2212), ``≈``/``~``/
    ``ca.``, currencies (€, EUR, $, USD, £, GBP, CHF), ``%``, fractions
    ``a/b`` and ``1e3`` (exponent up to two digits). ``12.5%`` equals
    ``0.125`` in both directions, and a bare ``12.5`` answers a ``12.5%`` key;
    ``50%`` for a bare ``50`` is left undecided (not comparable). At most one
    trailing unit word is allowed; it must match the key's unit unless one
    side has none, and single letters, magnitude words (``x``, ``Mio.``,
    ``Tausend``) or a unit next to a currency must always match. Prose, attached letters (``3x``) or symbols (``3²``) make
    the answer non-numeric so callers keep their existing behaviour.

    Separator rule: one ``.`` or ``,`` followed by exactly three digits
    (``125.000``, ``1,250``) is ambiguous. Its preferred reading uses the
    convention the same side proves elsewhere (``1.234,57`` proves a decimal
    comma), otherwise the other side's. A match under the preferred reading
    is correct. Without any proof, both sides are read with the same
    convention and must match under both. Any other case where some reading
    matches is not correct but ``ambiguous`` (``125000`` vs ``125.000``,
    ``12.500`` vs ``12,500``).

    Tolerance is half a unit of the key's last written decimal (``3.48``
    accepts ``|x - 3.48| <= 0.005``). Integer keys are exact; fraction keys
    accept a decimal with at least two places that rounds to them.
    ``rel_tol``/``abs_tol`` replace that rule.

    Multi-part answers (``a) 12; b) 3,5``, ``x=3, y=4``, ``;``/newline lists)
    are compared by label when both sides are fully labelled, otherwise by
    position. They are correct only if the part counts match and every part
    matches.
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
    preferred, options = _conventions([g for _, g, _ in pairs], [k for _, _, k in pairs])
    outcomes = []
    for mg, mk in options:
        outcome = tuple(_matches(g, k, mg, mk, rel_tol, abs_tol) for _, g, k in pairs)
        if None in outcome:
            return NumericResult(False, False)
        outcomes.append(outcome)
    decisive = outcomes[:1] if preferred else outcomes[:2]
    correct = all(map(all, decisive))
    ambiguous = not correct and any(map(all, outcomes))
    part_ok = [all(column) for column in zip(*decisive)]
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
