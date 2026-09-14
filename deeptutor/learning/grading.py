"""Deterministic answer grading + coarse error classification for Mastery Path."""

from __future__ import annotations

from difflib import SequenceMatcher
import math
import re
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from deeptutor.learning.models import ErrorType


# ---------------------------------------------------------------------------
# Math answer normalization layer
#
# Short answers are often mathematically equivalent without being textually
# equal ("1/2" vs "0.5", "√2/2" vs "二分之√2", "x=1" vs "1", "1<x<2" vs
# "(1,2)", "y=2x+1" vs "2x+1=y"). ``_normalize_math_answer`` maps such forms
# onto one of six canonical kinds:
#
#   ("num", float)                     pure numeric value (tolerance compare)
#   ("interval", (lo, a, b, ro))       interval bounds (per-bound compare)
#   ("set", (elem, ...))               braced enumeration {a, b, c} (order-free)
#   ("solution_set", (elem, ...))      multi-solution list "±2" / "1或2" / "1,2"
#   ("interval_union", (iv, ...))      ∪-joined intervals / 或-joined inequalities
#   ("expr", str)                      canonical expression string (exact)
#
# The three collection kinds (set / solution_set / interval_union) compare
# order-free and only claim a string when the WHOLE string matches their form
# AND every element normalizes; anything unrecognizable returns None and
# ``grade_answer`` falls back to the legacy string/similarity logic, so
# existing behavior is preserved (fail-closed).
#
# TODO(判分1.5): set-builder forms ({x | x > 1}) are not claimed yet — their
# semantic equivalence with intervals (e.g. (1, +∞)) is future work.
# ---------------------------------------------------------------------------

#: Absolute tolerance for numeric equivalence.
_NUM_TOLERANCE = 1e-6

#: Full-width (U+FF01-U+FF5E) -> ASCII, plus ideographic space.
_FULLWIDTH_TRANS = {0xFF01 + i: 0x21 + i for i in range(0x5E)} | {0x3000: 0x20}

#: Unicode fraction/superscript/operator glyphs -> ASCII spellings.
_UNICODE_MATH_MAP = str.maketrans(
    {
        "½": "1/2", "⅓": "1/3", "⅔": "2/3", "¼": "1/4", "¾": "3/4",
        "⅕": "1/5", "⅖": "2/5", "⅗": "3/5", "⅘": "4/5", "⅙": "1/6",
        "⅚": "5/6", "⅛": "1/8", "⅜": "3/8", "⅝": "5/8", "⅞": "7/8",
        "⅐": "1/7", "⅑": "1/9", "⅒": "1/10",
        "¹": "^1", "²": "^2", "³": "^3",
        "×": "*", "÷": "/", "⋅": "*", "·": "*",
    }
)

#: Unit tokens stripped from numeric answers (longest first in the alternation).
_UNIT_TOKENS = [
    "千米", "公里", "厘米", "毫米", "分米", "微米", "纳米", "千克", "公斤",
    "毫克", "小时", "分钟", "毫升", "km/h", "m/s", "cm", "mm", "dm", "km",
    "mg", "ml", "min", "kg", "℃", "°c", "米", "克", "吨", "升", "秒", "毫秒",
    "元", "角", "分", "个", "只", "次", "名", "人", "岁", "天", "周", "月",
    "年", "倍", "度", "点", "t", "h", "ms", "°", "m", "g", "s", "l",
]
_UNIT_ALT = "|".join(re.escape(u) for u in sorted(_UNIT_TOKENS, key=len, reverse=True))
_UNIT_SUFFIX_RE = re.compile(r"^(.+?)\s*(" + _UNIT_ALT + r")$")

_PLAIN_NUM_RE = re.compile(r"[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?")
_NUM_FRACTION_RE = re.compile(r"^([+-]?\d+)\s*/\s*([+-]?\d+)$")
_NUM_PERCENT_RE = re.compile(r"^(" + _PLAIN_NUM_RE.pattern + r")\s*%$")
_NUM_WAN_RE = re.compile(r"^(" + _PLAIN_NUM_RE.pattern + r")\s*([万亿])$")

_CN_DIGITS = {"零": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4,
              "五": 5, "六": 6, "七": 7, "八": 8, "九": 9}

_ALGEBRA_PREFIX_RE = re.compile(
    r"^(?:[a-zA-Z]|f\s*\(\s*x\s*\)|g\s*\(\s*x\s*\)|h\s*\(\s*x\s*\))\s*=\s*(.+)$"
)
_ALGEBRA_TRAILING_RE = re.compile(r"^(.+?)\s*=\s*y$")

_CHINESE_FRACTION_RE = re.compile(r"^(.+?)分之(.+)$")

_RADICAL_PAREN_RE = re.compile(r"(?:√|根号)\s*\(([^()]*)\)")
_RADICAL_BARE_RE = re.compile(r"(√|根号|sqrt)\s*([0-9零一二三四五六七八九十百千两]+)")

_INF_TOKENS = {"∞", "+∞", "inf", "+inf", "infinity", "正无穷", "无穷大"}
_NEG_INF_TOKENS = {"-∞", "-inf", "负无穷"}

_Interval = tuple[bool, float, float, bool]
#: kind value for "num": bare float, or (value, unit) where the unit is part
#: of the comparison key — 20厘米 vs 20米 must NOT compare equal.
_NumValue = float | tuple[float, str]
#: An element inside a set / solution-set: any normalized math form. Nested
#: collections stay possible (elements go through ``_normalize_math_answer``).
_Collection = tuple[tuple[str, object], ...]
#: kind value for "interval_union": order-free tuple of interval bounds.
_IntervalUnion = tuple[_Interval, ...]
_Normalized = tuple[str, _NumValue | _Interval | str | _Collection | _IntervalUnion]


def _clean_text(text: str) -> str:
    """Lowercase, full-width -> ASCII, and normalize punctuation/space."""
    t = text.strip().lower()
    t = t.translate(_FULLWIDTH_TRANS)
    t = t.translate(_UNICODE_MATH_MAP)
    t = t.replace("，", ",").replace("；", ";").replace("（", "(").replace("）", ")")
    t = t.replace("。", ".").replace("：", ":").replace("　", " ")
    return re.sub(r"\s+", " ", t).strip()


def _chinese_numeral_to_int(text: str) -> int | None:
    """Convert a Chinese numeral (up to 万) to an int, or None when not one."""
    s = text.replace("两", "二")
    if not s or any(ch not in _CN_DIGITS and ch not in "十百千万" for ch in s):
        return None
    total, section, digit = 0, 0, 0
    for ch in s:
        if ch in _CN_DIGITS:
            digit = _CN_DIGITS[ch]
        elif ch == "十":
            section += (digit if digit else 1) * 10
            digit = 0
        elif ch == "百":
            section += (digit if digit else 1) * 100
            digit = 0
        elif ch == "千":
            section += (digit if digit else 1) * 1000
            digit = 0
        elif ch == "万":
            section += digit if digit else 1
            total += section * 10000
            section, digit = 0, 0
    return total + section + digit


def _to_arabic_int(text: str) -> int | None:
    t = text.strip()
    if re.fullmatch(r"\d+", t):
        return int(t)
    return _chinese_numeral_to_int(t)


def _to_arabic(text: str) -> str:
    n = _to_arabic_int(text)
    return str(n) if n is not None else text


def _parse_number_with_unit(text: str) -> _NumValue | None:
    """Parse a numeric token keeping its unit in the comparison key.

    ``20厘米`` → ``(20.0, "厘米")``; ``0.5`` → ``0.5``. The unit is normalized
    (lowercased, whitespace-stripped) but **kept**: two quantities only match
    when both value and unit match, so ``3kg`` vs ``3g`` stays unequal.
    Bare-unit trailing letters that look like algebra (e.g. ``4s`` where the
    expected answer is ``4t``) no longer swallow the letter — the whole token
    fails numeric parsing and falls back to the expression path.
    """
    t = text.strip()
    if not t:
        return None
    m = _UNIT_SUFFIX_RE.fullmatch(t)
    if m and m.group(1).strip():
        inner = _parse_number_bare(m.group(1).strip())
        if inner is not None:
            return (inner, m.group(2).strip().lower())
    return _parse_number_bare(t)


def _parse_number_bare(text: str) -> float | None:
    """Parse a pure numeric token: int, float, fraction, percent, 万/亿."""
    t = text.strip()
    if not t:
        return None
    m = _NUM_PERCENT_RE.fullmatch(t)
    if m:
        return float(m.group(1)) / 100.0
    m = _NUM_WAN_RE.fullmatch(t)
    if m:
        return float(m.group(1)) * (1e4 if m.group(2) == "万" else 1e8)
    m = _NUM_FRACTION_RE.fullmatch(t)
    if m:
        num, den = int(m.group(1)), int(m.group(2))
        if den == 0:
            return None
        return num / den
    if _PLAIN_NUM_RE.fullmatch(t):
        return float(t)
    arabic = _chinese_numeral_to_int(t)
    if arabic is not None:
        return float(arabic)
    return None


def _interval_bound(token: str) -> float | None:
    t = token.strip()
    if t in _INF_TOKENS:
        return math.inf
    if t in _NEG_INF_TOKENS:
        return -math.inf
    # Interval bounds are bare numbers; a unit there (rare) is left to the
    # expression path instead of silently swallowing it.
    return _parse_number_bare(t)


def _normalize_interval(text: str) -> _Interval | None:
    """Normalize interval forms to ``(left_open, a, b, right_open)``.

    Accepts bracket forms ``(1,2)`` / ``[1,2]`` (optionally prefixed by
    ``x∈``) and inequality forms ``1<x<2`` / ``1≤x≤2`` (either direction).
    """
    m = re.fullmatch(r"(?:x\s*∈\s*)?\s*([\[\(])\s*(.+?)\s*[,，]\s*(.+?)\s*([\]\)])\s*", text)
    if m:
        a, b = _interval_bound(m.group(2)), _interval_bound(m.group(3))
        if a is not None and b is not None:
            return (m.group(1) == "(", a, b, m.group(4) == ")")
        return None
    m = re.fullmatch(r"(.+?)\s*(<=|≤|<)\s*x\s*(<=|≤|<)\s*(.+)", text)
    if m:
        a, b = _interval_bound(m.group(1)), _interval_bound(m.group(4))
        if a is None or b is None:
            return None
        return (m.group(2) not in ("<=", "≤"), a, b, m.group(3) not in ("<=", "≤"))
    m = re.fullmatch(r"(.+?)\s*(>=|≥|>)\s*x\s*(>=|≥|>)\s*(.+)", text)
    if m:
        a, b = _interval_bound(m.group(4)), _interval_bound(m.group(1))
        if a is None or b is None:
            return None
        return (m.group(3) not in (">=", "≥"), a, b, m.group(2) not in (">=", "≥"))
    return None


def _normalize_interval_branch(text: str) -> _Interval | None:
    """Normalize one branch of an interval union to ``(left_open, a, b, right_open)``.

    Accepts everything ``_normalize_interval`` accepts plus single-direction
    inequalities (``x<1`` / ``x≤1`` / ``1<x`` / ``1≤x`` and the mirrored
    spellings) so inequality groups like ``x<1或x>3`` can meet bracket unions
    like ``(-∞,1)∪(3,+∞)`` on the same canonical form. Scoped to union
    branches on purpose: a bare ``x<1`` still flows through the legacy
    expression path.
    """
    interval = _normalize_interval(text)
    if interval is not None:
        return interval
    m = re.fullmatch(r"x\s*(<=|≤|<)\s*(.+)", text)
    if m:
        b = _interval_bound(m.group(2))
        if b is not None:
            return (True, -math.inf, b, m.group(1) not in ("<=", "≤"))
    m = re.fullmatch(r"(.+?)\s*(<=|≤|<)\s*x", text)
    if m:
        a = _interval_bound(m.group(1))
        if a is not None:
            return (m.group(2) not in ("<=", "≤"), a, math.inf, True)
    m = re.fullmatch(r"x\s*(>=|≥|>)\s*(.+)", text)
    if m:
        a = _interval_bound(m.group(2))
        if a is not None:
            return (m.group(1) not in (">=", "≥"), a, math.inf, True)
    m = re.fullmatch(r"(.+?)\s*(>=|≥|>)\s*x", text)
    if m:
        b = _interval_bound(m.group(1))
        if b is not None:
            return (True, -math.inf, b, m.group(2) not in (">=", "≥"))
    return None


def _normalize_interval_union(text: str) -> _IntervalUnion | None:
    """Normalize a union of intervals into a sorted, order-free tuple.

    Recognizes ``∪``-connected interval strings (``(-∞,1)∪(3,+∞)``) and
    ``或``-separated inequality groups (``x<1或x>3``). Claimed only when every
    branch is a valid interval, so a bare multi-solution list like ``1或2``
    falls through to the solution-set path instead.
    """
    if "∪" not in text and "或" not in text:
        return None
    branches = re.split(r"∪", text) if "∪" in text else re.split(r"或", text)
    intervals: list[_Interval] = []
    for branch in branches:
        interval = _normalize_interval_branch(branch.strip())
        if interval is None:
            return None
        intervals.append(interval)
    if len(intervals) < 2:
        return None
    return tuple(sorted(intervals))


def _expand_plus_minus(part: str) -> list[str]:
    """Expand a leading ``±`` prefix into the two signed copies of an element."""
    if not part.startswith("±"):
        return [part]
    rest = part[1:].strip()
    return [rest, f"-{rest}"] if rest else [part]


def _normalize_braced_set(text: str) -> _Collection | None:
    """Normalize a braced enumeration ``{a, b, c}`` into sorted normalized elements.

    Elements are separated by comma variants and each goes through the full
    ``_normalize_math_answer`` pipeline, so ``{1, 1/2}`` and ``{1, 0.5}`` meet.
    Set-builder forms (``{x | x > 1}``) are deliberately NOT claimed here —
    their equivalence with intervals is tracked as a TODO(判分1.5) — and a
    non-math element (``{apple, banana}``) rejects the whole claim so the
    string keeps flowing through the legacy path (fail-closed).
    """
    m = re.fullmatch(r"\{([^{}]*)\}", text)
    if not m:
        return None
    content = m.group(1)
    if "|" in content or "｜" in content:
        return None  # TODO(判分1.5): {x | x > 1} vs (1, +∞) semantic equivalence
    elements: list[_Normalized] = []
    for part in re.split(r"[,，、;；]+", content):
        token = part.strip()
        if not token:
            continue
        norm = _normalize_math_answer(token)
        if norm is None:
            return None
        elements.append(norm)
    return tuple(sorted(elements, key=repr))


def _normalize_solution_set(text: str) -> _Collection | None:
    """Normalize a multi-solution answer into sorted normalized elements.

    Recognizes the word separator ``或`` plus the list separators
    (``， , 、 ; ；``) and whitespace, and expands a leading ``±`` prefix into
    the two signed solutions. Every solution element goes through the existing
    ``_normalize_math_answer`` (so ``±1/2`` → {0.5, -0.5}) and the claim is
    only made with ≥ 2 solutions, keeping plain answers (``2``, ``1/2``,
    ``x^2+1``) on their single-value paths. ``/`` is deliberately NOT a
    separator: it is the fraction bar (``1/2``, ``√2/2``), and treating it as
    a solution separator would re-classify every fraction as a solution list
    (fail-closed: never claim when ambiguous).
    """
    tokens: list[str] = []
    for part in re.split(r"或", text):
        for sub in re.split(r"[,，、;；]+", part):
            for token in re.split(r"\s+", sub.strip()):
                if not token:
                    continue
                tokens.extend(_expand_plus_minus(token))
    if len(tokens) < 2:
        return None
    elements: list[_Normalized] = []
    for token in tokens:
        norm = _normalize_math_answer(token)
        if norm is None:
            return None
        elements.append(norm)
    return tuple(sorted(elements, key=repr))


def _strip_algebra_wrapper(text: str) -> str:
    """Strip a leading ``y=``/``f(x)=``/``x=`` prefix or trailing ``=y``."""
    m = _ALGEBRA_PREFIX_RE.match(text)
    if m:
        return m.group(1)
    m = _ALGEBRA_TRAILING_RE.fullmatch(text)
    if m:
        return m.group(1)
    return text


def _normalize_chinese_fraction(text: str) -> str:
    """Rewrite the Chinese verbal fraction ``a分之b`` as ``b/a``."""
    m = _CHINESE_FRACTION_RE.fullmatch(text)
    if not m:
        return text
    denominator = _to_arabic_int(m.group(1))
    if denominator is None:
        return text
    numerator = m.group(2)
    arabic = _to_arabic_int(numerator)
    if arabic is not None:
        numerator = str(arabic)
    return f"{numerator}/{denominator}"


def _normalize_radical_notation(text: str) -> str:
    """Map sqrt2/√2/根号2 (and parenthesized forms) onto ``sqrt(...)``."""
    text = _RADICAL_PAREN_RE.sub(r"sqrt(\1)", text)
    return _RADICAL_BARE_RE.sub(lambda m: f"sqrt({_to_arabic(m.group(2))})", text)


def _compact_expression(text: str) -> str:
    """Collapse whitespace in a math expression for canonical comparison."""
    return re.sub(r"\s+", "", text)


def _normalize_math_answer(text: str) -> _Normalized | None:
    """Return a canonical math form for ``text``, or None when it is not math.

    The returned tuple is ``(kind, value)`` where kind is one of ``"num"``
    (compare with tolerance), ``"interval"`` (compare per bound), ``"set"`` /
    ``"solution_set"`` (order-free element compare), ``"interval_union"``
    (order-free branch compare), or ``"expr"`` (compare exactly). Expression
    answers are only claimed when they contain a digit, so plain words keep
    flowing through the legacy string/similarity path unchanged.
    """
    t = _clean_text(text)
    if not t:
        return None

    interval = _normalize_interval(t)
    if interval is not None:
        return ("interval", interval)

    t = _strip_algebra_wrapper(t)
    if not t:
        return None

    interval = _normalize_interval(t)
    if interval is not None:
        return ("interval", interval)

    t = _normalize_chinese_fraction(t)
    t = _normalize_radical_notation(t)

    # Collection equivalence classes (判分1.5): interval unions must run
    # before the plain solution set (they share the 或 separator), and the
    # braced set must run before it too (its commas are set separators, not
    # solution separators).
    union = _normalize_interval_union(t)
    if union is not None:
        return ("interval_union", union)
    collection = _normalize_braced_set(t)
    if collection is not None:
        return ("set", collection)
    solutions = _normalize_solution_set(t)
    if solutions is not None:
        return ("solution_set", solutions)

    number = _parse_number_with_unit(t)
    if number is not None:
        return ("num", number)

    expr = _compact_expression(t)
    if not expr or not re.search(r"\d", expr):
        return None
    return ("expr", expr)


def _numbers_close(a: float, b: float) -> bool:
    if math.isinf(a) or math.isinf(b):
        return a == b
    return abs(a - b) <= _NUM_TOLERANCE


def _num_values_match(a: _NumValue, b: _NumValue) -> bool:
    """Compare numeric answers; a (value, unit) pair must match on both parts.

    ``20厘米`` vs ``20米`` → units differ → not equal. A bare number matches
    only another bare number (``5`` vs ``5米`` is a missing unit, judged
    unequal — expected answers should carry the unit they require).
    """
    if isinstance(a, tuple) or isinstance(b, tuple):
        if not (isinstance(a, tuple) and isinstance(b, tuple)):
            return False
        va, ua = a
        vb, ub = b
        return ua == ub and _numbers_close(va, vb)
    return _numbers_close(a, b)  # type: ignore[arg-type]


def _interval_matches(a: _Interval, b: _Interval) -> bool:
    """Compare two interval bounds per bound (with numeric tolerance)."""
    lo_a, a_lo, a_hi, ro_a = a
    lo_b, b_lo, b_hi, ro_b = b
    return (
        lo_a == lo_b
        and ro_a == ro_b
        and _numbers_close(a_lo, b_lo)
        and _numbers_close(a_hi, b_hi)
    )


def _math_element_matches(a: _Normalized, b: _Normalized) -> bool:
    """Kind-aware equality for one element of a set / solution-set."""
    kind_a, value_a = a
    kind_b, value_b = b
    if kind_a != kind_b:
        return False
    if kind_a == "num":
        return _num_values_match(value_a, value_b)  # type: ignore[arg-type]
    if kind_a == "interval":
        return _interval_matches(value_a, value_b)  # type: ignore[arg-type]
    return value_a == value_b


def _collection_matches(user: _Collection, expected: _Collection) -> bool:
    """Order-free element compare with greedy, no-reuse matching.

    Multiset semantics: duplicate elements are not collapsed, so ``{1,1,2}``
    vs ``{1,2}`` stays unequal (fail-closed). Numeric elements compare with
    the same tolerance as plain numbers (``{1/3}`` vs ``{0.3333333}``).
    """
    if len(user) != len(expected):
        return False
    remaining = list(expected)
    for element in user:
        matched = next(
            (
                i
                for i, candidate in enumerate(remaining)
                if _math_element_matches(element, candidate)
            ),
            None,
        )
        if matched is None:
            return False
        remaining.pop(matched)
    return True


def _interval_union_matches(user: _IntervalUnion, expected: _IntervalUnion) -> bool:
    """Order-free compare of union branches; no adjacent-branch merging."""
    if len(user) != len(expected):
        return False
    return all(
        _interval_matches(u, e) for u, e in zip(sorted(user), sorted(expected))
    )


def _math_answers_match(user_norm: _Normalized, expected_norm: _Normalized) -> bool:
    """Compare two normalized math answers of the same kind."""
    kind, user_val = user_norm
    expected_val = expected_norm[1]
    if kind == "num":
        return _num_values_match(user_val, expected_val)  # type: ignore[arg-type]
    if kind == "interval":
        return _interval_matches(user_val, expected_val)  # type: ignore[arg-type]
    if kind in ("set", "solution_set"):
        return _collection_matches(user_val, expected_val)  # type: ignore[arg-type]
    if kind == "interval_union":
        return _interval_union_matches(user_val, expected_val)  # type: ignore[arg-type]
    return user_val == expected_val


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
        user_math = _normalize_math_answer(user)
        expected_math = _normalize_math_answer(expected)
        if (
            user_math is not None
            and expected_math is not None
            and user_math[0] == expected_math[0]
        ):
            return _math_answers_match(user_math, expected_math)
        if user == expected:
            return True
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


def classify_error(user_answer: str) -> ErrorType:
    """Coarse error classification for a wrong answer.

    A blank answer signals the student did not know (metacognitive); anything
    else is treated as a wrong application. The richer four-type taxonomy is
    assigned later by the LLM in the error-diagnosis stage.
    """
    from deeptutor.learning.models import ErrorType

    return ErrorType.METACOGNITIVE if not user_answer.strip() else ErrorType.APPLICATION_ERROR


__all__ = ["grade_answer", "classify_error"]
