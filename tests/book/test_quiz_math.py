"""Quiz math must reach the reader as rendered KaTeX, never raw source.

Two writer mistakes used to print as LaTeX source: a formula with no
``$...$`` delimiters, and a fill-in-the-blank marker made of underscores
*fenced inside* the formula. The second is a hard KaTeX parse error
("Expected group after '_'"), which rehype-katex degrades to a visible
``katex-error`` span rather than rendering.
"""

from __future__ import annotations

import pytest

from deeptutor.book.blocks.quiz import QuizGenerator
from deeptutor.core.assessment import (
    normalize_math_delimiters,
    normalize_quiz_payload,
    validate_quiz_payload,
)

BARE_FTC = r"\frac{d}{dx}\int_a^x f(t)\,dt"
BLANK_FTC = r"$$\frac{d}{dx}\int_a^x f(t)\,dt = \;____$$"


def test_bare_frac_and_integral_are_wrapped() -> None:
    assert normalize_math_delimiters(BARE_FTC) == f"${BARE_FTC}$"


def test_bare_greek_and_scripts_are_wrapped() -> None:
    assert (
        normalize_math_delimiters(r"The value \alpha is large here.")
        == r"The value $\alpha$ is large here."
    )
    assert normalize_math_delimiters(r"x^{2} + y^{2} = 1") == r"$x^{2} + y^{2} = 1$"


def test_already_delimited_math_is_untouched() -> None:
    for text in (
        r"Because $f$ is continuous, $\int_a^b f(x)\,dx = F(b)-F(a)$ holds.",
        r"$$\frac{a}{b}$$",
        r"\(\frac{a}{b}\)",
        r"\[\int_0^1 x\,dx\]",
    ):
        assert normalize_math_delimiters(text) == text


def test_mixed_prose_and_math_wraps_only_the_formula() -> None:
    assert (
        normalize_math_delimiters(r"Evaluate \frac{x}{2} + \sqrt{y} at x=1.")
        == r"Evaluate $\frac{x}{2} + \sqrt{y}$ at x=1."
    )


def test_fill_in_blank_inside_math_becomes_a_katex_safe_blank() -> None:
    normalized = normalize_math_delimiters(BLANK_FTC)
    assert "____" not in normalized
    assert r"\underline{\hspace{2em}}" in normalized
    assert normalized.startswith("$$") and normalized.endswith("$$")


def test_blank_in_bare_math_is_sanitized_after_wrapping() -> None:
    normalized = normalize_math_delimiters(
        r"\frac{d}{dx}\int_a^x f(t)\,dt = \;____"
    )
    assert normalized == (
        r"$\frac{d}{dx}\int_a^x f(t)\,dt = \;\underline{\hspace{2em}}$"
    )


def test_loose_dollar_pair_is_tightened_without_double_wrapping() -> None:
    assert (
        normalize_math_delimiters(r"Let $a_n = \frac{1}{n}$, so $ \lim a_n = $ ____.")
        == r"Let $a_n = \frac{1}{n}$, so $\lim a_n =$ ____."
    )


def test_currency_and_plain_prose_are_not_mangled() -> None:
    for text in (
        r"价格 $100 起，另加 $20 运费和 $5 税。",
        r"It costs $5 and the value of $x$ is 2.",
        r"Put the file in C:\Users\frank\Desktop and match \d+.",
        "This is plain prose.",
        "The derivative is f'(a) = lim_{h -> 0} [f(a + h) - f(a)] / h.",
    ):
        assert normalize_math_delimiters(text) == text


def test_code_spans_and_fences_are_left_alone() -> None:
    assert (
        normalize_math_delimiters(r"`\frac{a}{b}` is a code span")
        == r"`\frac{a}{b}` is a code span"
    )
    fenced = "```tex\n\\frac{a}{b}\n```"
    assert normalize_math_delimiters(fenced) == fenced


def test_normalization_is_idempotent() -> None:
    for text in (
        BARE_FTC,
        BLANK_FTC,
        r"Evaluate \frac{x}{2} at x=1.",
        r"Let $a_n = \frac{1}{n}$, so $ \lim a_n = $ ____.",
        r"\begin{aligned} a &= b \\ c &= d \end{aligned}",
        r"价格 $100 起，另加 $20 运费。",
    ):
        once = normalize_math_delimiters(text)
        assert normalize_math_delimiters(once) == once, text


def test_normalize_quiz_payload_covers_every_rendered_field() -> None:
    payload = {
        "questions": [
            {
                "question": BARE_FTC,
                "options": {"A": r"\frac{a}{b}", "B": "plain"},
                "correct_answer": r"\sqrt{x}",
                "explanation": BLANK_FTC,
            }
        ]
    }
    normalized = normalize_quiz_payload(payload)
    question = normalized["questions"][0]
    assert question["question"] == f"${BARE_FTC}$"
    assert question["options"]["A"] == r"$\frac{a}{b}$"
    assert question["correct_answer"] == r"$\sqrt{x}$"
    assert "____" not in question["explanation"]
    # The input is not mutated in place.
    assert payload["questions"][0]["question"] == BARE_FTC


# ---------------------------------------------------------------------------
# verification hook
# ---------------------------------------------------------------------------


def test_validator_flags_bare_latex() -> None:
    issues = validate_quiz_payload(
        {"questions": [{"question": BARE_FTC, "options": {}, "explanation": ""}]}
    )
    assert len(issues) == 1
    assert issues[0].startswith("questions[0].question")


def test_validator_flags_an_unsafe_in_math_blank() -> None:
    issues = validate_quiz_payload(
        {"questions": [{"question": BLANK_FTC, "options": {}, "explanation": ""}]}
    )
    assert issues and "unsafe" in issues[0]


def test_validator_flags_bare_latex_in_options_and_answers() -> None:
    issues = validate_quiz_payload(
        {
            "questions": [
                {
                    "question": "Pick one.",
                    "options": {"A": r"\frac{a}{b}", "B": "$x$"},
                    "correct_answer": r"\sqrt{x}",
                    "explanation": "plain",
                }
            ]
        }
    )
    joined = "\n".join(issues)
    assert "options['A']" in joined
    assert "correct_answer" in joined
    assert "options['B']" not in joined


def test_validator_accepts_plain_text_limit_notation() -> None:
    """`lim_{h -> 0}` in a written answer is prose notation, not bare LaTeX."""
    payload = {
        "questions": [
            {
                "question": "Explain the derivative.",
                "options": {},
                "correct_answer": (
                    "The derivative is f'(a) = lim_{h -> 0} "
                    "[f(a + h) - f(a)] / h."
                ),
                "explanation": "",
            }
        ]
    }
    assert validate_quiz_payload(payload) == []


def test_validator_is_clean_after_normalization() -> None:
    payload = {
        "questions": [
            {
                "question": BARE_FTC,
                "options": {"A": r"\frac{a}{b}"},
                "correct_answer": r"\sqrt{x}",
                "explanation": BLANK_FTC,
            }
        ]
    }
    assert validate_quiz_payload(normalize_quiz_payload(payload)) == []


def test_extraction_normalizes_generated_quiz_text() -> None:
    summary = {
        "results": [
            {
                "success": True,
                "qa_pair": {
                    "question_id": "q1",
                    "question": BARE_FTC,
                    "options": {"A": r"\frac{a}{b}"},
                    "correct_answer": r"\sqrt{x}",
                    "explanation": BLANK_FTC,
                },
            }
        ]
    }
    [question] = QuizGenerator._extract_questions(summary)
    assert question["question"] == f"${BARE_FTC}$"
    assert question["options"]["A"] == r"$\frac{a}{b}$"
    assert question["correct_answer"] == r"$\sqrt{x}$"
    assert "____" not in question["explanation"]
    assert validate_quiz_payload({"questions": [question]}) == []


@pytest.mark.parametrize("blank_count", [2, 4, 8])
def test_any_underscore_run_is_replaced(blank_count: int) -> None:
    blank = "_" * blank_count
    normalized = normalize_math_delimiters(rf"$$x = {blank}$$")
    assert blank not in normalized
    assert r"\underline{\hspace{2em}}" in normalized