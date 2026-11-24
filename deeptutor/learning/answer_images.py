"""Photos a learner submits as their answer to a mastery card.

A card answer can carry images of a handwritten solution. They arrive as the
turn's ordinary chat attachments, so the runtime persists them to the
attachment store like any other upload. The interaction keeps only a reference
and a SHA-256 digest of each image's bytes. The digests take part in the commit
fingerprint, which lets a replay with different photos be told apart. At
grading time the bytes are read back from the store and checked against the
digests, so the grader sees exactly the images that were committed.
"""

from __future__ import annotations

import base64
import binascii
from hashlib import sha256
from typing import Any

MAX_ANSWER_IMAGES = 4


def answer_image_refs(
    attachment_ids: list[str] | None,
    attachments: list[dict[str, Any]] | None,
    *,
    session_id: str,
) -> list[dict[str, str]]:
    """Describe the turn's attachments named as the learner's answer images.

    Raises ``ValueError`` when an ID does not name a fresh image upload of this
    turn. A card answer that cannot carry its photos must not be committed as a
    text-only answer.
    """
    ids = [str(item) for item in attachment_ids or []]
    if not ids:
        return []
    if len(ids) > MAX_ANSWER_IMAGES or len(set(ids)) != len(ids):
        raise ValueError(f"A card answer can include up to {MAX_ANSWER_IMAGES} distinct photos.")
    by_id = {
        str(item.get("id") or ""): item for item in attachments or [] if isinstance(item, dict)
    }
    refs = []
    for attachment_id in ids:
        item = by_id.get(attachment_id)
        mime_type = str((item or {}).get("mime_type") or "") or "image/png"
        if (
            item is None
            or item.get("type") != "image"
            or not item.get("base64")
            or not mime_type.startswith("image/")
        ):
            raise ValueError("A card answer photo must be an image uploaded with the same answer.")
        try:
            digest = sha256(base64.b64decode(str(item["base64"]), validate=False)).hexdigest()
        except (binascii.Error, ValueError):
            # The runtime cannot store these bytes either. An empty digest
            # matches nothing, so grading reports the photo as unavailable.
            digest = ""
        refs.append(
            {
                "session_id": session_id,
                "attachment_id": attachment_id,
                "filename": str(item.get("filename") or "") or "file",
                "mime_type": mime_type,
                "sha256": digest,
            }
        )
    return refs


def image_digests(refs: list[dict[str, Any]] | None) -> list[str]:
    return [str(ref.get("sha256") or "") for ref in refs or []]


def load_answer_images(refs: list[dict[str, Any]], config=None) -> list[dict[str, Any]]:
    """Return the committed answer images as model input parts.

    Raises ``ValueError`` with a learner-facing explanation when the active
    model cannot see images or a stored image no longer matches its digest.
    The caller turns that into an ``ungraded`` verdict and never grades the
    typed text alone.
    """
    from deeptutor.services.llm.capabilities import supports_vision
    from deeptutor.services.llm.config import get_llm_config
    from deeptutor.services.storage import get_attachment_store

    llm = config or get_llm_config()
    if not supports_vision(llm.binding, llm.model):
        raise ValueError(
            "The active model cannot read images, so the photo of your solution was not "
            "graded. Choose a vision-capable model or type your answer; mastery is unchanged."
        )
    store = get_attachment_store()
    parts = []
    for ref in refs:
        path = store.resolve_path(
            session_id=ref["session_id"],
            attachment_id=ref["attachment_id"],
            filename=ref["filename"],
        )
        data = path.read_bytes() if path is not None else b""
        if not data or not ref["sha256"] or sha256(data).hexdigest() != ref["sha256"]:
            raise ValueError(
                "A photo of your solution is no longer available as submitted, so it was "
                "not graded. Submit the photo again; mastery is unchanged."
            )
        encoded = base64.b64encode(data).decode("ascii")
        parts.append(
            {"type": "image_url", "image_url": {"url": f"data:{ref['mime_type']};base64,{encoded}"}}
        )
    return parts
