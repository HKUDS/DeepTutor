"""Real-data replay for #2632: prior-turn images re-injected into a
text-only turn must be labelled as historical, not presented as a fresh
upload of the current message.

Sample source: the scenario described in issue #2632's body (message #131
carries an image, message #227 is text-only, and the request for message
#228 merges that old image into the current user text) plus this
repository's existing test idioms — the FakeStore lineage from
``tests/services/session/test_source_inventory.py`` and the temp-dir
attachment store from ``tests/services/llm/test_multimodal.py``. No
external capture: image bytes are tiny placeholders.

The replay follows the production path end to end at the unit seam:
persisted lineage → ``collect_prior_image_attachments`` → the
``Attachment`` construction used by ``turns/executor.py`` →
``prepare_multimodal_messages``.
"""

from __future__ import annotations

import base64
from typing import Any

import pytest

from deeptutor.core.context import Attachment
from deeptutor.services.llm.multimodal import PRIOR_IMAGE_NOTE, prepare_multimodal_messages
from deeptutor.services.session.source_inventory import collect_prior_image_attachments
from deeptutor.services.storage import attachment_store

SESSION_ID = "sess-2632"
# Minimal placeholder bytes — nothing decodes them, they only need to be
# stable and tiny (no real screenshots).
PRIOR_IMAGE_BYTES = b"\x89PNG\r\n\x1a\nTINY131"
FRESH_IMAGE_B64 = base64.b64encode(b"TINY228FRESH").decode("ascii")
PRIOR_IMAGE_URL = f"/files/attachments/{SESSION_ID}/img-131/fig131.png"


class ReplayStore:
    """Minimal session-store fake: only ``get_messages`` is on the
    prior-image collector's path."""

    def __init__(self, messages: list[dict[str, Any]]) -> None:
        self._messages = messages

    async def get_messages(self, session_id: str) -> list[dict[str, Any]]:
        return self._messages


def _issue_2632_lineage() -> list[dict[str, Any]]:
    """The persisted conversation up to message #227, per the issue: an
    earlier image upload (#131), a later text-only user message (#227)."""
    return [
        {
            "id": 1,
            "role": "user",
            "content": "start of the conversation",
            "parent_message_id": None,
            "attachments": [],
        },
        {"id": 130, "role": "assistant", "content": "…", "parent_message_id": 1},
        {
            "id": 131,
            "role": "user",
            "content": "请看这张图，帮我分析里面的曲线",
            "parent_message_id": 130,
            "attachments": [
                {
                    "id": "img-131",
                    "type": "image",
                    "filename": "fig131.png",
                    "mime_type": "image/png",
                    "url": PRIOR_IMAGE_URL,
                }
            ],
        },
        {"id": 132, "role": "assistant", "content": "…", "parent_message_id": 131},
        {"id": 226, "role": "assistant", "content": "…", "parent_message_id": 132},
        {
            "id": 227,
            "role": "user",
            "content": "继续，不用再传图了",
            "parent_message_id": 226,
            "attachments": [],
        },
    ]


def _fresh_attachment(record: dict[str, Any]) -> Attachment:
    """Current-turn attachment construction, mirroring turns/executor.py."""
    return Attachment(
        type=record.get("type", "file"),
        url=record.get("url", ""),
        base64=record.get("base64", ""),
        filename=record.get("filename", ""),
        mime_type=record.get("mime_type", ""),
        id=record.get("id", ""),
        extracted_text=record.get("extracted_text", ""),
    )


def _prior_attachment(record: dict[str, Any]) -> Attachment:
    """Prior-turn image attachment construction, mirroring turns/executor.py."""
    return Attachment(
        type="image",
        url=record["url"],
        base64="",
        filename=record.get("filename", ""),
        mime_type=record.get("mime_type", ""),
        id=record.get("id", ""),
        historical=bool(record.get("historical", False)),
        source_message_id=str(record.get("source_message_id", "") or ""),
    )


def _model_messages(current_text: str) -> list[dict[str, Any]]:
    return [
        {"role": "user", "content": "请看这张图，帮我分析里面的曲线"},
        {"role": "assistant", "content": "这条曲线呈现先升后降的趋势…"},
        {"role": "user", "content": "继续，不用再传图了"},
        {"role": "assistant", "content": "好的，结合上图结论…"},
        {"role": "user", "content": current_text},
    ]


def _note_indexes(parts: list[dict[str, Any]]) -> list[int]:
    return [
        i for i, p in enumerate(parts) if p.get("type") == "text" and p["text"] == PRIOR_IMAGE_NOTE
    ]


def _seed_attachment_store(tmp_path) -> None:
    session_dir = tmp_path / SESSION_ID
    session_dir.mkdir(parents=True)
    (session_dir / "img-131_fig131.png").write_bytes(PRIOR_IMAGE_BYTES)


@pytest.mark.asyncio
async def test_turn_228_text_only_replay_labels_the_reinjected_image(tmp_path, monkeypatch):
    """The #2632 report: turn #228 sends text only, yet the request carries
    message #131's image. The assembled last user message must say the image
    is from an earlier message, right before the image part."""
    monkeypatch.setenv("CHAT_ATTACHMENT_DIR", str(tmp_path))
    attachment_store.reset_attachment_store()
    _seed_attachment_store(tmp_path)

    try:
        store = ReplayStore(_issue_2632_lineage())
        prior_records = await collect_prior_image_attachments(
            store,
            session_id=SESSION_ID,
            leaf_message_id=227,
            exclude_urls=set(),
        )
        assert [rec["id"] for rec in prior_records] == ["img-131"]
        assert prior_records[0]["historical"] is True
        assert prior_records[0]["source_message_id"] == "131"

        attachments = [_prior_attachment(rec) for rec in prior_records]
        current_text = "帮我把结论整理成一段话"  # message #228: no new upload
        result = prepare_multimodal_messages(
            _model_messages(current_text), attachments, binding="openai", model="gpt-4o"
        )
    finally:
        attachment_store.reset_attachment_store()

    assert result.url_images_dropped == 0
    last = result.messages[-1]
    assert last["role"] == "user"
    parts = last["content"]
    assert parts[0] == {"type": "text", "text": current_text}
    notes = _note_indexes(parts)
    img_idx = next(i for i, p in enumerate(parts) if p.get("type") == "image_url")
    assert notes == [img_idx - 1], "origin note directly precedes the reinjected image"
    expected_b64 = base64.b64encode(PRIOR_IMAGE_BYTES).decode("ascii")
    assert parts[img_idx]["image_url"]["url"] == f"data:image/png;base64,{expected_b64}"
    # Earlier turns are untouched.
    assert all(isinstance(m["content"], str) for m in result.messages[:-1])


@pytest.mark.asyncio
async def test_turn_228_with_fresh_upload_replay_notes_only_the_prior_image(tmp_path, monkeypatch):
    """Same replay with a current-turn upload alongside: the fresh image is
    unannotated, the reinjected one keeps its origin note."""
    monkeypatch.setenv("CHAT_ATTACHMENT_DIR", str(tmp_path))
    attachment_store.reset_attachment_store()
    _seed_attachment_store(tmp_path)

    try:
        store = ReplayStore(_issue_2632_lineage())
        fresh_records = [
            {
                "id": "img-228",
                "type": "image",
                "base64": FRESH_IMAGE_B64,
                "filename": "new228.png",
                "mime_type": "image/png",
                "url": "",
            }
        ]
        prior_records = await collect_prior_image_attachments(
            store,
            session_id=SESSION_ID,
            leaf_message_id=227,
            exclude_urls={r["url"] for r in fresh_records if r["url"]},
        )
        assert [rec["id"] for rec in prior_records] == ["img-131"]

        attachments = [_fresh_attachment(r) for r in fresh_records]
        attachments.extend(_prior_attachment(rec) for rec in prior_records)
        result = prepare_multimodal_messages(
            _model_messages("再对比我新传的这张"),
            attachments,
            binding="openai",
            model="gpt-4o",
        )
    finally:
        attachment_store.reset_attachment_store()

    assert result.url_images_dropped == 0
    parts = result.messages[-1]["content"]
    img_idx = [i for i, p in enumerate(parts) if p.get("type") == "image_url"]
    assert img_idx == [1, 3]
    assert _note_indexes(parts) == [2], "only the prior-turn image carries a note"
    assert parts[1]["image_url"]["url"] == f"data:image/png;base64,{FRESH_IMAGE_B64}"
    expected_b64 = base64.b64encode(PRIOR_IMAGE_BYTES).decode("ascii")
    assert parts[3]["image_url"]["url"] == f"data:image/png;base64,{expected_b64}"


def test_attachment_defaults_keep_current_uploads_unmarked():
    """Default Attachment fields preserve pre-#2632 behavior: nothing is
    historical unless explicitly marked by the prior-image path."""
    fresh = Attachment(type="image", base64="QUJD", mime_type="image/png")
    assert fresh.historical is False
    assert fresh.source_message_id == ""

    result = prepare_multimodal_messages(
        _model_messages("text only turn"), [fresh], binding="openai", model="gpt-4o"
    )
    parts = result.messages[-1]["content"]
    assert _note_indexes(parts) == []
