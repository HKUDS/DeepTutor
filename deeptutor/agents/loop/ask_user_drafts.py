"""Publish an ``ask_user`` card while the model is still writing it.

A tool call is a single JSON object, and nothing about it used to leave the
backend until its closing brace arrived. For most tools that is invisible —
the reader sees a tool row either way. ``ask_user`` is different: its
arguments *are* what the reader looks at, and a card carrying an intro, a
question and three explained options is several seconds of generation. The
turn therefore went silent right after the prose that introduced the
question, and then the whole card landed at once.

This turns the partial argument text into card previews as it accumulates,
so the card appears with the intro and grows its options in place. Three
rules keep it cheap and quiet:

* only ``ask_user`` is previewed — every other tool is unchanged;
* a preview is skipped unless the arguments grew enough *and* enough time
  passed, so a fast provider cannot emit one event per token;
* an identical payload is never published twice, which is what keeps the
  trailing deltas of a finished call (and any provider that repeats its
  final arguments) from re-publishing the same card.

The preview is strictly a rendering hint. The dispatched call is still built
from the complete arguments by the ordinary path, so nothing here can change
which tool runs or with what.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import json
import time
from typing import Any

from deeptutor.core.trace import merge_trace_metadata
from deeptutor.tools.ask_user import build_ask_user_preview

__all__ = ["ASK_USER_DRAFT_TRACE_KIND", "AskUserDraftEmitter"]

#: ``trace_kind`` the frontend matches to draw a still-streaming card. Kept
#: distinct from the resolved payload's key so a draft can never be mistaken
#: for a dispatched call the user may answer.
ASK_USER_DRAFT_TRACE_KIND = "ask_user_draft"

_TOOL_NAME = "ask_user"


def _call_key(call_id: str) -> str:
    """Identity a preview and its dispatched call agree on.

    A Responses-API call is dispatched under ``"<call id>|<output item id>"``
    (``_build_tool_call``) while its argument deltas only ever carry the call
    id. Keying on the call id alone lets a preview, the round's own settle
    pass and the frontend all name the same card.
    """
    return (call_id or "").split("|", 1)[0]


#: Characters the arguments must gain before another preview is worth it.
#: Roughly a short option label — small enough to look continuous, large
#: enough that a burst of one-token deltas collapses into one event.
_MIN_GROWTH_CHARS = 24
#: Floor on the gap between two previews of the same call.
_MIN_INTERVAL_S = 0.18


@dataclass
class _CallState:
    """What has already been published for one in-flight call."""

    published_length: int = 0
    published_at: float = 0.0
    published_payload: str = ""
    #: Question count and per-question option counts of the last published
    #: preview, used to refuse a preview that would shrink the card.
    published_shape: tuple[int, ...] = ()


def _payload_shape(payload: dict[str, Any]) -> tuple[int, ...]:
    """(question count, options of q1, options of q2, …) for *payload*."""
    questions = payload.get("questions") or []
    return (len(questions), *(len(q.get("options") or []) for q in questions))


def _shrinks(previous: tuple[int, ...], candidate: tuple[int, ...]) -> bool:
    """Whether *candidate* has fewer questions or options than *previous*.

    ``json_repair`` closes an object whose key is mid-word as a list, so a
    question or option can momentarily parse as unrenderable and vanish from
    an otherwise growing preview. Publishing that frame would blink the card
    — the question area empties and refills — so the emitter holds the last
    good preview and waits for the next delta instead. Growth in either
    dimension is always published.
    """
    if not previous:
        return False
    if not candidate or candidate[0] < previous[0]:
        return True
    return any(candidate[position] < previous[position] for position in range(1, len(previous)))


@dataclass
class AskUserDraftEmitter:
    """Turn streamed ``ask_user`` arguments into card-preview events."""

    stream: Any
    source: str
    stage: str
    metadata: dict[str, Any]
    _calls: dict[str, _CallState] = field(default_factory=dict)

    async def observe(
        self,
        *,
        call_id: str,
        tool_name: str,
        arguments: str,
        force: bool = False,
    ) -> None:
        """Consider publishing a preview for the call's arguments so far.

        *force* bypasses the growth/interval throttle, for the final call of
        a round whose closing fragments the throttle would otherwise drop.
        """
        if tool_name != _TOOL_NAME:
            return
        text = arguments or ""
        key = _call_key(call_id)
        state = self._calls.setdefault(key, _CallState())
        now = time.monotonic()
        grown = len(text) - state.published_length
        if (
            not force
            and state.published_length
            and (grown < _MIN_GROWTH_CHARS or now - state.published_at < _MIN_INTERVAL_S)
        ):
            return

        payload = build_ask_user_preview(text)
        if payload is None:
            # Nothing renderable yet (an opening brace, a key without its
            # value). Leave the counters alone so the next delta is judged
            # against the same baseline rather than being throttled out.
            return
        shape = _payload_shape(payload)
        if _shrinks(state.published_shape, shape):
            return
        serialised = json.dumps(payload, ensure_ascii=False, sort_keys=True)
        if serialised == state.published_payload:
            # Growth that changed no rendered field — a description still
            # inside its opening quote, or a provider repeating the final
            # arguments after the call closed.
            state.published_length = len(text)
            state.published_at = now
            return

        state.published_length = len(text)
        state.published_at = now
        state.published_payload = serialised
        state.published_shape = shape
        await self.stream.progress(
            "",
            source=self.source,
            stage=self.stage,
            metadata=merge_trace_metadata(
                self.metadata,
                {
                    "trace_kind": ASK_USER_DRAFT_TRACE_KIND,
                    "tool_name": _TOOL_NAME,
                    "draft_call_id": key,
                    "ask_user_draft": payload,
                },
            ),
        )

    async def settle(self, tool_calls: list[dict[str, Any]]) -> None:
        """Publish each previewed call's finished arguments, once.

        The throttle can drop the last fragments of a fast-closing call, and
        a card that is never dispatched (a duplicate parallel call, a guard
        that rejects the arguments) has no tool result coming to replace its
        preview. Both leave the reader looking at a half-written card, so the
        round's own tool calls get the last word.
        """
        for call in tool_calls:
            call_id = str(call.get("id") or "")
            if _call_key(call_id) not in self._calls:
                continue
            await self.observe(
                call_id=call_id,
                tool_name=str(call.get("name") or ""),
                arguments=str(call.get("arguments") or ""),
                force=True,
            )
