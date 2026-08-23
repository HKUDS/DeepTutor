from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys


def _load_module():
    module_path = Path(__file__).resolve().parents[2] / "scripts" / "kids_dual_track_sync.py"
    spec = importlib.util.spec_from_file_location("kids_dual_track_sync_under_test", module_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    try:
        spec.loader.exec_module(module)
        return module
    finally:
        sys.modules.pop(spec.name, None)


def _write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")


def _read_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _make_roots(tmp_path: Path):
    legacy = tmp_path / "legacy-home" / "immersive_reading"
    experimental = tmp_path / "experimental-home" / "immersive_reading"
    progress = {
        "profile_id": "child001",
        "document_id": "doc001",
        "current_section_id": "section_0001",
        "current_section_index": 0,
        "scroll_percent": 10.0,
        "epub_cfi": "cfi-1",
        "section_href": "chapter-1.xhtml",
        "completed_section_ids": ["section_0001"],
        "total_stars": 3,
        "quiz_attempts": 1,
        "quiz_best_score": 3,
        "quiz_scores": {"section_0001": 3},
        "quiz_stars_awarded": {"section_0001": 3},
        "time_spent_seconds": 10.0,
        "last_read_at": 100.0,
        "updated_at": 101.0,
    }
    profiles = [
        {
            "id": "child001",
            "name": "Reader",
            "updated_at": 100.0,
        }
    ]
    assignments = [
        {
            "id": "assignment001",
            "profile_id": "child001",
            "document_id": "doc001",
            "updated_at": 100.0,
        }
    ]
    usage = {
        "profile_id": "child001",
        "date": "2026-08-22",
        "seconds": 10.0,
        "bonus_seconds": 0.0,
        "updated_at": 101.0,
    }
    for root in (legacy, experimental):
        _write_json(root / "kids" / "profiles.json", profiles)
        _write_json(root / "kids" / "assignments.json", assignments)
        _write_json(root / "kids" / "progress" / "child001_doc001.json", progress)
        _write_json(root / "kids" / "usage" / "child001_2026-08-22.json", usage)
    return legacy, experimental


def test_switch_sync_merges_both_deltas_and_preserves_legacy_stars(tmp_path: Path) -> None:
    module = _load_module()
    legacy, experimental = _make_roots(tmp_path)
    assert module.run(legacy, experimental, apply=True) == 0

    old_progress_path = legacy / "kids" / "progress" / "child001_doc001.json"
    new_progress_path = experimental / "kids" / "progress" / "child001_doc001.json"
    old_progress = _read_json(old_progress_path)
    old_progress.update(
        {
            "current_section_id": "section_0002",
            "current_section_index": 1,
            "completed_section_ids": ["section_0001", "section_0002"],
            "total_stars": 6,
            "quiz_attempts": 2,
            "quiz_scores": {
                "section_0001": 3,
                "section_0002": 3,
            },
            "quiz_stars_awarded": {
                "section_0001": 3,
                "section_0002": 3,
            },
            "time_spent_seconds": 12.0,
            "last_read_at": 110.0,
            "updated_at": 111.0,
        }
    )
    _write_json(old_progress_path, old_progress)

    new_progress = _read_json(new_progress_path)
    # A normal save in the extension build drops its ignored legacy fields.
    new_progress.pop("total_stars")
    new_progress.pop("quiz_stars_awarded")
    new_progress.update(
        {
            "current_section_id": "section_0003",
            "current_section_index": 2,
            "completed_section_ids": ["section_0001", "section_0003"],
            "quiz_attempts": 3,
            "quiz_scores": {
                "section_0001": 3,
                "section_0003": 3,
            },
            "time_spent_seconds": 17.0,
            "last_read_at": 120.0,
            "updated_at": 121.0,
        }
    )
    _write_json(new_progress_path, new_progress)

    old_usage_path = legacy / "kids" / "usage" / "child001_2026-08-22.json"
    new_usage_path = experimental / "kids" / "usage" / "child001_2026-08-22.json"
    old_usage = _read_json(old_usage_path)
    old_usage.update({"seconds": 12.0, "updated_at": 111.0})
    new_usage = _read_json(new_usage_path)
    new_usage.update({"seconds": 17.0, "updated_at": 121.0})
    _write_json(old_usage_path, old_usage)
    _write_json(new_usage_path, new_usage)

    assert module.run(legacy, experimental, apply=True) == 0
    merged_old = _read_json(old_progress_path)
    merged_new = _read_json(new_progress_path)

    assert merged_old == merged_new
    assert merged_old["completed_section_ids"] == [
        "section_0001",
        "section_0002",
        "section_0003",
    ]
    assert merged_old["quiz_attempts"] == 4
    assert merged_old["quiz_best_score"] == 3
    assert merged_old["quiz_scores"] == {
        "section_0001": 3,
        "section_0002": 3,
        "section_0003": 3,
    }
    assert merged_old["time_spent_seconds"] == 19.0
    assert merged_old["total_stars"] == 12
    assert merged_old["quiz_stars_awarded"] == {
        "section_0001": 3,
        "section_0002": 3,
        "section_0003": 3,
    }
    assert _read_json(old_usage_path)["seconds"] == 19.0
    assert _read_json(new_usage_path)["seconds"] == 19.0

    state = _read_json(legacy / "kids" / module.STATE_NAME)
    assert state["progress"]["child001_doc001.json"] == merged_old

    # Repeating with no writes is idempotent.
    assert module.run(legacy, experimental, apply=True) == 0
    assert _read_json(old_progress_path) == merged_old
    assert _read_json(new_progress_path) == merged_old


def test_switch_sync_bootstraps_from_legacy_and_dry_run_does_not_write(tmp_path: Path) -> None:
    module = _load_module()
    legacy, experimental = _make_roots(tmp_path)
    experimental_progress = experimental / "kids" / "progress" / "child001_doc001.json"
    before = _read_json(experimental_progress)
    before.pop("total_stars")
    before.pop("quiz_stars_awarded")
    _write_json(experimental_progress, before)

    assert module.run(legacy, experimental, apply=False) == 0
    assert not (legacy / "kids" / module.STATE_NAME).exists()
    assert "total_stars" not in _read_json(experimental_progress)

    assert module.run(legacy, experimental, apply=True) == 0
    restored = _read_json(experimental_progress)
    assert restored["total_stars"] == 3
    assert restored["quiz_stars_awarded"] == {"section_0001": 3}
    assert (legacy / "kids" / module.STATE_NAME).is_file()


def test_switch_sync_copies_assigned_interactive_book_content(tmp_path: Path) -> None:
    module = _load_module()
    legacy, experimental = _make_roots(tmp_path)

    _write_json(
        legacy / "kids" / "assignments.json",
        [
            {
                "id": "assignment-legacy-book",
                "profile_id": "child001",
                "content_type": "interactive_book",
                "book_id": "bk_legacy",
                "status": "active",
                "updated_at": 110.0,
            }
        ],
    )
    _write_json(
        experimental / "kids" / "assignments.json",
        [
            {
                "id": "assignment-experimental-book",
                "profile_id": "child001",
                "content_type": "interactive_book",
                "book_id": "bk_experimental",
                "status": "active",
                "updated_at": 120.0,
            }
        ],
    )

    legacy_book = legacy.parent / "book" / "book_bk_legacy"
    experimental_book = experimental.parent / "book" / "book_bk_experimental"
    legacy_book.mkdir(parents=True)
    experimental_book.mkdir(parents=True)
    (legacy_book / "manifest.json").write_text('{"title": "legacy"}', encoding="utf-8")
    (legacy_book / "progress.json").write_text('{"local": true}', encoding="utf-8")
    (experimental_book / "spine.json").write_text('{"pages": []}', encoding="utf-8")

    unassigned = experimental.parent / "book" / "book_bk_unassigned"
    unassigned.mkdir(parents=True)
    (unassigned / "manifest.json").write_text('{"title": "unassigned"}', encoding="utf-8")

    assert module.run(legacy, experimental, apply=True) == 0

    assert (legacy_book / "manifest.json").is_file()
    assert (legacy.parent / "book" / "book_bk_experimental" / "spine.json").is_file()
    assert not (experimental_book / "progress.json").exists()
    assert (experimental.parent / "book" / "book_bk_legacy" / "manifest.json").is_file()
    assert (experimental_book / "spine.json").is_file()
    assert not (legacy.parent / "book" / "book_bk_unassigned").exists()
    merged_assignments = _read_json(legacy / "kids" / "assignments.json")
    assert {row["book_id"] for row in merged_assignments} == {
        "bk_legacy",
        "bk_experimental",
    }
