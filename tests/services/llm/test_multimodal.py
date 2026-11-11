"""Tests for the two-stage multimodal pipeline.

Stage 1 (:func:`prepare_multimodal_messages`) injects image attachments for
*every* provider/model — there is no ``supports_vision`` pre-flight gate. It
only resolves URL→base64 where the provider's *format* requires it and drops
url-only images it cannot encode (``url_images_dropped``).

Stage 2 (:func:`should_degrade_to_text` + :func:`strip_image_parts*`) is the
post-failure fallback: applied at each call site's retry seam, it strips images
and retries text-only only when the model is *not* in the known-vision
allowlist.
"""

from __future__ import annotations

import base64
from types import SimpleNamespace
from urllib.parse import quote

import pytest

from deeptutor.services.llm.multimodal import (
    PRIOR_IMAGE_NOTE,
    has_image_parts,
    prepare_multimodal_messages,
    should_degrade_to_text,
    strip_image_parts,
    strip_image_parts_inplace,
)
from deeptutor.services.storage import attachment_store


def _msgs() -> list[dict]:
    return [{"role": "user", "content": "describe"}]


def _img_part_url(message: dict) -> str:
    parts = message["content"]
    img = next(p for p in parts if p.get("type") == "image_url")
    return img["image_url"]["url"]


# ---------------------------------------------------------------------------
# Stage 1: optimistic injection
# ---------------------------------------------------------------------------
def test_openai_compat_passes_url_through() -> None:
    """OpenAI-compatible providers (default vision_url_supported=True) accept
    URL-form image_url blocks unchanged."""
    att = SimpleNamespace(type="image", url="https://example.com/cat.png", base64="")
    result = prepare_multimodal_messages(_msgs(), [att], binding="openai", model="gpt-4o")
    assert result.url_images_dropped == 0
    assert _img_part_url(result.messages[0]) == "https://example.com/cat.png"


def test_openai_compat_prefers_base64_when_both_present() -> None:
    """When base64 is set we always inline it — works for everyone."""
    att = SimpleNamespace(
        type="image",
        url="https://example.com/cat.png",
        base64="QUJD",  # "ABC"
        mime_type="image/png",
    )
    result = prepare_multimodal_messages(_msgs(), [att], binding="openai", model="gpt-4o")
    url = _img_part_url(result.messages[0])
    assert url.startswith("data:image/png;base64,QUJD")


def test_unknown_provider_still_injects_images() -> None:
    """Regression for the Doubao/VolcEngine bug: a provider with no capability
    entry (``supports_vision`` defaults False) must STILL receive the image —
    Stage 1 never gates on the capability flag."""
    att = SimpleNamespace(type="image", base64="QUJD", mime_type="image/png")
    result = prepare_multimodal_messages(
        _msgs(), [att], binding="some-unregistered-provider", model="doubao-1.5-vision-pro"
    )
    assert _img_part_url(result.messages[0]).startswith("data:image/png;base64,QUJD")


def test_text_only_model_still_injects_images() -> None:
    """A plain Moonshot text model no longer strips images at Stage 1 — the
    image is injected optimistically; degrade happens later via Stage 2."""
    att = SimpleNamespace(type="image", base64="QUJD", mime_type="image/png")
    result = prepare_multimodal_messages(_msgs(), [att], binding="moonshot", model="moonshot-v1-8k")
    assert _img_part_url(result.messages[0]).startswith("data:image/png;base64,QUJD")


# ---------------------------------------------------------------------------
# Stage 1: URL→base64 format resolution (unchanged behaviour)
# ---------------------------------------------------------------------------
def test_moonshot_kimi_drops_external_url_only_attachment(caplog) -> None:
    """Moonshot rejects URL-form image_url; an external url-only attachment
    cannot be resolved locally and must be dropped (a *format* drop, not a
    capability gate)."""
    att = SimpleNamespace(type="image", url="https://example.com/cat.png", base64="")
    with caplog.at_level("WARNING"):
        result = prepare_multimodal_messages(_msgs(), [att], binding="moonshot", model="kimi-k2.6")
    assert result.url_images_dropped == 1
    parts = result.messages[0]["content"]
    assert not any(p.get("type") == "image_url" for p in parts)


def test_moonshot_kimi_resolves_local_attachment_url(tmp_path, monkeypatch) -> None:
    """A ``/files/attachments/...`` URL is read from the AttachmentStore and
    re-encoded as inline base64 before being sent to Moonshot."""
    monkeypatch.setenv("CHAT_ATTACHMENT_DIR", str(tmp_path))
    attachment_store.reset_attachment_store()

    sid, aid, name = "sess1", "att1", "cat.png"
    raw_bytes = b"\x89PNG\r\n\x1a\nFAKE"
    session_dir = tmp_path / sid
    session_dir.mkdir(parents=True)
    (session_dir / f"{aid}_{name}").write_bytes(raw_bytes)

    url = f"/files/attachments/{quote(sid)}/{quote(aid)}/{quote(name)}"
    att = SimpleNamespace(type="image", url=url, base64="")

    try:
        result = prepare_multimodal_messages(_msgs(), [att], binding="moonshot", model="kimi-k2.6")
    finally:
        attachment_store.reset_attachment_store()

    assert result.url_images_dropped == 0
    inlined = _img_part_url(result.messages[0])
    expected_b64 = base64.b64encode(raw_bytes).decode("ascii")
    assert inlined == f"data:image/png;base64,{expected_b64}"


def test_resolved_local_attachment_mime_wins_over_filename_guess(tmp_path, monkeypatch) -> None:
    """When an attachment declares no mime_type and no useful filename, the MIME
    resolved from the stored attachment name must be used, not the image/png
    fallback guessed from the (empty) attachment filename."""
    monkeypatch.setenv("CHAT_ATTACHMENT_DIR", str(tmp_path))
    attachment_store.reset_attachment_store()

    sid, aid, name = "sess1", "att1", "photo.jpg"
    raw_bytes = b"\xff\xd8\xff\xe0FAKEJPEG"
    session_dir = tmp_path / sid
    session_dir.mkdir(parents=True)
    (session_dir / f"{aid}_{name}").write_bytes(raw_bytes)

    url = f"/files/attachments/{quote(sid)}/{quote(aid)}/{quote(name)}"
    # No mime_type and no filename on the attachment record.
    att = SimpleNamespace(type="image", url=url, base64="")

    try:
        result = prepare_multimodal_messages(_msgs(), [att], binding="moonshot", model="kimi-k2.6")
    finally:
        attachment_store.reset_attachment_store()

    expected_b64 = base64.b64encode(raw_bytes).decode("ascii")
    assert _img_part_url(result.messages[0]) == f"data:image/jpeg;base64,{expected_b64}"


def test_anthropic_url_only_attachment_is_dropped_not_sent_empty(caplog) -> None:
    """Previously the Anthropic path silently emitted an empty base64 source.
    url-only attachments without local resolution are dropped instead."""
    att = SimpleNamespace(type="image", url="https://example.com/cat.png", base64="")
    with caplog.at_level("WARNING"):
        result = prepare_multimodal_messages(
            _msgs(), [att], binding="anthropic", model="claude-3-5-sonnet"
        )
    assert result.url_images_dropped == 1
    parts = result.messages[0]["content"]
    for p in parts:
        if p.get("type") == "image":
            data = p.get("source", {}).get("data", "")
            assert data, "Anthropic image part must not have empty base64"


# ---------------------------------------------------------------------------
# Stage 1: prior-turn image origin note (#2632)
#
# Prior-turn images are re-attached by the turn executor with
# ``historical=True``; without an origin note the model reads them as fresh
# uploads of the current message ("in the screenshot you sent...").
# ---------------------------------------------------------------------------
def _note_indexes(parts: list[dict]) -> list[int]:
    return [
        i for i, p in enumerate(parts) if p.get("type") == "text" and p["text"] == PRIOR_IMAGE_NOTE
    ]


def test_prior_turn_image_is_preceded_by_origin_note() -> None:
    att = SimpleNamespace(type="image", base64="QUJD", mime_type="image/png", historical=True)
    result = prepare_multimodal_messages(_msgs(), [att], binding="openai", model="gpt-4o")
    parts = result.messages[0]["content"]
    notes = _note_indexes(parts)
    assert notes == [1], "exactly one note, between the message text and the image"
    assert parts[0]["text"] == "describe"
    assert parts[2]["type"] == "image_url"


def test_current_turn_upload_gets_no_origin_note() -> None:
    # No ``historical`` attribute at all — every pre-#2632 caller shape.
    att = SimpleNamespace(type="image", base64="QUJD", mime_type="image/png")
    result = prepare_multimodal_messages(_msgs(), [att], binding="openai", model="gpt-4o")
    parts = result.messages[0]["content"]
    assert _note_indexes(parts) == []
    assert [p["type"] for p in parts] == ["text", "image_url"]


def test_current_turn_upload_with_explicit_historical_false_gets_no_note() -> None:
    att = SimpleNamespace(type="image", base64="QUJD", mime_type="image/png", historical=False)
    result = prepare_multimodal_messages(_msgs(), [att], binding="openai", model="gpt-4o")
    assert _note_indexes(result.messages[0]["content"]) == []


def test_mixed_uploads_note_only_the_prior_turn_image() -> None:
    """Current-turn uploads first (executor order), prior images after: the
    note must precede only the historical image."""
    fresh = SimpleNamespace(type="image", base64="QUJD", mime_type="image/png")
    prior = SimpleNamespace(type="image", base64="Q0FB", mime_type="image/png", historical=True)
    result = prepare_multimodal_messages(_msgs(), [fresh, prior], binding="openai", model="gpt-4o")
    parts = result.messages[0]["content"]
    img_idx = [i for i, p in enumerate(parts) if p["type"] == "image_url"]
    assert img_idx == [1, 3]
    assert _note_indexes(parts) == [2], "note sits directly before the prior image only"
    assert parts[1]["image_url"]["url"].startswith("data:image/png;base64,QUJD")
    assert parts[3]["image_url"]["url"].startswith("data:image/png;base64,Q0FB")


def test_anthropic_prior_turn_image_also_gets_origin_note() -> None:
    att = SimpleNamespace(type="image", base64="QUJD", mime_type="image/png", historical=True)
    result = prepare_multimodal_messages(
        _msgs(), [att], binding="anthropic", model="claude-3-5-sonnet"
    )
    parts = result.messages[0]["content"]
    assert _note_indexes(parts) == [1]
    assert parts[2]["type"] == "image"


def test_dropped_prior_turn_image_leaves_no_orphan_note() -> None:
    """A url-only image that cannot be resolved for a base64-only provider
    is dropped — its origin note must not survive alone."""
    att = SimpleNamespace(
        type="image",
        url="https://example.com/old.png",
        base64="",
        historical=True,
    )
    result = prepare_multimodal_messages(_msgs(), [att], binding="moonshot", model="kimi-k2.6")
    assert result.url_images_dropped == 1
    assert _note_indexes(result.messages[0]["content"]) == []


# ---------------------------------------------------------------------------
# Stage 2: fallback decision + stripping
# ---------------------------------------------------------------------------
def _img_messages() -> list[dict]:
    return [
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "what is this"},
                {"type": "image_url", "image_url": {"url": "data:image/png;base64,QUJD"}},
            ],
        }
    ]


def test_should_degrade_only_for_non_vision_model_with_images() -> None:
    msgs = _img_messages()
    # Not in the known-vision allowlist → degrade to text on failure.
    assert should_degrade_to_text("moonshot", "moonshot-v1-8k", msgs) is True
    # Known vision-capable model → keep images, surface the real error.
    assert should_degrade_to_text("openai", "gpt-4o", msgs) is False
    # Codex uses the Responses API and must not silently retry without its image.
    assert should_degrade_to_text("openai_codex", "gpt-5.6-sol", msgs) is False
    # Qwen3.8-Max is multimodal even though its model ID has no ``-vl`` suffix.
    assert should_degrade_to_text("dashscope", "qwen3.8-max", msgs) is False
    # An allowlisted provider (VolcEngine) is trusted even for a model we have
    # no per-model entry for.
    assert should_degrade_to_text("volcengine", "doubao-1.5-vision-pro", msgs) is False


def test_should_degrade_is_false_without_images() -> None:
    text_only = [{"role": "user", "content": "hi"}]
    assert should_degrade_to_text("moonshot", "moonshot-v1-8k", text_only) is False


def test_strip_image_parts_inplace_mutates_and_reports() -> None:
    msgs = _img_messages()
    assert has_image_parts(msgs) is True
    changed = strip_image_parts_inplace(msgs)
    assert changed is True
    assert has_image_parts(msgs) is False
    # The text block survives; the image becomes a placeholder.
    types = [p["type"] for p in msgs[0]["content"]]
    assert types == ["text", "text"]
    # No-op on a message list without images.
    assert strip_image_parts_inplace([{"role": "user", "content": "hi"}]) is False


def test_strip_image_parts_returns_new_list_without_mutating() -> None:
    msgs = _img_messages()
    stripped = strip_image_parts(msgs)
    assert has_image_parts(stripped) is False
    # Original is untouched (new-list variant).
    assert has_image_parts(msgs) is True
