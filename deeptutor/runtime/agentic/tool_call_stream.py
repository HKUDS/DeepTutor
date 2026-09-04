"""Accumulate OpenAI-compatible streaming tool-call deltas.

Three call sites replay the same provider wire protocol — the chat agent
loop, the explore capability, and the labeled step runner — so the rule for
each field is stated here once instead of being restated per site:

* ``id`` and ``name`` arrive **complete** on whichever delta carries them.
  A provider may repeat them on every subsequent chunk. Assign, never append.
* ``arguments`` arrives as **fragments** that must be concatenated.
* Provider extensions attached to the call arrive **complete** and must be
  preserved. Gemini thinking models put the opaque signature required by the
  next tool round in ``extra_content.google.thought_signature`` (#1181).
  Capture the whole ``extra_content`` object (SDK attribute, ``model_extra``,
  or plain dict delta) so the assistant replay keeps the provider contract.

Appending a complete field is issue #937: a router that re-sent ``id`` on
every chunk grew it to 47241 characters, far past the 64-character limit the
provider itself enforces, so the round died with HTTP 400 and the user got
the "could not produce a useful response" fallback. The same append also
corrupted ``name`` into ``toolnametoolnametoolname``, which no registry can
resolve — latent for that reporter's gateway, fatal for any gateway that
repeats the name.

The services-layer provider keeps its own accumulator
(``openai_compat_provider._accum_tc``): it already applies these same rules
and reads deltas that may be plain dicts rather than SDK objects, so folding
it in here would widen the blast radius without fixing anything.
"""

from __future__ import annotations

from typing import Any

__all__ = ["ToolCallAccumulator", "extra_content_from_tool_call_delta"]


def extra_content_from_tool_call_delta(tc_delta: Any) -> dict[str, Any] | None:
    """Return Gemini (or other) ``extra_content`` from a tool-call delta.

    Handles SDK models, ``model_extra``, and plain dict deltas so signatures
    are not dropped when the OpenAI client does not promote the field.
    """
    extra = getattr(tc_delta, "extra_content", None)
    if extra is None and isinstance(tc_delta, dict):
        extra = tc_delta.get("extra_content")
    if extra is None:
        model_extra = getattr(tc_delta, "model_extra", None)
        if isinstance(model_extra, dict):
            extra = model_extra.get("extra_content")
    if isinstance(extra, dict) and extra:
        return extra

    # Some gateways flatten the signature onto the tool-call object.
    signature = getattr(tc_delta, "thought_signature", None)
    if signature is None and isinstance(tc_delta, dict):
        signature = tc_delta.get("thought_signature")
    if signature:
        return {"google": {"thought_signature": str(signature)}}
    return None


class ToolCallAccumulator:
    """Fold a stream of ``delta.tool_calls`` entries into whole tool calls."""

    def __init__(self) -> None:
        self._parts: dict[int, dict[str, Any]] = {}

    def feed(self, tc_delta: Any) -> int:
        """Fold one tool-call delta in; return the characters it contributed.

        The count covers ``name`` and ``arguments`` only, matching what
        callers bill as provider output.
        """
        raw_index = getattr(tc_delta, "index", None)
        if raw_index is None and isinstance(tc_delta, dict):
            raw_index = tc_delta.get("index")
        index = int(raw_index or 0)
        part = self._parts.setdefault(index, {"id": "", "name": "", "arguments": ""})

        tcid = getattr(tc_delta, "id", None)
        if tcid is None and isinstance(tc_delta, dict):
            tcid = tc_delta.get("id")
        if tcid:
            part["id"] = str(tcid)

        # Gemini's OpenAI-compatible endpoint adds ``extra_content`` to the
        # tool-call delta. Assign rather than merge: like id/name, the
        # provider sends this metadata as a complete value.
        extra_content = extra_content_from_tool_call_delta(tc_delta)
        if extra_content is not None:
            part["extra_content"] = extra_content

        fn = getattr(tc_delta, "function", None)
        if fn is None and isinstance(tc_delta, dict):
            fn = tc_delta.get("function")
        if fn is None:
            return 0

        chars = 0
        name = getattr(fn, "name", None)
        if name is None and isinstance(fn, dict):
            name = fn.get("name")
        if name:
            part["name"] = str(name)
            chars += len(str(name))
        arguments = getattr(fn, "arguments", None)
        if arguments is None and isinstance(fn, dict):
            arguments = fn.get("arguments")
        if arguments:
            part["arguments"] += str(arguments)
            chars += len(str(arguments))
        return chars

    def ordered(self) -> list[dict[str, Any]]:
        """Every accumulated part, in provider index order, unfiltered."""
        return [self._parts[key] for key in sorted(self._parts)]

    def collected(self) -> list[dict[str, Any]]:
        """Dispatchable tool calls: named parts only, with defaults applied.

        A provider that streams arguments but never an ``id`` still needs one
        to correlate the result message, hence the positional fallback.
        """
        calls: list[dict[str, Any]] = []
        for index, part in sorted(self._parts.items()):
            if not part.get("name"):
                continue
            call: dict[str, Any] = {
                "id": part.get("id") or f"call_{index}",
                "name": part.get("name", ""),
                "arguments": part.get("arguments") or "{}",
            }
            extra_content = part.get("extra_content")
            if isinstance(extra_content, dict) and extra_content:
                call["extra_content"] = extra_content
            calls.append(call)
        return calls
