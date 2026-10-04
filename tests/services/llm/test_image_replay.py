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
    assert [
        part for part in deduplicate_user_images(messages)[0]["content"] if part["type"] != "text"
    ] == blocks


def test_projection_keeps_previous_wire_prefix_when_a_turn_is_appended():
    image = {"type": "image_url", "image_url": {"url": "data:image/png;base64,YWJj"}}
    messages = [{"role": "user", "content": [image]}]
    first = deduplicate_user_images(messages)
    later = deduplicate_user_images([*messages, {"role": "user", "content": [image]}])
    assert later[: len(first)] == first


def test_duplicate_inside_one_message_references_retained_image_and_preserves_count():
    image = {"type": "image_url", "image_url": {"url": "data:image/png;base64,YWJj"}}
    wire = deduplicate_user_images([{"role": "user", "content": [image, image, image]}])
    assert wire[0]["content"][1] == image
    assert len(wire[0]["content"]) == 4
    label = wire[0]["content"][0]["text"].removeprefix("[Image ").removesuffix("]")
    assert all(label in part["text"] for part in wire[0]["content"][2:])


def test_changed_mime_and_provider_options_are_not_duplicates():
    image = {
        "type": "image",
        "source": {"type": "base64", "media_type": "image/png", "data": "YWJj"},
    }
    other = deepcopy(image)
    other["source"]["media_type"] = "image/jpeg"
    with_cache = {**image, "cache_control": {"type": "ephemeral"}}
    messages = [{"role": "user", "content": [image, other, with_cache]}]
    assert [
        part for part in deduplicate_user_images(messages)[0]["content"] if part["type"] != "text"
    ] == [image, other, with_cache]


def test_stable_label_references_inline_image_among_remote_images():
    remote = {"type": "image_url", "image_url": {"url": "https://example.org/image.png"}}
    image = {"type": "image_url", "image_url": {"url": "data:image/png;base64,YWJj"}}
    wire = deduplicate_user_images([{"role": "user", "content": [remote, image, image]}])
    assert wire[0]["content"][0] == remote
    assert wire[0]["content"][2] == image
    label = wire[0]["content"][1]["text"].removeprefix("[Image ").removesuffix("]")
    assert label in wire[0]["content"][3]["text"]
