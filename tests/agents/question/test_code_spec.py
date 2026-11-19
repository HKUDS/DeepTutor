"""Coding questions carry an optional, sanitised ``code`` block."""

from __future__ import annotations

from deeptutor.agents.question.pipeline import _normalize_code_spec


def test_normalizes_language_and_public_tests() -> None:
    spec = _normalize_code_spec(
        {
            "language": "C++",
            "starter_code": "int main() { /* TODO */ }",
            "tests": [
                {"name": " sample ", "stdin": "1\n", "expected_stdout": "1\n"},
                "not a test",
                {"name": "missing expected"},
            ],
        }
    )

    assert spec is not None
    assert spec["language"] == "cpp"
    assert spec["starter_code"].startswith("int main")
    assert spec["tests"] == [{"name": " sample ", "stdin": "1\n", "expected_stdout": "1\n"}]


def test_rejects_unknown_language_and_non_dict() -> None:
    assert _normalize_code_spec(None) is None
    assert _normalize_code_spec({"language": "ruby"}) is None


def test_caps_tests_and_drops_missing_expected_output() -> None:
    spec = _normalize_code_spec(
        {
            "language": "python",
            "tests": [{"expected_stdout": str(index)} for index in range(20)],
        }
    )

    assert spec is not None
    assert len(spec["tests"]) == 10
    assert spec["tests"][0]["expected_stdout"] == "0"


def test_starter_code_must_not_contain_reference_implementation() -> None:
    reference = "def solve(values):\n    return sum(values)\n"
    spec = _normalize_code_spec(
        {
            "language": "python",
            "starter_code": "def solve(values):\n    return sum(values)\n",
        },
        correct_answer=reference,
    )

    assert spec is not None
    assert spec["starter_code"] == ""


def test_emitted_qa_pair_includes_code_spec() -> None:
    from deeptutor.agents.question.pipeline import QuestionPipeline, QuizPair

    spec = {
        "language": "python",
        "starter_code": "print('TODO')",
        "stdin": "",
        "tests": [],
    }
    payload = QuestionPipeline._qa_pair_to_dict(
        QuizPair(
            question_id="q_1",
            question="Print something.",
            question_type="coding",
            correct_answer="print(1)",
            explanation="One line.",
            code=spec,
        )
    )

    assert payload["code"] == spec
