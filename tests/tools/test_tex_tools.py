"""Tests for deeptutor.tools.tex_downloader and deeptutor.tools.tex_chunker.

Covers the happy paths (download + extract + locate main tex; section/paragraph
chunking), boundary inputs (empty, oversized, malformed archives, path-traversal
members) and the mocked network-failure branches. No real network access.
"""

from __future__ import annotations

import io
from pathlib import Path
import tarfile
from unittest.mock import MagicMock
import zipfile

import pytest
import requests

from deeptutor.tools.tex_chunker import TexChunker
import deeptutor.tools.tex_downloader as tex_downloader_module
from deeptutor.tools.tex_downloader import (
    TexDownloader,
    TexDownloadResult,
    read_tex_file,
)

MIN_TEX = "\\documentclass{article}\n\\begin{document}\nHello arxiv.\n\\end{document}\n"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_tar_bytes(files: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with tarfile.open(fileobj=buf, mode="w") as tar:
        for name, data in files.items():
            info = tarfile.TarInfo(name=name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))
    return buf.getvalue()


def _make_zip_bytes(files: dict[str, bytes]) -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        for name, data in files.items():
            zf.writestr(name, data)
    return buf.getvalue()


def _mock_response(content: bytes) -> MagicMock:
    response = MagicMock()
    response.content = content
    response.raise_for_status.return_value = None
    return response


@pytest.fixture()
def downloader(tmp_path: Path) -> TexDownloader:
    return TexDownloader(workspace_dir=str(tmp_path / "ws"))


# ---------------------------------------------------------------------------
# TexDownloader — construction and result object
# ---------------------------------------------------------------------------


class TestTexDownloaderBasics:
    def test_workspace_dir_created_recursively(self, tmp_path: Path) -> None:
        nested = tmp_path / "a" / "b" / "ws"
        TexDownloader(workspace_dir=str(nested))
        assert nested.is_dir()

    def test_existing_workspace_reused(self, tmp_path: Path) -> None:
        ws = tmp_path / "ws"
        ws.mkdir()
        marker = ws / "keep.txt"
        marker.write_text("keep", encoding="utf-8")
        TexDownloader(workspace_dir=str(ws))
        assert marker.read_text(encoding="utf-8") == "keep"

    def test_result_defaults(self) -> None:
        result = TexDownloadResult(success=False)
        assert result.success is False
        assert result.tex_path is None
        assert result.tex_content is None
        assert result.error is None


# ---------------------------------------------------------------------------
# TexDownloader — ArXiv ID extraction
# ---------------------------------------------------------------------------


class TestExtractArxivId:
    def test_abs_url(self, downloader: TexDownloader) -> None:
        assert downloader._extract_arxiv_id("https://arxiv.org/abs/1706.03762") == "1706.03762"

    def test_pdf_url_with_version(self, downloader: TexDownloader) -> None:
        assert downloader._extract_arxiv_id("https://arxiv.org/pdf/2401.12345v2") == "2401.12345"

    def test_unrelated_url_returns_none(self, downloader: TexDownloader) -> None:
        assert downloader._extract_arxiv_id("https://example.com/paper") is None

    def test_empty_url_returns_none(self, downloader: TexDownloader) -> None:
        assert downloader._extract_arxiv_id("") is None


# ---------------------------------------------------------------------------
# TexDownloader — download + extract happy paths (network mocked)
# ---------------------------------------------------------------------------


class TestDownloadHappyPaths:
    def test_tar_source_lands_in_paper_dir(self, downloader: TexDownloader, tmp_path: Path) -> None:
        payload = _make_tar_bytes({"main.tex": MIN_TEX.encode("utf-8")})

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(
                tex_downloader_module.requests, "get", lambda *a, **k: _mock_response(payload)
            )
            result = downloader.download_arxiv_source(
                "https://arxiv.org/abs/1706.03762", arxiv_id="1706.03762"
            )

        assert result.success is True, result.error
        assert result.tex_path is not None
        assert Path(result.tex_path) == tmp_path / "ws" / "paper_1706.03762" / "main.tex"
        assert result.tex_content == MIN_TEX
        # temporary extraction dir is cleaned up, only the permanent paper dir remains
        assert [p.name for p in (tmp_path / "ws").iterdir()] == ["paper_1706.03762"]

    def test_zip_source_picks_paper_tex(self, downloader: TexDownloader, tmp_path: Path) -> None:
        payload = _make_zip_bytes({"paper.tex": MIN_TEX.encode("utf-8")})

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(
                tex_downloader_module.requests, "get", lambda *a, **k: _mock_response(payload)
            )
            result = downloader.download_arxiv_source(
                "https://arxiv.org/pdf/2401.12345", arxiv_id="2401.12345"
            )

        assert result.success is True, result.error
        assert Path(result.tex_path).name == "main.tex"  # always finalised to main.tex
        assert result.tex_content == MIN_TEX

    def test_plain_bytes_treated_as_single_tex_file(self, downloader: TexDownloader) -> None:
        # Not a tar, not a zip → stored as <arxiv_id>.tex and still found.
        payload = b"some raw tex body without documentclass"

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(
                tex_downloader_module.requests, "get", lambda *a, **k: _mock_response(payload)
            )
            result = downloader.download_arxiv_source(
                "https://arxiv.org/abs/2101.00001", arxiv_id="2101.00001"
            )

        assert result.success is True, result.error
        assert result.tex_content == "some raw tex body without documentclass"

    def test_arxiv_id_taken_from_url_when_arg_missing(self, downloader: TexDownloader) -> None:
        payload = _make_tar_bytes({"main.tex": MIN_TEX.encode("utf-8")})

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(
                tex_downloader_module.requests, "get", lambda *a, **k: _mock_response(payload)
            )
            result = downloader.download_arxiv_source("https://arxiv.org/abs/2401.12345v2")

        assert result.success is True, result.error
        assert "paper_2401.12345" in result.tex_path


# ---------------------------------------------------------------------------
# TexDownloader — failure branches
# ---------------------------------------------------------------------------


class TestDownloadFailureBranches:
    def test_unextractable_id_fails_fast(self, downloader: TexDownloader) -> None:
        result = downloader.download_arxiv_source("https://example.com/no-id")
        assert result.success is False
        assert result.error == "Unable to extract ArXiv ID"

    def test_network_error_maps_to_download_failed(self, downloader: TexDownloader) -> None:
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(
                tex_downloader_module.requests,
                "get",
                lambda *a, **k: (_ for _ in ()).throw(
                    requests.exceptions.ConnectionError("conn refused")
                ),
            )
            result = downloader.download_arxiv_source(
                "https://arxiv.org/abs/1706.03762", arxiv_id="1706.03762"
            )

        assert result.success is False
        assert result.error is not None
        assert result.error.startswith("Download failed")
        assert "conn refused" in result.error

    def test_http_error_maps_to_download_failed(self, downloader: TexDownloader) -> None:
        response = MagicMock()
        response.raise_for_status.side_effect = requests.exceptions.HTTPError("404")

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(tex_downloader_module.requests, "get", lambda *a, **k: response)
            result = downloader.download_arxiv_source(
                "https://arxiv.org/abs/1706.03762", arxiv_id="1706.03762"
            )

        assert result.success is False
        assert result.error is not None
        assert result.error.startswith("Download failed")
        assert "404" in result.error

    def test_processing_error_maps_to_processing_failed(self, downloader: TexDownloader) -> None:
        payload = _make_tar_bytes({"main.tex": MIN_TEX.encode("utf-8")})

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(
                tex_downloader_module.requests, "get", lambda *a, **k: _mock_response(payload)
            )
            mp.setattr(
                downloader,
                "_find_main_tex",
                lambda *a, **k: (_ for _ in ()).throw(RuntimeError("boom")),
            )
            result = downloader.download_arxiv_source(
                "https://arxiv.org/abs/1706.03762", arxiv_id="1706.03762"
            )

        assert result.success is False
        assert result.error == "Processing failed: boom"

    def test_archive_without_tex_reports_main_not_found(self, downloader: TexDownloader) -> None:
        payload = _make_tar_bytes({"README.txt": b"no tex here"})

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(
                tex_downloader_module.requests, "get", lambda *a, **k: _mock_response(payload)
            )
            result = downloader.download_arxiv_source(
                "https://arxiv.org/abs/1706.03762", arxiv_id="1706.03762"
            )

        assert result.success is False
        assert result.error == "Main tex file not found"

    def test_tar_path_traversal_member_is_skipped(
        self, downloader: TexDownloader, tmp_path: Path
    ) -> None:
        # TarSlip guard: "../evil.tex" must not be written anywhere in the workspace.
        payload = _make_tar_bytes({"../evil.tex": b"malicious"})

        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(
                tex_downloader_module.requests, "get", lambda *a, **k: _mock_response(payload)
            )
            result = downloader.download_arxiv_source(
                "https://arxiv.org/abs/1706.03762", arxiv_id="1706.03762"
            )

        assert result.success is False
        assert result.error == "Main tex file not found"
        assert list(tmp_path.rglob("evil.tex")) == []


# ---------------------------------------------------------------------------
# TexDownloader — main tex selection priority
# ---------------------------------------------------------------------------


class TestFindMainTex:
    def test_prefers_main_tex_over_documentclass(
        self, downloader: TexDownloader, tmp_path: Path
    ) -> None:
        (tmp_path / " appendix.tex").write_text("\\documentclass{book}", encoding="utf-8")
        (tmp_path / "main.tex").write_text("main", encoding="utf-8")
        found = downloader._find_main_tex(tmp_path)
        assert found is not None and found.name == "main.tex"

    def test_falls_back_to_documentclass_file(
        self, downloader: TexDownloader, tmp_path: Path
    ) -> None:
        (tmp_path / "chapter.tex").write_text("no marker", encoding="utf-8")
        (tmp_path / "chapter-a.tex").write_text("\\documentclass{article}", encoding="utf-8")
        found = downloader._find_main_tex(tmp_path)
        assert found is not None and found.name == "chapter-a.tex"

    def test_falls_back_to_largest_tex(self, downloader: TexDownloader, tmp_path: Path) -> None:
        (tmp_path / "a.tex").write_text("x", encoding="utf-8")
        (tmp_path / "b.tex").write_text("x" * 500, encoding="utf-8")
        found = downloader._find_main_tex(tmp_path)
        assert found is not None and found.name == "b.tex"

    def test_no_tex_files_returns_none(self, downloader: TexDownloader, tmp_path: Path) -> None:
        (tmp_path / "notes.txt").write_text("nothing", encoding="utf-8")
        assert downloader._find_main_tex(tmp_path) is None

    def test_mixed_case_main_tex_matched(self, downloader: TexDownloader, tmp_path: Path) -> None:
        # Name comparison is case-insensitive for files that match the *.tex glob.
        (tmp_path / "Main.tex").write_text("mixed", encoding="utf-8")
        found = downloader._find_main_tex(tmp_path)
        assert found is not None and found.name == "Main.tex"

    def test_uppercase_extension_file_is_invisible(
        self, downloader: TexDownloader, tmp_path: Path
    ) -> None:
        # Known limitation: discovery globs "*.tex" case-sensitively, so a file
        # named MAIN.TEX is never even considered a candidate.
        (tmp_path / "MAIN.TEX").write_text("upper", encoding="utf-8")
        assert downloader._find_main_tex(tmp_path) is None


# ---------------------------------------------------------------------------
# read_tex_file convenience function
# ---------------------------------------------------------------------------


class TestReadTexFile:
    def test_reads_utf8_content(self, tmp_path: Path) -> None:
        tex = tmp_path / "paper.tex"
        tex.write_text("\\section{引言}\n内容", encoding="utf-8")
        assert read_tex_file(str(tex)) == "\\section{引言}\n内容"

    def test_invalid_utf8_bytes_are_ignored_not_raised(self, tmp_path: Path) -> None:
        tex = tmp_path / "broken.tex"
        tex.write_bytes(b"ok \\documentclass \xff\xfe end")
        content = read_tex_file(str(tex))
        assert content.startswith("ok \\documentclass")


# ---------------------------------------------------------------------------
# TexChunker — construction
# ---------------------------------------------------------------------------


def _cl100k_chunker(monkeypatch: pytest.MonkeyPatch) -> TexChunker:
    """Chunker forced onto the cl100k_base fallback, independent of local LLM config."""
    import deeptutor.tools.tex_chunker as chunker_module

    def _raise() -> None:
        raise RuntimeError("no llm config in tests")

    monkeypatch.setattr(chunker_module, "resolve_llm_runtime_config", _raise)
    return TexChunker()


class TestTexChunkerInit:
    def test_no_model_resolves_fallback_encoding(self, monkeypatch: pytest.MonkeyPatch) -> None:
        chunker = _cl100k_chunker(monkeypatch)
        assert chunker.encoder.name == "cl100k_base"

    def test_unsupported_model_falls_back_to_cl100k(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            "deeptutor.tools.tex_chunker.resolve_llm_runtime_config",
            lambda: MagicMock(model="definitely-not-a-real-model"),
        )
        chunker = TexChunker(model="definitely-not-a-real-model")
        assert chunker.encoder.name == "cl100k_base"

    def test_supported_model_uses_its_encoding(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            "deeptutor.tools.tex_chunker.resolve_llm_runtime_config",
            lambda: MagicMock(model="gpt-4o"),
        )
        chunker = TexChunker(model="gpt-4o")
        assert chunker.encoder.name in {"o200k_base", "cl100k_base"}


# ---------------------------------------------------------------------------
# TexChunker — token estimation and text cleaning
# ---------------------------------------------------------------------------


class TestEstimateTokens:
    def test_empty_string_is_zero_tokens(self, monkeypatch: pytest.MonkeyPatch) -> None:
        assert _cl100k_chunker(monkeypatch).estimate_tokens("") == 0

    def test_estimation_is_positive_and_monotonic(self, monkeypatch: pytest.MonkeyPatch) -> None:
        chunker = _cl100k_chunker(monkeypatch)
        short = chunker.estimate_tokens("one two three")
        longer = chunker.estimate_tokens("one two three four five six seven eight")
        assert short > 0
        assert longer > short

    def test_encoder_failure_falls_back_to_char_estimate(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        chunker = _cl100k_chunker(monkeypatch)

        def _boom(text: str) -> list[int]:
            raise RuntimeError("encode failed")

        monkeypatch.setattr(chunker.encoder, "encode", _boom)
        text = "x" * 40
        assert chunker.estimate_tokens(text) == len(text) // 4


class TestCleanText:
    def test_collapses_repeated_whitespace(self, monkeypatch: pytest.MonkeyPatch) -> None:
        chunker = _cl100k_chunker(monkeypatch)
        cleaned = chunker._clean_text("a" + "\n" * 200 + "b")
        assert "\n" * 10 in cleaned
        assert "\n" * 11 not in cleaned

    def test_truncates_overlong_single_line(self, monkeypatch: pytest.MonkeyPatch) -> None:
        chunker = _cl100k_chunker(monkeypatch)
        cleaned = chunker._clean_text("x" * 15000)
        assert cleaned.endswith("...[truncated]")
        assert len(cleaned) == 10000 + len("...[truncated]")

    def test_normal_lines_pass_through(self, monkeypatch: pytest.MonkeyPatch) -> None:
        chunker = _cl100k_chunker(monkeypatch)
        text = "line one\nline two\nline three"
        assert chunker._clean_text(text) == text


# ---------------------------------------------------------------------------
# TexChunker — chunking
# ---------------------------------------------------------------------------

SECTION_DOC = (
    "\\documentclass{article}\n\\begin{document}\n"
    + "\n\n".join(
        f"\\section{{Section {i}}}\nParagraph {i} explains topic {i} with words.\n"
        f"Second paragraph of section {i} adds more detail words here."
        for i in range(12)
    )
    + "\n\\end{document}\n"
)


class TestSplitTexIntoChunks:
    def test_short_content_passes_through_verbatim(self, monkeypatch: pytest.MonkeyPatch) -> None:
        chunker = _cl100k_chunker(monkeypatch)
        content = "\\section{Intro}\nShort body."
        assert chunker.split_tex_into_chunks(content, max_tokens=10_000) == [content]

    def test_empty_content_returns_single_empty_chunk(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        chunker = _cl100k_chunker(monkeypatch)
        result = chunker.split_tex_into_chunks("", max_tokens=100)
        assert result == [""]

    def test_sectioned_document_splits_into_bounded_chunks(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        chunker = _cl100k_chunker(monkeypatch)
        max_tokens = 120
        chunks = chunker.split_tex_into_chunks(SECTION_DOC, max_tokens=max_tokens, overlap=0)
        assert len(chunks) > 1
        for chunk in chunks:
            assert chunker.estimate_tokens(chunk) <= max_tokens
        joined = "\n".join(chunks)
        for i in range(12):
            assert f"\\section{{Section {i}}}" in joined

    def test_single_oversized_section_splits_by_paragraphs(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        chunker = _cl100k_chunker(monkeypatch)
        body = "\n\n".join(
            f"Paragraph {i} contains several words of body text for testing." for i in range(40)
        )
        doc = f"\\section{{Huge}}\n{body}"
        max_tokens = 60
        chunks = chunker.split_tex_into_chunks(doc, max_tokens=max_tokens, overlap=0)
        assert len(chunks) > 1
        for chunk in chunks:
            assert chunker.estimate_tokens(chunk) <= max_tokens

    def test_document_without_sections_still_chunks(self, monkeypatch: pytest.MonkeyPatch) -> None:
        chunker = _cl100k_chunker(monkeypatch)
        doc = "\n\n".join(
            f"Plain paragraph number {i} with a handful of ordinary words." for i in range(40)
        )
        chunks = chunker.split_tex_into_chunks(doc, max_tokens=80, overlap=0)
        assert len(chunks) > 1
        for chunk in chunks:
            assert chunker.estimate_tokens(chunk) <= 80

    def test_overlap_connects_adjacent_chunks(self, monkeypatch: pytest.MonkeyPatch) -> None:
        chunker = _cl100k_chunker(monkeypatch)
        chunks = chunker.split_tex_into_chunks(SECTION_DOC, max_tokens=120, overlap=50)
        assert len(chunks) > 1
        # The second chunk must open with text taken from the tail of the first.
        assert chunks[1][:40] in chunks[0]

    def test_degenerate_single_sentence_cannot_be_split(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # One huge paragraph without any sentence-ending punctuation cannot be
        # split below max_tokens by the current strategy: the blob is emitted
        # oversized (known limitation), possibly next to a blank trailing chunk.
        chunker = _cl100k_chunker(monkeypatch)
        doc = "a" * 6000
        chunks = chunker.split_tex_into_chunks(doc, max_tokens=50, overlap=0)
        assert chunks
        assert chunker.estimate_tokens(chunks[0]) > 50
        assert "".join(chunks).strip() == doc

    def test_tiny_max_tokens_never_hangs_or_crashes(self, monkeypatch: pytest.MonkeyPatch) -> None:
        chunker = _cl100k_chunker(monkeypatch)
        chunks = chunker.split_tex_into_chunks(SECTION_DOC, max_tokens=1, overlap=0)
        assert chunks  # produces something instead of failing


class TestGetOverlapText:
    def test_shorter_chunk_returned_whole(self, monkeypatch: pytest.MonkeyPatch) -> None:
        chunker = _cl100k_chunker(monkeypatch)
        assert chunker._get_overlap_text("tiny", 100) == "tiny"

    def test_tail_overlap_is_suffix_of_previous_chunk(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        chunker = _cl100k_chunker(monkeypatch)
        text = " ".join(f"word{i}" for i in range(200))
        overlap = chunker._get_overlap_text(text, 10)
        assert overlap
        assert overlap in text
        assert text.endswith(overlap)
