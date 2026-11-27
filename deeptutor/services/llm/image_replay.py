"""Deduplicate immutable user images in a request-only projection.

Durable model turns remain complete. Keep the first identical inline image
at its original position, preserving the request prefix and all unique images.
Remote URLs can change underneath a stable address and are never deduplicated.
"""

from __future__ import annotations

import hashlib
import json
from typing import Any


def _inline_image_key(block: Any) -> str | None:
    if not isinstance(block, dict):
        return None
    kind = block.get("type")
    if kind in {"image_url", "input_image"}:
        image = block.get("image_url")
        url = image.get("url") if isinstance(image, dict) else image
        if not isinstance(url, str) or not url.startswith("data:image/"):
            return None
        payload_hash = hashlib.sha256(url.encode()).hexdigest()
        compact = {
            **block,
            "image_url": {**image, "url": payload_hash}
            if isinstance(image, dict)
            else payload_hash,
        }
    elif kind == "image":
        source = block.get("source")
        if not (
            isinstance(source, dict)
            and source.get("type") == "base64"
            and isinstance(source.get("data"), str)
            and source["data"]
        ):
            return None
        compact = {
            **block,
            "source": {**source, "data": hashlib.sha256(source["data"].encode()).hexdigest()},
        }
    else:
        return None
    # Include detail, MIME and other options: only exactly equal image blocks
    # are interchangeable. No bytes are decoded and no URLs are fetched.
    encoded = json.dumps(compact, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(encoded.encode()).hexdigest()


def deduplicate_user_images(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Project repeated inline user images to stable references in this request.

    Label each retained image even when unique so appending a repeat never
    changes earlier request prefixes. Labels also survive provider translation,
    which may move system messages or combine tool results with user messages.
    Recompute from full history after a cut: every reference still has real
    bytes in the current request. Original image blocks and history are intact.
    """
    seen: set[str] = set()
    projected = []
    for message in messages:
        content = message.get("content")
        if message.get("role") != "user" or not isinstance(content, list):
            projected.append(dict(message))
            continue
        parts = []
        for block in content:
            key = _inline_image_key(block)
            if key is None:
                parts.append(block)
                continue
            label = key[:32]
            if key not in seen:
                seen.add(key)
                marker = {"type": "text", "text": f"[Image {label}]"}
                if not parts or parts[-1] != marker:
                    parts.append(marker)
                parts.append(block)
                continue
            parts.append(
                {
                    "type": "text",
                    "text": f"[Repeated image {label}; see the identical image included earlier in this request.]",
                }
            )
        projected.append({**message, "content": parts})
    return projected
