"""MinerU cloud (mineru.net) v4 API backend.

Implements the token-required *Precision API* flow for a single local PDF:

1. ``POST /api/v4/file-urls/batch`` → ``{batch_id, file_urls: [signed_url]}``
2. ``PUT`` the raw PDF bytes to ``signed_url`` (no auth, no Content-Type)
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
import io
import logging
from pathlib import Path
import time
import zipfile

import httpx

from .config import MinerUConfig, MinerUError

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
    pdf_path: Path,
    output_base: Path,
    config: MinerUConfig,
    *,
    poll_interval: float = DEFAULT_POLL_INTERVAL_SECONDS,
    timeout: float = DEFAULT_TIMEOUT_SECONDS,
    on_progress: Callable[[str], None] | None = None,
) -> Path:
    """Parse ``pdf_path`` via the MinerU cloud API; return the working dir.

    The working dir sits under ``output_base`` (named after the PDF stem) and
    holds the unzipped MinerU artifacts. ``on_progress`` (if given) receives a
    short status line whenever the polled task state / page count changes.
    Raises :class:`MinerUError` on any misconfiguration, API error, timeout,
    or extraction failure.
    """
    if not config.api_token:
        raise MinerUError(
            "MinerU cloud mode is selected but no API token is configured. "
            "Add a token in Settings → MinerU, or switch to local mode."
        )
    pdf_path = Path(pdf_path)
    if not pdf_path.is_file():
        raise MinerUError(f"PDF file not found: {pdf_path}")

    base_url = config.api_base_url.rstrip("/")
    headers = {
        "Authorization": f"Bearer {config.api_token}",
        "Accept": "application/json",
    }

    def report(message: str) -> None:
        if on_progress is None:
            return
        try:
            on_progress(message)
        except Exception:
            logger.debug("on_progress callback failed", exc_info=True)

    with httpx.Client(base_url=base_url, headers=headers) as client:
        report(f"MinerU cloud: requesting upload slot for {pdf_path.name}")
        batch_id, upload_url = _request_upload(client, pdf_path, config)
        size_mb = pdf_path.stat().st_size / (1024 * 1024)
        report(f"MinerU cloud: uploading {pdf_path.name} ({size_mb:.1f} MB)")
        _upload_file(pdf_path, upload_url)
        zip_url = _poll_for_zip(
            client,
            batch_id,
            pdf_path.name,
            poll_interval=poll_interval,
            timeout=timeout,
            on_progress=on_progress,
        )
        report("MinerU cloud: downloading parsed result archive")
        archive_bytes = _download(zip_url)

    report("MinerU cloud: extracting archive")
    working_dir = output_base / pdf_path.stem
    _reset_dir(working_dir)
    _extract_archive(archive_bytes, working_dir)
    logger.info("MinerU cloud parse complete: %s → %s", pdf_path.name, working_dir)
    return working_dir


# ---------------------------------------------------------------------------
# Steps
# ---------------------------------------------------------------------------


def _request_upload(client: httpx.Client, pdf_path: Path, config: MinerUConfig) -> tuple[str, str]:
    """POST file-urls/batch → ``(batch_id, signed_upload_url)``."""
    file_entry: dict[str, object] = {"name": pdf_path.name, "is_ocr": config.is_ocr}
    body: dict[str, object] = {
        "files": [file_entry],
        "model_version": config.model_version,
        "enable_formula": config.enable_formula,
        "enable_table": config.enable_table,
    }
    if config.api_language:
        body["language"] = config.api_language

    payload = _post_json(client, "/api/v4/file-urls/batch", body)
    data = payload.get("data") or {}
    batch_id = str(data.get("batch_id") or "").strip()
    file_urls = data.get("file_urls") or []
    if not batch_id or not isinstance(file_urls, list) or not file_urls:
        raise MinerUError("MinerU API did not return an upload URL (missing batch_id/file_urls).")
    return batch_id, str(file_urls[0])


def _upload_file(pdf_path: Path, upload_url: str) -> None:
    """PUT the PDF bytes to the signed URL.

    The signed URL carries its own auth; per MinerU's docs we must NOT send an
    ``Authorization`` or ``Content-Type`` header (a stray Content-Type breaks
    the OSS signature).
    """
    data = pdf_path.read_bytes()
    try:
        response = httpx.put(upload_url, content=data, timeout=_UPLOAD_TIMEOUT_SECONDS)
        response.raise_for_status()
    except httpx.HTTPError as exc:
        raise MinerUError(f"Failed to upload PDF to MinerU: {exc}") from exc


def _poll_for_zip(
    client: httpx.Client,
    batch_id: str,
    file_name: str,
    *,
    poll_interval: float,
    timeout: float,
    on_progress: Callable[[str], None] | None = None,
) -> str:
    """Poll the batch results until our file is ``done``; return full_zip_url."""
    deadline = time.monotonic() + timeout
    last_state = ""
    last_report = ""
    while True:
        payload = _get_json(client, f"/api/v4/extract-results/batch/{batch_id}")
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
    if not config.api_token:
        raise MinerUError("No API token configured.")
    base_url = config.api_base_url.rstrip("/")
    headers = {
        "Authorization": f"Bearer {config.api_token}",
        "Accept": "application/json",
    }
    body: dict[str, object] = {
        "files": [{"name": "connectivity-check.pdf", "is_ocr": False}],
        "model_version": config.model_version,
        "enable_formula": config.enable_formula,
        "enable_table": config.enable_table,
    }
    if config.api_language:
        body["language"] = config.api_language
    with httpx.Client(base_url=base_url, headers=headers) as client:
        _post_json(client, "/api/v4/file-urls/batch", body)


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


def _post_json(client: httpx.Client, path: str, body: dict) -> dict:
    try:
        response = client.post(path, json=body, timeout=_SUBMIT_TIMEOUT_SECONDS)
        response.raise_for_status()
        payload = response.json()
    except httpx.HTTPStatusError as exc:
        raise MinerUError(_http_error_message(exc)) from exc
    except httpx.HTTPError as exc:
        raise MinerUError(f"MinerU API request failed: {exc}") from exc
    _check_code(payload)
    return payload


def _get_json(client: httpx.Client, path: str) -> dict:
    try:
        response = client.get(path, timeout=_SUBMIT_TIMEOUT_SECONDS)
        response.raise_for_status()
        payload = response.json()
    except httpx.HTTPStatusError as exc:
        raise MinerUError(_http_error_message(exc)) from exc
    except httpx.HTTPError as exc:
        raise MinerUError(f"MinerU API request failed: {exc}") from exc
    _check_code(payload)
    return payload


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
