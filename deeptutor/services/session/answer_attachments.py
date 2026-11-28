"""Answers the learner attached to a message from an inline answer card.

The chat surface can render a small answer card under a question.  Pressing
"Attach" puts the answer on the learner's next message as an ordinary
attachment of ``type == "answer"`` (a JSON object in ``base64``).  It is not a
document: the turn reads it back and appends it to the message the model sees,
while the transcript renders it as a chip that links back to the question.
"""

from __future__ import annotations

import base64
import binascii
import json

ANSWER_ATTACHMENT_TYPE = "answer"
# A card is a short written answer, not a document.  Keep a generous bound so
# a worked solution is not truncated in normal use.
ANSWER_MAX_CHARS = 20_000


def is_answer(record: dict) -> bool:
    return str(record.get("type") or "") == ANSWER_ATTACHMENT_TYPE


def _payload(record: dict) -> dict:
    """Decode one answer record, preferring the persisted JSON mirror."""
    text = str(record.get("extracted_text") or "")
    if text:
        try:
            decoded = json.loads(text)
            if isinstance(decoded, dict):
                return decoded
        except (TypeError, ValueError):
            pass
    try:
        decoded = json.loads(
            base64.b64decode(record.get("base64") or "", validate=False).decode(
                "utf-8", errors="replace"
            )
        )
    except (binascii.Error, TypeError, ValueError):
        return {}
    return decoded if isinstance(decoded, dict) else {}


def read_answers(records: list[dict]) -> list[dict]:
    """Decode answer records in place and return their payloads in order."""
    answers: list[dict] = []
    for record in records:
        if not is_answer(record):
            continue
        payload = _payload(record)
        answer = str(payload.get("answer") or "").strip()[:ANSWER_MAX_CHARS]
        if not answer:
            continue
        question = str(payload.get("question") or "").strip()
        question_id = str(payload.get("question_id") or "").strip()
        source_message_id = payload.get("source_message_id")
        if not isinstance(source_message_id, int):
            source_message_id = None
        row = {
            "question_id": question_id,
            "question": question,
            "answer": answer,
            "source_message_id": source_message_id,
        }
        # Keep a JSON mirror for the transcript after the attachment store
        # prunes ``base64``.
        record["extracted_text"] = json.dumps(row, ensure_ascii=False)
        record["extracted_chars"] = len(answer)
        answers.append(row)
    return answers


def answer_block(answers: list[dict]) -> str:
    """The answers as the model reads them, after the learner's words."""
    if not answers:
        return ""
    lines = ["[Answers attached to the learner's message]"]
    for answer in answers:
        question_id = str(answer.get("question_id") or "").strip()
        question = str(answer.get("question") or "").strip()
        label = f"Question {question_id}" if question_id else "Question"
        if question:
            lines.append(f"{label}: {question}")
        else:
            lines.append(label)
        lines.append(f"Answer: {answer.get('answer') or ''}")
    return "\n".join(lines)


def with_answers(user_message: str, answers: list[dict]) -> str:
    block = answer_block(answers)
    return f"{user_message}\n\n{block}" if block else user_message


__all__ = [
    "ANSWER_ATTACHMENT_TYPE",
    "answer_block",
    "is_answer",
    "read_answers",
    "with_answers",
]
