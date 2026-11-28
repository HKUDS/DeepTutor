"""Inline answer cards travel as ordinary message attachments."""

import base64
import json

from deeptutor.services.session.answer_attachments import (
    answer_block,
    read_answers,
    with_answers,
)


def _record(payload: dict) -> dict:
    return {
        "type": "answer",
        "filename": "answer-q1.json",
        "mime_type": "application/json",
        "base64": base64.b64encode(json.dumps(payload).encode()).decode(),
    }


def test_read_answers_decodes_the_card_and_keeps_a_json_mirror() -> None:
    record = _record(
        {
            "question_id": "q1",
            "question": "Why is the sky blue?",
            "answer": "Rayleigh scattering.",
            "source_message_id": 42,
        }
    )

    answers = read_answers([record])

    assert answers == [
        {
            "question_id": "q1",
            "question": "Why is the sky blue?",
            "answer": "Rayleigh scattering.",
            "source_message_id": 42,
        }
    ]
    assert json.loads(record["extracted_text"])["answer"] == "Rayleigh scattering."
    assert record["extracted_chars"] == len("Rayleigh scattering.")


def test_read_answers_ignores_other_attachments_and_empty_answers() -> None:
    empty = _record({"question_id": "q2", "answer": "   "})
    quote = {"type": "quote", "base64": "not-an-answer"}

    assert read_answers([empty, quote]) == []


def test_answer_block_keeps_the_question_with_its_answer() -> None:
    answers = [
        {"question_id": "q1", "question": "What is pH?", "answer": "12.26"},
        {"question_id": "q2", "question": "", "answer": "Because it is buffered."},
    ]

    block = answer_block(answers)

    assert "Question q1: What is pH?" in block
    assert "Answer: 12.26" in block
    assert "Question q2" in block
    assert with_answers("Here are my answers.", answers).startswith(
        "Here are my answers.\n\n[Answers attached"
    )
