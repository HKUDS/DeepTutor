"""
Multimodal Message Utilities
=============================

Converts plain-text messages + image attachments into the multimodal
message format expected by vision-capable LLMs.

Supports:
- OpenAI-compatible API (content array with image_url blocks)
- Anthropic API (content array with image source blocks)
"""

from __future__ import annotations

import base64 as _b64
from dataclasses import dataclass
import logging
from typing import Any
from urllib.parse import unquote, urlparse

from .capabilities import supports_vision, supports_vision_url

logger = logging.getLogger(__name__)

MIME_FALLBACK = "image/png"
_LOCAL_ATTACHMENT_PREFIX = "/api/attachments/"


@dataclass
class MultimodalResult:
    """Result of Stage-1 multimodal message preparation.

    Images are injected optimistically for every provider, so there is no
    "stripped because unsupported" outcome here — that decision is deferred
    to the Stage-2 fallback at each call site's retry seam (see
    :func:`should_degrade_to_text`).
    """

    messages: list[dict[str, Any]]
    # Number of url-only images we had to drop because the provider requires
    # base64 and we couldn't resolve the URL locally (external URL or missing
    # file). The caller can surface this to the user.
    url_images_dropped: int = 0


def _guess_mime_type(filename: str, fallback: str = MIME_FALLBACK) -> str:
    ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    return {
        "png": "image/png",
        "jpg": "image/jpeg",
        "jpeg": "image/jpeg",
        "gif": "image/gif",
        "webp": "image/webp",
        "svg": "image/svg+xml",
    }.get(ext, fallback)


def _build_openai_image_part(
    *,
    base64_data: str,
    mime_type: str,
    url: str = "",
) -> dict[str, Any]:
    if url:
        image_url = url
    else:
        image_url = f"data:{mime_type};base64,{base64_data}"
    return {"type": "image_url", "image_url": {"url": image_url}}


def _build_anthropic_image_part(
    *,
    base64_data: str,
    mime_type: str,
) -> dict[str, Any]:
    return {
        "type": "image",
        "source": {
            "type": "base64",
            "media_type": mime_type,
            "data": base64_data,
        },
    }


def _resolve_local_attachment_url(url: str) -> tuple[str, str] | None:
    """Resolve a ``/api/attachments/<sid>/<aid>/<name>`` URL to (base64, mime).

    External URLs (http/https) are not fetched here — that would be sync
    network IO inside an async-friendly path and a security footgun. Returns
    None for anything we cannot resolve from the local AttachmentStore.
    """
    if not url:
        return None
    parsed = urlparse(url)
    path = parsed.path or url
    if not path.startswith(_LOCAL_ATTACHMENT_PREFIX):
        return None
    parts = path[len(_LOCAL_ATTACHMENT_PREFIX) :].split("/")
    if len(parts) != 3:
        return None
    sid, aid, name = (unquote(p) for p in parts)
    try:
        # Local import to avoid an import-time cycle: storage already imports
        # capabilities indirectly via path service.
        from deeptutor.services.storage import get_attachment_store

        store = get_attachment_store()
        resolve = getattr(store, "resolve_path", None)
        if resolve is None:
            return None
        target = resolve(session_id=sid, attachment_id=aid, filename=name)
        if target is None:
            return None
        data = target.read_bytes()
    except Exception as exc:
        logger.warning("failed to resolve local attachment %s: %s", url, exc)
        return None
    return _b64.b64encode(data).decode("ascii"), _guess_mime_type(name)


def prepare_multimodal_messages(
    messages: list[dict[str, Any]],
    attachments: list[Any] | None,
    binding: str = "openai",
    model: str | None = None,
) -> MultimodalResult:
    """
    Inject image attachments into the last user message (Stage 1).

    Images are injected **optimistically for every provider/model** — this
    function does not consult ``supports_vision``. A model that natively
    understands images therefore always receives them, even one DeepTutor has
    no capability entry for (the original Doubao/VolcEngine bug). When a model
    genuinely cannot handle images the request fails and the Stage-2 fallback
    (:func:`should_degrade_to_text` + :func:`strip_image_parts`, applied at
    each call site's retry seam) strips the images and retries as text-only.

    The last user message ``content`` is converted from a plain string into a
    content-parts array holding the original text plus the image(s). The only
    images dropped *here* are url-only attachments the provider can't accept in
    URL form (Anthropic, or ``vision_url_supported=False``) and that can't be
    resolved to local bytes — counted in ``url_images_dropped``.

    Args:
        messages: The OpenAI-style messages list (may be mutated).
        attachments: ``Attachment`` objects from ``UnifiedContext``.
        binding: Provider binding (``"openai"``, ``"anthropic"``, …).
        model: Model name (used only to pick the URL-vs-base64 image format).

    Returns:
        A ``MultimodalResult`` with the (potentially modified) messages.
    """
    if not attachments:
        return MultimodalResult(messages=messages)

    image_attachments = [a for a in attachments if getattr(a, "type", "") == "image"]
    if not image_attachments:
        return MultimodalResult(messages=messages)

    last_user_idx = _find_last_user_message(messages)
    if last_user_idx is None:
        return MultimodalResult(messages=messages)

    is_anthropic = (binding or "").lower() in ("anthropic", "claude")
    # Anthropic adapter only emits base64 source blocks, and providers like
    # Moonshot / VolcEngine reject URL form outright. In both cases url-only
    # attachments must be resolved to bytes before injection.
    require_base64 = is_anthropic or not supports_vision_url(binding, model)
    dropped = _inject_images(
        messages,
        last_user_idx,
        image_attachments,
        anthropic=is_anthropic,
        require_base64=require_base64,
    )

    return MultimodalResult(messages=messages, url_images_dropped=dropped)


def _find_last_user_message(messages: list[dict[str, Any]]) -> int | None:
    for i in range(len(messages) - 1, -1, -1):
        if messages[i].get("role") == "user":
            return i
    return None


def _inject_images(
    messages: list[dict[str, Any]],
    user_idx: int,
    image_attachments: list[Any],
    *,
    anthropic: bool = False,
    require_base64: bool = False,
) -> int:
    """Inject image parts into the user message at *user_idx*.

    Returns the count of url-only attachments we had to drop because the
    provider needs base64 and the URL could not be resolved locally.
    """
    msg = messages[user_idx]
    original_content = msg.get("content", "")

    if isinstance(original_content, str):
        content_parts: list[dict[str, Any]] = [{"type": "text", "text": original_content}]
    elif isinstance(original_content, list):
        content_parts = list(original_content)
    else:
        content_parts = [{"type": "text", "text": str(original_content)}]

    dropped = 0
    for att in image_attachments:
        mime = getattr(att, "mime_type", "") or _guess_mime_type(
            getattr(att, "filename", "image.png")
        )
        b64 = getattr(att, "base64", "") or ""
        url = getattr(att, "url", "") or ""

        if not b64 and not url:
            continue

        # Local AttachmentStore URLs ("/api/attachments/...") are server-
        # relative paths and are never valid to send to an external LLM
        # provider — even providers that accept image URLs would receive a
        # path they can't fetch. Resolve them to base64 unconditionally so
        # the inline-base64 branch below takes over.
        is_local_attachment_url = url.startswith(_LOCAL_ATTACHMENT_PREFIX) if url else False
        if not b64 and url and (require_base64 or is_local_attachment_url):
            resolved = _resolve_local_attachment_url(url)
            if resolved is not None:
                b64, resolved_mime = resolved
                mime = mime or resolved_mime
            elif require_base64:
                logger.warning(
                    "Dropping url-only image %r: provider requires base64 but"
                    " URL is not a resolvable local attachment-store path",
                    url,
                )
                dropped += 1
                continue
            elif is_local_attachment_url:
                logger.warning(
                    "Dropping local attachment URL %r that could not be"
                    " resolved from the AttachmentStore",
                    url,
                )
                dropped += 1
                continue

        if anthropic:
            if not b64:
                logger.warning("Anthropic image part requires base64; dropping %r", url)
                dropped += 1
                continue
            content_parts.append(_build_anthropic_image_part(base64_data=b64, mime_type=mime))
        else:
            if b64:
                # Always prefer inline base64 when available — providers that
                # reject URL form (Moonshot) accept this; providers that
                # accept URLs accept this too.
                content_parts.append(_build_openai_image_part(base64_data=b64, mime_type=mime))
            else:
                content_parts.append(
                    _build_openai_image_part(base64_data="", mime_type=mime, url=url)
                )

    messages[user_idx] = {**msg, "content": content_parts}
    return dropped


_IMAGE_BLOCK_TYPES = frozenset({"image_url", "image"})


def _block_image_placeholder(block: dict[str, Any]) -> str:
    """Human-readable text placeholder for an image block being stripped."""
    meta = block.get("_meta") or {}
    label = ""
    if isinstance(meta, dict):
        label = str(meta.get("path") or meta.get("filename") or "").strip()
    if not label and block.get("type") == "image_url":
        image_url = block.get("image_url") or {}
        if isinstance(image_url, dict):
            url = str(image_url.get("url") or "").strip()
            if url and not url.startswith("data:"):
                label = url
    return f"[image: {label}]" if label else "[image omitted]"


def has_image_parts(messages: list[dict[str, Any]]) -> bool:
    """Return True when any message content contains image blocks."""
    for msg in messages:
        content = msg.get("content")
        if not isinstance(content, list):
            continue
        for item in content:
            if isinstance(item, dict) and item.get("type") in _IMAGE_BLOCK_TYPES:
                return True
    return False


def strip_image_parts(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Return a **new** message list with image blocks replaced by text
    placeholders. Use when the caller must preserve the original (e.g. to
    attempt a text-only retry while keeping the image payload for a possible
    second provider)."""
    stripped: list[dict[str, Any]] = []
    for msg in messages:
        content = msg.get("content")
        if not isinstance(content, list):
            stripped.append(dict(msg))
            continue
        new_content: list[dict[str, Any]] = [
            {"type": "text", "text": _block_image_placeholder(item)}
            if isinstance(item, dict) and item.get("type") in _IMAGE_BLOCK_TYPES
            else item
            for item in content
        ]
        stripped.append({**msg, "content": new_content})
    return stripped


def strip_image_parts_inplace(messages: list[dict[str, Any]]) -> bool:
    """Replace image blocks with text placeholders **in place**; return True
    if any were replaced.

    Used by call sites that share one message list across retries / loop
    iterations (the chat agentic loop) so the degrade persists and images are
    not re-sent — and re-rejected — on every subsequent call."""
    found = False
    for msg in messages:
        content = msg.get("content")
        if not isinstance(content, list):
            continue
        for idx, block in enumerate(content):
            if isinstance(block, dict) and block.get("type") in _IMAGE_BLOCK_TYPES:
                content[idx] = {"type": "text", "text": _block_image_placeholder(block)}
                found = True
    return found


def should_degrade_to_text(
    binding: str | None,
    model: str | None,
    messages: list[dict[str, Any]],
) -> bool:
    """Stage-2 fallback decision.

    After a request that carried image content fails, return True when we
    should strip the images and retry as text-only — i.e. the payload
    actually had image parts **and** the model is *not* in the known-vision
    allowlist (``supports_vision`` is False). For allowlisted (known
    vision-capable) models we keep the images so a genuine error surfaces
    instead of silently returning a misleading text-only answer.
    """
    if not has_image_parts(messages):
        return False
    return not supports_vision(binding or "openai", model)


__all__ = [
    "MultimodalResult",
    "has_image_parts",
    "prepare_multimodal_messages",
    "should_degrade_to_text",
    "strip_image_parts",
    "strip_image_parts_inplace",
]
