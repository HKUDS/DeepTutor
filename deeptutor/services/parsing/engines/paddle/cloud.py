"""PaddleOCR AI Studio cloud API backend (飞桨云端).

Implements the same REST protocol the official ``paddleocr`` package's API
client and the ``paddleocr-mcp`` server use:

1. ``POST /api/v2/ocr/jobs`` with a multipart form (``model``,
   ``optionalPayload`` as a JSON string, ``file``) → ``{code: 0, data: {jobId}}``
2. Poll ``GET /api/v2/ocr/jobs/{jobId}`` until ``state`` is ``done``/``failed``
   (``pending``/``running`` intermediate states)
3. On ``done``, fetch ``resultUrl.jsonUrl`` (a pre-signed object-storage link)
   → JSONL, one line per page:
   ``{"result": {"layoutParsingResults": [{"markdown": {"text": ..., "images": {...}}}]}}``
4. Assemble the page markdown into ``<stem>.md`` and download referenced images
   into ``images/`` so the workdir matches the shared cache contract.

The module is synchronous on purpose — it runs inside the worker thread the
ParseService spawns, so a blocking ``httpx.Client`` is the simplest correct
choice (no nested event loop).

Model ids (document parsing): ``PaddleOCR-VL``, ``PaddleOCR-VL-1.5``,
``PaddleOCR-VL-1.6``, ``PP-StructureV3``. Token quota: free 20000 pages/day.
"""

from __future__ import annotations

import json
import logging
import re
import time
from pathlib import Path
from typing import Callable, Optional

import httpx

from .config import PaddleConfig, PaddleError

logger = logging.getLogger(__name__)

DEFAULT_BASE_URL = "https://paddleocr.aistudio-app.com"
JOBS_PATH = "/api/v2/ocr/jobs"

# Polling defaults (mirror the paddleocr package's async poller).
DEFAULT_POLL_INTERVAL_SECONDS = 2.0
_POLL_MULTIPLIER = 1.5
_POLL_MAX_INTERVAL_SECONDS = 10.0
_SUBMIT_TIMEOUT_SECONDS = 120.0
_DOWNLOAD_TIMEOUT_SECONDS = 300.0

_TERMINAL_DONE = "done"
_TERMINAL_FAIL = "failed"

# Block-style markdown that only names an image without an inline path.
_IMAGE_RE = re.compile(r"!\[[^\]]*\]\(([^)]+)\)")


def _snake_to_camel(name: str) -> str:
    """``use_layout_detection`` → ``useLayoutDetection``."""
    first, *rest = name.split("_")
    return first + "".join(part.capitalize() for part in rest)


def parse_cloud(
    source_path: Path,
    workdir: Path,
    config: PaddleConfig,
    *,
    on_progress: Optional[Callable[[str], None]] = None,
) -> Path:
    """Parse ``source_path`` (PDF or image) via PaddleOCR cloud; return workdir.

    Writes ``<stem>.md`` and ``images/`` directly into ``workdir`` (the cache
    signature dir) so ParseService's ``load_ir`` picks them up. Raises
    :class:`PaddleError` on any misconfiguration, API error, or timeout.
    """
    if not config.api_keys:
        raise PaddleError(
            "PaddleOCR cloud mode is selected but no API token is configured. "
            "Add your AI Studio access token in Settings → Document Parsing → PaddleOCR."
        )
    source_path = Path(source_path)
    if not source_path.is_file():
        raise PaddleError(f"File not found: {source_path}")

    def report(message: str) -> None:
        if on_progress is None:
            return
        try:
            on_progress(message)
        except Exception:
            logger.debug("on_progress callback failed", exc_info=True)

    base_url = config.base_url.rstrip("/") or DEFAULT_BASE_URL
    jobs_url = f"{base_url}{JOBS_PATH}"
    headers = {
        "Authorization": f"Bearer {config.api_keys[0]}",
        "Accept": "application/json",
    }

    report(f"PaddleOCR: submitting {source_path.name} ({source_path.stat().st_size / 1024:.0f} KB)")
    job_id = _submit(jobs_url, source_path, config, headers)
    report(f"PaddleOCR: job {job_id} submitted, polling…")

    jsonl_data = _poll_until_done(jobs_url, job_id, config, headers, report=report)
    report("PaddleOCR: downloading result")
    md_text, image_urls = _render_markdown(jsonl_data, config.model)

    (workdir / f"{source_path.stem}.md").write_text(md_text, encoding="utf-8")
    if config.write_images and image_urls:
        images_dir = workdir / "images"
        images_dir.mkdir(parents=True, exist_ok=True)
        for index, url in enumerate(image_urls, 1):
            _download_image(url, images_dir, index)
        report(f"PaddleOCR: saved {len(image_urls)} images")
    logger.info("PaddleOCR cloud parse complete: %s → %s", source_path.name, workdir)
    return workdir


# ---------------------------------------------------------------------------
# Steps
# ---------------------------------------------------------------------------


def _submit(jobs_url: str, source_path: Path, config: PaddleConfig, headers: dict) -> str:
    """POST the file as multipart form; return the job id."""
    optional_payload = json.dumps(
        {_snake_to_camel(k): v for k, v in config.optional_payload().items()}
    )
    data = {
        "model": config.model,
        "optionalPayload": optional_payload,
    }
    try:
        with open(source_path, "rb") as handle:
            response = httpx.post(
                jobs_url,
                headers=headers,
                data=data,
                files={"file": (source_path.name, handle)},
                timeout=_SUBMIT_TIMEOUT_SECONDS,
            )
    except httpx.HTTPError as exc:
        raise PaddleError(f"Failed to submit file to PaddleOCR: {exc}") from exc
    payload = _unwrap(response)
    job_id = (payload.get("data") or {}).get("jobId")
    if not isinstance(job_id, str) or not job_id:
        raise PaddleError("PaddleOCR API did not return a jobId.")
    return job_id


def _poll_until_done(
    jobs_url: str,
    job_id: str,
    config: PaddleConfig,
    headers: dict,
    *,
    report: Optional[Callable[[str], None]] = None,
) -> list[dict]:
    """Poll the job status until ``done``; return the parsed JSONL rows."""
    deadline = time.monotonic() + config.poll_timeout
    interval = DEFAULT_POLL_INTERVAL_SECONDS
    last_state = ""
    last_report = ""
    while True:
        try:
            response = httpx.get(f"{jobs_url}/{job_id}", headers=headers, timeout=_SUBMIT_TIMEOUT_SECONDS)
        except httpx.HTTPError as exc:
            raise PaddleError(f"PaddleOCR status poll failed: {exc}") from exc
        payload = _unwrap(response)
        data = payload.get("data") or {}
        state = str(data.get("state") or "").strip().lower()
        if state not in ("pending", "running", "done", "failed"):
            raise PaddleError(f"PaddleOCR returned unknown job state: {state!r}")
        last_state = state or last_state
        if state == _TERMINAL_DONE:
            result_url = data.get("resultUrl") or {}
            json_url = str(result_url.get("jsonUrl") or "").strip()
            if not json_url:
                raise PaddleError("PaddleOCR reported done but returned no resultUrl.jsonUrl.")
            return _fetch_jsonl(json_url)
        if state == _TERMINAL_FAIL:
            error_msg = str(data.get("errorMsg") or "unknown error")
            raise PaddleError(f"PaddleOCR failed to parse the document: {error_msg}")
        if report is not None:
            progress = data.get("progress") or {}
            done_pages = progress.get("extractedPages") if isinstance(progress, dict) else None
            total_pages = progress.get("totalPages") if isinstance(progress, dict) else None
            text = f"PaddleOCR: {state}"
            if done_pages is not None and total_pages:
                text += f" ({done_pages}/{total_pages} pages)"
            if text != last_report:
                last_report = text
                try:
                    report(text)
                except Exception:
                    report = None
        if time.monotonic() >= deadline:
            raise PaddleError(
                f"PaddleOCR parsing timed out after {int(config.poll_timeout)}s "
                f"(last state: {last_state or 'unknown'})."
            )
        time.sleep(min(interval, max(0.5, deadline - time.monotonic())))
        interval = min(interval * _POLL_MULTIPLIER, _POLL_MAX_INTERVAL_SECONDS)


def _fetch_jsonl(json_url: str) -> list[dict]:
    """Download and parse the result JSONL (pre-signed URL, no auth header)."""
    try:
        response = httpx.get(json_url, timeout=_DOWNLOAD_TIMEOUT_SECONDS)
        response.raise_for_status()
    except httpx.HTTPError as exc:
        raise PaddleError(f"Failed to download PaddleOCR result: {exc}") from exc
    rows: list[dict] = []
    for line in response.text.strip().splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError as exc:
            raise PaddleError(f"PaddleOCR returned malformed result JSONL: {exc}") from exc
    return rows


def _render_markdown(jsonl_data: list[dict], model: str) -> tuple[str, list[str]]:
    """Turn JSONL rows into (page markdown joined, ordered image URLs).

    A page whose VLM output carries no text (e.g. a scanned image containing
    only a layout block like ``footer_image``) still contributes its extracted
    image references, so the markdown is never silently empty when the engine
    did produce something.
    """
    parts: list[str] = []
    image_urls: list[str] = []
    seen: set[str] = set()
    for line_obj in jsonl_data:
        result = line_obj.get("result") or {}
        for item in result.get("layoutParsingResults") or []:
            markdown = item.get("markdown") or {}
            text = str(markdown.get("text") or "").strip()
            images = markdown.get("images") or {}
            page_urls: list[str] = []
            if isinstance(images, dict):
                for url in images.values():
                    url = str(url or "").strip()
                    if url and url not in seen:
                        seen.add(url)
                        image_urls.append(url)
                        page_urls.append(url)
            if text:
                parts.append(text)
            elif page_urls:
                # No extractable text but images were produced — reference them
                # by the local paths parse_cloud will write (global index).
                for url in page_urls:
                    index = image_urls.index(url) + 1
                    suffix = Path(url.split("?")[0]).suffix.lower() or ".png"
                    parts.append(f"![img](images/img_{index:03d}{suffix})")
    if not parts:
        raise PaddleError(
            "PaddleOCR returned no markdown or images for the document. The file "
            "may be empty or in an unsupported format (PDF or common images)."
        )
    return "\n\n".join(parts), image_urls


def _download_image(url: str, images_dir: Path, index: int) -> None:
    """Download a referenced image, guessing an extension from the URL."""
    suffix = Path(url.split("?")[0]).suffix.lower()
    if suffix not in {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".gif"}:
        suffix = ".png"
    dest = images_dir / f"img_{index:03d}{suffix}"
    try:
        response = httpx.get(url, timeout=_DOWNLOAD_TIMEOUT_SECONDS)
        response.raise_for_status()
        dest.write_bytes(response.content)
    except httpx.HTTPError as exc:
        logger.warning("PaddleOCR image download failed (%s): %s", url, exc)


def _unwrap(response: httpx.Response) -> dict:
    """Validate HTTP + business code; return the full payload dict."""
    if response.status_code == 401:
        raise PaddleError(
            "PaddleOCR rejected the token (401). Check the AI Studio access token "
            "in Settings → Document Parsing → PaddleOCR."
        )
    if response.status_code == 429:
        raise PaddleError(
            "PaddleOCR rate limit hit (429). Try again later or reduce request volume."
        )
    if response.status_code >= 400:
        raise PaddleError(
            f"PaddleOCR API returned HTTP {response.status_code}: {response.text[:300]}"
        )
    try:
        payload = response.json()
    except ValueError as exc:
        raise PaddleError(f"PaddleOCR returned a non-JSON response: {exc}") from exc
    code = payload.get("code")
    if code not in (0, None):
        message = str(payload.get("message") or payload.get("msg") or "unknown error")
        raise PaddleError(f"PaddleOCR API error (code {code}): {message}")
    return payload


def verify_credentials(config: PaddleConfig) -> None:
    """Best-effort connectivity check for the Settings test button.

    Submits a tiny 1-page image (1x1 PNG) and waits for the job to finish —
    consumes one page of the daily quota but validates token + model access.
    """
    if not config.api_keys:
        raise PaddleError("No PaddleOCR API token configured.")
    base_url = config.base_url.rstrip("/") or DEFAULT_BASE_URL
    jobs_url = f"{base_url}{JOBS_PATH}"
    headers = {"Authorization": f"Bearer {config.api_keys[0]}", "Accept": "application/json"}
    import io

    # 1x1 transparent PNG (smallest valid image).
    tiny_png = (
        b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
        b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01"
        b"\x00\x00\x05\x00\x01\x0d\n\x2d\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
    )
    optional_payload = json.dumps(
        {_snake_to_camel(k): v for k, v in config.optional_payload().items()}
    )
    try:
        response = httpx.post(
            jobs_url,
            headers=headers,
            data={"model": config.model, "optionalPayload": optional_payload},
            files={"file": ("connectivity-check.png", io.BytesIO(tiny_png))},
            timeout=_SUBMIT_TIMEOUT_SECONDS,
        )
    except httpx.HTTPError as exc:
        raise PaddleError(f"PaddleOCR connectivity check failed: {exc}") from exc
    payload = _unwrap(response)
    job_id = (payload.get("data") or {}).get("jobId")
    if not isinstance(job_id, str) or not job_id:
        raise PaddleError("PaddleOCR API did not return a jobId.")
    # Poll to completion so the check reflects a real parse (and cleans up).
    _poll_until_done(jobs_url, job_id, config, headers)


__all__ = ["parse_cloud", "verify_credentials"]
