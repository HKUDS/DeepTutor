"""Tests for the retrieval-evaluation QA-set schema."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from deeptutor.services.rag.eval import EvalCase, EvalDataset, EvalDatasetError, load_dataset


def _write_jsonl(path: Path, rows: list[dict]) -> Path:
    path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")
    return path


def test_load_jsonl_assigns_default_ids_in_file_order(tmp_path: Path) -> None:
    path = _write_jsonl(
        tmp_path / "physics.jsonl",
        [
            {"query": "What is inertia?", "gold": "Inertia resists a change in motion."},
            {"query": "What is momentum?", "gold": ["Momentum is mass times velocity."]},
        ],
    )

    dataset = load_dataset(path)

    assert dataset.name == "physics"
    assert dataset.source == str(path)
    assert [case.id for case in dataset.cases] == ["q1", "q2"]
    assert dataset.cases[0].gold == ["Inertia resists a change in motion."]
    assert len(dataset) == 2
    assert [case.query for case in dataset.iter_cases()] == [
        "What is inertia?",
        "What is momentum?",
    ]


def test_explicit_id_and_notes_survive_a_round_trip(tmp_path: Path) -> None:
    path = _write_jsonl(
        tmp_path / "set.jsonl",
        [
            {
                "id": "attention-1",
                "query": "Why scale attention?",
                "gold": ["Dot products grow."],
                "notes": "ch.3",
            }
        ],
    )

    case = load_dataset(path).cases[0]

    assert case.id == "attention-1"
    assert case.notes == "ch.3"


def test_query_and_gold_are_trimmed(tmp_path: Path) -> None:
    path = _write_jsonl(
        tmp_path / "set.jsonl",
        [{"query": "  spaced query  ", "gold": ["  padded passage  "]}],
    )

    case = load_dataset(path).cases[0]

    assert case.query == "spaced query"
    assert case.gold == ["padded passage"]


def test_blank_query_is_rejected_with_case_context(tmp_path: Path) -> None:
    path = _write_jsonl(
        tmp_path / "set.jsonl",
        [{"query": "ok", "gold": ["passage"]}, {"query": "   ", "gold": ["passage"]}],
    )

    with pytest.raises(EvalDatasetError) as excinfo:
        load_dataset(path)

    message = str(excinfo.value)
    assert "case #2" in message
    assert "query must be a non-empty string" in message


def test_blank_gold_passage_is_rejected(tmp_path: Path) -> None:
    path = _write_jsonl(tmp_path / "set.jsonl", [{"query": "q", "gold": ["  "]}])

    with pytest.raises(EvalDatasetError) as excinfo:
        load_dataset(path)

    assert "gold must hold at least one non-empty passage" in str(excinfo.value)


def test_unknown_case_field_is_rejected(tmp_path: Path) -> None:
    path = _write_jsonl(
        tmp_path / "set.jsonl",
        [{"query": "q", "gold": ["passage"], "ansr": "typo"}],
    )

    with pytest.raises(EvalDatasetError) as excinfo:
        load_dataset(path)

    assert "case #1" in str(excinfo.value)


def test_non_object_line_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "set.jsonl"
    path.write_text('["not an object"]\n', encoding="utf-8")

    with pytest.raises(EvalDatasetError) as excinfo:
        load_dataset(path)

    assert "must be a JSON object" in str(excinfo.value)


def test_invalid_json_reports_the_line_number(tmp_path: Path) -> None:
    path = tmp_path / "set.jsonl"
    path.write_text('{"query": "ok", "gold": ["p"]}\n{"query": broken}\n', encoding="utf-8")

    with pytest.raises(EvalDatasetError) as excinfo:
        load_dataset(path)

    assert "line 2" in str(excinfo.value)


def test_missing_file_is_reported(tmp_path: Path) -> None:
    with pytest.raises(EvalDatasetError) as excinfo:
        load_dataset(tmp_path / "absent.jsonl")

    assert "not found" in str(excinfo.value)


def test_unsupported_suffix_is_reported(tmp_path: Path) -> None:
    path = tmp_path / "set.txt"
    path.write_text("{}", encoding="utf-8")

    with pytest.raises(EvalDatasetError) as excinfo:
        load_dataset(path)

    assert "Unsupported evaluation set format" in str(excinfo.value)


def test_empty_set_is_reported(tmp_path: Path) -> None:
    path = tmp_path / "set.jsonl"
    path.write_text("\n\n", encoding="utf-8")

    with pytest.raises(EvalDatasetError) as excinfo:
        load_dataset(path)

    assert "holds no cases" in str(excinfo.value)


def test_duplicate_case_ids_are_rejected(tmp_path: Path) -> None:
    path = _write_jsonl(
        tmp_path / "set.jsonl",
        [
            {"id": "dup", "query": "a", "gold": ["p1"]},
            {"id": "dup", "query": "b", "gold": ["p2"]},
        ],
    )

    with pytest.raises(EvalDatasetError) as excinfo:
        load_dataset(path)

    assert "duplicate case id 'dup'" in str(excinfo.value)


def test_json_object_form_carries_its_name(tmp_path: Path) -> None:
    path = tmp_path / "set.json"
    path.write_text(
        json.dumps({"name": "textbook-ch4", "cases": [{"query": "q", "gold": ["passage"]}]}),
        encoding="utf-8",
    )

    assert load_dataset(path).name == "textbook-ch4"


def test_explicit_name_overrides_the_file(tmp_path: Path) -> None:
    path = tmp_path / "set.jsonl"
    _write_jsonl(path, [{"query": "q", "gold": ["passage"]}])

    assert load_dataset(path, name="override").name == "override"


def test_json_bare_list_form_is_accepted(tmp_path: Path) -> None:
    path = tmp_path / "set.json"
    path.write_text(json.dumps([{"query": "q", "gold": ["passage"]}]), encoding="utf-8")

    dataset = load_dataset(path)

    assert len(dataset) == 1
    assert dataset.cases[0].id == "q1"


def test_json_without_cases_list_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "set.json"
    path.write_text(json.dumps({"name": "x"}), encoding="utf-8")

    with pytest.raises(EvalDatasetError) as excinfo:
        load_dataset(path)

    assert "must hold a 'cases' list" in str(excinfo.value)


def test_limited_truncates_and_none_keeps_everything() -> None:
    dataset = EvalDataset.from_cases(
        [
            {"query": "a", "gold": ["p1"]},
            {"query": "b", "gold": ["p2"]},
            {"query": "c", "gold": ["p3"]},
        ]
    )

    assert [case.query for case in dataset.limited(2).cases] == ["a", "b"]
    assert len(dataset.limited(None)) == 3
    assert len(dataset.limited(9)) == 3


def test_from_cases_fills_ids_and_validates() -> None:
    dataset = EvalDataset.from_cases([EvalCase(query="a", gold=["p1"])], name="inline")

    assert dataset.name == "inline"
    assert dataset.cases[0].id == "q1"
