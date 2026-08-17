from __future__ import annotations

import os
from pathlib import Path

import deeptutor.immersive_reading.bilingual.service as bilingual_service_module
import deeptutor.immersive_reading.service as service_module
from deeptutor.immersive_reading.service import ImmersiveReadingService
from deeptutor.services.path_service import PathService


def test_list_documents_gracefully_skips_unreadable_folders(monkeypatch, tmp_path: Path) -> None:
    paths = PathService(workspace_root=tmp_path / "data")
    monkeypatch.setattr(service_module, "get_path_service", lambda: paths)
    service = ImmersiveReadingService()
    doc_summary = service.import_document("sample.txt", b"Hello world text book.")

    unreadable_dir = paths.ensure_immersive_reading_document_root("broken_unreadable")
    unreadable_dir.mkdir(parents=True, exist_ok=True)
    os.chmod(unreadable_dir, 0o000)
    try:
        docs = service.list_documents()
        assert len(docs) == 1
        assert docs[0]["id"] == doc_summary["id"]
    finally:
        os.chmod(unreadable_dir, 0o755)


def test_list_pairings_gracefully_skips_unreadable_folders(monkeypatch, tmp_path: Path) -> None:
    paths = PathService(workspace_root=tmp_path / "data")
    monkeypatch.setattr(bilingual_service_module, "get_path_service", lambda: paths)
    bilingual_service = bilingual_service_module.BilingualPairingService()
    pairing_dir = bilingual_service._root() / "pairing_broken"
    pairing_dir.mkdir(parents=True, exist_ok=True)
    os.chmod(pairing_dir, 0o000)
    try:
        pairings = bilingual_service.list_pairings()
        assert pairings == []
    finally:
        os.chmod(pairing_dir, 0o755)
