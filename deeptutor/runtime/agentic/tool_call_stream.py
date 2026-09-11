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

__all__ = ["ToolCallAccumulator"]


class ToolCallAccumulator:
    """Fold a stream of ``delta.tool_calls`` entries into whole tool calls."""

    def __init__(self) -> None:
        self._parts: dict[int, dict[str, Any]] = {}

    def feed(self, tc_delta: Any) -> int:
        """Fold one tool-call delta in; return the characters it contributed.

        The count covers ``name`` and ``arguments`` only, matching what
        callers bill as provider output.
        """
        index = int(getattr(tc_delta, "index", 0) or 0)
        part = self._parts.setdefault(index, {"id": "", "name": "", "arguments": ""})

        tcid = getattr(tc_delta, "id", None)
        if tcid:
            part["id"] = str(tcid)

        # Gemini's OpenAI-compatible endpoint adds ``extra_content`` to the
        # tool-call delta. The OpenAI SDK keeps unknown response fields on the
        # model, so preserve the extension as an opaque object and replay it on
        # the assistant tool-call message. Assign rather than merge: like the
        # id/name fields, the provider sends this metadata as a complete value.
        extra_content = getattr(tc_delta, "extra_content", None)
        if isinstance(extra_content, dict) and extra_content:
            part["extra_content"] = extra_content

        fn = getattr(tc_delta, "function", None)
        if fn is None:
            return 0

        chars = 0
        name = getattr(fn, "name", None)
        if name:
            part["name"] = str(name)
            chars += len(str(name))
        arguments = getattr(fn, "arguments", None)
        if arguments:
            part["arguments"] += str(arguments)
            chars += len(str(arguments))
        return chars

    def part_at(self, index: int) -> dict[str, Any] | None:
        """The part a provider index is folding into, if it exists yet.

        Lets a caller read one call's running ``name``/``arguments`` right
        after feeding a delta for it, without guessing that the provider's
        indices happen to line up with list positions.
        """
        return self._parts.get(int(index))

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
