"""MinerU cloud (mineru.net) v4 API backend.

Implements the token-required *Precision API* flow for one local input:

1. ``POST /api/v4/file-urls/batch`` → ``{batch_id, file_urls: [signed_url]}``
2. ``PUT`` the raw file bytes to ``signed_url`` (no auth, no Content-Type)
3. Poll ``GET /api/v4/extract-results/batch/{batch_id}`` until the file's
   ``state`` reaches ``done`` / ``failed``
4. Download the ``full_zip_url`` archive and extract it into a working dir
   whose layout matches the local CLI output (``*.md`` +
   ``*_content_list.json`` + ``images/``), so the downstream question
   extractor is backend-agnostic.

The module is synchronous on purpose: it runs inside the worker thread that
:func:`deeptutor.agents.question.mimic_source.parse_exam_paper_to_templates`
spawns via ``asyncio.to_thread``, so a blocking ``httpx.Client`` is the
simplest correct choice (no nested event loop).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import io
import json
import logging
from pathlib import Path
import shutil
import tempfile
import time
import zipfile

import httpx
from pypdf import PdfReader, PdfWriter

from deeptutor.services.keypool import KeyPool

from .config import MinerUConfig, MinerUError
from .formats import MINERU_PDF_FORMATS, MINERU_SUPPORTED_FORMATS

logger = logging.getLogger(__name__)

# Async polling defaults. MinerU recommends a 3–5s interval; parsing a typical
# exam paper completes well under a few minutes.
DEFAULT_POLL_INTERVAL_SECONDS = 4.0
DEFAULT_TIMEOUT_SECONDS = 300.0
_SUBMIT_TIMEOUT_SECONDS = 60.0
_UPLOAD_TIMEOUT_SECONDS = 300.0
_DOWNLOAD_TIMEOUT_SECONDS = 300.0

_TERMINAL_OK = "done"
_TERMINAL_FAIL = "failed"

# Bounds for the extracted archive (defends a hostile/buggy CDN response).
_MAX_TOTAL_BYTES = 500 * 1024 * 1024
_MAX_ENTRIES = 5000


def parse_cloud(
    source_path: Path,
    output_base: Path,
    config: MinerUConfig,
    *,
    poll_interval: float = DEFAULT_POLL_INTERVAL_SECONDS,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    on_progress: Callable[[str], None] | None = None,
) -> Path:
    """Parse ``source_path`` via the MinerU cloud API; return the working dir.

    The working dir sits under ``output_base`` (named after the input stem) and
    holds the unzipped MinerU artifacts. ``on_progress`` (if given) receives a
    short status line whenever the polled task state / page count changes.
    Raises :class:`MinerUError` on any misconfiguration, API error, timeout,
    or extraction failure.
    """
    if not config.api_keys:
        raise MinerUError(
            "MinerU cloud mode is selected but no API token is configured. "
            "Add a token in Settings → MinerU, or switch to local mode."
        )
    source_path = Path(source_path)
    if not source_path.is_file():
        raise MinerUError(f"Input file not found: {source_path}")
    if source_path.suffix.lower() not in MINERU_SUPPORTED_FORMATS:
        raise MinerUError(f"Unsupported MinerU cloud input format: {source_path.suffix or 'none'}")

    base_url = config.api_base_url.rstrip("/")
    key_pool = KeyPool(config.api_keys)

    def report(message: str) -> None:
        if on_progress is None:
            return
        try:
            on_progress(message)
        except Exception:
            logger.debug("on_progress callback failed", exc_info=True)

    with httpx.Client(base_url=base_url, headers={"Accept": "application/json"}) as client:
        if source_path.suffix.lower() in MINERU_PDF_FORMATS:
            page_count = _pdf_page_count(source_path)
            if page_count is not None and page_count > config.max_pages_per_part:
                return _parse_pdf_in_parts(
                    client,
                    source_path,
                    output_base,
                    config,
                    key_pool,
                    page_count=page_count,
                    report=report,
                    poll_interval=poll_interval,
                    timeout=timeout,
                )

        report(f"MinerU cloud: requesting upload slot for {source_path.name}")
        archive_bytes = _upload_and_fetch_archive(
            client,
            source_path,
            config,
            key_pool,
            report=report,
            poll_interval=poll_interval,
            timeout=timeout,
        )

    report("MinerU cloud: extracting archive")
    working_dir = output_base / source_path.stem
    _reset_dir(working_dir)
    _extract_archive(archive_bytes, working_dir)
    logger.info("MinerU cloud parse complete: %s → %s", source_path.name, working_dir)
    return working_dir


# ---------------------------------------------------------------------------
# Steps
# ---------------------------------------------------------------------------


def _upload_and_fetch_archive(
    client: httpx.Client,
    part_path: Path,
    config: MinerUConfig,
    key_pool: KeyPool,
    *,
    report: Callable[[str], None],
    poll_interval: float,
    timeout: float,
) -> bytes:
    """Run the upload → poll → download trio for one input file and return the
    result archive bytes. Shared by the single-file path and each slice of the
    auto-split path."""
    report(f"MinerU cloud: requesting upload slot for {part_path.name}")
    batch_id, upload_url = _request_upload(client, part_path, config, key_pool)
    size_mb = part_path.stat().st_size / (1024 * 1024)
    report(f"MinerU cloud: uploading {part_path.name} ({size_mb:.1f} MB)")
    _upload_file(part_path, upload_url)
    zip_url = _poll_for_zip(
        client,
        batch_id,
        part_path.name,
        poll_interval=poll_interval,
        timeout=timeout,
        on_progress=report,
        key_pool=key_pool,
    )
    report("MinerU cloud: downloading parsed result archive")
    return _download(zip_url)


def _parse_pdf_in_parts(
    client: httpx.Client,
    source_path: Path,
    output_base: Path,
    config: MinerUConfig,
    key_pool: KeyPool,
    *,
    page_count: int,
    report: Callable[[str], None],
    poll_interval: float,
    timeout: float,
) -> Path:
    """Slice an oversized PDF, parse each part through the normal cloud flow,
    and merge the per-part artifacts into one working dir that is isomorphic to
    the single-file output (one ``*.md`` + ``*_content_list.json`` + ``images/``)."""
    working_dir = output_base / source_path.stem
    _reset_dir(working_dir)
    markdown_chunks: list[str] = []
    content_items: list = []
    has_content_list = False

    with tempfile.TemporaryDirectory(prefix="mineru-slice-") as tmp:
        parts = _split_pdf(source_path, config.max_pages_per_part, Path(tmp))
        total = len(parts)
        report(
            f"MinerU cloud: {source_path.name} has {page_count} pages, exceeding the "
            f"{config.max_pages_per_part}-page per-file limit; auto-splitting into "
            f"{total} part(s)"
        )
        for index, part in enumerate(parts, start=1):
            report(
                f"MinerU cloud: parsing part {index}/{total} (pages {part.start + 1}-{part.end})"
            )
            archive_bytes = _upload_and_fetch_archive(
                client,
                part.path,
                config,
                key_pool,
                report=report,
                poll_interval=poll_interval,
                timeout=timeout,
            )
            report(f"MinerU cloud: merging part {index}/{total} artifacts")
            with tempfile.TemporaryDirectory(prefix="mineru-part-") as part_tmp:
                part_dir = Path(part_tmp) / "out"
                part_dir.mkdir()
                _extract_archive(archive_bytes, part_dir)
                _merge_part_artifacts(
                    part_dir,
                    working_dir,
                    markdown_chunks=markdown_chunks,
                    content_items=content_items,
                    part_index=index,
                )
                has_content_list = True

    merged_md = "".join(
        chunk if chunk.endswith("\n") else chunk + "\n" for chunk in markdown_chunks
    )
    (working_dir / f"{source_path.stem}.md").write_text(merged_md, encoding="utf-8")
    if has_content_list:
        content_list_path = working_dir / f"{source_path.stem}_content_list.json"
        content_list_path.write_text(
            json.dumps(content_items, ensure_ascii=False), encoding="utf-8"
        )
    logger.info(
        "MinerU cloud parse complete (%d parts): %s → %s", total, source_path.name, working_dir
    )
    return working_dir


def _pdf_page_count(source_path: Path) -> int | None:
    """Number of pages in a PDF, or ``None`` when pypdf cannot read it (e.g. a
    truncated/encrypted file). ``None`` keeps the legacy single-file behaviour —
    an unreadable PDF goes to MinerU as-is and fails there if it is truly broken."""
    try:
        with PdfReader(str(source_path)) as reader:
            return len(reader.pages)
    except Exception:
        logger.warning("Could not count pages of %s; skipping auto-slicing", source_path.name)
        return None


def _split_pdf(source_path: Path, max_pages_per_part: int, work_dir: Path) -> list[_PdfPart]:
    """Evenly cut ``source_path`` into parts of at most ``max_pages_per_part``
    pages (the last part may be shorter) and write each part PDF into
    ``work_dir``. 250 pages @180 → [180, 70]."""
    try:
        with PdfReader(str(source_path)) as reader:
            total = len(reader.pages)
            parts: list[_PdfPart] = []
            for index, start in enumerate(range(0, total, max_pages_per_part), start=1):
                end = min(start + max_pages_per_part, total)
                part_path = work_dir / f"{source_path.stem}_part{index:02d}.pdf"
                writer = PdfWriter()
                for page_number in range(start, end):
                    writer.add_page(reader.pages[page_number])
                with open(part_path, "wb") as out:
                    writer.write(out)
                parts.append(_PdfPart(path=part_path, start=start, end=end))
            return parts
    except Exception as exc:
        raise MinerUError(f"Failed to split PDF {source_path.name} into parts: {exc}") from exc


def _merge_part_artifacts(
    part_dir: Path,
    working_dir: Path,
    *,
    markdown_chunks: list[str],
    content_items: list,
    part_index: int,
) -> None:
    """Accumulate one part's artifacts: markdown text, ``images/`` (renamed with
    a part prefix so names stay globally unique) and ``content_list`` entries
    (with ``img_path`` rewritten to match)."""
    md_files = sorted(path for path in part_dir.rglob("*.md") if path.is_file())
    if not md_files:
        raise MinerUError(f"MinerU part {part_index} archive contains no markdown output.")
    content_root = md_files[0].parent

    rename_map = _copy_part_images(content_root / "images", working_dir / "images", part_index)

    markdown = md_files[0].read_text(encoding="utf-8")
    for original, unique in rename_map.items():
        markdown = markdown.replace(f"images/{original}", f"images/{unique}")
    markdown_chunks.append(markdown)

    for content_list_path in sorted(content_root.glob("*_content_list.json")):
        try:
            payload = json.loads(content_list_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise MinerUError(
                f"MinerU part {part_index} content list is unreadable: {exc}"
            ) from exc
        if isinstance(payload, list):
            _rewrite_image_paths(payload, rename_map)
            content_items.extend(payload)

    # Keep the remaining artifacts (middle/model/layout files, origin PDF, …)
    # on disk with a part prefix, mirroring the single-file layout as closely
    # as their per-part nature allows.
    for extra in sorted(content_root.iterdir()):
        if not extra.is_file() or extra.suffix.lower() == ".md":
            continue
        if extra.name.endswith("_content_list.json"):
            continue
        shutil.copyfile(extra, working_dir / f"part{part_index:02d}_{extra.name}")


def _copy_part_images(images_dir: Path, target_dir: Path, part_index: int) -> dict[str, str]:
    """Copy one part's ``images/`` into the merged ``images/`` dir, prefixing
    each name with the part index so names stay globally unique across parts.
    Returns ``{original_name: unique_name}``."""
    if not images_dir.is_dir():
        return {}
    target_dir.mkdir(parents=True, exist_ok=True)
    rename_map: dict[str, str] = {}
    for image in sorted(images_dir.iterdir()):
        if not image.is_file():
            continue
        unique_name = f"part{part_index:02d}_{image.name}"
        shutil.copyfile(image, target_dir / unique_name)
        rename_map[image.name] = unique_name
    return rename_map


def _rewrite_image_paths(node: object, rename_map: dict[str, str]) -> None:
    """Rewrite ``img_path``/``image_path`` values in a content-list tree to the
    renamed (part-prefixed) image files."""
    if isinstance(node, dict):
        for key, value in node.items():
            if key in ("img_path", "image_path") and isinstance(value, str):
                name = value.rsplit("/", 1)[-1]
                if name in rename_map:
                    node[key] = value.replace(name, rename_map[name])
            else:
                _rewrite_image_paths(value, rename_map)
    elif isinstance(node, list):
        for item in node:
            _rewrite_image_paths(item, rename_map)


@dataclass(frozen=True)
class _PdfPart:
    """One slice of an oversized PDF: 0-based ``start``, exclusive ``end``."""

    path: Path
    start: int
    end: int


def _request_upload(
    client: httpx.Client, source_path: Path, config: MinerUConfig, key_pool: KeyPool
) -> tuple[str, str]:
    """POST file-urls/batch → ``(batch_id, signed_upload_url)``."""
    file_entry: dict[str, object] = {"name": source_path.name, "is_ocr": config.is_ocr}
    body: dict[str, object] = {
        "files": [file_entry],
        "model_version": config.model_version,
        "enable_formula": config.enable_formula,
        "enable_table": config.enable_table,
    }
    if config.api_language:
        body["language"] = config.api_language

    payload = _post_json(client, "/api/v4/file-urls/batch", body, key_pool)
    data = payload.get("data") or {}
    batch_id = str(data.get("batch_id") or "").strip()
    file_urls = data.get("file_urls") or []
    if not batch_id or not isinstance(file_urls, list) or not file_urls:
        raise MinerUError("MinerU API did not return an upload URL (missing batch_id/file_urls).")
    return batch_id, str(file_urls[0])


def _upload_file(source_path: Path, upload_url: str) -> None:
    """PUT the input bytes to the signed URL.

    The signed URL carries its own auth; per MinerU's docs we must NOT send an
    ``Authorization`` or ``Content-Type`` header (a stray Content-Type breaks
    the OSS signature).
    """
    data = source_path.read_bytes()
    try:
        response = httpx.put(upload_url, content=data, timeout=_UPLOAD_TIMEOUT_SECONDS)
        response.raise_for_status()
    except httpx.HTTPError as exc:
        raise MinerUError(f"Failed to upload file to MinerU: {exc}") from exc


def _poll_for_zip(
    client: httpx.Client,
    batch_id: str,
    file_name: str,
    *,
    key_pool: KeyPool,
    poll_interval: float,
    timeout: float,
    on_progress: Callable[[str], None] | None = None,
) -> str:
    """Poll the batch results until our file is ``done``; return full_zip_url."""
    deadline = time.monotonic() + timeout
    last_state = ""
    last_report = ""
    while True:
        payload = _get_json(client, f"/api/v4/extract-results/batch/{batch_id}", key_pool)
        results = (payload.get("data") or {}).get("extract_result") or []
        entry = _match_entry(results, file_name)
        if entry is not None:
            state = str(entry.get("state") or "").strip().lower()
            last_state = state or last_state
            if on_progress is not None:
                progress = entry.get("extract_progress") or {}
                total_pages = progress.get("total_pages")
                report = f"MinerU cloud: {state or 'queued'}"
                if total_pages:
                    report += f" ({progress.get('extracted_pages') or 0}/{total_pages} pages)"
                if report != last_report:
                    last_report = report
                    try:
                        on_progress(report)
                    except Exception:
                        on_progress = None
            if state == _TERMINAL_OK:
                zip_url = str(entry.get("full_zip_url") or "").strip()
                if not zip_url:
                    raise MinerUError("MinerU reported done but returned no full_zip_url.")
                return zip_url
            if state == _TERMINAL_FAIL:
                err = str(entry.get("err_msg") or "unknown error")
                raise MinerUError(f"MinerU failed to parse the document: {err}")
        if time.monotonic() >= deadline:
            raise MinerUError(
                f"MinerU parsing timed out after {int(timeout)}s "
                f"(last state: {last_state or 'unknown'})."
            )
        time.sleep(poll_interval)


def verify_credentials(config: MinerUConfig) -> None:
    """Best-effort connectivity / token check for the Settings → MinerU "Test"
    button. Requests an upload slot (which does not consume parsing quota and
    is never followed by an upload, so it simply expires) and validates the
    business code. Raises :class:`MinerUError` with a user-facing message on
    any failure."""
    if not config.api_keys:
        raise MinerUError("No API token configured.")
    base_url = config.api_base_url.rstrip("/")
    key_pool = KeyPool(config.api_keys)
    body: dict[str, object] = {
        "files": [{"name": "connectivity-check.pdf", "is_ocr": False}],
        "model_version": config.model_version,
        "enable_formula": config.enable_formula,
        "enable_table": config.enable_table,
    }
    if config.api_language:
        body["language"] = config.api_language
    with httpx.Client(base_url=base_url, headers={"Accept": "application/json"}) as client:
        _post_json(client, "/api/v4/file-urls/batch", body, key_pool)


def _download(zip_url: str) -> bytes:
    try:
        response = httpx.get(zip_url, timeout=_DOWNLOAD_TIMEOUT_SECONDS, follow_redirects=True)
        response.raise_for_status()
        return response.content
    except httpx.HTTPError as exc:
        raise MinerUError(f"Failed to download MinerU result archive: {exc}") from exc


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _match_entry(results: list, file_name: str) -> dict | None:
    """Pick our file's result row. Single-file batch → first row is ours, but
    match on ``file_name`` when present to be safe."""
    rows = [r for r in results if isinstance(r, dict)]
    if not rows:
        return None
    for row in rows:
        if str(row.get("file_name") or "") == file_name:
            return row
    return rows[0]


def _request_json(
    request: Callable[..., httpx.Response],
    path: str,
    key_pool: KeyPool,
    **kwargs,
) -> dict:
    for attempt in range(2):
        api_key = key_pool.next()
        try:
            response = request(
                path,
                timeout=_SUBMIT_TIMEOUT_SECONDS,
                headers={"Authorization": f"Bearer {api_key}"},
                **kwargs,
            )
            response.raise_for_status()
            payload = response.json()
        except httpx.HTTPStatusError as exc:
            if exc.response.status_code == 429:
                key_pool.mark_429(api_key)
                if attempt == 0:
                    continue
            raise MinerUError(_http_error_message(exc)) from exc
        except httpx.HTTPError as exc:
            raise MinerUError(f"MinerU API request failed: {exc}") from exc
        _check_code(payload)
        return payload
    raise MinerUError("MinerU API key rotation exhausted.")


def _post_json(client: httpx.Client, path: str, body: dict, key_pool: KeyPool) -> dict:
    return _request_json(client.post, path, key_pool, json=body)


def _get_json(client: httpx.Client, path: str, key_pool: KeyPool) -> dict:
    return _request_json(client.get, path, key_pool)


def _check_code(payload: dict) -> None:
    """MinerU wraps errors in ``{"code": <non-zero>, "msg": ...}`` even on
    HTTP 200, so the business code must be inspected explicitly."""
    if not isinstance(payload, dict):
        raise MinerUError("MinerU API returned an unexpected (non-JSON) response.")
    code = payload.get("code")
    if code not in (0, None):
        msg = str(payload.get("msg") or "unknown error")
        raise MinerUError(f"MinerU API error (code {code}): {msg}")


def _http_error_message(exc: httpx.HTTPStatusError) -> str:
    status = exc.response.status_code
    if status in (401, 403):
        return "MinerU API rejected the token (401/403). Check the API token in Settings → MinerU."
    if status == 429:
        return "MinerU API rate limit hit (429). Try again later or reduce request volume."
    return f"MinerU API returned HTTP {status}."


def _reset_dir(path: Path) -> None:
    if path.exists():
        import shutil

        shutil.rmtree(path)
    path.mkdir(parents=True, exist_ok=True)


def _extract_archive(archive_bytes: bytes, target_dir: Path) -> None:
    """Extract the MinerU zip into ``target_dir``, preserving its directory
    tree (the ``images/`` subdir matters) while defending against Zip Slip and
    zip bombs. Unlike :func:`safe_extract_zip`, this keeps subdirectories and
    does not apply a document-extension whitelist — the archive is a trusted
    MinerU artifact, not a user upload."""
    target_root = target_dir.resolve()
    total = 0
    try:
        with zipfile.ZipFile(io.BytesIO(archive_bytes)) as archive:
            members = [m for m in archive.infolist() if not m.is_dir()]
            if len(members) > _MAX_ENTRIES:
                raise MinerUError(f"MinerU archive has too many entries ({len(members)}).")
            for member in members:
                # Collapse to a POSIX-relative path and reject traversal.
                rel = Path(member.filename.replace("\\", "/"))
                if rel.is_absolute() or ".." in rel.parts:
                    logger.warning("Skipping unsafe zip member: %s", member.filename)
                    continue
                dest = (target_root / rel).resolve()
                if target_root not in dest.parents and dest != target_root:
                    logger.warning("Skipping zip member escaping root: %s", member.filename)
                    continue
                total += member.file_size
                if total > _MAX_TOTAL_BYTES:
                    raise MinerUError("MinerU archive exceeds the size limit.")
                dest.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(member) as src, open(dest, "wb") as out:
                    out.write(src.read())
    except zipfile.BadZipFile as exc:
        raise MinerUError(f"MinerU returned an invalid archive: {exc}") from exc


__all__ = ["parse_cloud", "verify_credentials"]
