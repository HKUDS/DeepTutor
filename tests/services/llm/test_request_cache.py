from deeptutor.services.llm.provider_core.openai_codex_provider import _prompt_cache_key
from deeptutor.services.llm.request_cache import compare_requests, fingerprint_request


def test_prefix_diagnostics_distinguish_append_history_tools_and_route_changes():
    messages = [{"role": "system", "content": "rules"}, {"role": "user", "content": "question"}]
    route = {"model": "example"}
    previous = fingerprint_request(messages, [], route)
    current = fingerprint_request(
        [*messages, {"role": "assistant", "content": "answer"}], [], route
    )
    assert compare_requests(previous, current)["first_change"] == "append"
    assert compare_requests(previous, current)["shared_prefix_messages"] == 2
    assert "question" not in str(previous)
    assert (
        compare_requests(previous, fingerprint_request(messages[:1], [], route))["first_change"]
        == "history"
    )
    assert (
        compare_requests(previous, fingerprint_request(messages, [{"name": "new"}], route))[
            "first_change"
        ]
        == "tools"
    )
    assert (
        compare_requests(previous, fingerprint_request(messages, [], {"model": "other"}))[
            "first_change"
        ]
        == "route"
    )


def test_codex_cache_affinity_survives_new_turns_and_tool_messages():
    messages = [{"role": "system", "content": "rules"}, {"role": "user", "content": "question"}]
    assert _prompt_cache_key(messages) == _prompt_cache_key(
        [*messages, {"role": "assistant", "content": "answer"}, {"role": "user", "content": "next"}]
    )
    assert _prompt_cache_key(messages) != _prompt_cache_key(
        [{"role": "system", "content": "new rules"}]
    )


def test_claude_compat_marks_latest_tool_result_with_at_most_four_breakpoints():
    from copy import deepcopy

    from deeptutor.services.llm.provider_core.openai_compat_provider import OpenAICompatProvider

    messages = [
        {"role": "system", "content": "rules"},
        {"role": "user", "content": "question"},
        {"role": "tool", "tool_call_id": "a", "content": "large new evidence"},
    ]
    tools = [{"type": "function", "function": {"name": f"tool{i}"}} for i in range(25)]
    original = deepcopy((messages, tools))
    marked, schemas = OpenAICompatProvider._apply_cache_control(messages, tools)
    assert marked[-1]["content"][-1]["cache_control"] == {"type": "ephemeral"}
    count = sum("cache_control" in tool for tool in schemas)
    count += sum(
        "cache_control" in block
        for m in marked
        for block in m["content"]
        if isinstance(block, dict)
    )
    assert count <= 4
    assert (messages, tools) == original


def test_image_fingerprint_keeps_payload_hash_without_tokenizing_image_data(monkeypatch):
    from copy import deepcopy

    from deeptutor.services.session import context_builder

    payload = "YWJj" * 1000
    blocks = [
        {"type": "image_url", "image_url": {"url": "data:image/png;base64," + payload}},
        {"type": "input_image", "image_url": "https://example.org/image.png"},
        {"type": "input_image", "file_id": "file-example"},
        {"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": payload}},
    ]
    messages = [{"role": "user", "content": [*blocks, {"type": "text", "text": "hello"}]}]
    original = deepcopy(messages)
    tokenized = []

    def count(text):
        tokenized.append(text)
        return 7

    monkeypatch.setattr(context_builder, "count_tokens", count)
    fingerprint = fingerprint_request(messages, [], {})
    assert payload not in "".join(tokenized)
    assert "https://example.org" not in "".join(tokenized)
    assert "file-example" not in "".join(tokenized)
    assert "hello" in "".join(tokenized)
    assert (
        fingerprint["messages"][0]["tokens"] == 7 + 4 * context_builder.IMAGE_CONTEXT_TOKEN_ESTIMATE
    )
    assert messages == original
    changed = deepcopy(messages)
    changed[0]["content"][0]["image_url"]["url"] += "AAAA"
    assert (
        fingerprint_request(changed, [], {})["messages"][0]["hash"]
        != fingerprint["messages"][0]["hash"]
    )
    assert (
        compare_requests(fingerprint, fingerprint_request(changed, [], {}))["first_change"]
        == "history"
    )


def test_fingerprint_estimate_preserves_tool_and_provider_replay_text(monkeypatch):
    from deeptutor.services.session import context_builder

    tokenized = []
    monkeypatch.setattr(context_builder, "count_tokens", lambda text: tokenized.append(text) or 11)
    messages = [
        {
            "role": "assistant",
            "content": "reasoning",
            "tool_calls": [{"arguments": "important"}],
            "thinking_blocks": [{"signature": "signature", "text": "thought"}],
        },
        {"role": "tool", "content": "result", "tool_call_id": "call"},
    ]
    fingerprint = fingerprint_request(messages, [], {})
    assert [message["tokens"] for message in fingerprint["messages"]] == [11, 11]
    assert all(
        value in "".join(tokenized)
        for value in ("reasoning", "important", "signature", "thought", "result", "call")
    )
