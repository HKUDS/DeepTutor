"""Apache Tika REST API backend.

Sends a local file to a Tika server via ``PUT /tika`` (``Accept: text/plain``)
and writes the extracted text into the working directory as ``<stem>.md``, so
the downstream ``ParseService`` is backend-agnostic.

Runs synchronously inside the worker thread that the parsing service invokes, so
a blocking ``httpx.Client`` is the simplest correct choice (no nested event
loop).
"""

from __future__ import annotations

from collections.abc import Callable
import logging
from pathlib import Path
from urllib.parse import quote

import httpx

from ...types import ParserError
from .config import TikaConfig

logger = logging.getLogger(__name__)

_CONVERT_ENDPOINT = "/tika"
_VERSION_ENDPOINT = "/version"

_SUBMIT_TIMEOUT_SECONDS = 300.0
_HEALTH_TIMEOUT_SECONDS = 8.0


def parse_remote(
    source_path: Path,
    workdir: Path,
    config: TikaConfig,
    *,
    on_output: Callable[[str], None] | None = None,
) -> None:
    """Send ``source_path`` to the Tika server; write ``<stem>.md``.

    Raises :class:`ParserError` on any failure."""
    if not source_path.is_file():
        raise ParserError(f"File not found: {source_path}")
    if not (config.server_url or "").strip():
        raise ParserError(
            "Tika has no server URL configured. Set one under Settings → Document Parsing."
        )

    def report(message: str) -> None:
        if on_output:
            try:
                on_output(message)
            except Exception:
                logger.debug("on_output callback failed", exc_info=True)

    base_url = config.server_url.rstrip("/")
    report(f"Tika server: converting {source_path.name}…")
    try:
        text = _convert_file(source_path, base_url)
    except _ConnectivityError as exc:
        raise ParserError(str(exc)) from exc

    stem = source_path.stem
    (workdir / f"{stem}.md").write_text(text, encoding="utf-8")
    report(f"Tika server: wrote {stem}.md")


def verify_remote(config: TikaConfig, timeout: float = _HEALTH_TIMEOUT_SECONDS) -> tuple[bool, str]:
    """Best-effort connectivity check for the Settings "Test connection" button.

    Pings ``/version`` — cheap and non-destructive. Never raises; returns
    ``(ok, detail)``."""
    if not (config.server_url or "").strip():
        return False, "No Tika server URL configured."
    base_url = config.server_url.rstrip("/")
    try:
        with httpx.Client(timeout=timeout) as client:
            version = _get_text(client, base_url + _VERSION_ENDPOINT)
    except _ConnectivityError as exc:
        return False, str(exc)
    return True, version


class _ConnectivityError(Exception):
    """Wraps any network/HTTP failure so callers get one user-facing error."""


def _convert_file(source_path: Path, base_url: str) -> str:
    headers = {
        "Accept": "text/plain",
        "Content-Type": "application/octet-stream",
        "Content-Disposition": f"attachment; filename*=UTF-8''{quote(source_path.name, safe='')}",
    }
    with source_path.open("rb") as source:
        with httpx.Client(base_url=base_url, timeout=_SUBMIT_TIMEOUT_SECONDS) as client:
            try:
                response = client.put(_CONVERT_ENDPOINT, content=source, headers=headers)
            except httpx.HTTPError as exc:
                raise _ConnectivityError(f"Tika server request failed: {exc}") from exc
            try:
                response.raise_for_status()
            except httpx.HTTPStatusError as exc:
                raise _ConnectivityError(_http_error_message(exc)) from exc
    text = response.text
    if not isinstance(text, str):
        raise _ConnectivityError(f"Tika server returned no text for {source_path.name}.")
    return text


def _http_error_message(exc: httpx.HTTPStatusError) -> str:
    status = exc.response.status_code
    if status in (401, 403):
        return "Tika server rejected the request (401/403)."
    if status == 415:
        return "Tika server does not support this file type (415)."
    if status == 422:
        return "Tika server could not parse the document (422)."
    if status == 429:
        return "Tika server rate limit hit (429). Try again later."
    return f"Tika server returned HTTP {status}."


def _get_text(client: httpx.Client, url: str) -> str:
    try:
        response = client.get(url)
        try:
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise _ConnectivityError(_http_error_message(exc)) from exc
    except httpx.HTTPError as exc:
        raise _ConnectivityError(f"Tika server request failed: {exc}") from exc
    text = response.text.strip()
    return text or "reachable"


__all__ = ["parse_remote", "verify_remote"]
