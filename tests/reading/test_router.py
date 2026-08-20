"""Router tests for the reading API, driven through a real ASGI client.

Mounted on a bare FastAPI app rather than the full one so the suite does not
boot every other router; the routes themselves are the real ones.
"""

from __future__ import annotations

import io
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from deeptutor.api.routers import reading
from deeptutor.services.path_service import PathService

pymupdf = pytest.importorskip("pymupdf")


PAGES = [
    "Chapter one. Sequence models read tokens one at a time.",
    "Chapter two. Transformers use scaled dot-product attention.",
]


@pytest.fixture
def client(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("DEEPTUTOR_HOME", str(tmp_path))
    PathService.reset_instance()
    app = FastAPI()
    app.include_router(reading.router, prefix="/api/v1/reading")
    with TestClient(app) as test_client:
        yield test_client
    PathService.reset_instance()


def _pdf_bytes(pages: list[str] = PAGES, *, toc: bool = True) -> bytes:
    doc = pymupdf.open()
    for body in pages:
        page = doc.new_page()
        page.insert_textbox(pymupdf.Rect(50, 50, 545, 780), body, fontsize=11)
    if toc:
        doc.set_toc([[1, "Introduction", 1], [1, "Transformers", 2]])
    data = doc.tobytes()
    doc.close()
    return data


def _upload(client: TestClient, name: str = "attention.pdf", data: bytes | None = None):
    payload = data if data is not None else _pdf_bytes()
    response = client.post(
        "/api/v1/reading/materials",
        files={"file": (name, io.BytesIO(payload), "application/pdf")},
    )
    assert response.status_code == 200, response.text
    return response.json()


# ---------------------------------------------------------------------------
# materials
# ---------------------------------------------------------------------------


def test_upload_returns_a_readable_material_with_its_outline(client: TestClient) -> None:
    body = _upload(client)

    assert body["unit"] == "page"
    assert body["unit_count"] == 2
    assert body["has_raw_view"] is True
    assert body["annotation_count"] == 0
    assert [row["title"] for row in body["outline"]] == ["Introduction", "Transformers"]
    assert "attention.pdf" in body["outline_text"]


def test_upload_rejects_an_empty_file(client: TestClient) -> None:
    response = client.post(
        "/api/v1/reading/materials",
        files={"file": ("empty.pdf", io.BytesIO(b""), "application/pdf")},
    )

    assert response.status_code == 400


def test_upload_rejects_an_oversized_file(client: TestClient, monkeypatch) -> None:
    monkeypatch.setattr(reading, "MAX_MATERIAL_BYTES", 1024)

    response = client.post(
        "/api/v1/reading/materials",
        files={"file": ("big.txt", io.BytesIO(b"x" * 4096), "text/plain")},
    )

    assert response.status_code == 413


def test_upload_of_an_image_only_pdf_explains_itself(client: TestClient) -> None:
    doc = pymupdf.open()
    doc.new_page()  # a page with no text at all
    blank = doc.tobytes()
    doc.close()

    response = client.post(
        "/api/v1/reading/materials",
        files={"file": ("scan.pdf", io.BytesIO(blank), "application/pdf")},
    )

    assert response.status_code == 400
    assert "OCR" in response.json()["detail"]


def test_list_materials_reports_annotation_counts(client: TestClient) -> None:
    material = _upload(client)
    client.put(
        f"/api/v1/reading/materials/{material['material_id']}/annotations",
        json={"locator": 1, "quote": "Sequence models", "note": "n"},
    )

    rows = client.get("/api/v1/reading/materials").json()

    assert len(rows) == 1
    assert rows[0]["annotation_count"] == 1


def test_get_material_404s_for_an_unknown_id(client: TestClient) -> None:
    response = client.get("/api/v1/reading/materials/0123456789abcdef")
    assert response.status_code == 404


def test_get_material_400s_for_a_traversal_attempt(client: TestClient) -> None:
    response = client.get("/api/v1/reading/materials/..%2F..%2Fetc")
    assert response.status_code in (400, 404)


def test_delete_material_is_idempotent_then_404s(client: TestClient) -> None:
    material = _upload(client)
    material_id = material["material_id"]

    assert client.delete(f"/api/v1/reading/materials/{material_id}").status_code == 200
    assert client.delete(f"/api/v1/reading/materials/{material_id}").status_code == 404


def test_supported_formats_names_pdf_as_the_faithful_view(client: TestClient) -> None:
    body = client.get("/api/v1/reading/supported-formats").json()

    assert ".pdf" in body["extensions"]
    assert ".epub" in body["extensions"]
    assert body["raw_view_extensions"] == [".pdf"]
    assert body["max_bytes"] > 0


# ---------------------------------------------------------------------------
# unit text and raw bytes
# ---------------------------------------------------------------------------


def test_unit_text_is_addressed_by_locator(client: TestClient) -> None:
    material = _upload(client)

    body = client.get(f"/api/v1/reading/materials/{material['material_id']}/units/2").json()

    assert body["locator"] == 2
    assert body["unit"] == "page"
    assert "scaled dot-product" in body["text"]


def test_unit_text_out_of_range_is_a_400_with_the_real_range(client: TestClient) -> None:
    material = _upload(client)

    response = client.get(f"/api/v1/reading/materials/{material['material_id']}/units/99")

    assert response.status_code == 400
    assert "2" in response.json()["detail"]


def test_raw_route_serves_the_pdf_inline_and_accepts_ranges(client: TestClient) -> None:
    material = _upload(client)

    response = client.get(f"/api/v1/reading/materials/{material['material_id']}/raw")

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    assert "inline" in response.headers["content-disposition"]
    assert response.content[:5] == b"%PDF-"

    partial = client.get(
        f"/api/v1/reading/materials/{material['material_id']}/raw",
        headers={"Range": "bytes=0-99"},
    )
    # Range support is what lets pdf.js stream a large book.
    assert partial.status_code == 206
    assert len(partial.content) == 100


def test_raw_route_404s_for_a_text_only_material(client: TestClient) -> None:
    material = _upload(client, name="notes.txt", data=b"plain readable text content")

    response = client.get(f"/api/v1/reading/materials/{material['material_id']}/raw")

    assert response.status_code == 404


# ---------------------------------------------------------------------------
# annotations
# ---------------------------------------------------------------------------


def test_annotation_create_update_list_delete_round_trip(client: TestClient) -> None:
    material = _upload(client)
    base = f"/api/v1/reading/materials/{material['material_id']}/annotations"

    created = client.put(
        base,
        json={
            "locator": 2,
            "kind": "highlight",
            "color": "blue",
            "quote": "scaled dot-product",
            "note": "core",
            "rects": [[0.1, 0.2, 0.6, 0.24]],
        },
    ).json()
    assert created["annotation_id"]
    assert created["author"] == "user"
    assert created["rects"] == [[0.1, 0.2, 0.6, 0.24]]

    updated = client.put(
        base,
        json={
            "annotation_id": created["annotation_id"],
            "locator": 2,
            "quote": "scaled dot-product",
            "note": "revised",
        },
    ).json()
    assert updated["note"] == "revised"

    rows = client.get(base).json()
    assert len(rows) == 1

    assert client.delete(f"{base}/{created['annotation_id']}").status_code == 200
    assert client.get(base).json() == []
    assert client.delete(f"{base}/{created['annotation_id']}").status_code == 404


def test_annotation_on_an_out_of_range_locator_is_a_400(client: TestClient) -> None:
    material = _upload(client)

    response = client.put(
        f"/api/v1/reading/materials/{material['material_id']}/annotations",
        json={"locator": 99, "quote": "x"},
    )

    assert response.status_code == 400


def test_annotation_locator_must_be_positive(client: TestClient) -> None:
    material = _upload(client)

    response = client.put(
        f"/api/v1/reading/materials/{material['material_id']}/annotations",
        json={"locator": 0, "quote": "x"},
    )

    assert response.status_code == 422


def test_unknown_colour_is_normalised_rather_than_rejected(client: TestClient) -> None:
    material = _upload(client)

    created = client.put(
        f"/api/v1/reading/materials/{material['material_id']}/annotations",
        json={"locator": 1, "quote": "Sequence models", "color": "neon"},
    ).json()

    assert created["color"] == "yellow"


def test_inverted_rects_are_ordered_server_side(client: TestClient) -> None:
    material = _upload(client)

    created = client.put(
        f"/api/v1/reading/materials/{material['material_id']}/annotations",
        json={"locator": 1, "quote": "x", "rects": [[0.9, 0.9, 0.2, 0.2]]},
    ).json()

    assert created["rects"] == [[0.2, 0.2, 0.9, 0.9]]


# ---------------------------------------------------------------------------
# export
# ---------------------------------------------------------------------------


def test_pdf_export_contains_the_annotation(client: TestClient) -> None:
    material = _upload(client)
    client.put(
        f"/api/v1/reading/materials/{material['material_id']}/annotations",
        json={
            "locator": 2,
            "quote": "scaled dot-product",
            "note": "core mechanism",
            "rects": [[0.1, 0.1, 0.8, 0.16]],
        },
    )

    response = client.get(f"/api/v1/reading/materials/{material['material_id']}/export")

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    assert "attention-annotated.pdf" in response.headers["content-disposition"]
    with pymupdf.open(stream=response.content, filetype="pdf") as doc:
        annots = list(doc[1].annots())
        assert len(annots) == 1
        assert annots[0].info.get("content") == "core mechanism"


def test_markdown_export_is_the_default_for_text_materials(client: TestClient) -> None:
    material = _upload(client, name="notes.md", data=b"# Alpha\n\nsome readable body text")
    client.put(
        f"/api/v1/reading/materials/{material['material_id']}/annotations",
        json={"locator": 1, "quote": "readable body", "note": "keep"},
    )

    response = client.get(f"/api/v1/reading/materials/{material['material_id']}/export")

    assert "markdown" in response.headers["content-type"]
    text = response.content.decode("utf-8")
    assert "> readable body" in text
    assert "keep" in text


def test_pdf_export_is_refused_for_a_text_material(client: TestClient) -> None:
    material = _upload(client, name="notes.txt", data=b"plain readable text content")

    response = client.get(
        f"/api/v1/reading/materials/{material['material_id']}/export",
        params={"fmt": "pdf"},
    )

    assert response.status_code == 400


def test_export_filename_survives_non_ascii(client: TestClient) -> None:
    material = _upload(client, name="注意力机制.pdf")

    response = client.get(f"/api/v1/reading/materials/{material['material_id']}/export")

    disposition = response.headers["content-disposition"]
    assert "filename*=UTF-8''" in disposition


def test_export_rejects_an_unknown_format(client: TestClient) -> None:
    material = _upload(client)

    response = client.get(
        f"/api/v1/reading/materials/{material['material_id']}/export",
        params={"fmt": "docx"},
    )

    assert response.status_code == 422
