"""Request-scoped regression coverage for the file library API (issue #1437)."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from deeptutor.services.auth import TokenPayload
from deeptutor.services.storage.file_library import reset_file_library_store

LibraryAppFactory = Callable[..., tuple[TestClient, Path]]


@pytest.fixture
def library_app(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> LibraryAppFactory:
    """Build a standalone FastAPI app with the file_library router.

    Each test gets an isolated per-user workspace tree under ``tmp_path`` and
    a fresh FileLibraryStore singleton (reset on teardown, since the store
    cache is a process-wide module-level dict). Auth is disabled by default
    so most tests don't need JWT tokens; pass ``auth_enabled=True`` and
    ``tokens`` (mirroring ``tests/api/test_output_files.py``) to exercise
    per-user isolation.
    """
    from deeptutor.api.routers import auth as auth_router
    from deeptutor.api.routers import file_library
    from deeptutor.multi_user import paths as multi_user_paths

    admin_root = tmp_path / "data"
    users_root = admin_root / "users"
    monkeypatch.setattr(multi_user_paths, "ADMIN_WORKSPACE_ROOT", admin_root)
    monkeypatch.setattr(multi_user_paths, "USERS_ROOT", users_root)
    monkeypatch.setattr(multi_user_paths, "_path_services", {})

    def make_app(
        auth_enabled: bool = False,
        tokens: dict[str, TokenPayload | None] | None = None,
    ) -> tuple[TestClient, Path]:
        monkeypatch.setattr(auth_router, "AUTH_ENABLED", auth_enabled)
        if tokens is not None:
            monkeypatch.setattr(auth_router, "decode_token", lambda token: tokens.get(token))
        app = FastAPI()
        app.include_router(file_library.router, prefix="/files/library")
        return TestClient(app), admin_root

    yield make_app
    reset_file_library_store()


# ── tests ─────────────────────────────────────────────────────────────────


def test_add_file_returns_entry(library_app: LibraryAppFactory) -> None:
    client, _ = library_app()
    response = client.post(
        "/files/library/",
        data={"filename": "report.txt", "mime_type": "text/plain"},
        files={"file": ("report.txt", b"Hello, world!", "text/plain")},
    )
    assert response.status_code == 200, response.json()
    data = response.json()
    assert data["filename"] == "report.txt"
    assert len(data["sha256"]) == 64
    assert data["size_bytes"] == 13
    assert data["is_deleted"] is False
    assert data["id"]


def test_add_file_deduplicates_by_hash(library_app: LibraryAppFactory) -> None:
    client, _ = library_app()
    payload = {"filename": "dup.txt", "mime_type": "text/plain"}
    files = {"file": ("dup.txt", b"same content", "text/plain")}
    r1 = client.post("/files/library/", data=payload, files=files)
    r2 = client.post("/files/library/", data=payload, files=files)
    assert r1.status_code == r2.status_code == 200
    assert r1.json()["id"] == r2.json()["id"]


def test_add_file_different_content_gives_different_id(library_app: LibraryAppFactory) -> None:
    client, _ = library_app()
    r1 = client.post(
        "/files/library/",
        data={"filename": "a.txt", "mime_type": ""},
        files={"file": ("a.txt", b"content A", "")},
    )
    r2 = client.post(
        "/files/library/",
        data={"filename": "a.txt", "mime_type": ""},
        files={"file": ("a.txt", b"content B", "")},
    )
    assert r1.json()["id"] != r2.json()["id"]


def test_list_files_returns_active(library_app: LibraryAppFactory) -> None:
    client, _ = library_app()
    client.post(
        "/files/library/",
        data={"filename": "f1.txt", "mime_type": ""},
        files={"file": ("f1.txt", b"data1", "")},
    )
    client.post(
        "/files/library/",
        data={"filename": "f2.txt", "mime_type": ""},
        files={"file": ("f2.txt", b"data2", "")},
    )
    response = client.get("/files/library/")
    assert response.status_code == 200
    entries = response.json()
    assert len(entries) == 2
    assert {e["filename"] for e in entries} == {"f1.txt", "f2.txt"}


def test_list_files_excludes_deleted(library_app: LibraryAppFactory) -> None:
    client, _ = library_app()
    r = client.post(
        "/files/library/",
        data={"filename": "todelete.txt", "mime_type": ""},
        files={"file": ("todelete.txt", b"delete me", "")},
    )
    file_id = r.json()["id"]
    client.delete(f"/files/library/{file_id}")
    entries = client.get("/files/library/").json()
    assert file_id not in {e["id"] for e in entries}


def test_list_files_respects_limit_offset(library_app: LibraryAppFactory) -> None:
    client, _ = library_app()
    for i in range(5):
        client.post(
            "/files/library/",
            data={"filename": f"f{i}.txt", "mime_type": ""},
            files={"file": (f"f{i}.txt", f"d{i}".encode(), "")},
        )
    page1 = client.get("/files/library/?limit=2&offset=0").json()
    page2 = client.get("/files/library/?limit=2&offset=2").json()
    assert len(page1) == 2
    assert len(page2) == 2
    assert page1[0]["id"] != page2[0]["id"]


def test_search_files_returns_matches(library_app: LibraryAppFactory) -> None:
    client, _ = library_app()
    client.post(
        "/files/library/",
        data={"filename": "quarterly_report.pdf", "mime_type": ""},
        files={"file": ("quarterly_report.pdf", b"Q3 report", "")},
    )
    client.post(
        "/files/library/",
        data={"filename": "photo.jpg", "mime_type": ""},
        files={"file": ("photo.jpg", b"photo bytes", "")},
    )
    results = client.get("/files/library/search?q=report").json()
    assert len(results) == 1
    assert results[0]["filename"] == "quarterly_report.pdf"


def test_search_files_no_match_returns_empty(library_app: LibraryAppFactory) -> None:
    client, _ = library_app()
    client.post(
        "/files/library/",
        data={"filename": "alpha.txt", "mime_type": ""},
        files={"file": ("alpha.txt", b"alpha", "")},
    )
    results = client.get("/files/library/search?q=beta").json()
    assert results == []


def test_search_files_excludes_deleted(library_app: LibraryAppFactory) -> None:
    client, _ = library_app()
    r = client.post(
        "/files/library/",
        data={"filename": "to_search.txt", "mime_type": ""},
        files={"file": ("to_search.txt", b"search me", "")},
    )
    file_id = r.json()["id"]
    client.delete(f"/files/library/{file_id}")
    results = client.get("/files/library/search?q=search").json()
    assert all(e["id"] != file_id for e in results)


def test_get_file_returns_entry(library_app: LibraryAppFactory) -> None:
    client, _ = library_app()
    r = client.post(
        "/files/library/",
        data={"filename": "myfile.txt", "mime_type": "text/plain"},
        files={"file": ("myfile.txt", b"content", "text/plain")},
    )
    file_id = r.json()["id"]
    entry = client.get(f"/files/library/{file_id}").json()
    assert entry["id"] == file_id
    assert entry["filename"] == "myfile.txt"


def test_get_file_nonexistent_returns_404(library_app: LibraryAppFactory) -> None:
    client, _ = library_app()
    response = client.get("/files/library/nonexistent-id")
    assert response.status_code == 404


def test_delete_file_soft_deletes(library_app: LibraryAppFactory) -> None:
    client, _ = library_app()
    r = client.post(
        "/files/library/",
        data={"filename": "delme.txt", "mime_type": ""},
        files={"file": ("delme.txt", b"delete", "")},
    )
    file_id = r.json()["id"]
    response = client.delete(f"/files/library/{file_id}")
    assert response.status_code == 200
    assert response.json()["deleted"] is True
    entry = client.get(f"/files/library/{file_id}").json()
    assert entry["is_deleted"] is True


def test_delete_file_nonexistent_returns_404(library_app: LibraryAppFactory) -> None:
    client, _ = library_app()
    response = client.delete("/files/library/nonexistent-id")
    assert response.status_code == 404


def test_delete_file_idempotent(library_app: LibraryAppFactory) -> None:
    client, _ = library_app()
    r = client.post(
        "/files/library/",
        data={"filename": "dupdel.txt", "mime_type": ""},
        files={"file": ("dupdel.txt", b"dup", "")},
    )
    file_id = r.json()["id"]
    r1 = client.delete(f"/files/library/{file_id}")
    r2 = client.delete(f"/files/library/{file_id}")
    assert r1.status_code == r2.status_code == 200


def test_restore_file_clears_deleted_flag(library_app: LibraryAppFactory) -> None:
    client, _ = library_app()
    r = client.post(
        "/files/library/",
        data={"filename": "restoreme.txt", "mime_type": ""},
        files={"file": ("restoreme.txt", b"restore", "")},
    )
    file_id = r.json()["id"]
    client.delete(f"/files/library/{file_id}")
    response = client.post(f"/files/library/{file_id}/restore")
    assert response.status_code == 200
    assert response.json()["restored"] is True
    entry = client.get(f"/files/library/{file_id}").json()
    assert entry["is_deleted"] is False


def test_restore_file_nonexistent_returns_404(library_app: LibraryAppFactory) -> None:
    client, _ = library_app()
    response = client.post("/files/library/nonexistent-id/restore")
    assert response.status_code == 404


def test_restore_file_idempotent(library_app: LibraryAppFactory) -> None:
    client, _ = library_app()
    r = client.post(
        "/files/library/",
        data={"filename": "active.txt", "mime_type": ""},
        files={"file": ("active.txt", b"active", "")},
    )
    file_id = r.json()["id"]
    r1 = client.post(f"/files/library/{file_id}/restore")
    r2 = client.post(f"/files/library/{file_id}/restore")
    assert r1.status_code == r2.status_code == 200


def test_download_library_file(library_app: LibraryAppFactory) -> None:
    client, _ = library_app()
    content = b"downloadable content"
    r = client.post(
        "/files/library/",
        data={"filename": "download.txt", "mime_type": "text/plain"},
        files={"file": ("download.txt", content, "text/plain")},
    )
    file_id = r.json()["id"]
    response = client.get(f"/files/library/{file_id}/download")
    assert response.status_code == 200
    assert response.content == content


def test_download_deleted_file_returns_404(library_app: LibraryAppFactory) -> None:
    client, _ = library_app()
    r = client.post(
        "/files/library/",
        data={"filename": "del.txt", "mime_type": ""},
        files={"file": ("del.txt", b"del", "")},
    )
    file_id = r.json()["id"]
    client.delete(f"/files/library/{file_id}")
    response = client.get(f"/files/library/{file_id}/download")
    assert response.status_code == 404


def test_download_nonexistent_returns_404(library_app: LibraryAppFactory) -> None:
    client, _ = library_app()
    response = client.get("/files/library/nonexistent-id/download")
    assert response.status_code == 404


def test_upload_and_list_are_isolated_between_users(library_app: LibraryAppFactory) -> None:
    """Regression test: the FileLibraryStore singleton used to be keyed by a
    constant ("default") instead of the resolved per-user root, so the
    second authenticated user to hit any endpoint transparently shared the
    first user's library (list/get/download all leaked across accounts).
    """
    tokens = {
        "alice-token": TokenPayload(username="alice", role="user", user_id="u_alice"),
        "bob-token": TokenPayload(username="bob", role="user", user_id="u_bob"),
    }
    client, _ = library_app(auth_enabled=True, tokens=tokens)

    with client:
        client.cookies.set("dt_token", "alice-token")
        upload = client.post(
            "/files/library/",
            data={"filename": "alice-only.txt", "mime_type": "text/plain"},
            files={"file": ("alice-only.txt", b"alice's secret file", "text/plain")},
        )
        assert upload.status_code == 200
        alice_file_id = upload.json()["id"]

        client.cookies.set("dt_token", "bob-token")
        bob_list = client.get("/files/library/")
        bob_get = client.get(f"/files/library/{alice_file_id}")
        bob_download = client.get(f"/files/library/{alice_file_id}/download")

    assert bob_list.json() == []
    assert bob_get.status_code == 404
    assert bob_download.status_code == 404
