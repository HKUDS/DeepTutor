"""Mastery history accounting uses the same routed, image-projected replay as the request."""

from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from deeptutor.capabilities.mastery.history import project_mastery_replay
from deeptutor.capabilities.mastery.memory import MasteryContextBuilder
from deeptutor.services.llm.image_replay import deduplicate_user_images
from deeptutor.services.session.context_builder import _count_model_context_tokens
from deeptutor.services.session.model_history import replay_history


def _routed_rows():
    return [
        {"id": 1, "role": "user", "content": "Explain the diagram."},
        {
            "id": 2,
            "role": "assistant",
            "content": "The diagram illustrates the mechanism.",
            "metadata": {
                "model_turn": {
                    "version": 1,
                    "route": {"provider": "source-provider", "model": "source-model"},
                    "messages": [
                        {"role": "user", "content": "Explain the diagram."},
                        {
                            "role": "assistant",
                            "content": "The diagram illustrates the mechanism.",
                            "reasoning_content": "route-specific reasoning " * 1000,
                            "thinking_blocks": [
                                {
                                    "type": "thinking",
                                    "thinking": "Private thought",
                                    "signature": "opaque-signature",
                                }
                            ],
                        },
                    ],
                }
            },
        },
    ]


@pytest.mark.parametrize(
    "route",
    [
        None,
        {"provider": "source-provider", "model": "source-model"},
        {"provider": "other-provider", "model": "other-model"},
    ],
)
def test_mastery_accounting_uses_requested_route_without_mutating_records(route):
    rows = _routed_rows()
    original = deepcopy(rows)
    builder = MasteryContextBuilder(MagicMock())
    expected = _count_model_context_tokens(
        deduplicate_user_images(project_mastery_replay(replay_history(rows, route=route)))
    )

    assert builder._model_tokens(rows, route=route) == expected
    assert rows == original


def test_route_free_mastery_accounting_keeps_existing_replay_behavior():
    rows = _routed_rows()
    builder = MasteryContextBuilder(MagicMock())
    assert builder._model_tokens(rows) == _count_model_context_tokens(
        deduplicate_user_images(project_mastery_replay(replay_history(rows)))
    )


@pytest.mark.asyncio
async def test_final_mastery_token_count_projects_duplicate_images_without_changing_history():
    image = {"type": "image_url", "image_url": {"url": "data:image/png;base64,aGVsbG8="}}
    rows = [
        {"id": 1, "role": "user", "content": "Look at the diagram."},
        {
            "id": 2,
            "role": "assistant",
            "content": "The same diagram remains relevant.",
            "metadata": {
                "model_turn": {
                    "version": 1,
                    "messages": [
                        {"role": "user", "content": [deepcopy(image)]},
                        {"role": "assistant", "content": "The diagram illustrates the mechanism."},
                        {"role": "user", "content": [deepcopy(image)]},
                        {"role": "assistant", "content": "The same diagram remains relevant."},
                    ],
                }
            },
        },
    ]
    original = deepcopy(rows)
    store = MagicMock()
    store.get_session = AsyncMock(
        return_value={"compressed_summary": "", "summary_up_to_msg_id": 0}
    )
    store.get_messages_for_context = AsyncMock(return_value=rows)
    store.update_summary = AsyncMock()
    builder = MasteryContextBuilder(store)
    builder._summarize = AsyncMock()

    built = await builder.build(
        session_id="synthetic-session",
        llm_config=SimpleNamespace(model="synthetic-model", context_window=272000, max_tokens=8192),
    )

    assert built.token_count == _count_model_context_tokens(
        deduplicate_user_images(built.model_history)
    )
    assert built.model_history == project_mastery_replay(replay_history(rows))
    assert rows == original
    builder._summarize.assert_not_awaited()
    store.update_summary.assert_not_awaited()
