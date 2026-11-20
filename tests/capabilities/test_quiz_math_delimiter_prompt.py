"""Every question payload path must tell the model to delimit maths with ``$``.

HKUDS/DeepTutor#2805: stems and options printed raw subscript source
(``f_0``, ``B_{0.707}``, ``R'_L``) because the model emitted bare LaTeX with
no ``$`` delimiters and no backslash command — a shape every renderer
predicate treats as plain text. The runtime policy already required dollar
delimiters, but the payload schemas the model actually fills in only said
"math in LaTeX", which a lone ``f_0`` satisfies. These tests pin the
delimiter rule into each payload surface: the quiz pipeline FINISH schema
(zh/en), the ``mastery_quiz`` tool descriptions (single call and the
``questions`` group, which reuses the same leaf schemas), and the mastery
loop policy paragraph.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from deeptutor.capabilities.mastery.tools import MasteryQuizTool

_ROOT = Path(__file__).resolve().parents[2]
_QUESTION_PROMPTS = _ROOT / "deeptutor" / "agents" / "question" / "prompts"
_MASTERY_PROMPTS = _ROOT / "deeptutor" / "capabilities" / "mastery" / "prompts"


def _load(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8"))


@pytest.mark.parametrize("lang", ["zh", "en"])
def test_finish_schema_requires_dollar_delimiters_for_every_formula(lang: str) -> None:
    system = _load(_QUESTION_PROMPTS / lang / "pipeline.yaml")["quiz_step"]["system"]
    # Assert on the rendered prompt the model actually sees: literal braces
    # are doubled in the template for str.format.
    rendered = system.format(
        question_number=1,
        total_questions=3,
        kb_note="",
        tool_list="",
    )
    assert "$...$" in rendered
    # A lone subscripted variable counts as a formula — the exact shapes
    # from the report must be named so the rule cannot be read as
    # applying only to backslash commands.
    assert "B_{0.707}" in rendered
    assert "R'_L" in rendered
    # The rule must cover every learner-facing payload field, not just the
    # question stem: one rule line naming the delimiter and all fields.
    rule_lines = [
        line
        for line in rendered.splitlines()
        if "$...$" in line
        and all(field in line for field in ("question", "options", "correct_answer", "explanation"))
    ]
    assert rule_lines, "no single schema rule requires $...$ across all payload fields"


@pytest.mark.parametrize("lang", ["zh", "en"])
def test_finish_schema_still_formats_with_the_runtime_kwargs(lang: str) -> None:
    system = _load(_QUESTION_PROMPTS / lang / "pipeline.yaml")["quiz_step"]["system"]
    rendered = system.format(
        question_number=1,
        total_questions=3,
        kb_note="",
        tool_list="",
    )
    # Literal braces in the template must be doubled for str.format; the
    # rendered prompt the model sees carries the single-brace shapes.
    assert "B_{0.707}" in rendered
    assert "{{" not in rendered


def _quiz_schema() -> dict:
    definition = MasteryQuizTool().get_definition()
    return definition.to_openai_schema()["function"]["parameters"]["properties"]


def test_mastery_quiz_question_description_requires_dollar_delimiters() -> None:
    description = _quiz_schema()["question"]["description"]
    assert "$" in description
    assert "B_{0.707}" in description


def test_mastery_quiz_option_body_description_requires_dollar_delimiters() -> None:
    body = _quiz_schema()["options"]["items"]["properties"]["body"]
    assert "$" in body["description"]
    assert "B_{0.707}" in body["description"]


def test_questions_group_inherits_the_delimiter_rule() -> None:
    leaf = _quiz_schema()["questions"]["items"]["properties"]
    assert "$" in leaf["question"]["description"]
    assert "$" in leaf["options"]["items"]["properties"]["body"]["description"]


@pytest.mark.parametrize("lang", ["zh", "en"])
def test_mastery_loop_policy_names_bare_subscripts_as_a_failure_mode(lang: str) -> None:
    general = _load(_MASTERY_PROMPTS / lang / "mastery_loop.yaml")["runtime_policy"]
    assert "$...$" in general
    # The policy used to frame bare writing as a backslash-command problem
    # only — exactly the half the renderer already handles. Bare
    # subscripts must be named too.
    assert "f_0" in general
    assert "B_{0.707}" in general
