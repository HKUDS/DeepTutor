"""The runtime's `_`-prefixed arguments must not be writable by a model.

Tools read `_learner_message`, `_sandbox_mounts`, `_turn_id` and the rest as
provenance the runtime injected, and a few of them gate credit or sandbox
access on that. Nothing enforced it on the way in: a model emits arbitrary
JSON and the dispatch path never rejected a name it did not expect, so a
model could write `_learner_message` itself and be believed. That is how
`mastery_grade` came to accept a model-authored answer as grounds to
overwrite a committed learner answer (#2595).

The guard is a fixed list of the names the runtime owns, withheld at bind
time. These tests drive the real dispatcher, because the binding was the
vulnerable part — the tools did nothing wrong.
"""

from __future__ import annotations

import json

import pytest

from deeptutor.core.context import UnifiedContext
from deeptutor.core.tool_protocol import BaseTool, ToolDefinition, ToolParameter, ToolResult
from deeptutor.runtime.agentic.tool_dispatch import (
    RESERVED_ARGUMENT_NAMES,
    _drop_server_owned_args,
    dispatch_tool_calls,
)
from deeptutor.runtime.registry.tool_registry import ToolRegistry
from deeptutor.runtime.stream_bus import StreamBus


def _prepare(tool_calls, context, augmenter, *, rebinding=frozenset()):
    from deeptutor.runtime.agentic.tool_dispatch import _prepare_tool_args

    prepared, _raw = _prepare_tool_args(tool_calls, context, augmenter)
    return [args for _tcid, _name, args in prepared]


def test_a_reserved_name_is_withheld_from_the_model():
    """The model cannot claim a runtime-owned name by typing it."""

    filtered = _drop_server_owned_args(
        {
            "question_id": "q1",
            "_mastery_path_id": "forged",
            "_learner_message": "photosynthesis",
            "_turn_id": "forged",
            "_sandbox_mounts": "forged",
        }
    )
    assert filtered == {"question_id": "q1"}


def test_an_unreserved_underscore_argument_is_left_alone():
    """Adapters own their own names; only the runtime's list is withheld.

    An MCP server or plugin may publish a public argument such as `_id`. It is
    not a name the runtime injects, so it is not ours to remove — and removing
    it would break the schema the model was shown.
    """

    assert _drop_server_owned_args({"document_id": "d", "_id": "rec"}) == {
        "document_id": "d",
        "_id": "rec",
    }


def test_the_reserved_set_is_not_empty_and_all_prefixed():
    """A guard against a truncated list silently protecting nothing."""

    assert len(RESERVED_ARGUMENT_NAMES) >= 40
    assert all(name.startswith("_") for name in RESERVED_ARGUMENT_NAMES)


def test_a_forged_name_is_dropped_at_bind_time():
    """The filter runs before augmentation, so the model's copy never lands."""

    context = UnifiedContext(session_id="s", user_message="hi")
    calls = [
        {
            "id": "c1",
            "name": "mastery_grade",
            "arguments": json.dumps({"question_id": "q1", "_learner_message": "photosynthesis"}),
        }
    ]
    [args] = _prepare(calls, context, lambda name, a, ctx: a)
    assert args == {"question_id": "q1"}


def test_a_server_injected_value_still_lands(monkeypatch, tmp_path):
    """Withholding happens before injection, so the runtime's own value wins."""

    _use_store_root(monkeypatch, tmp_path)
    from deeptutor.capabilities.mastery.loop import MasteryLoopCapability

    context = UnifiedContext(
        session_id="session-1",
        user_message="the learner's actual words",
        metadata={"mastery_mode": True, "mastery_path_id": "p", "turn_id": "turn-1"},
    )
    calls = [
        {
            "id": "c1",
            "name": "mastery_grade",
            "arguments": json.dumps({"question_id": "q1", "_learner_message": "forged"}),
        }
    ]
    [args] = _prepare(calls, context, MasteryLoopCapability().augment_kwargs)
    assert args["_learner_message"] == "the learner's actual words"
    assert args["_mastery_path_id"] == "p"
    assert args["_turn_id"] == "turn-1"


def _use_store_root(monkeypatch, root):
    def _init(self, root_arg=None):
        self._root = root / "learning"
        self._root.mkdir(parents=True, exist_ok=True)

    monkeypatch.setattr("deeptutor.learning.storage.LearningStore.__init__", _init)


@pytest.mark.asyncio
async def test_a_rebinding_round_does_not_re_admit_a_filtered_name():
    """A deferred re-bind must not replay what the filter removed.

    `_prepare_tool_args` records the call's original arguments so a round can
    be re-bound at a pause boundary, and the rebind replays them into the
    augmenter. Recording the pre-filter JSON meant any round containing a
    rebinding tool — `ask_user` and `workspace_export` always qualify — put a
    forged `_learner_message` back into the arguments the first bind had
    already dropped.
    """

    received = {}

    class _Spy(BaseTool):
        def get_definition(self):
            return ToolDefinition(
                name="spy", description="d", parameters=[ToolParameter(name="q", type="string")]
            )

        async def execute(self, **kwargs):
            received.update(kwargs)
            return ToolResult(content="ok")

    class _AskUser(BaseTool):
        def get_definition(self):
            return ToolDefinition(
                name="ask_user",
                description="d",
                parameters=[ToolParameter(name="questions", type="string")],
            )

        async def execute(self, **kwargs):
            return ToolResult(content="asked")

    registry = ToolRegistry()
    registry.register(_Spy())
    registry.register(_AskUser())

    await dispatch_tool_calls(
        tool_calls=[
            {
                "id": "c1",
                "name": "spy",
                "arguments": json.dumps({"q": "hello", "_learner_message": "forged"}),
            },
            # ask_user is a pause tool, so the round rebinds everything.
            {"id": "c2", "name": "ask_user", "arguments": json.dumps({"questions": "x"})},
        ],
        context=UnifiedContext(session_id="s", user_message="hi"),
        stream=StreamBus(),
        source="chat",
        stage="responding",
        iteration_index=0,
        registry=registry,
        kwarg_augmenter=lambda name, args, _ctx: dict(args),
        rebinding_tools=frozenset({"ask_user"}),
    )

    assert "_learner_message" not in received
    assert received.get("q") == "hello"


def test_a_mastery_brief_flag_cannot_be_turned_off_by_the_model():
    """`_working_brief` is injected by the mastery loop and read as trusted.

    It decides whether `mastery_status` projects the working brief. It was
    missing from the reserved list, so a model could send `_working_brief:
    False` and have the tool honour it — the same class of bug as
    `_learner_message`, caught on a later pass.
    """

    assert "_working_brief" in RESERVED_ARGUMENT_NAMES
    assert _drop_server_owned_args({"knowledge_point_id": "k", "_working_brief": False}) == {
        "knowledge_point_id": "k"
    }
