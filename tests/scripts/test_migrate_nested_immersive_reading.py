from __future__ import annotations

import json
from pathlib import Path
import runpy


def _write_json(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value), encoding="utf-8")


def test_nested_immersive_migration_is_non_destructive_and_idempotent(
    tmp_path: Path,
) -> None:
    module = runpy.run_path(
        str(Path(__file__).resolve().parents[2] / "scripts/migrate_nested_immersive_reading.py")
    )

    source = tmp_path / "source"
    destination = tmp_path / "destination"
    backup = tmp_path / "backup"
    _write_json(source / "settings/model_catalog.json", {"version": 1})
    _write_json(source / "workspace/immersive_reading/document_en/manifest.json", {"id": "en"})
    _write_json(source / "workspace/immersive_reading/document_zh/manifest.json", {"id": "zh"})
    _write_json(
        source / "workspace/immersive_reading/bilingual/pairing_one/pairing.json",
        {"en_document_id": "en", "zh_document_id": "zh"},
    )
    _write_json(
        source / "workspace/immersive_reading/bilingual/pairing_duplicate/pairing.json",
        {"en_document_id": "en", "zh_document_id": "zh"},
    )
    _write_json(destination / "settings/model_catalog.json", {"version": 2})
    _write_json(
        destination / "workspace/immersive_reading/document_en/progress.json",
        {"keep": True},
    )

    report = module["_plan_and_migrate"](
        source,
        destination,
        backup_root=backup / "run",
        requested_ids={"en", "missing"},
    )

    assert (backup / "run/source/settings/model_catalog.json").is_file()
    assert json.loads((destination / "settings/model_catalog.json").read_text())["version"] == 2
    assert (destination / "workspace/immersive_reading/document_en/progress.json").is_file()
    assert (destination / "workspace/immersive_reading/document_zh/manifest.json").is_file()
    assert (
        destination / "workspace/immersive_reading/bilingual/pairing_duplicate/pairing.json"
    ).is_file()
    assert not (destination / "workspace/immersive_reading/bilingual/pairing_one").exists()
    assert report["requested_ids_found"] == ["en"]
    assert any(
        action["action"] == "skip-duplicate-pairing" for action in report["executed_actions"]
    )

    document_count = len(list((destination / "workspace/immersive_reading").glob("document_*")))
    second = module["_plan_and_migrate"](
        source,
        destination,
        backup_root=backup / "second",
        requested_ids=set(),
    )
    assert (
        len(list((destination / "workspace/immersive_reading").glob("document_*")))
        == document_count
    )
    assert any(
        action["action"] == "skip-duplicate-pairing" for action in second["executed_actions"]
    )
