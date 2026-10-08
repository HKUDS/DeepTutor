"""Saved quiz-answer images are sent to the judge as provider-readable data."""

import base64
from pathlib import Path

import pytest

from deeptutor.api.routers.quiz_judge import _build_multimodal_user_content
from deeptutor.services.storage.attachment_store import LocalDiskAttachmentStore


@pytest.mark.asyncio
@pytest.mark.parametrize("legacy", [False, True])
async def test_saved_answer_image_is_materialized(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, legacy: bool
) -> None:
    """Use the actual store's URL, including an encoded Unicode filename."""
    store = LocalDiskAttachmentStore(tmp_path / "attachments")
    image = b"test-only-image-bytes"
    filename = "answer 中文.png"
    url = await store.put(
        session_id="quiz-session",
        attachment_id="answer-1",
        filename=filename,
        data=image,
    )
    if legacy:
        url = url.replace("/files/attachments/", "/api/attachments/")
    monkeypatch.setattr("deeptutor.services.storage.get_attachment_store", lambda: store)
    content = await _build_multimodal_user_content(
        text="Judge this answer",
        image_records=[{"url": url, "filename": filename, "mime_type": "image/png"}],
    )
    assert content == [
        {"type": "text", "text": "Judge this answer"},
        {
            "type": "image_url",
            "image_url": {"url": "data:image/png;base64," + base64.b64encode(image).decode()},
        },
    ]
