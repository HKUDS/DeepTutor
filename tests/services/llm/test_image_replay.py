from copy import deepcopy

import pytest

from deeptutor.services.llm.image_replay import deduplicate_user_images


@pytest.mark.parametrize(
    "image",
    [
        {"type": "image_url", "image_url": {"url": "data:image/png;base64,YWJj"}},
        {"type": "input_image", "image_url": "data:image/png;base64,YWJj"},
        {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": "YWJj"}},
    ],
)
def test_only_duplicate_user_images_are_projected_and_history_is_complete(image):
    messages = [
        {"role": "user", "content": [{"type": "text", "text": "first"}, image]},
        {"role": "assistant", "content": "answer", "reasoning_content": "unchanged"},
        {"role": "user", "content": [{"type": "text", "text": "again"}, deepcopy(image)]},
        {"role": "tool", "tool_call_id": "t", "content": [deepcopy(image)]},
    ]
    before = deepcopy(messages)
    wire = deduplicate_user_images(messages)
    assert messages == before
    assert wire[0]["content"][-1] == image
    assert wire[0]["content"][0] == messages[0]["content"][0]
    assert "Repeated image" in wire[2]["content"][-1]["text"]
    assert wire[1] == messages[1]
    assert wire[3] == messages[3]
    # Projecting again is harmless; a later history cut still has real bytes.
    assert deduplicate_user_images(wire) == wire
    assert deduplicate_user_images(messages[2:])[0]["content"][-1] == image


def test_remote_images_unique_images_and_detail_options_are_preserved():
    blocks = [
        {"type": "image_url", "image_url": {"url": "https://example.com/changing.png"}},
        {"type": "image_url", "image_url": {"url": "https://example.com/changing.png"}},
        {"type": "image_url", "image_url": {"url": "data:image/png;base64,YWJj", "detail": "low"}},
        {"type": "image_url", "image_url": {"url": "data:image/png;base64,YWJj", "detail": "high"}},
        {"type": "image_url", "image_url": {"url": "data:image/png;base64,ZGVm"}},
    ]
    messages = [{"role": "user", "content": blocks}]
    assert deduplicate_user_images(messages) == messages


def test_projection_keeps_previous_wire_prefix_when_a_turn_is_appended():
    image = {"type": "image_url", "image_url": {"url": "data:image/png;base64,YWJj"}}
    messages = [{"role": "user", "content": [image]}]
    first = deduplicate_user_images(messages)
    later = deduplicate_user_images([*messages, {"role": "user", "content": [image]}])
    assert later[: len(first)] == first


def test_duplicate_inside_one_message_references_retained_image_and_preserves_count():
    image = {"type": "image_url", "image_url": {"url": "data:image/png;base64,YWJj"}}
    wire = deduplicate_user_images([{"role": "user", "content": [image, image, image]}])
    assert wire[0]["content"][0] == image
    assert len(wire[0]["content"]) == 3
    assert all("image 1 in message 1" in part["text"] for part in wire[0]["content"][1:])


def test_changed_mime_and_provider_options_are_not_duplicates():
    image = {
        "type": "image",
        "source": {"type": "base64", "media_type": "image/png", "data": "YWJj"},
    }
    other = deepcopy(image)
    other["source"]["media_type"] = "image/jpeg"
    with_cache = {**image, "cache_control": {"type": "ephemeral"}}
    messages = [{"role": "user", "content": [image, other, with_cache]}]
    assert deduplicate_user_images(messages) == messages
