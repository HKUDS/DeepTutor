"""Docling Serve REST API backend.

Sends a local file to a Docling Serve server via ``POST /v1/convert/file`` and
writes the returned Markdown into the working directory — matching the canonical
IR the local ``DoclingParser`` produces (``<stem>.md``), so the downstream
``ParseService`` is backend-agnostic.

Runs synchronously inside the worker thread that the parsing service invokes, so
a blocking ``httpx.Client`` is the simplest correct choice (no nested event
loop).
"""

from __future__ import annotations

from collections.abc import Callable
import json
import logging
from pathlib import Path

import httpx

from ...types import ParserError
from .config import DoclingConfig

logger = logging.getLogger(__name__)

_CONVERT_ENDPOINT = "/v1/convert/file"
_READY_ENDPOINT = "/health"
_VERSION_ENDPOINT = "/version"

_SUBMIT_TIMEOUT_SECONDS = 300.0
_HEALTH_TIMEOUT_SECONDS = 8.0


def parse_remote(
    source_path: Path,
    workdir: Path,
    config: DoclingConfig,
    *,
    on_output: Callable[[str], None] | None = None,
) -> None:
    """Send ``source_path`` to the Docling Serve server; write ``<stem>.md``.

    Raises :class:`ParserError` on any failure."""
    if not source_path.is_file():
        raise ParserError(f"File not found: {source_path}")
    if not (config.api_base_url or "").strip():
        raise ParserError(
            "Docling remote mode has no server URL configured. Set one under "
            "Settings → Document Parsing."
        )

    def report(message: str) -> None:
        if on_output:
            try:
                on_output(message)
            except Exception:
                logger.debug("on_output callback failed", exc_info=True)

    base_url = config.api_base_url.rstrip("/")
    report(f"Docling server: converting {source_path.name}…")
    try:
        markdown = _convert_file(source_path, base_url, config)
    except _ConnectivityError as exc:
        raise ParserError(str(exc)) from exc

    stem = source_path.stem
    (workdir / f"{stem}.md").write_text(markdown, encoding="utf-8")
    report(f"Docling server: wrote {stem}.md")


def verify_remote(
    config: DoclingConfig, timeout: float = _HEALTH_TIMEOUT_SECONDS
) -> tuple[bool, str]:
    """Best-effort connectivity check for the Settings "Test connection" button.

    Pings ``/health`` and reads ``/version`` — cheap and non-destructive. Never
    raises; returns ``(ok, detail)``."""
    if not (config.api_base_url or "").strip():
        return False, "No Docling server URL configured."
    base_url = config.api_base_url.rstrip("/")
    headers = _auth_headers(config)
    try:
        with httpx.Client(timeout=timeout) as client:
            ready = _get_text(client, base_url + _READY_ENDPOINT, headers=headers)
            version = _get_text(client, base_url + _VERSION_ENDPOINT, headers=headers)
    except _ConnectivityError as exc:
        return False, str(exc)
    return True, f"{ready} · {version}"


class _ConnectivityError(Exception):
    """Wraps any network/HTTP failure so callers get one user-facing error."""


def _convert_file(source_path: Path, base_url: str, config: DoclingConfig) -> str:
    headers = _auth_headers(config)
    data = {
        "to_formats": "md",
        "do_ocr": "true" if config.do_ocr else "false",
        "do_table_structure": "true" if config.do_table_structure else "false",
    }
    with source_path.open("rb") as source:
        files = {"files": (source_path.name, source, "application/octet-stream")}
        with httpx.Client(
            base_url=base_url, headers=headers, timeout=_SUBMIT_TIMEOUT_SECONDS
        ) as client:
            try:
                response = client.post(_CONVERT_ENDPOINT, files=files, data=data)
            except httpx.HTTPError as exc:
                raise _ConnectivityError(f"Docling server request failed: {exc}") from exc
            try:
                response.raise_for_status()
            except httpx.HTTPStatusError as exc:
                raise _ConnectivityError(_http_error_message(exc)) from exc
            try:
                payload = response.json()
            except ValueError as exc:
                raise _ConnectivityError("Docling server returned a non-JSON response.") from exc
    return _extract_markdown(payload, source_path.name)


def _extract_markdown(payload: dict, file_name: str) -> str:
    """Pull Markdown out of the sync endpoint's ``{document, status, errors}``
    envelope, failing on business errors even when the server returns HTTP 200."""
    if not isinstance(payload, dict):
        raise _ConnectivityError("Docling server returned an unexpected (non-JSON) response.")
    status = str(payload.get("status") or "").strip().lower()
    if status == "success":
        markdown = (payload.get("document") or {}).get("md_content")
        if isinstance(markdown, str):
            return markdown
        raise _ConnectivityError(
            f"Docling server reported success but returned no Markdown for {file_name}."
        )
    detail = _format_errors(payload.get("errors")) or f"status: {status or 'unknown'}"
    raise _ConnectivityError(f"Docling failed to convert {file_name}: {detail}")


def _format_errors(errors) -> str:
    if not isinstance(errors, list):
        return ""
    parts = [
        str(err["error"]) if isinstance(err, dict) and err.get("error") else "" for err in errors
    ]
    return "; ".join(p for p in parts if p)


def _auth_headers(config: DoclingConfig) -> dict[str, str]:
    token = (config.api_token or "").strip()
    # Docling Serve sends auth via the ``X-Api-Key`` header.
    return {"X-Api-Key": token} if token else {}


def _http_error_message(exc: httpx.HTTPStatusError) -> str:
    status = exc.response.status_code
    if status in (401, 403):
        return (
            "Docling server rejected the API key (401/403). Check the key under "
            "Settings → Document Parsing."
        )
    if status == 413:
        return "Docling server refused the file — it exceeds the server size limit (413)."
    if status == 429:
        return "Docling server rate limit hit (429). Try again later."
    return f"Docling server returned HTTP {status}."


def _get_text(client: httpx.Client, url: str, headers: dict[str, str]) -> str:
    try:
        response = client.get(url, headers=headers)
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise _ConnectivityError(_http_error_message(exc)) from exc
    except httpx.HTTPError as exc:
        raise _ConnectivityError(f"Docling server request failed: {exc}") from exc
    text = response.text.strip()
    if not text:
        return "reachable"
    if text.startswith("{"):
        # /version returns JSON like {"docling-serve": "1.29.0", ...}; summarise it.
        try:
            obj = json.loads(text)
            version = obj.get("docling-serve") or obj.get("version")
            return f"Docling Serve {version or 'reachable'}"
        except Exception:
            return "reachable"
    return text


__all__ = ["parse_remote", "verify_remote"]
