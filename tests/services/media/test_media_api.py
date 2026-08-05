"""MED-03 focused tests: user-scoped media API contract (spec §11.3, §12.3).

Offline only — no real provider, no catalog file, no request context.  The
store is rooted in a temp dir (mirroring the learning API tests) and the image
catalog is injected so profile/model/protocol validation is exact and
deterministic.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
import uuid

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from deeptutor.api.routers.media import router
from deeptutor.services.media.models import (
    GeneratedArtifact,
    ImageGenerationJob,
    ImageJobStatus,
    ReferenceOwnerType,
)
from deeptutor.services.media.store import MediaStore
from tests.services.media._media_helpers import make_png


def _catalog() -> dict[str, Any]:
    return {
        "version": 1,
        "services": {
            "imagegen": {
                "active_profile_id": "img1",
                "active_model_id": "m1",
                "profiles": [
                    {
                        "id": "img1",
                        "binding": "openai",
                        "base_url": "https://example.invalid/v1",
                        "api_key": "sk-test-1234567890",
                        "models": [
                            {"id": "m1", "model": "gpt-image-2", "size": "1024x1024"},
                        ],
                    },
                    {
                        "id": "mcp1",
                        "binding": "custom",
                        "base_url": "",
                        "api_key": "",
                        "models": [],
                    },
                ],
            }
        },
    }


class _FakeCatalogService:
    def __init__(self, catalog: dict[str, Any]) -> None:
        self._catalog = catalog

    def load(self) -> dict[str, Any]:
        return self._catalog


@pytest.fixture
def app(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    from deeptutor.services.config import model_catalog as model_catalog_mod
    from deeptutor.services.media import store as store_mod

    monkeypatch.setattr(
        model_catalog_mod,
        "get_model_catalog_service",
        lambda: _FakeCatalogService(_catalog()),
    )

    def _store_init(self, root=None, limits=None):
        from deeptutor.services.media.config import MediaLimits

        self._root = Path(tmp_path) / "media"
        self._limits = limits or MediaLimits()
        self._jobs_dir = self._root / "jobs"
        self._artifacts_dir = self._root / "artifacts"
        self._references_dir = self._root / "references"
        from deeptutor.services.media.persistence import MediaPersistence

        self._persistence = MediaPersistence(self._root, self._limits)
        for directory in (self._jobs_dir, self._artifacts_dir, self._references_dir):
            directory.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr(store_mod.MediaStore, "__init__", _store_init)

    app = FastAPI()
    app.include_router(router, prefix="/api/v1")
    return app


@pytest.fixture
def client(app) -> TestClient:
    return TestClient(app)


@pytest.fixture
def store(tmp_path: Path) -> MediaStore:
    return MediaStore(root=tmp_path / "media")


def _submit_payload(**overrides: Any) -> dict[str, Any]:
    payload = dict(
        operation="generate",
        prompt="a red fox in the snow",
        profile="img1",
        model="m1",
        protocol="openai_images",
        # The API now requires a nonblank idempotency_key (§8.3); each call gets
        # a fresh key unless the test overrides it.
        idempotency_key=f"test-key-{uuid.uuid4().hex}",
        session_id="sess-1",
        turn_id="turn-1",
        tool_call_id="tool-1",
    )
    payload.update(overrides)
    return payload


def _persisted_artifact(
    store: MediaStore,
    *,
    user_id: str = "local-admin",
    session_id: str = "sess-a",
    **overrides: Any,
) -> GeneratedArtifact:
    saved = store.persistence.save_media(make_png(8, 8), mime_type="image/png")
    artifact = GeneratedArtifact(
        id=uuid.uuid4().hex,
        user_id=user_id,
        job_id="job-art",
        session_id=session_id,
        provider="openai",
        profile="img1",
        protocol="openai_images",
        model="gpt-image-2",
        sha256=saved.sha256,
        mime_type=saved.mime_type,
        width=saved.width,
        height=saved.height,
        size_bytes=saved.size_bytes,
        original_path=saved.original_path,
        thumbnail_path=saved.thumbnail_path,
    )
    for key, value in overrides.items():
        setattr(artifact, key, value)
    store.save_artifact(artifact, check_quota=False)
    return artifact


# ── submit ───────────────────────────────────────────────────────────────────


def test_submit_generate_creates_queued_job(client: TestClient) -> None:
    resp = client.post("/api/v1/image-jobs", json=_submit_payload())
    assert resp.status_code == 201
    body = resp.json()
    job = body["job"]
    assert job["status"] == "queued"
    assert job["status_version"] == 0
    assert job["profile"] == "img1"
    assert job["protocol"] == "openai_images"
    assert job["model"] == "m1"
    assert job["prompt"] == "a red fox in the snow"
    assert job["operation"] == "generate"
    # Provider/remote ids are never exposed in the card.
    assert "remote_response_id" not in job
    assert "remote_job_id" not in job


def test_submit_is_idempotent_per_key(client: TestClient) -> None:
    payload = _submit_payload(idempotency_key="same")
    first = client.post("/api/v1/image-jobs", json=payload)
    second = client.post("/api/v1/image-jobs", json=payload)
    assert first.status_code == 201 and second.status_code == 201
    assert first.json()["job"]["id"] == second.json()["job"]["id"]


def test_submit_requires_nonblank_idempotency_key(client: TestClient) -> None:
    empty = _submit_payload(idempotency_key="")
    resp = client.post("/api/v1/image-jobs", json=empty)
    assert resp.status_code == 422
    # Pydantic reports the empty required field; the endpoint strip check
    # rejects whitespace-only keys with a stable string detail.
    assert "idempotency_key" in str(resp.json()["detail"])

    blank = _submit_payload(idempotency_key="   ")
    resp = client.post("/api/v1/image-jobs", json=blank)
    assert resp.status_code == 422
    assert "idempotency_key" in resp.json()["detail"]


def test_submit_same_key_different_payload_conflicts(client: TestClient) -> None:
    client.post("/api/v1/image-jobs", json=_submit_payload(idempotency_key="dup"))
    resp = client.post(
        "/api/v1/image-jobs",
        json=_submit_payload(idempotency_key="dup", prompt="a different prompt"),
    )
    assert resp.status_code == 409


def test_submit_rejects_unknown_profile(client: TestClient) -> None:
    resp = client.post("/api/v1/image-jobs", json=_submit_payload(profile="nope"))
    assert resp.status_code == 422
    assert "does not exist" in resp.json()["detail"]


def test_submit_rejects_unsupported_protocol(client: TestClient) -> None:
    resp = client.post("/api/v1/image-jobs", json=_submit_payload(protocol="anthropic_messages"))
    assert resp.status_code == 422
    assert "Unsupported image protocol" in resp.json()["detail"]


def test_submit_rejects_model_not_on_profile(client: TestClient) -> None:
    resp = client.post("/api/v1/image-jobs", json=_submit_payload(model="gpt-999"))
    assert resp.status_code == 422


def test_submit_mcp_does_not_require_model(client: TestClient) -> None:
    resp = client.post(
        "/api/v1/image-jobs",
        json=_submit_payload(profile="mcp1", protocol="mcp", model=""),
    )
    assert resp.status_code == 201
    assert resp.json()["job"]["protocol"] == "mcp"


def test_submit_generate_rejects_sources(client: TestClient) -> None:
    resp = client.post(
        "/api/v1/image-jobs",
        json=_submit_payload(source_artifact_ids=["a1"]),
    )
    assert resp.status_code == 409


def test_submit_edit_without_source_rejected(client: TestClient) -> None:
    resp = client.post(
        "/api/v1/image-jobs",
        json=_submit_payload(operation="edit"),
    )
    assert resp.status_code == 409


def test_submit_rejects_secret_in_prompt(client: TestClient, store: MediaStore) -> None:
    resp = client.post(
        "/api/v1/image-jobs",
        json=_submit_payload(prompt="draw the key sk-abc123def456ghi"),
    )
    assert resp.status_code == 201
    job = resp.json()["job"]
    assert "sk-abc123def456ghi" not in job["prompt"]
    assert "sk-***" in job["prompt"]


# ── list / read ──────────────────────────────────────────────────────────────


def test_list_jobs_returns_user_jobs(client: TestClient, store: MediaStore) -> None:
    client.post("/api/v1/image-jobs", json=_submit_payload(idempotency_key="k1"))
    client.post("/api/v1/image-jobs", json=_submit_payload(idempotency_key="k2"))
    resp = client.get("/api/v1/image-jobs")
    assert resp.status_code == 200
    jobs = resp.json()["jobs"]
    assert len(jobs) == 2


def test_list_jobs_filters_by_session(client: TestClient) -> None:
    client.post(
        "/api/v1/image-jobs", json=_submit_payload(idempotency_key="k1", session_id="sess-a")
    )
    client.post(
        "/api/v1/image-jobs", json=_submit_payload(idempotency_key="k2", session_id="sess-b")
    )
    resp = client.get("/api/v1/image-jobs", params={"session_id": "sess-a"})
    jobs = resp.json()["jobs"]
    assert len(jobs) == 1
    assert jobs[0]["session_id"] == "sess-a"


def test_read_job_is_404_for_missing(client: TestClient) -> None:
    resp = client.get(f"/api/v1/image-jobs/{uuid.uuid4().hex}")
    assert resp.status_code == 404


# ── cancel ───────────────────────────────────────────────────────────────────


def test_cancel_queued_job_becomes_cancelled(client: TestClient) -> None:
    job_id = client.post("/api/v1/image-jobs", json=_submit_payload()).json()["job"]["id"]
    resp = client.post(f"/api/v1/image-jobs/{job_id}/cancel", json={})
    assert resp.status_code == 200
    assert resp.json()["job"]["status"] == "cancelled"


def test_cancel_running_job_becomes_cancel_requested(client: TestClient, store: MediaStore) -> None:
    job = store.save_job(
        ImageGenerationJob(
            id=uuid.uuid4().hex,
            user_id="local-admin",
            status=ImageJobStatus.RUNNING,
            profile="img1",
            protocol="openai_images",
            model="gpt-image-2",
        )
    )
    resp = client.post(f"/api/v1/image-jobs/{job.id}/cancel", json={})
    assert resp.status_code == 200
    assert resp.json()["job"]["status"] == "cancel_requested"


def test_cancel_terminal_job_is_409(client: TestClient, store: MediaStore) -> None:
    job = store.save_job(
        ImageGenerationJob(
            id=uuid.uuid4().hex,
            user_id="local-admin",
            status=ImageJobStatus.FAILED,
            profile="img1",
            protocol="openai_images",
            model="gpt-image-2",
        )
    )
    resp = client.post(f"/api/v1/image-jobs/{job.id}/cancel", json={})
    assert resp.status_code == 409


def test_cancel_version_conflict(client: TestClient) -> None:
    job_id = client.post("/api/v1/image-jobs", json=_submit_payload()).json()["job"]["id"]
    resp = client.post(
        f"/api/v1/image-jobs/{job_id}/cancel",
        json={"expected_status_version": 999},
    )
    assert resp.status_code == 409
    assert "version conflict" in resp.json()["detail"]


# ── retry ────────────────────────────────────────────────────────────────────


def test_retry_failed_job_creates_new_lineage(client: TestClient, store: MediaStore) -> None:
    source = store.save_job(
        ImageGenerationJob(
            id=uuid.uuid4().hex,
            user_id="local-admin",
            status=ImageJobStatus.FAILED,
            error_code="provider_error",
            original_prompt="a red fox",
            profile="img1",
            protocol="openai_images",
            model="gpt-image-2",
            request_snapshot={"size": "1024x1024", "count": 1},
        )
    )
    resp = client.post(
        f"/api/v1/image-jobs/{source.id}/retry",
        json={"expected_status_version": source.status_version},
    )
    assert resp.status_code == 201
    new_job = resp.json()["job"]
    assert new_job["id"] != source.id
    assert new_job["retry_of_job_id"] == source.id
    assert new_job["status"] == "queued"
    assert new_job["prompt"] == "a red fox"


def test_retry_with_new_profile_uses_new_profile(client: TestClient, store: MediaStore) -> None:
    source = store.save_job(
        ImageGenerationJob(
            id=uuid.uuid4().hex,
            user_id="local-admin",
            status=ImageJobStatus.TIMED_OUT,
            original_prompt="a red fox",
            profile="img1",
            protocol="openai_images",
            model="gpt-image-2",
        )
    )
    resp = client.post(
        f"/api/v1/image-jobs/{source.id}/retry",
        json={
            "expected_status_version": source.status_version,
            "profile": "mcp1",
            "protocol": "mcp",
            "model": "",
        },
    )
    assert resp.status_code == 201
    new_job = resp.json()["job"]
    assert new_job["profile"] == "mcp1"
    assert new_job["protocol"] == "mcp"
    assert new_job["retry_of_job_id"] == source.id


def test_retry_rejects_active_job(client: TestClient, store: MediaStore) -> None:
    source = store.save_job(
        ImageGenerationJob(
            id=uuid.uuid4().hex,
            user_id="local-admin",
            status=ImageJobStatus.RUNNING,
            profile="img1",
            protocol="openai_images",
            model="gpt-image-2",
        )
    )
    resp = client.post(
        f"/api/v1/image-jobs/{source.id}/retry",
        json={"expected_status_version": source.status_version},
    )
    assert resp.status_code == 409


def test_retry_rejects_succeeded_job(client: TestClient, store: MediaStore) -> None:
    source = store.save_job(
        ImageGenerationJob(
            id=uuid.uuid4().hex,
            user_id="local-admin",
            status=ImageJobStatus.SUCCEEDED,
            profile="img1",
            protocol="openai_images",
            model="gpt-image-2",
        )
    )
    resp = client.post(
        f"/api/v1/image-jobs/{source.id}/retry",
        json={"expected_status_version": source.status_version},
    )
    assert resp.status_code == 409


def test_retry_cross_user_is_404(client: TestClient, store: MediaStore) -> None:
    source = store.save_job(
        ImageGenerationJob(
            id=uuid.uuid4().hex,
            user_id="other-user",
            status=ImageJobStatus.FAILED,
            profile="img1",
            protocol="openai_images",
            model="gpt-image-2",
        )
    )
    resp = client.post(
        f"/api/v1/image-jobs/{source.id}/retry",
        json={"expected_status_version": source.status_version},
    )
    assert resp.status_code == 404


def test_retry_requires_expected_status_version(client: TestClient, store: MediaStore) -> None:
    source = store.save_job(
        ImageGenerationJob(
            id=uuid.uuid4().hex,
            user_id="local-admin",
            status=ImageJobStatus.FAILED,
            original_prompt="a red fox",
            profile="img1",
            protocol="openai_images",
            model="gpt-image-2",
        )
    )
    resp = client.post(f"/api/v1/image-jobs/{source.id}/retry", json={})
    assert resp.status_code == 422
    assert "expected_status_version" in str(resp.json()["detail"])


def test_retry_version_conflict(client: TestClient, store: MediaStore) -> None:
    source = store.save_job(
        ImageGenerationJob(
            id=uuid.uuid4().hex,
            user_id="local-admin",
            status=ImageJobStatus.FAILED,
            original_prompt="a red fox",
            profile="img1",
            protocol="openai_images",
            model="gpt-image-2",
        )
    )
    resp = client.post(
        f"/api/v1/image-jobs/{source.id}/retry",
        json={"expected_status_version": source.status_version + 1},
    )
    assert resp.status_code == 409
    assert "version conflict" in resp.json()["detail"]


def test_retry_is_idempotent_per_source_version(client: TestClient, store: MediaStore) -> None:
    source = store.save_job(
        ImageGenerationJob(
            id=uuid.uuid4().hex,
            user_id="local-admin",
            status=ImageJobStatus.TIMED_OUT,
            original_prompt="a red fox",
            profile="img1",
            protocol="openai_images",
            model="gpt-image-2",
        )
    )
    payload = {"expected_status_version": source.status_version}
    first = client.post(f"/api/v1/image-jobs/{source.id}/retry", json=payload)
    second = client.post(f"/api/v1/image-jobs/{source.id}/retry", json=payload)
    assert first.status_code == 201 and second.status_code == 201
    assert first.json()["job"]["id"] == second.json()["job"]["id"]
    # Exactly one queued child job exists for this source lineage.
    children = [
        job for job in store.list_jobs(user_id="local-admin") if job.retry_of_job_id == source.id
    ]
    assert len(children) == 1


def test_retry_same_source_version_different_payload_conflicts(
    client: TestClient, store: MediaStore
) -> None:
    source = store.save_job(
        ImageGenerationJob(
            id=uuid.uuid4().hex,
            user_id="local-admin",
            status=ImageJobStatus.FAILED,
            original_prompt="a red fox",
            profile="img1",
            protocol="openai_images",
            model="gpt-image-2",
        )
    )
    # First retry creates the lineage child.
    first = client.post(
        f"/api/v1/image-jobs/{source.id}/retry",
        json={"expected_status_version": source.status_version},
    )
    assert first.status_code == 201
    # Same source/version but a different profile/model/protocol payload: the
    # server-side idempotency key is stable (user + source + version), so this
    # is a stable conflict, never a second child job.
    resp = client.post(
        f"/api/v1/image-jobs/{source.id}/retry",
        json={
            "expected_status_version": source.status_version,
            "profile": "mcp1",
            "protocol": "mcp",
            "model": "",
        },
    )
    assert resp.status_code == 409
    children = [
        job for job in store.list_jobs(user_id="local-admin") if job.retry_of_job_id == source.id
    ]
    assert len(children) == 1


# ── artifacts ────────────────────────────────────────────────────────────────


def test_artifact_list_includes_quota_and_refs(client: TestClient, store: MediaStore) -> None:
    artifact = _persisted_artifact(store)
    store.create_reference(
        artifact_id=artifact.id,
        user_id="local-admin",
        owner_type=ReferenceOwnerType.SESSION,
        owner_id="sess-a",
    )
    resp = client.get("/api/v1/generated-artifacts")
    assert resp.status_code == 200
    body = resp.json()
    assert body["quota"]["used_bytes"] == artifact.size_bytes
    assert body["quota"]["file_count"] == 1
    assert len(body["artifacts"]) == 1
    view = body["artifacts"][0]
    assert view["id"] == artifact.id
    assert view["reference_count"] == 1
    assert view["references"][0]["owner_id"] == "sess-a"
    # Server-side paths never leak to the browser.
    assert "original_path" not in view
    assert "thumbnail_path" not in view
    assert view["preview_url"].endswith("/file?disposition=inline")
    assert view["download_url"].endswith("/file?disposition=attachment")


def test_artifact_quota_endpoint(client: TestClient, store: MediaStore) -> None:
    _persisted_artifact(store, size_bytes=12345)
    resp = client.get("/api/v1/generated-artifacts/quota")
    assert resp.status_code == 200
    quota = resp.json()["quota"]
    assert quota["used_bytes"] == 12345
    assert quota["limit_bytes"] > 0


def test_artifact_file_serves_preview_and_download(client: TestClient, store: MediaStore) -> None:
    artifact = _persisted_artifact(store)
    preview = client.get(
        f"/api/v1/generated-artifacts/{artifact.id}/file", params={"disposition": "inline"}
    )
    assert preview.status_code == 200
    assert preview.headers["content-type"].startswith("image/")
    assert "inline" in preview.headers["content-disposition"]
    # Inline preview serves the derived JPEG thumbnail when one exists.
    assert preview.content[:2] == b"\xff\xd8"

    download = client.get(
        f"/api/v1/generated-artifacts/{artifact.id}/file",
        params={"disposition": "attachment"},
    )
    assert download.status_code == 200
    assert "attachment" in download.headers["content-disposition"]
    assert download.content[:8] == b"\x89PNG\r\n\x1a\n"


def test_artifact_file_cross_user_is_404(client: TestClient, store: MediaStore) -> None:
    artifact = _persisted_artifact(store, user_id="other-user")
    resp = client.get(
        f"/api/v1/generated-artifacts/{artifact.id}/file",
        params={"disposition": "inline"},
    )
    assert resp.status_code == 404


def test_artifact_file_missing_original_is_404(client: TestClient, store: MediaStore) -> None:
    artifact = _persisted_artifact(store)
    store.persistence.resolve(artifact.original_path).unlink()
    resp = client.get(
        f"/api/v1/generated-artifacts/{artifact.id}/file",
        params={"disposition": "attachment"},
    )
    assert resp.status_code == 404


# ── references / deletion / gc ───────────────────────────────────────────────


def test_detach_reference(client: TestClient, store: MediaStore) -> None:
    artifact = _persisted_artifact(store)
    ref = store.create_reference(
        artifact_id=artifact.id,
        user_id="local-admin",
        owner_type=ReferenceOwnerType.SESSION,
        owner_id="sess-a",
    )
    resp = client.request(
        "DELETE",
        f"/api/v1/generated-artifacts/{artifact.id}/references/{ref.id}",
        json={"expected_version": ref.version},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["reference"]["deleted_at"] > 0
    assert body["artifact"]["reference_count"] == 0
    assert body["artifact"]["is_gc_candidate"] is True


def test_detach_reference_version_conflict(client: TestClient, store: MediaStore) -> None:
    artifact = _persisted_artifact(store)
    ref = store.create_reference(
        artifact_id=artifact.id,
        user_id="local-admin",
        owner_type=ReferenceOwnerType.SESSION,
        owner_id="sess-a",
    )
    resp = client.request(
        "DELETE",
        f"/api/v1/generated-artifacts/{artifact.id}/references/{ref.id}",
        json={"expected_version": ref.version + 1},
    )
    assert resp.status_code == 409


def test_detach_reference_cross_user_is_404(client: TestClient, store: MediaStore) -> None:
    artifact = _persisted_artifact(store, user_id="other-user")
    ref = store.create_reference(
        artifact_id=artifact.id,
        user_id="other-user",
        owner_type=ReferenceOwnerType.SESSION,
        owner_id="sess-a",
    )
    resp = client.request(
        "DELETE",
        f"/api/v1/generated-artifacts/{artifact.id}/references/{ref.id}",
        json={},
    )
    assert resp.status_code == 404


def test_detach_reference_from_wrong_artifact_fails_closed(
    client: TestClient, store: MediaStore
) -> None:
    """A same-user reference may only be detached through its own artifact.

    Deleting artifact A's reference through artifact B's URL must fail without
    mutating either artifact's references, and the response must never
    misreport that the deletion succeeded on the path artifact.
    """
    artifact_a = _persisted_artifact(store, session_id="sess-a")
    artifact_b = _persisted_artifact(store, session_id="sess-b")
    ref_on_a = store.create_reference(
        artifact_id=artifact_a.id,
        user_id="local-admin",
        owner_type=ReferenceOwnerType.SESSION,
        owner_id="sess-a",
    )
    ref_on_b = store.create_reference(
        artifact_id=artifact_b.id,
        user_id="local-admin",
        owner_type=ReferenceOwnerType.SESSION,
        owner_id="sess-b",
    )
    # Attempt to detach A's reference through B's URL.
    resp = client.request(
        "DELETE",
        f"/api/v1/generated-artifacts/{artifact_b.id}/references/{ref_on_a.id}",
        json={"expected_version": ref_on_a.version},
    )
    assert resp.status_code == 409
    assert "belongs to artifact" in resp.json()["detail"]
    # Neither artifact's references were mutated.
    assert store.load_reference(ref_on_a.id) is not None
    assert store.load_reference(ref_on_a.id).deleted_at == 0
    assert store.load_reference(ref_on_b.id) is not None
    assert store.load_reference(ref_on_b.id).deleted_at == 0
    # The path artifact B is untouched and still fully referenced.
    resp_b = client.get(f"/api/v1/generated-artifacts/{artifact_b.id}")
    assert resp_b.status_code == 200
    assert resp_b.json()["artifact"]["reference_count"] == 1


def test_remove_everywhere_requires_confirmation(client: TestClient, store: MediaStore) -> None:
    artifact = _persisted_artifact(store)
    store.create_reference(
        artifact_id=artifact.id,
        user_id="local-admin",
        owner_type=ReferenceOwnerType.SESSION,
        owner_id="sess-a",
    )
    resp = client.post(
        f"/api/v1/generated-artifacts/{artifact.id}/delete",
        json={"mode": "remove_everywhere", "confirmed": False},
    )
    assert resp.status_code == 409
    assert "confirmation" in resp.json()["detail"].lower()


def test_remove_everywhere_confirmed(client: TestClient, store: MediaStore) -> None:
    artifact = _persisted_artifact(store)
    store.create_reference(
        artifact_id=artifact.id,
        user_id="local-admin",
        owner_type=ReferenceOwnerType.SESSION,
        owner_id="sess-a",
    )
    store.create_reference(
        artifact_id=artifact.id,
        user_id="local-admin",
        owner_type=ReferenceOwnerType.MESSAGE,
        owner_id="msg-1",
    )
    resp = client.post(
        f"/api/v1/generated-artifacts/{artifact.id}/delete",
        json={"mode": "remove_everywhere", "confirmed": True},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["deleted_references"]) == 2
    assert body["artifact"]["reference_count"] == 0


def test_detach_current_requires_owner(client: TestClient, store: MediaStore) -> None:
    artifact = _persisted_artifact(store)
    resp = client.post(
        f"/api/v1/generated-artifacts/{artifact.id}/delete",
        json={"mode": "detach_current"},
    )
    assert resp.status_code == 422


def test_gc_only_removes_unreferenced_candidates(client: TestClient, store: MediaStore) -> None:
    candidate = _persisted_artifact(store, session_id="sess-a")
    store.arm_gc_if_unreferenced(candidate.id)
    referenced = _persisted_artifact(store, session_id="sess-b")
    store.create_reference(
        artifact_id=referenced.id,
        user_id="local-admin",
        owner_type=ReferenceOwnerType.SESSION,
        owner_id="sess-b",
    )
    resp = client.post("/api/v1/generated-artifacts/gc", json={})
    assert resp.status_code == 200
    assert resp.json()["result"]["deleted_count"] == 1
    assert store.load_artifact(candidate.id) is None
    assert store.load_artifact(referenced.id) is not None


# ── sanitization ─────────────────────────────────────────────────────────────


def test_job_card_never_exposes_raw_provider_error(client: TestClient, store: MediaStore) -> None:
    job = store.save_job(
        ImageGenerationJob(
            id=uuid.uuid4().hex,
            user_id="local-admin",
            status=ImageJobStatus.FAILED,
            error_code="provider_error",
            sanitized_error="provider returned 401 Authorization: Bearer replace-me-0000",
            profile="img1",
            protocol="openai_images",
            model="gpt-image-2",
        )
    )
    resp = client.get(f"/api/v1/image-jobs/{job.id}")
    assert resp.status_code == 200
    body = resp.json()["job"]
    assert "replace-me-0000" not in body["sanitized_error"]
    # The full Authorization header value is collapsed to a redaction marker.
    assert "replace-me-0000" not in str(body)


def test_submit_redacts_secrets_in_provider_options(client: TestClient) -> None:
    resp = client.post(
        "/api/v1/image-jobs",
        json=_submit_payload(
            provider_options={
                "api_key": "sk-super-secret-123",
                "headers": {"Authorization": "Bearer xyz"},
            }
        ),
    )
    assert resp.status_code == 201
    job_id = resp.json()["job"]["id"]
    persisted = MediaStore().load_job(job_id)  # patched __init__ -> tmp root
    assert persisted is not None
    # The persisted snapshot must never carry the credential.
    snapshot = persisted.request_snapshot
    assert "sk-super-secret-123" not in str(snapshot)
    assert "sk-***" in str(snapshot) or "[REDACTED]" in str(snapshot)
