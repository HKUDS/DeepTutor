from __future__ import annotations

import json
import stat

from deeptutor.multi_user.kids_migration import KidsToLearningMigration


def _write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def _source(tmp_path):
    immersive = tmp_path / "legacy-immersive"
    kids = immersive / "kids"
    _write(
        kids / "profiles.json",
        [{"id": "p1", "name": "A Learner", "birth_date": "2016-01-01"}],
    )
    _write(
        kids / "assignments.json",
        [{"id": "a1", "profile_id": "p1", "document_id": "doc1", "status": "active"}],
    )
    document = immersive / "document_doc1"
    document.mkdir(parents=True)
    (document / "original.txt").write_text("Chapter One\nThe moon reflects sunlight.", encoding="utf-8")
    _write(document / "manifest.json", {"source_filename": "moon.txt"})
    _write(
        kids / "progress" / "p1_doc1.json",
        {
            "current_section_index": 0,
            "scroll_percent": 25,
            "completed_section_ids": ["section_0001"],
            "quiz_scores": {"section_0001": 2},
            "time_spent_seconds": 30,
        },
    )
    return immersive, kids


def test_dry_run_has_zero_writes(tmp_path, mu_isolated_root):
    immersive, kids = _source(tmp_path)
    journal = tmp_path / "journal.json"
    migration = KidsToLearningMigration(
        kids_root=kids,
        immersive_root=immersive,
        users_root=tmp_path / "data" / "users",
        journal_path=journal,
    )
    result = migration.plan()
    assert result["writes"] == 0
    assert result["profiles"][0]["username"] == "learner-a-learner"
    assert not journal.exists()


def test_apply_is_idempotent_and_writes_private_activation_report(
    tmp_path, mu_isolated_root, monkeypatch, seed_user
):
    from deeptutor.multi_user import activation, kids_migration

    immersive, kids = _source(tmp_path)
    seed_user("admin", role="admin")
    activations = tmp_path / "data" / "system" / "auth" / "learning_activations.json"
    monkeypatch.setattr(activation, "ACTIVATIONS_FILE", activations)
    monkeypatch.setattr(kids_migration, "issue_activation", activation.issue_activation)
    migration = KidsToLearningMigration(
        kids_root=kids,
        immersive_root=immersive,
        users_root=tmp_path / "data" / "users",
        journal_path=tmp_path / "journal.json",
    )
    report = tmp_path / "activation-report.json"
    first = migration.apply(activation_report=report)
    second = migration.apply(activation_report=tmp_path / "activation-report-2.json")

    entry = first["profiles"][0]
    assert entry["status"] == "complete"
    assert entry["materials"]
    assert second["profiles"][0]["user_id"] == entry["user_id"]
    assert stat.S_IMODE(report.stat().st_mode) == 0o600
    grant_path = tmp_path / "data" / "system" / "grants" / f"{entry['user_id']}.json"
    grant = json.loads(grant_path.read_text(encoding="utf-8"))
    assert grant["learning_policy"]["reading"]["allow_upload"] is False
    assert len(grant["learning_policy"]["reading"]["material_ids"]) == 1
    learning_records = (
        tmp_path
        / "data"
        / "users"
        / entry["user_id"]
        / "user"
        / "workspace"
        / "learning"
        / "learning_records.json"
    )
    assert len(json.loads(learning_records.read_text(encoding="utf-8"))) == 2
