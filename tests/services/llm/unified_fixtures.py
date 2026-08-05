"""Shared wire-format fixtures for the unified three-protocol contract tests.

Every fixture is a plain dict (the shape a transport would return), so the
tests exercise the deterministic converters with no real endpoint.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Equivalent semantic conversation (system + user + assistant tool call +
# tool result) used to prove the three protocols preserve the same message.
# ---------------------------------------------------------------------------

LEGACY_MESSAGES = [
    {"role": "system", "content": "You are a helpful assistant."},
    {"role": "user", "content": "What is the weather in Paris?"},
    {
        "role": "assistant",
        "content": None,
        "tool_calls": [
            {
                "id": "call_1",
                "type": "function",
                "function": {
                    "name": "get_weather",
                    "arguments": '{"city": "Paris"}',
                },
            }
        ],
    },
    {"role": "tool", "tool_call_id": "call_1", "content": "21C, sunny"},
]

# ---------------------------------------------------------------------------
# OpenAI Chat Completions
# ---------------------------------------------------------------------------

CHAT_COMPLETIONS_TEXT = {
    "id": "chatcmpl_123",
    "model": "gpt-5.6",
    "choices": [
        {
            "index": 0,
            "message": {"role": "assistant", "content": "Hello there!"},
            "finish_reason": "stop",
        }
    ],
    "usage": {"prompt_tokens": 10, "completion_tokens": 2, "total_tokens": 12},
}

CHAT_COMPLETIONS_TOOL = {
    "id": "chatcmpl_456",
    "model": "gpt-5.6",
    "choices": [
        {
            "index": 0,
            "message": {
                "role": "assistant",
                "content": None,
                "tool_calls": [
                    {
                        "id": "call_1",
                        "type": "function",
                        "function": {
                            "name": "get_weather",
                            "arguments": '{"city": "Paris"}',
                        },
                    },
                    {
                        "id": "call_2",
                        "type": "function",
                        "function": {
                            "name": "get_time",
                            "arguments": '{"city": "Paris"}',
                        },
                    },
                ],
            },
            "finish_reason": "tool_calls",
        }
    ],
    "usage": {"prompt_tokens": 15, "completion_tokens": 6, "total_tokens": 21},
}

CHAT_COMPLETIONS_REASONING = {
    "id": "chatcmpl_789",
    "model": "o3-mini",
    "choices": [
        {
            "index": 0,
            "message": {
                "role": "assistant",
                "content": None,
                "reasoning_content": "Let me think step by step.",
            },
            "finish_reason": "stop",
        }
    ],
    "usage": {"prompt_tokens": 8, "completion_tokens": 3, "total_tokens": 11},
}

CHAT_COMPLETIONS_STREAM_TEXT = [
    {
        "id": "chatcmpl_s1",
        "model": "gpt-5.6",
        "choices": [
            {"index": 0, "delta": {"role": "assistant", "content": "Hel"}, "finish_reason": None}
        ],
    },
    {
        "id": "chatcmpl_s1",
        "model": "gpt-5.6",
        "choices": [{"index": 0, "delta": {"content": "lo"}, "finish_reason": None}],
    },
    {
        "id": "chatcmpl_s1",
        "model": "gpt-5.6",
        "choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}],
    },
    {
        "id": "chatcmpl_s1",
        "model": "gpt-5.6",
        "choices": [],
        "usage": {"prompt_tokens": 10, "completion_tokens": 2, "total_tokens": 12},
    },
]

CHAT_COMPLETIONS_STREAM_TOOL = [
    {
        "choices": [
            {
                "index": 0,
                "delta": {
                    "tool_calls": [
                        {
                            "index": 0,
                            "id": "call_1",
                            "type": "function",
                            "function": {"name": "get_weather", "arguments": ""},
                        }
                    ]
                },
                "finish_reason": None,
            }
        ]
    },
    {
        "choices": [
            {
                "index": 0,
                "delta": {"tool_calls": [{"index": 0, "function": {"arguments": '{"cit'}}]},
                "finish_reason": None,
            }
        ]
    },
    {
        "choices": [
            {
                "index": 0,
                "delta": {"tool_calls": [{"index": 0, "function": {"arguments": 'y": "Paris"}'}}]},
                "finish_reason": None,
            }
        ]
    },
    {"choices": [{"index": 0, "delta": {}, "finish_reason": "tool_calls"}]},
]

CHAT_COMPLETIONS_STREAM_BAD_ARGS = [
    {
        "choices": [
            {
                "index": 0,
                "delta": {
                    "tool_calls": [
                        {
                            "index": 0,
                            "id": "call_1",
                            "type": "function",
                            "function": {"name": "f", "arguments": ""},
                        }
                    ]
                },
                "finish_reason": None,
            }
        ]
    },
    {
        "choices": [
            {
                "index": 0,
                "delta": {
                    "tool_calls": [{"index": 0, "function": {"arguments": "{not valid json"}}]
                },
                "finish_reason": None,
            }
        ]
    },
    {"choices": [{"index": 0, "delta": {}, "finish_reason": "tool_calls"}]},
]

CHAT_COMPLETIONS_STREAM_INCOMPLETE = [
    {
        "choices": [
            {
                "index": 0,
                "delta": {"tool_calls": [{"index": 0, "function": {"name": "f", "arguments": ""}}]},
                "finish_reason": None,
            }
        ]
    },
    {"choices": [{"index": 0, "delta": {}, "finish_reason": "stop"}]},
]

# ---------------------------------------------------------------------------
# OpenAI Responses
# ---------------------------------------------------------------------------

RESPONSES_TEXT = {
    "id": "resp_123",
    "model": "gpt-5.6",
    "status": "completed",
    "output": [
        {
            "type": "message",
            "role": "assistant",
            "content": [{"type": "output_text", "text": "Hello there!"}],
        }
    ],
    "usage": {"input_tokens": 10, "output_tokens": 2, "total_tokens": 12},
}

RESPONSES_TOOL = {
    "id": "resp_456",
    "model": "gpt-5.6",
    "status": "completed",
    "output": [
        {
            "type": "function_call",
            "id": "fc_1",
            "call_id": "call_1",
            "name": "get_weather",
            "arguments": '{"city": "Paris"}',
        },
        {
            "type": "function_call",
            "id": "fc_2",
            "call_id": "call_2",
            "name": "get_time",
            "arguments": '{"city": "Paris"}',
        },
    ],
    "usage": {"input_tokens": 15, "output_tokens": 6, "total_tokens": 21},
}

RESPONSES_REASONING = {
    "id": "resp_789",
    "model": "gpt-5.6",
    "status": "completed",
    "output": [
        {
            "type": "reasoning",
            "summary": [{"type": "summary_text", "text": "Reasoning summary"}],
        },
        {
            "type": "message",
            "role": "assistant",
            "content": [{"type": "output_text", "text": "Final answer"}],
        },
    ],
    "usage": {"input_tokens": 8, "output_tokens": 3, "total_tokens": 11},
}

RESPONSES_STREAM_TOOL = [
    {"type": "response.created", "response": {"id": "resp_s1", "model": "gpt-5.6"}},
    {
        "type": "response.output_item.added",
        "item": {
            "type": "function_call",
            "id": "fc_1",
            "call_id": "call_1",
            "name": "get_weather",
            "arguments": "",
        },
    },
    {"type": "response.function_call_arguments.delta", "call_id": "call_1", "delta": '{"cit'},
    {
        "type": "response.function_call_arguments.delta",
        "call_id": "call_1",
        "delta": 'y": "Paris"}',
    },
    {
        "type": "response.function_call_arguments.done",
        "call_id": "call_1",
        "arguments": '{"city": "Paris"}',
    },
    {
        "type": "response.output_item.done",
        "item": {
            "type": "function_call",
            "id": "fc_1",
            "call_id": "call_1",
            "name": "get_weather",
            "arguments": '{"city": "Paris"}',
        },
    },
    {"type": "response.output_text.delta", "item_id": "msg_0", "delta": "Hel"},
    {"type": "response.output_text.delta", "item_id": "msg_0", "delta": "lo"},
    {
        "type": "response.completed",
        "response": {
            "id": "resp_s1",
            "model": "gpt-5.6",
            "status": "completed",
            "usage": {"input_tokens": 10, "output_tokens": 4, "total_tokens": 14},
        },
    },
]

RESPONSES_STREAM_INCOMPLETE = [
    {"type": "response.created", "response": {"id": "resp_s2", "model": "gpt-5.6"}},
    {
        "type": "response.output_item.added",
        "item": {
            "type": "function_call",
            "id": "fc_1",
            "call_id": "call_1",
            "name": "get_weather",
            "arguments": "",
        },
    },
    {"type": "response.function_call_arguments.delta", "call_id": "call_1", "delta": '{"cit'},
    {
        "type": "response.completed",
        "response": {"id": "resp_s2", "model": "gpt-5.6", "status": "completed", "usage": {}},
    },
]

# Responses background lifecycle
RESPONSES_BG_SUBMIT = {
    "id": "resp_bg_1",
    "model": "gpt-5.6",
    "status": "in_progress",
    "output": [],
    "usage": None,
}

RESPONSES_BG_DONE = {
    "id": "resp_bg_1",
    "model": "gpt-5.6",
    "status": "completed",
    "output": [
        {
            "type": "message",
            "role": "assistant",
            "content": [{"type": "output_text", "text": "Background done"}],
        }
    ],
    "usage": {"input_tokens": 10, "output_tokens": 2, "total_tokens": 12},
}

RESPONSES_BG_CANCELLED = {
    "id": "resp_bg_1",
    "model": "gpt-5.6",
    "status": "cancelled",
    "output": [],
    "usage": None,
}

# ---------------------------------------------------------------------------
# Anthropic Messages
# ---------------------------------------------------------------------------

ANTHROPIC_TEXT = {
    "id": "msg_123",
    "model": "claude-sonnet-4",
    "stop_reason": "end_turn",
    "content": [{"type": "text", "text": "Hello there!"}],
    "usage": {"input_tokens": 10, "output_tokens": 2},
}

ANTHROPIC_TOOL = {
    "id": "msg_456",
    "model": "claude-sonnet-4",
    "stop_reason": "tool_use",
    "content": [
        {"type": "text", "text": "I will check the weather."},
        {
            "type": "tool_use",
            "id": "toolu_1",
            "name": "get_weather",
            "input": {"city": "Paris"},
        },
    ],
    "usage": {"input_tokens": 15, "output_tokens": 6},
}

ANTHROPIC_STREAM_TEXT = [
    {
        "type": "message_start",
        "message": {"id": "msg_s1", "model": "claude-sonnet-4", "usage": {"input_tokens": 10}},
    },
    {"type": "content_block_start", "index": 0, "content_block": {"type": "text", "text": ""}},
    {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "Hel"}},
    {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": "lo"}},
    {"type": "content_block_stop", "index": 0},
    {"type": "message_delta", "delta": {"stop_reason": "end_turn"}, "usage": {"output_tokens": 2}},
    {"type": "message_stop"},
]

ANTHROPIC_STREAM_THINKING = [
    {
        "type": "message_start",
        "message": {"id": "msg_s2", "model": "claude-sonnet-4", "usage": {"input_tokens": 10}},
    },
    {
        "type": "content_block_start",
        "index": 0,
        "content_block": {"type": "thinking", "thinking": ""},
    },
    {
        "type": "content_block_delta",
        "index": 0,
        "delta": {"type": "thinking_delta", "thinking": "Let me reason"},
    },
    {
        "type": "content_block_delta",
        "index": 0,
        "delta": {"type": "signature_delta", "signature": "sig_123"},
    },
    {"type": "content_block_stop", "index": 0},
    {"type": "content_block_start", "index": 1, "content_block": {"type": "text", "text": ""}},
    {"type": "content_block_delta", "index": 1, "delta": {"type": "text_delta", "text": "Answer"}},
    {"type": "content_block_stop", "index": 1},
    {"type": "message_delta", "delta": {"stop_reason": "end_turn"}, "usage": {"output_tokens": 5}},
    {"type": "message_stop"},
]

ANTHROPIC_STREAM_TOOL = [
    {
        "type": "message_start",
        "message": {"id": "msg_s3", "model": "claude-sonnet-4", "usage": {"input_tokens": 15}},
    },
    {
        "type": "content_block_start",
        "index": 0,
        "content_block": {"type": "tool_use", "id": "toolu_1", "name": "get_weather"},
    },
    {
        "type": "content_block_delta",
        "index": 0,
        "delta": {"type": "input_json_delta", "partial_json": '{"cit'},
    },
    {
        "type": "content_block_delta",
        "index": 0,
        "delta": {"type": "input_json_delta", "partial_json": 'y": "Paris"}'},
    },
    {"type": "content_block_stop", "index": 0},
    {"type": "message_delta", "delta": {"stop_reason": "tool_use"}, "usage": {"output_tokens": 4}},
    {"type": "message_stop"},
]

ANTHROPIC_STREAM_INCOMPLETE = [
    {
        "type": "message_start",
        "message": {"id": "msg_s4", "model": "claude-sonnet-4", "usage": {"input_tokens": 15}},
    },
    {
        "type": "content_block_start",
        "index": 0,
        "content_block": {"type": "tool_use", "id": "toolu_1", "name": "get_weather"},
    },
    {
        "type": "content_block_delta",
        "index": 0,
        "delta": {"type": "input_json_delta", "partial_json": '{"cit'},
    },
    {"type": "message_delta", "delta": {"stop_reason": "tool_use"}, "usage": {"output_tokens": 4}},
    {"type": "message_stop"},
]
