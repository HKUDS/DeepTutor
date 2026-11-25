"""File metadata for the app-owned Windows desktop shell."""

from __future__ import annotations

from mimetypes import guess_type
import os
from pathlib import Path
from secrets import compare_digest
from urllib.parse import quote

from fastapi import Request

_DESKTOP_FILE_KEY = os.environ.pop("DEEPTUTOR_DESKTOP_FILE_KEY", "")


def desktop_file_request(request: Request) -> bool:
    supplied = request.headers.get("x-deeptutor-desktop-file-key", "")
    return bool(
        request.method == "HEAD"
        and _DESKTOP_FILE_KEY
        and compare_digest(supplied.encode(), _DESKTOP_FILE_KEY.encode())
    )


def desktop_file_headers(path: Path | None) -> dict[str, str]:
    headers = {"Cache-Control": "private, no-store"}
    if path is not None and path.is_file():
        headers["X-DeepTutor-Local-File"] = quote(str(path), safe="")
    return headers


def browser_file_media_type(
    request: Request, path: Path, media_type: str | None = None
) -> str | None:
    if request.query_params.get("view") == "browser":
        if (media_type or guess_type(path.name)[0]) == "text/markdown":
            return "text/plain"
    return media_type
