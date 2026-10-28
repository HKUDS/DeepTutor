"""QTI exchange must stay workspace-scoped, version-aware, and fail closed."""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from deeptutor.services.practice.qti_exchange import QtiExchange
from deeptutor.services.practice.storage import PracticeStore
from deeptutor.services.question_content import normalize_question_document
from deeptutor.services.question_content.exchange import build_package, load_package
from deeptutor.services.session.sqlite_store import SQLiteSessionStore

pytestmark = pytest.mark.asyncio


def _bank_question(**changes) -> dict:
    payload = {
        "question_id": "q1",
        "question": "2 + 2 = ?",
        "question_type": "single_choice",
        "options": {"A": "3", "B": "4"},
        "correct_answer": "B",
        "explanation": "2 + 2 = 4",
    }
    payload.update(changes)
    return normalize_question_document(payload, source_format="bank-v1")


def _kitchen_sink() -> list[dict]:
    return [
        _bank_question(),
        _bank_question(
            question_id="q2",
            question="The Earth orbits the Sun",
            question_type="true_false",
            options={},
            correct_answer="true",
        ),
        _bank_question(
            question_id="q3",
            question="The capital is {{blank:b1}}.",
            question_type="fill_blank",
            options={},
            correct_answer="Paris",
            fill_spec={
                "version": 2,
                "policy_version": "fill-grading/v2",
                "blanks": [
                    {
                        "id": "b1",
                        "label": "capital",
                        "max_score": "1.00000",
                        "accepted_answers": [{"value": "Paris", "score": "1.00000"}],
                        "comparison_policy": "qti_literal_v1",
                        "rubric": "",
                    }
                ],
            },
        ),
        _bank_question(
            question_id="q4",
            question="Explain the water cycle",
            question_type="written",
            options={},
            correct_answer="Evaporation and condensation.",
        ),
    ]


@pytest.fixture
def exchange(tmp_path: Path) -> QtiExchange:
    store = SQLiteSessionStore(tmp_path / "practice.db")
    return QtiExchange(PracticeStore(store.db_path))


async def _package(documents: list[dict], version: str = "3.0") -> bytes:
    built = await asyncio.to_thread(
        build_package,
        [{"document": document} for document in documents],
        asset_bytes={},
        version=version,
    )
    assert built["packageValidation"] == "valid", built["diagnostics"]
    return built["zip"]


async def test_qti3_roundtrip_and_selected_commit(exchange: QtiExchange):
    data = await _package(_kitchen_sink())
    preview = await exchange.preview(data, "bank.zip")

    assert preview["version"] == "3.0"
    assert preview["packageValidation"] == "valid"
    assert preview["counts"]["ready"] == 4
    assert [row["itemKey"] for row in preview["items"]] == [
        "item_1",
        "item_2",
        "item_3",
        "item_4",
    ]

    commit = await exchange.commit(preview["token"], ["item_1", "item_3"])
    assert commit == {"created": 2, "duplicates": 0, "total": 2}

    # The report survives the commit so the UI can still explain the import.
    stored_report = await exchange.report(preview["token"])
    assert stored_report["counts"]["ready"] == 4
    assert stored_report["commitResult"] == commit

    entries = exchange.store.entries_by_id([1, 2])
    assert [entry["question_type"] for entry in entries] == ["single_choice", "fill_blank"]
    assert entries[1]["correct_answer"] == "Paris"
    assert entries[1]["fill_spec"]["blanks"][0]["id"] == "b1"
    assert entries[0]["question_content"]["author"]["correctAnswer"] == "B"

    exported, media, filename = await exchange.export([1, 2])
    assert media == "application/zip"
    assert filename.startswith("qti30-")
    reloaded = await asyncio.to_thread(
        load_package, exported, filename="export.zip", trusted_export=True
    )
    assert reloaded["packageValidation"] == "valid"
    assert [item["document"]["questionType"] for item in reloaded["items"]] == [
        "single_choice",
        "fill_blank",
    ]


async def test_commit_is_idempotent(exchange: QtiExchange):
    preview = await exchange.preview(await _package([_bank_question()]), "one.zip")
    first = await exchange.commit(preview["token"], ["item_1"])
    second = await exchange.commit(preview["token"], ["item_1"])

    assert first == {"created": 1, "duplicates": 0, "total": 1}
    assert second == first
    assert len(exchange.store.entries_by_id([1])) == 1


@pytest.mark.parametrize("version", ["2.1", "2.2"])
async def test_qti2_dialects_are_imported(exchange: QtiExchange, version: str):
    preview = await exchange.preview(await _package(_kitchen_sink(), version), "bank.zip")

    assert preview["version"] == version
    assert preview["packageValidation"] == "valid"
    assert preview["counts"]["ready"] == 4
    commit = await exchange.commit(preview["token"], [row["itemKey"] for row in preview["items"]])
    assert commit["created"] == 4


async def test_chat_quiz_rows_export_and_coding_is_blocked(exchange: QtiExchange):
    store = SQLiteSessionStore(exchange.store.db_path)
    await store.ensure_notebook_session("s1", "Session")
    await store.upsert_notebook_entries(
        "s1",
        [
            {
                "question_id": "q_1",
                "turn_id": "t1",
                "source": "deep_question",
                "question_type": "choice",
                "question": "Pick two",
                "options": {"A": "1", "B": "2", "C": "3", "D": "4"},
                "correct_answer": "B",
            },
            {
                "question_id": "q_2",
                "turn_id": "t1",
                "source": "deep_question",
                "question_type": "concept",
                "question": "The sky is blue",
                "options": {},
                "correct_answer": "true",
            },
            {
                "question_id": "q_3",
                "turn_id": "t1",
                "source": "deep_question",
                "question_type": "fill_in_blank",
                "question": "The capital is ____",
                "options": {},
                "correct_answer": "Paris",
            },
            {
                "question_id": "q_4",
                "turn_id": "t1",
                "source": "deep_question",
                "question_type": "coding",
                "question": "Write code",
                "options": {},
                "correct_answer": "print(1)",
            },
        ],
    )

    # Chat blanks keep the learner-facing token in the flat column; the
    # canonical document carries an addressable marker for QTI.
    fill = exchange.store.entries_by_id([3])[0]
    assert fill["question"] == "The capital is ____"
    assert fill["question_content"]["body"][0]["text"] == "The capital is {{blank:blank-1}}"

    exported, _, _ = await exchange.export([1, 2, 3])
    reloaded = await asyncio.to_thread(
        load_package, exported, filename="chat.zip", trusted_export=True
    )
    assert [item["document"]["questionType"] for item in reloaded["items"]] == [
        "single_choice",
        "true_false",
        "fill_blank",
    ]

    with pytest.raises(ValueError) as excinfo:
        await exchange.export([4])
    assert "coding" in str(excinfo.value).lower() or "unsupported" in str(excinfo.value).lower()


async def test_unsafe_xml_is_rejected(exchange: QtiExchange):
    payload = b"""<?xml version="1.0"?>
    <!DOCTYPE foo [<!ENTITY xxe SYSTEM "file:///etc/passwd">]>
    <qti-assessment-item xmlns="http://www.imsglobal.org/xsd/imsqtiasi_v3p0"/>
    """
    preview = await exchange.preview(payload, "unsafe.xml")

    assert preview["packageValidation"] == "invalid"
    assert preview["counts"]["discovered"] in (None, 0)
    assert any(row["severity"] == "error" for row in preview["diagnostics"])


async def test_export_requires_existing_rows(exchange: QtiExchange):
    with pytest.raises(LookupError):
        await exchange.export([99])


async def test_export_respects_session_visibility_and_workspace(
    exchange: QtiExchange, tmp_path: Path
):
    store = SQLiteSessionStore(exchange.store.db_path)
    await store.ensure_notebook_session("visible", "Visible")
    await store.ensure_notebook_session("hidden", "Hidden")
    for session_id in ("visible", "hidden"):
        await store.upsert_notebook_entries(
            session_id,
            [
                {
                    "question_id": session_id,
                    "turn_id": "t1",
                    "source": "deep_question",
                    "question_type": "choice",
                    "question": session_id,
                    "options": {"A": "yes", "B": "no"},
                    "correct_answer": "A",
                }
            ],
        )
    preview = await exchange.preview(await _package([_bank_question()]), "import.zip")
    await exchange.commit(preview["token"], ["item_1"])
    with exchange.store.connect() as conn:
        conn.execute("UPDATE sessions SET deleted_at=1 WHERE id='hidden'")
        rows = conn.execute("SELECT id, session_id FROM notebook_entries").fetchall()
    ids = {row["session_id"]: row["id"] for row in rows}
    visible, hidden, imported = ids["visible"], ids["hidden"], ids[None]

    other_store = SQLiteSessionStore(tmp_path / "other-workspace.db")
    other_exchange = QtiExchange(PracticeStore(other_store.db_path))
    other_preview = await other_exchange.preview(await _package(_kitchen_sink()), "other.zip")
    await other_exchange.commit(other_preview["token"], ["item_1", "item_2", "item_3", "item_4"])
    other_only = 4

    assert [row["id"] for row in exchange.store.entries_by_id([imported, hidden, visible, 99])] == [
        imported,
        visible,
    ]
    assert exchange.store.entries_by_id([]) == []
    assert exchange.store.is_visible(imported)
    assert not exchange.store.is_visible(hidden)
    await exchange.export([visible, imported])
    for selection in ([hidden], [visible, hidden], [visible, 99], [visible, other_only]):
        with pytest.raises(LookupError):
            await exchange.export(selection)
    await other_exchange.export([other_only])


async def test_external_fill_policy_can_be_explicitly_imported_for_self_assessment(exchange):
    document = _bank_question(
        question_id="comparison",
        question="3.3 × 0.4 {{blank:blank-1}} 4.4 × 0.3",
        question_type="fill_blank",
        options={},
        correct_answer="=",
    )
    document["author"]["fillSpec"]["blanks"][0]["comparison_policy"] = "comparison_v1"
    preview = await exchange.preview(await _package([document]), "comparison.zip")
    item = preview["items"][0]
    assert item["bankAdmission"] == "review"
    assert item["importable"] is True
    assert item["correctAnswer"] == "="
    assert "{{blank:blank-1}}" in item["question"]
    result = await exchange.commit(preview["token"], [item["itemKey"]])
    assert result["created"] == 1
    entry = exchange.store.entries_by_id([1])[0]
    assert entry["result"] == "ungraded"
    assert entry["correct_answer"] == "="
    assert entry["fill_spec"]["blanks"][0]["comparison_policy"] == "qti_literal_v1"
    from deeptutor.services.practice.answers import check_answer

    assert check_answer(entry, "=") is None
