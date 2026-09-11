"""Router tests for the reading API, driven through a real ASGI client.

Mounted on a bare FastAPI app rather than the full one so the suite does not
boot every other router; the routes themselves are the real ones.
"""

from __future__ import annotations

import io
from pathlib import Path
import zipfile

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from deeptutor.api.routers import reading
from deeptutor.reading import ReadingCatalogStore, ReadingError, ReadingStore
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
    app.include_router(reading.router, prefix="/api/reading")
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
        "/api/reading/materials",
        files={"file": (name, io.BytesIO(payload), "application/pdf")},
    )
    assert response.status_code == 200, response.text
    return response.json()


def _epub_bytes(*, language: str = "en", paragraph: str = "Readable EPUB text.") -> bytes:
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, "w") as archive:
        archive.writestr("mimetype", "application/epub+zip")
        archive.writestr(
            "META-INF/container.xml",
            "<container><rootfiles><rootfile full-path='OPS/book.opf'/></rootfiles></container>",
        )
        archive.writestr(
            "OPS/book.opf",
            "<package xmlns:dc='http://purl.org/dc/elements/1.1/'>"
            "<metadata><dc:identifier>urn:uuid:router-bilingual</dc:identifier>"
            "<dc:title>Router book</dc:title>"
            f"<dc:language>{language}</dc:language></metadata>"
            "<manifest><item id='one' href='one.xhtml'/></manifest>"
            "<spine><itemref idref='one'/></spine></package>",
        )
        archive.writestr(
            "OPS/one.xhtml",
            f"<html><body><h1>Opening</h1><p>{paragraph}</p></body></html>",
        )
    return stream.getvalue()


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
        "/api/reading/materials",
        files={"file": ("empty.pdf", io.BytesIO(b""), "application/pdf")},
    )

    assert response.status_code == 400


def test_upload_rejects_an_oversized_file(client: TestClient, monkeypatch) -> None:
    monkeypatch.setattr(reading, "MAX_MATERIAL_BYTES", 1024)

    response = client.post(
        "/api/reading/materials",
        files={"file": ("big.txt", io.BytesIO(b"x" * 4096), "text/plain")},
    )

    assert response.status_code == 413


def test_upload_of_an_image_only_pdf_explains_itself(client: TestClient) -> None:
    doc = pymupdf.open()
    doc.new_page()  # a page with no text at all
    blank = doc.tobytes()
    doc.close()

    response = client.post(
        "/api/reading/materials",
        files={"file": ("scan.pdf", io.BytesIO(blank), "application/pdf")},
    )

    assert response.status_code == 400
    assert "OCR" in response.json()["detail"]


def test_list_materials_reports_annotation_counts(client: TestClient) -> None:
    material = _upload(client)
    client.put(
        f"/api/reading/materials/{material['material_id']}/annotations",
        json={"locator": 1, "quote": "Sequence models", "note": "n"},
    )

    rows = client.get("/api/reading/materials").json()

    assert len(rows) == 1
    assert rows[0]["annotation_count"] == 1


def test_get_material_404s_for_an_unknown_id(client: TestClient) -> None:
    response = client.get("/api/reading/materials/0123456789abcdef")
    assert response.status_code == 404


def test_get_material_400s_for_a_traversal_attempt(client: TestClient) -> None:
    response = client.get("/api/reading/materials/..%2F..%2Fetc")
    assert response.status_code in (400, 404)


def test_snapshot_assets_are_served_with_sniffed_private_headers(client: TestClient) -> None:
    store = ReadingStore()
    material_id = "0123456789abcdef"
    name = "a" * 20 + ".png"
    store.ingest_units(
        material_id,
        filename="snapshot.md",
        units=["# Snapshot"],
        content_format="web_markdown",
        source_type="url_snapshot",
        source_url="https://example.com",
        assets={name: b"\x89PNG\r\n\x1a\nasset"},
    )

    response = client.get(f"/api/reading/materials/{material_id}/assets/{name}")

    assert response.status_code == 200
    assert response.headers["content-type"] == "image/png"
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["cache-control"].startswith("private")
    assert (
        client.get(f"/api/reading/materials/{material_id}/assets/not-an-image.svg").status_code
        == 404
    )


def test_delete_material_is_idempotent_then_404s(client: TestClient) -> None:
    material = _upload(client)
    material_id = material["material_id"]

    assert client.delete(f"/api/reading/materials/{material_id}").status_code == 200
    assert client.delete(f"/api/reading/materials/{material_id}").status_code == 404


def test_delete_material_restores_content_when_catalog_cleanup_fails(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    material_id = _upload(client)["material_id"]

    def fail_catalog_delete(_self, _material_id: str) -> bool:
        raise ReadingError("catalog cleanup failed")

    monkeypatch.setattr(ReadingCatalogStore, "delete_material", fail_catalog_delete)
    response = client.delete(f"/api/reading/materials/{material_id}")

    assert response.status_code == 400
    assert response.json()["detail"] == "catalog cleanup failed"
    assert ReadingStore().manifest(material_id).material_id == material_id
    assert ReadingCatalogStore().get_material(material_id) is not None


def test_supported_formats_names_faithful_documents_and_media(client: TestClient) -> None:
    body = client.get("/api/reading/supported-formats").json()

    assert ".pdf" in body["extensions"]
    assert ".epub" in body["extensions"]
    assert ".pdf" in body["raw_view_extensions"]
    assert ".mp4" in body["raw_view_extensions"]
    assert ".mp3" in body["raw_view_extensions"]
    assert body["max_bytes"] > 0


def _stub_media(monkeypatch: pytest.MonkeyPatch, cues_by_chunk) -> None:
    """Drive the media path without ffmpeg or a speech-to-text provider."""
    from deeptutor.reading import ingestion
    from deeptutor.services import voice

    async def chunker(_path: Path):
        return [(0.0, 600.0, b"chunk-one"), (600.0, 900.0, b"chunk-two")]

    async def transcriber(audio: bytes, **_kwargs):
        return cues_by_chunk(audio)

    monkeypatch.setattr(ingestion, "_chunk_media_audio", chunker)
    monkeypatch.setattr(ingestion, "_probe_stt_configuration", lambda: "")
    monkeypatch.setattr(voice, "transcribe_audio_cues", transcriber)


def test_local_video_answers_before_transcription_and_plays_immediately(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Uploading media queues work; it does not hold the request open.

    Transcribing a lecture takes minutes, so the route answers as soon as the
    file is stored — with a material that already plays — and the transcript
    lands afterwards. The old shape ran the whole pipeline inline, which meant
    no progress could reach the client and a proxy timeout threw away work that
    had already been paid for.
    """
    from deeptutor.services.voice import TranscriptCue

    _stub_media(
        monkeypatch,
        lambda audio: (
            [
                TranscriptCue(0.0, 30.0, "Gradient descent, briefly."),
                TranscriptCue(30.0, 62.0, "Then the learning rate."),
            ]
            if audio == b"chunk-one"
            else [TranscriptCue(0.0, 25.0, "Closing remarks.")]
        ),
    )

    response = client.post(
        "/api/reading/materials",
        files={"file": ("lecture.mp4", io.BytesIO(b"playable video bytes"), "video/mp4")},
    )

    assert response.status_code == 200, response.text
    queued = response.json()
    material_id = queued["material_id"]
    assert queued["render_mode"] == "video"
    assert queued["mime"] == "video/mp4"
    # Playable before a single word has been transcribed.
    raw = client.get(f"/api/reading/materials/{material_id}/raw")
    assert raw.status_code == 200
    assert raw.content == b"playable video bytes"

    ready = client.get(f"/api/reading/materials/{material_id}").json()
    assert ready["unit_count"] == 3
    # Cue timings, rebased onto the clip — not one marker per audio chunk.
    assert [row["source_href"] for row in ready["unit_refs"]] == [
        "#t=0",
        "#t=30",
        "#t=600",
    ]
    assert [row["title"] for row in ready["unit_refs"]] == ["00:00", "00:30", "10:00"]


def test_media_without_speech_stays_playable_instead_of_failing(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A silent screencast is a recording with no speech, not a failed import.

    A YouTube video without captions already imports and plays; a local one
    used to be rejected outright, taking the stored original with it.
    """
    _stub_media(monkeypatch, lambda _audio: [])

    material = client.post(
        "/api/reading/materials",
        files={"file": ("silent.mp4", io.BytesIO(b"no speech here"), "video/mp4")},
    ).json()
    detail = client.get(f"/api/reading/materials/{material['material_id']}").json()

    assert detail["render_mode"] == "video"
    assert detail["extractor"] == "media-no-speech"
    assert (
        client.get(f"/api/reading/materials/{material['material_id']}/raw").content
        == b"no speech here"
    )


def test_uploaded_audio_is_served_as_a_type_browsers_can_play(
    client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``mimetypes`` calls .m4a ``audio/mp4a-latm``, which no player accepts."""
    _stub_media(monkeypatch, lambda _audio: [])

    material = client.post(
        "/api/reading/materials",
        files={"file": ("talk.m4a", io.BytesIO(b"podcast bytes"), "audio/mp4")},
    ).json()

    assert material["render_mode"] == "audio"
    assert material["mime"] == "audio/mp4"
    raw = client.get(f"/api/reading/materials/{material['material_id']}/raw")
    assert raw.headers["content-type"] == "audio/mp4"


def test_epub_contract_exposes_source_refs_original_and_position(client: TestClient) -> None:
    material = _upload(client, name="book.epub", data=_epub_bytes())

    assert material["render_mode"] == "epub"
    assert material["has_raw_view"] is False
    assert material["unit_refs"] == [
        {"locator": 1, "source_href": "OPS/one.xhtml", "title": "Opening"}
    ]
    raw = client.get(f"/api/reading/materials/{material['material_id']}/raw")
    assert raw.status_code == 200
    assert raw.headers["content-type"] == "application/epub+zip"

    base = f"/api/reading/materials/{material['material_id']}/position"
    saved = client.put(
        base,
        json={"locator": 1, "source_anchor": "epubcfi(/6/2)", "percentage": 0.4},
    )
    assert saved.status_code == 200
    assert client.get(base).json()["source_anchor"] == "epubcfi(/6/2)"
    assert client.put(base, json={"locator": 2, "percentage": 0}).status_code == 400


def test_epub_pairing_requires_confirmation_and_preserves_source_materials(
    client: TestClient,
) -> None:
    english = _upload(client, name="english.epub", data=_epub_bytes())
    chinese = _upload(
        client,
        name="chinese.epub",
        data=_epub_bytes(language="zh", paragraph="可读的 EPUB 文本。"),
    )

    candidates = client.get(
        f"/api/reading/materials/{english['material_id']}/epub-pairing-candidates"
    )
    assert candidates.status_code == 200
    assert candidates.json()[0]["material_id"] == chinese["material_id"]
    assert client.get("/api/reading/epub-pairings").json() == []

    created = client.post(
        "/api/reading/epub-pairings",
        json={
            "english_material_id": english["material_id"],
            "chinese_material_id": chinese["material_id"],
        },
    )
    assert created.status_code == 200, created.text
    body = created.json()
    assert body["pairing"]["status"] == "confirmed"
    assert body["pairing"]["english_material_id"] == english["material_id"]
    assert body["pairing"]["chinese_material_id"] == chinese["material_id"]
    assert client.get("/api/reading/epub-pairings").json() == [body["pairing"]]
    assert len(client.get("/api/reading/materials").json()) == 2

    removed = client.delete(f"/api/reading/epub-pairings/{body['pairing']['pairing_id']}")
    assert removed.status_code == 200
    assert client.get("/api/reading/epub-pairings").json() == []
    assert len(client.get("/api/reading/materials").json()) == 2


def test_epub_pairing_rejects_the_same_language(client: TestClient) -> None:
    english = _upload(client, name="english.epub", data=_epub_bytes())
    other = _upload(client, name="other.epub", data=_epub_bytes())

    response = client.post(
        "/api/reading/epub-pairings",
        json={
            "english_material_id": english["material_id"],
            "chinese_material_id": other["material_id"],
        },
    )

    assert response.status_code == 400


# ---------------------------------------------------------------------------
# unit text and raw bytes
# ---------------------------------------------------------------------------


def test_unit_text_is_addressed_by_locator(client: TestClient) -> None:
    material = _upload(client)

    body = client.get(f"/api/reading/materials/{material['material_id']}/units/2").json()

    assert body["locator"] == 2
    assert body["unit"] == "page"
    assert "scaled dot-product" in body["text"]


def test_unit_text_out_of_range_is_a_400_with_the_real_range(client: TestClient) -> None:
    material = _upload(client)

    response = client.get(f"/api/reading/materials/{material['material_id']}/units/99")

    assert response.status_code == 400
    assert "2" in response.json()["detail"]


def test_raw_route_serves_the_pdf_inline_and_accepts_ranges(client: TestClient) -> None:
    material = _upload(client)

    response = client.get(f"/api/reading/materials/{material['material_id']}/raw")

    assert response.status_code == 200
    assert response.headers["content-type"] == "application/pdf"
    assert "inline" in response.headers["content-disposition"]
    assert response.content[:5] == b"%PDF-"

    partial = client.get(
        f"/api/reading/materials/{material['material_id']}/raw",
        headers={"Range": "bytes=0-99"},
    )
    # Range support is what lets pdf.js stream a large book.
    assert partial.status_code == 206
    assert len(partial.content) == 100


def test_raw_route_404s_for_a_text_only_material(client: TestClient) -> None:
    material = _upload(client, name="notes.txt", data=b"plain readable text content")

    response = client.get(f"/api/reading/materials/{material['material_id']}/raw")

    assert response.status_code == 404


# ---------------------------------------------------------------------------
# annotations
# ---------------------------------------------------------------------------


def test_annotation_create_update_list_delete_round_trip(client: TestClient) -> None:
    material = _upload(client)
    base = f"/api/reading/materials/{material['material_id']}/annotations"

    created = client.put(
        base,
        json={
            "locator": 2,
            "kind": "highlight",
            "color": "blue",
            "quote": "scaled dot-product",
            "note": "core",
            "rects": [[0.1, 0.2, 0.6, 0.24]],
            "source_anchor": "epubcfi(/6/4)",
        },
    ).json()
    assert created["annotation_id"]
    assert created["author"] == "user"
    assert created["rects"] == [[0.1, 0.2, 0.6, 0.24]]
    assert created["source_anchor"] == "epubcfi(/6/4)"

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


def test_annotation_round_trips_w3c_text_selectors(client: TestClient) -> None:
    material = _upload(client)
    base = f"/api/reading/materials/{material['material_id']}/annotations"

    created = client.put(
        base,
        json={
            "locator": 1,
            "quote": "Sequence models",
            "selectors": [
                {
                    "type": "TextQuoteSelector",
                    "exact": "Sequence models",
                    "prefix": "Chapter one. ",
                    "suffix": " read",
                },
                {"type": "TextPositionSelector", "start": 13, "end": 28},
            ],
        },
    )

    assert created.status_code == 200, created.text
    assert created.json()["selectors"] == [
        {
            "type": "TextQuoteSelector",
            "exact": "Sequence models",
            "prefix": "Chapter one. ",
            "suffix": " read",
        },
        {"type": "TextPositionSelector", "start": 13, "end": 28},
    ]


def test_citation_round_trips_through_the_existing_annotation_api(
    client: TestClient,
) -> None:
    material = _upload(client)
    base = f"/api/reading/materials/{material['material_id']}/annotations"

    created = client.put(
        base,
        json={
            "locator": 1,
            "kind": "citation",
            "quote": "Sequence models",
            "selectors": [
                {"type": "TextQuoteSelector", "exact": "Sequence models"},
                {"type": "TextPositionSelector", "start": 13, "end": 28},
            ],
        },
    )

    assert created.status_code == 200, created.text
    assert created.json()["kind"] == "citation"
    assert created.json()["material_revision"] == material["revision"]
    assert client.get(base).json()[0]["kind"] == "citation"


def test_annotation_rejects_mismatched_quote_selector(client: TestClient) -> None:
    material = _upload(client)
    response = client.put(
        f"/api/reading/materials/{material['material_id']}/annotations",
        json={
            "locator": 1,
            "quote": "Sequence models",
            "selectors": [
                {"type": "TextQuoteSelector", "exact": "different text"},
            ],
        },
    )

    assert response.status_code == 400
    assert "does not match" in response.json()["detail"]


@pytest.mark.parametrize(
    "selector",
    [
        {"type": "TextPositionSelector", "start": 5, "end": 5},
        {"type": "TextPositionSelector", "start": 6, "end": 5},
        {"type": "TextPositionSelector", "start": 0, "end": 2001},
    ],
)
def test_annotation_rejects_invalid_text_positions(
    client: TestClient,
    selector: dict,
) -> None:
    material = _upload(client)
    response = client.put(
        f"/api/reading/materials/{material['material_id']}/annotations",
        json={"locator": 1, "quote": "x", "selectors": [selector]},
    )

    assert response.status_code == 422


def test_annotation_on_an_out_of_range_locator_is_a_400(client: TestClient) -> None:
    material = _upload(client)

    response = client.put(
        f"/api/reading/materials/{material['material_id']}/annotations",
        json={"locator": 99, "quote": "x"},
    )

    assert response.status_code == 400


def test_annotation_locator_must_be_positive(client: TestClient) -> None:
    material = _upload(client)

    response = client.put(
        f"/api/reading/materials/{material['material_id']}/annotations",
        json={"locator": 0, "quote": "x"},
    )

    assert response.status_code == 422


def test_unknown_colour_is_normalised_rather_than_rejected(client: TestClient) -> None:
    material = _upload(client)

    created = client.put(
        f"/api/reading/materials/{material['material_id']}/annotations",
        json={"locator": 1, "quote": "Sequence models", "color": "neon"},
    ).json()

    assert created["color"] == "yellow"


def test_inverted_rects_are_ordered_server_side(client: TestClient) -> None:
    material = _upload(client)

    created = client.put(
        f"/api/reading/materials/{material['material_id']}/annotations",
        json={"locator": 1, "quote": "x", "rects": [[0.9, 0.9, 0.2, 0.2]]},
    ).json()

    assert created["rects"] == [[0.2, 0.2, 0.9, 0.9]]


# ---------------------------------------------------------------------------
# export
# ---------------------------------------------------------------------------


def test_pdf_export_contains_the_annotation(client: TestClient) -> None:
    material = _upload(client)
    client.put(
        f"/api/reading/materials/{material['material_id']}/annotations",
        json={
            "locator": 2,
            "quote": "scaled dot-product",
            "note": "core mechanism",
            "rects": [[0.1, 0.1, 0.8, 0.16]],
        },
    )

    response = client.get(f"/api/reading/materials/{material['material_id']}/export")

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
        f"/api/reading/materials/{material['material_id']}/annotations",
        json={"locator": 1, "quote": "readable body", "note": "keep"},
    )

    response = client.get(f"/api/reading/materials/{material['material_id']}/export")

    assert "markdown" in response.headers["content-type"]
    text = response.content.decode("utf-8")
    assert "> readable body" in text
    assert "keep" in text


def test_pdf_export_is_refused_for_a_text_material(client: TestClient) -> None:
    material = _upload(client, name="notes.txt", data=b"plain readable text content")

    response = client.get(
        f"/api/reading/materials/{material['material_id']}/export",
        params={"fmt": "pdf"},
    )

    assert response.status_code == 400


def test_export_filename_survives_non_ascii(client: TestClient) -> None:
    material = _upload(client, name="注意力机制.pdf")

    response = client.get(f"/api/reading/materials/{material['material_id']}/export")

    disposition = response.headers["content-disposition"]
    assert "filename*=UTF-8''" in disposition


def test_export_rejects_an_unknown_format(client: TestClient) -> None:
    material = _upload(client)

    response = client.get(
        f"/api/reading/materials/{material['material_id']}/export",
        params={"fmt": "docx"},
    )

    assert response.status_code == 422


def test_library_lists_collection_membership_and_totals(client: TestClient) -> None:
    shared = _upload(client, name="shared.pdf")
    orphan = _upload(client, name="orphan.pdf", data=_pdf_bytes(["Only page. Alone."]))
    for title in ("Close reading", "Seminar prep"):
        created = client.post(
            "/api/reading/workspaces",
            json={"title": title, "material_ids": [shared["material_id"]]},
        )
        assert created.status_code == 201, created.text

    payload = client.get("/api/reading/library/materials").json()
    rows = {row["material_id"]: row for row in payload["materials"]}

    assert [row["title"] for row in rows[shared["material_id"]]["collections"]] == [
        "Close reading",
        "Seminar prep",
    ]
    assert rows[orphan["material_id"]]["collections"] == []
    assert rows[shared["material_id"]]["size_bytes"] > 0
    assert rows[shared["material_id"]]["unit_count"] == len(PAGES)
    assert payload["counts"]["all"] == 2
    assert payload["counts"]["unassigned"] == 1

    unassigned = client.get(
        "/api/reading/library/materials", params={"filter": "unassigned"}
    ).json()
    assert [row["material_id"] for row in unassigned["materials"]] == [orphan["material_id"]]
    # Counts describe the library, not the filtered page.
    assert unassigned["counts"]["all"] == 2


def test_duplicate_check_separates_same_content_from_same_name(
    client: TestClient,
) -> None:
    data = _pdf_bytes()
    material = _upload(client, name="attention.pdf", data=data)
    client.post(
        "/api/reading/workspaces",
        json={"title": "Close reading", "material_ids": [material["material_id"]]},
    )

    response = client.post(
        "/api/reading/library/duplicate-check",
        json={
            "files": [
                {
                    "filename": "attention.pdf",
                    "content_id": material["material_id"],
                    "size_bytes": len(data),
                },
                {"filename": "attention.pdf", "content_id": "", "mime": "application/pdf"},
                {"filename": "never-seen.pdf", "content_id": ""},
            ]
        },
    )

    matches = response.json()["matches"]
    assert [row["kind"] for row in matches] == ["same_content", "same_name"]
    assert matches[0]["material"]["material_id"] == material["material_id"]
    assert [row["title"] for row in matches[0]["collections"]] == ["Close reading"]


def test_reuse_false_keeps_a_second_copy_with_its_own_annotations(
    client: TestClient,
) -> None:
    data = _pdf_bytes()
    first = _upload(client, name="attention.pdf", data=data)
    second = client.post(
        "/api/reading/materials",
        params={"reuse": "false"},
        files={"file": ("attention.pdf", io.BytesIO(data), "application/pdf")},
    )
    assert second.status_code == 200, second.text
    second_id = second.json()["material_id"]

    assert second_id != first["material_id"]
    client.put(
        f"/api/reading/materials/{first['material_id']}/annotations",
        json={"locator": 1, "quote": "Sequence models", "note": "first copy"},
    )

    assert len(client.get(f"/api/reading/materials/{first['material_id']}/annotations").json()) == 1
    # The second copy shares the extracted text but none of the reading state.
    assert client.get(f"/api/reading/materials/{second_id}/annotations").json() == []
    assert client.get(f"/api/reading/materials/{second_id}/units/1").json()["text"]


def test_deleting_a_material_reports_where_it_was_used(client: TestClient) -> None:
    data = _pdf_bytes()
    first = _upload(client, name="attention.pdf", data=data)
    second_id = client.post(
        "/api/reading/materials",
        params={"reuse": "false"},
        files={"file": ("attention.pdf", io.BytesIO(data), "application/pdf")},
    ).json()["material_id"]
    client.post(
        "/api/reading/workspaces",
        json={"title": "Close reading", "material_ids": [first["material_id"]]},
    )

    removed = client.request("DELETE", f"/api/reading/materials/{first['material_id']}").json()

    assert [row["title"] for row in removed["removed_from"]] == ["Close reading"]
    # The sibling still reads the same extracted content, so it survives.
    assert client.get(f"/api/reading/materials/{second_id}/units/1").json()["text"]
