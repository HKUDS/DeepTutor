from __future__ import annotations

import logging
from pathlib import Path

import pytest

from deeptutor.reading import ingestion as ingestion_module
from deeptutor.reading.catalog_models import IngestionStatus, SourceKind
from deeptutor.reading.catalog_store import ReadingCatalogStore
from deeptutor.reading.extract import (
    SECTION_HARD_CHARS,
    split_into_sections,
    split_markdown_by_headings,
)
from deeptutor.reading.ingestion import (
    MAX_TRANSCRIPT_BYTES,
    TRANSCRIPT_UNAVAILABLE_TEXT,
    BilibiliMedia,
    ReadingIngestionService,
    TranscriptSegment,
    build_transcript_segments,
    normalize_transcript_segments,
    parse_bilibili_url,
    parse_youtube_url,
)
from deeptutor.reading.models import ReadingError
from deeptutor.reading.store import ReadingStore
from deeptutor.services.web_source.snapshot_assets import SnapshotAsset
from deeptutor.tools.web_fetch import FetchOutcome, _extract_readable

_ARTICLE_FIXTURE = Path(__file__).parents[1] / "fixtures" / "web" / "vector_article.html"


@pytest.fixture
def stores(tmp_path: Path):
    root = tmp_path / "reading"
    return ReadingStore(root), ReadingCatalogStore(root)


@pytest.mark.asyncio
async def test_web_import_uses_safe_fetch_result_and_builds_sections(stores) -> None:
    reading, catalog = stores

    async def fetcher(url: str, **_kwargs):
        return FetchOutcome(
            ok=True,
            url=url,
            title="A careful article",
            markdown="# A careful article\n\nFirst claim.\n\nSecond claim.",
        )

    service = ReadingIngestionService(reading, catalog, web_fetcher=fetcher)
    queued = service.queue_url("https://example.com/article")
    ready = await service.process_url(queued.material_id)

    assert queued.status is IngestionStatus.QUEUED
    assert ready.status is IngestionStatus.READY
    assert ready.source_kind is SourceKind.WEB
    manifest = reading.manifest(ready.material_id)
    assert manifest.title == "A careful article"
    assert "First claim" in reading.unit_text(ready.material_id, 1)
    assert reading.outline(ready.material_id)[0].synthesised is True


@pytest.mark.asyncio
async def test_web_import_is_rich_localizes_images_and_preserves_old_revision(stores) -> None:
    reading, catalog = stores
    url = "https://example.com/article"

    async def fetcher(_url: str, **_kwargs):
        return FetchOutcome(
            ok=True,
            url="https://example.com/final/article",
            title="Snapshot",
            markdown=(
                "<!-- source: https://example.com/legacy -->\n"
                "# Snapshot\n\n![Diagram](https://cdn.example.com/diagram.png)"
            ),
        )

    async def image_fetcher(_url: str):
        return SnapshotAsset(b"\x89PNG\r\n\x1a\nimage", "image/png", "png")

    service = ReadingIngestionService(
        reading,
        catalog,
        web_fetcher=fetcher,
        image_fetcher=image_fetcher,
    )
    queued = service.queue_url(url)
    reading.ingest_units(
        queued.material_id,
        filename=f"{queued.material_id}.md",
        units=["<!-- source: https://example.com/old -->\n# Old snapshot"],
        source_type="url_snapshot",
        source_url=url,
    )

    ready = await service.process_url(queued.material_id)
    manifest = reading.manifest(ready.material_id)
    current = reading.unit_text(ready.material_id, 1)

    assert manifest.content_format == "web_markdown"
    assert manifest.source_url == "https://example.com/final/article"
    assert manifest.revision == 2
    assert "<!-- source:" not in current
    assert "/api/reading/materials/" in current
    assert (
        reading.asset_path(
            ready.material_id,
            next((reading._dir(ready.material_id) / "assets").iterdir()).name,
        )
        is not None
    )
    revisions = reading.revisions(ready.material_id)
    assert [row.revision for row in revisions] == [1]
    assert "# Old snapshot" in reading.revision_unit_text(ready.material_id, 1, 1)


@pytest.mark.asyncio
async def test_web_article_fixture_builds_heading_derived_outline(stores) -> None:
    reading, catalog = stores
    title, markdown = _extract_readable(_ARTICLE_FIXTURE.read_text(encoding="utf-8"))

    async def fetcher(url: str, **_kwargs):
        return FetchOutcome(ok=True, url=url, title=title, markdown=markdown)

    service = ReadingIngestionService(reading, catalog, web_fetcher=fetcher)
    queued = service.queue_url("https://example.com/structured-article")
    ready = await service.process_url(queued.material_id)

    assert ready.status is IngestionStatus.READY
    assert reading.manifest(ready.material_id).unit_count == 4
    outline = reading.outline(ready.material_id)
    assert [(row.locator, row.title, row.level) for row in outline] == [
        (1, "Transformer (deep learning)", 1),
        (2, "History", 2),
        (3, "Predecessors", 3),
        (4, "Applications", 2),
    ]
    assert all(row.synthesised is False for row in outline)
    stored_text = "\n".join(
        reading.unit_text(ready.material_id, locator) for locator in range(1, 5)
    )
    assert "Jump to content" not in stored_text
    assert "navigation footer" not in stored_text


def test_heading_sections_keep_long_continuations_under_the_same_title() -> None:
    markdown = (
        "# Article\n\nLead.\n\n## Long section\n\n"
        + ("history detail " * (SECTION_HARD_CHARS // 8))
        + "\n\n## Finish\n\nDone."
    )

    units, outline = split_markdown_by_headings(markdown)

    long_rows = [row for row in outline if row.title == "Long section"]
    assert len(long_rows) > 1
    assert [row.locator for row in long_rows] == list(
        range(long_rows[0].locator, long_rows[-1].locator + 1)
    )
    # The first piece also carries the heading line; the paragraph payload
    # itself still obeys the existing hard-split limit.
    assert all(
        len(units[row.locator - 1]) <= SECTION_HARD_CHARS + len("## Long section\n\n")
        for row in long_rows
    )


def test_heading_splitter_falls_back_when_only_the_page_title_exists() -> None:
    markdown = "# Article title\n\nA flat article paragraph.\n\nAnother paragraph."

    units, outline = split_markdown_by_headings(markdown)

    assert units == split_into_sections(markdown)
    assert outline == ()


@pytest.mark.asyncio
async def test_failed_url_import_is_retryable(stores, caplog: pytest.LogCaptureFixture) -> None:
    _reading, catalog = stores

    async def fetcher(_url: str, **_kwargs):
        return FetchOutcome(ok=False, error="blocked by host policy")

    service = ReadingIngestionService(stores[0], catalog, web_fetcher=fetcher)
    queued = service.queue_url("https://example.com/private")
    with caplog.at_level(logging.ERROR, logger="deeptutor.reading.ingestion"):
        failed = await service.process_url(queued.material_id)

    assert failed.status is IngestionStatus.FAILED
    assert failed.error_code == "web_fetch_failed"
    assert "blocked" in failed.error_detail
    assert "Reading URL ingestion failed" in caplog.text


@pytest.mark.asyncio
async def test_youtube_import_prefers_timed_captions(stores) -> None:
    reading, catalog = stores

    async def youtube_loader(_url: str, _languages):
        return (
            "Retrieval Lecture",
            "https://i.ytimg.com/vi/abc123xyz00/hqdefault.jpg",
            [
                TranscriptSegment(0, 12, "Welcome to the lecture."),
                TranscriptSegment(12, 28, "We now define dense retrieval."),
            ],
        )

    service = ReadingIngestionService(reading, catalog, youtube_loader=youtube_loader)
    queued = service.queue_url("https://youtu.be/abc123xyz00")
    ready = await service.process_url(queued.material_id)

    assert ready.source_kind is SourceKind.YOUTUBE
    assert ready.render_mode == "video"
    assert ready.cover_url.endswith("hqdefault.jpg")
    assert reading.manifest(ready.material_id).unit == "segment"
    assert reading.manifest(ready.material_id).render_mode == "video"
    assert reading.unit_references(ready.material_id)[1].source_href == "#t=12"


@pytest.mark.parametrize(
    ("url", "video_id", "start"),
    [
        ("https://youtu.be/abc123xyz00?t=82", "abc123xyz00", 82),
        ("https://www.youtube.com/watch?v=abc123xyz00&t=1m2s&si=tracking", "abc123xyz00", 62),
        ("https://youtube.com/shorts/abc123xyz00", "abc123xyz00", 0),
        ("https://youtube.com/live/abc123xyz00?start=12", "abc123xyz00", 12),
        ("https://youtube.com/embed/abc123xyz00", "abc123xyz00", 0),
    ],
)
def test_youtube_url_shapes_are_canonical(url: str, video_id: str, start: int) -> None:
    parsed = parse_youtube_url(url)
    assert parsed.video_id == video_id
    assert parsed.entry_time_seconds == start
    assert "si=" not in parsed.canonical_url


@pytest.mark.parametrize(
    "url",
    [
        "javascript:alert(1)",
        "https://example.com/watch?v=abc123xyz00",
        "https://youtube.com/watch?v=../../etc",
        "https://youtube.com.evil.test/watch?v=abc123xyz00",
    ],
)
def test_invalid_youtube_urls_are_rejected(url: str) -> None:
    with pytest.raises(ReadingError):
        parse_youtube_url(url)


@pytest.mark.parametrize(
    ("url", "bvid", "page", "start"),
    [
        ("https://www.bilibili.com/video/BV1E7wtzaEdq/", "BV1E7wtzaEdq", 1, 0),
        ("https://m.bilibili.com/video/BV1E7wtzaEdq?p=2&t=82", "BV1E7wtzaEdq", 2, 82),
        ("https://player.bilibili.com/player.html?bvid=BV1E7wtzaEdq&p=3", "BV1E7wtzaEdq", 3, 0),
        ("https://b23.tv/BV1E7wtzaEdq", "BV1E7wtzaEdq", 1, 0),
    ],
)
def test_bilibili_url_shapes_are_canonical(url: str, bvid: str, page: int, start: int) -> None:
    parsed = parse_bilibili_url(url)
    assert parsed.bvid == bvid
    assert parsed.page_number == page
    assert parsed.entry_time_seconds == start
    assert "spm_id_from=" not in parsed.canonical_url


@pytest.mark.parametrize(
    "url",
    [
        "javascript:alert(1)",
        "https://example.com/video/BV1E7wtzaEdq",
        "https://bilibili.com.evil.test/video/BV1E7wtzaEdq",
        "https://www.bilibili.com/video/not-a-bvid",
        "https://b23.tv/some-short-link",
    ],
)
def test_invalid_bilibili_urls_are_rejected(url: str) -> None:
    with pytest.raises(ReadingError):
        parse_bilibili_url(url)


@pytest.mark.asyncio
async def test_bilibili_import_uses_native_video_metadata_and_subtitles(stores) -> None:
    reading, catalog = stores

    async def bilibili_loader(_url: str, _languages):
        return BilibiliMedia(
            title="Agent Skill",
            cover_url="https://i0.hdslb.com/cover.jpg",
            duration_seconds=1951,
            page_number=1,
            cid=36694721904,
            segments=[TranscriptSegment(0, 31, "视频内容介绍")],
            chapters=[TranscriptSegment(0, 31, "视频内容介绍")],
        )

    service = ReadingIngestionService(reading, catalog, bilibili_loader=bilibili_loader)
    queued = service.queue_url("https://www.bilibili.com/video/BV1E7wtzaEdq/?spm_id_from=tracking")
    ready = await service.process_url(queued.material_id)

    assert queued.source_kind is SourceKind.BILIBILI
    assert ready.source_kind is SourceKind.BILIBILI
    assert ready.duration_seconds == 1951
    assert ready.cover_url.endswith("cover.jpg")
    assert reading.manifest(ready.material_id).extractor == "bilibili-subtitles"
    assert reading.unit_references(ready.material_id)[0].source_href == "#t=0"


@pytest.mark.asyncio
async def test_bilibili_chapters_remain_navigable_without_claiming_transcript(stores) -> None:
    reading, catalog = stores

    async def bilibili_loader(_url: str, _languages):
        return BilibiliMedia(
            title="Chaptered lecture",
            cover_url="",
            duration_seconds=120,
            page_number=1,
            cid=123,
            segments=[],
            chapters=[
                TranscriptSegment(0, 60, "LLM"),
                TranscriptSegment(60, 120, "Agent"),
            ],
        )

    service = ReadingIngestionService(reading, catalog, bilibili_loader=bilibili_loader)
    queued = service.queue_url("https://www.bilibili.com/video/BV1E7wtzaEdq")
    ready = await service.process_url(queued.material_id)

    manifest = reading.manifest(ready.material_id)
    assert manifest.extractor == "bilibili-chapters-only"
    assert reading.unit_references(ready.material_id)[1].source_href == "#t=60"
    assert "Chapter marker: Agent" in reading.unit_text(ready.material_id, 2)
    assert "Spoken transcript unavailable" in reading.unit_text(ready.material_id, 2)


def test_caption_flashes_become_stable_learning_segments() -> None:
    cues = [
        TranscriptSegment(0.0, 10.0, "One"),
        TranscriptSegment(10.0, 22.0, "sentence."),
        TranscriptSegment(22.0, 45.0, "Next concept."),
    ]
    segments = build_transcript_segments(cues)
    assert segments[0] == TranscriptSegment(0.0, 22.0, "One sentence.")
    assert segments[1].start_seconds == 22.0


def test_transcript_normalization_has_a_storage_budget(monkeypatch) -> None:
    monkeypatch.setattr("deeptutor.reading.ingestion.MAX_TRANSCRIPT_BYTES", 8)
    cues = normalize_transcript_segments(
        [
            {"start": 0, "duration": 1, "text": "1234"},
            {"start": 1, "duration": 1, "text": "5678"},
            {"start": 2, "duration": 1, "text": "overflow"},
        ]
    )
    assert MAX_TRANSCRIPT_BYTES > 8
    assert [cue.text for cue in cues] == ["1234", "5678"]


@pytest.mark.asyncio
async def test_missing_youtube_captions_does_not_block_native_playback(stores) -> None:
    reading, catalog = stores

    async def youtube_loader(_url: str, _languages):
        return "Visual lecture", "", []

    service = ReadingIngestionService(reading, catalog, youtube_loader=youtube_loader)
    queued = service.queue_url("https://youtube.com/live/abc123xyz00?start=12")
    ready = await service.process_url(queued.material_id)

    manifest = reading.manifest(ready.material_id)
    assert ready.status is IngestionStatus.READY
    assert manifest.extractor == "youtube-no-captions"
    assert reading.unit_text(ready.material_id, 1) == TRANSCRIPT_UNAVAILABLE_TEXT
    assert reading.unit_references(ready.material_id)[0].source_href == "#t=12"


@pytest.mark.asyncio
async def test_local_video_keeps_playable_raw_and_transcribes_chunks(
    stores, tmp_path: Path
) -> None:
    reading, catalog = stores
    source = tmp_path / "lecture.mp4"
    source.write_bytes(b"fake but stable video bytes")

    async def chunker(_path: Path):
        return [(0.0, 600.0, b"audio-one"), (600.0, 720.0, b"audio-two")]

    async def transcriber(audio: bytes, **_kwargs):
        return "first section" if audio == b"audio-one" else "second section"

    service = ReadingIngestionService(
        reading,
        catalog,
        media_chunker=chunker,
        transcriber=transcriber,
    )
    ready = await service.import_media(source, filename="lecture.mp4")

    assert ready.status is IngestionStatus.READY
    assert ready.source_kind is SourceKind.VIDEO
    assert reading.manifest(ready.material_id).render_mode == "video"
    assert reading.raw_path(ready.material_id).read_bytes() == source.read_bytes()
    assert reading.unit_text(ready.material_id, 2) == "second section"


@pytest.mark.asyncio
async def test_media_without_a_configured_provider_fails_before_running_ffmpeg(
    stores, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Name the missing setting, and do not spend ffmpeg proving it is missing."""
    reading, catalog = stores
    source = tmp_path / "lecture.mp4"
    source.write_bytes(b"video bytes")
    ran = {"chunker": False}

    async def chunker(_path: Path):
        ran["chunker"] = True
        return []

    monkeypatch.setattr(
        ingestion_module,
        "_probe_stt_configuration",
        lambda: "No active STT model is configured. Set it in Settings > Voice.",
    )
    service = ReadingIngestionService(reading, catalog, media_chunker=chunker)
    service._probes_stt = True

    queued = await service.queue_media(source, filename="lecture.mp4")
    failed = await service.process_media(queued.material_id)

    assert failed.status is IngestionStatus.FAILED
    assert failed.error_code == "stt_not_configured"
    assert "Settings > Voice" in failed.error_detail
    assert ran["chunker"] is False
    # The upload survives the failure, so configuring a provider and retrying
    # is all the user has to do.
    assert reading.raw_path(queued.material_id).read_bytes() == b"video bytes"


@pytest.mark.asyncio
async def test_media_retry_reruns_transcription_from_the_stored_original(
    stores, tmp_path: Path
) -> None:
    """A failed transcription must not cost the user the upload.

    The original is stored before speech-to-text is attempted, so retrying is
    a server-side re-run — not "please find that two-gigabyte lecture again".
    """
    reading, catalog = stores
    source = tmp_path / "lecture.mp4"
    source.write_bytes(b"stable video bytes")
    attempts = {"n": 0}

    async def chunker(_path: Path):
        return [(0.0, 600.0, b"audio-one")]

    async def transcriber(_audio: bytes, **_kwargs):
        attempts["n"] += 1
        if attempts["n"] == 1:
            raise RuntimeError("No endpoint URL configured for STT.")
        return "the transcript, second time around"

    service = ReadingIngestionService(
        reading, catalog, media_chunker=chunker, transcriber=transcriber
    )
    queued = await service.queue_media(source, filename="lecture.mp4")
    failed = await service.process_media(queued.material_id)

    assert failed.status is IngestionStatus.FAILED
    # Still playable while it is broken: the bytes never depended on the text.
    assert reading.raw_path(queued.material_id).read_bytes() == b"stable video bytes"

    recovered = await service.retry(queued.material_id)

    assert recovered.status is IngestionStatus.READY
    assert reading.unit_text(queued.material_id, 1) == "the transcript, second time around"
    assert reading.raw_path(queued.material_id).read_bytes() == b"stable video bytes"


@pytest.mark.asyncio
async def test_media_ingestion_failure_is_logged_and_persisted(
    stores,
    tmp_path: Path,
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _reading, catalog = stores
    source = tmp_path / "broken.mp4"
    source.write_bytes(b"broken video")

    async def failing_chunker(_path: Path):
        raise RuntimeError("decoder crashed")

    monkeypatch.setattr(ingestion_module, "_probe_stt_configuration", lambda: "")
    service = ReadingIngestionService(*stores, media_chunker=failing_chunker)
    with caplog.at_level(logging.ERROR, logger="deeptutor.reading.ingestion"):
        with pytest.raises(RuntimeError, match="decoder crashed"):
            await service.import_media(source)

    material_id = next(row.material_id for row in catalog.list_materials())
    failed = catalog.get_material(material_id)
    assert failed is not None
    assert failed.status is IngestionStatus.FAILED
    assert "Reading media ingestion failed" in caplog.text
