"""Materialize image attachments to files so a subagent CLI can ingest them.

When ``forward_images`` is on for a backend, the consult tool writes the turn's
image attachments to a temp directory and hands the backend their paths — Codex
attaches them with ``-i``, Claude Code is pointed at them for its Read tool. The
bytes come from the attachment's inline base64 or, failing that, the local
:class:`AttachmentStore`; external URLs are never fetched (sync network IO in an
async path, and a request-forgery footgun).
"""

from __future__ import annotations

import base64
import logging
from pathlib import Path
import re
from typing import Any
from urllib.parse import unquote, urlparse

logger = logging.getLogger(__name__)

_LOCAL_ATTACHMENT_PREFIX = "/api/attachments/"
_EXT_BY_MIME = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/jpg": ".jpg",
    "image/gif": ".gif",
    "image/webp": ".webp",
}


def materialize_images(attachments: list[Any], dest_dir: Path) -> list[str]:
    """Write each image attachment into *dest_dir*, returning the file paths.

    Non-image attachments and ones whose bytes can't be resolved are skipped;
    the result is therefore exactly the images the backend can actually forward.
    """
    paths: list[str] = []
    for idx, att in enumerate(attachments or []):
        if getattr(att, "type", "") != "image":
            continue
        data = _image_bytes(att)
        if not data:
            continue
        target = dest_dir / f"{idx:02d}{_image_ext(att)}"
        try:
            target.write_bytes(data)
        except OSError:
            logger.warning("failed to write forwarded image %s", target, exc_info=True)
            continue
        paths.append(str(target))
    return paths


def _image_bytes(att: Any) -> bytes | None:
    b64 = (getattr(att, "base64", "") or "").strip()
    if b64:
        if b64.startswith("data:") and "," in b64:
            b64 = b64.split(",", 1)[1]
        try:
            return base64.b64decode(b64)
        except Exception:
            logger.warning("failed to decode inline image base64", exc_info=True)
            return None
    return _local_store_bytes((getattr(att, "url", "") or "").strip())


def _local_store_bytes(url: str) -> bytes | None:
    """Resolve a ``/api/attachments/<sid>/<aid>/<name>`` URL to its bytes."""
    if not url:
        return None
    path = urlparse(url).path or url
    if not path.startswith(_LOCAL_ATTACHMENT_PREFIX):
        return None
    parts = path[len(_LOCAL_ATTACHMENT_PREFIX) :].split("/")
    if len(parts) != 3:
        return None
    sid, aid, name = (unquote(p) for p in parts)
    try:
        from deeptutor.services.storage import get_attachment_store

        store = get_attachment_store()
        resolve = getattr(store, "resolve_path", None)
        if resolve is None:
            return None
        target = resolve(session_id=sid, attachment_id=aid, filename=name)
        return Path(target).read_bytes() if target else None
    except Exception:
        logger.warning("failed to resolve attachment %s", url, exc_info=True)
        return None


def _image_ext(att: Any) -> str:
    mime = (getattr(att, "mime_type", "") or "").lower()
    if mime in _EXT_BY_MIME:
        return _EXT_BY_MIME[mime]
    match = re.search(r"(\.[A-Za-z0-9]{1,5})$", getattr(att, "filename", "") or "")
    return match.group(1) if match else ".png"


__all__ = ["materialize_images"]
