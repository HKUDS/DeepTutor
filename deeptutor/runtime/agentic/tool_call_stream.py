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

import json
import re
from typing import Any, NoReturn


def _reject_ambiguous_arguments(text: str) -> None:
    """Check streamed arguments before tolerant parsing can select one call.

    Only balanced top-level, JSON-shaped containers count. This deliberately
    does not change the shared response parser or non-streamed dispatch.
    """
    message = "Ambiguous or conflicting streamed tool-call JSON"

    def unique_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(message)
            result[key] = value
        return result

    def inspect(candidate: str) -> bool:
        try:
            value = json.loads(candidate, object_pairs_hook=unique_pairs)
        except json.JSONDecodeError:
            # Detect duplicate keys in the common trailing-comma repair case
            # without rewriting commas that occur inside JSON strings.
            chars = []
            in_string = escaped = False
            for i, char in enumerate(candidate):
                if in_string:
                    if escaped:
                        escaped = False
                    elif char == "\\":
                        escaped = True
                    elif char == '"':
                        in_string = False
                elif char == '"':
                    in_string = True
                elif char == ",":
                    following = i + 1
                    while following < len(candidate) and candidate[following].isspace():
                        following += 1
                    if following < len(candidate) and candidate[following] in "}]":
                        continue
                chars.append(char)
            try:
                value = json.loads("".join(chars), object_pairs_hook=unique_pairs)
            except json.JSONDecodeError:
                return False
            except RecursionError:
                raise ValueError(message) from None
        except RecursionError:
            raise ValueError(message) from None
        if isinstance(value, list) and (
            len(value) > 1 or any(isinstance(item, (dict, list)) for item in value)
        ):
            raise ValueError(message)
        return True

    # Do not interpret braces, code fences or <think> inside valid JSON strings.
    if inspect(text):
        return
    # Match the shared parser's treatment of closed reasoning blocks. Such
    # text cannot be disambiguated from an actual second call in the block.
    text = re.sub(r"<think\b[^>]*>.*?</think>", "", text, flags=re.I | re.S)
    stack: list[str] = []
    start = 0
    quoted = escaped = False
    object_colon = False
    count = 0
    for pos, char in enumerate(text):
        if not stack:
            if char in "{[":
                start = pos
                stack.append(char)
                quoted = escaped = object_colon = False
            continue
        if quoted:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == '"':
                quoted = False
            continue
        if char == '"':
            quoted = True
        elif char in "{[":
            stack.append(char)
        elif char == ":" and len(stack) == 1 and stack[0] == "{":
            object_colon = True
        elif char in "}]":
            if (stack[-1], char) not in (("{", "}"), ("[", "]")):
                stack.clear()
                continue
            stack.pop()
            if not stack:
                candidate = text[start : pos + 1]
                valid = inspect(candidate)
                # Retain recovery of malformed single objects, while noticing
                # balanced malformed documents such as trailing-comma JSON.
                shaped = valid or (candidate[0] == "{" and object_colon)
                if shaped:
                    count += 1
                    if count > 1:
                        raise ValueError(message)
    # A second top-level object with a key/value separator is identifiable
    # even if its closing brace (or value) was truncated. Ignore an isolated
    # opening brace or key: those can simply be surrounding prose.
    if count and stack and stack[0] == "{" and object_colon:
        raise ValueError(message)


__all__ = ["ToolCallAccumulator"]


class ToolCallAccumulator:
    """Fold a stream of ``delta.tool_calls`` entries into whole tool calls."""

    def __init__(self) -> None:
        self._parts: dict[tuple[int, Any], dict[str, Any]] = {}
        self._indices: dict[int, tuple[int, Any]] = {}
        self._ids: dict[str, tuple[int, Any]] = {}
        # Only a renderable ask_user draft exposes a provisional identity.
        self._preview_ids: dict[tuple[int, Any], str] = {}
        self._last_key: tuple[int, Any] | None = None
        self._last_index: int | None = None
        self._has_indexless_call = False
        self._failed = False

    def _fail(self) -> NoReturn:
        self._failed = True
        self._last_key = None
        raise ValueError("Ambiguous or conflicting streamed tool-call identity")

    def _ordered_keys(self) -> list[tuple[int, Any]]:
        if self._failed:
            self._fail()
        for part in self._parts.values():
            try:
                _reject_ambiguous_arguments(part.get("arguments", ""))
            except ValueError:
                self._fail()
        if not self._has_indexless_call:
            return [self._indices[index] for index in sorted(self._indices)]
        # With missing indices, preserve arrival order instead of inventing one.
        return list(self._parts)

    def feed(self, tc_delta: Any) -> int:
        """Fold one tool-call delta in; return the characters it contributed.

        The count covers ``name`` and ``arguments`` only, matching what
        callers bill as provider output.
        """
        if self._failed:
            self._fail()
        raw_index = getattr(tc_delta, "index", None)
        try:
            index = int(raw_index) if raw_index is not None else None
        except (TypeError, ValueError, OverflowError):
            self._fail()
        tcid = getattr(tc_delta, "id", None)
        tcid = str(tcid) if tcid else None
        by_index = self._indices.get(index) if index is not None else None
        by_id = self._ids.get(tcid) if tcid else None
        if by_index is not None and by_id is not None and by_index != by_id:
            self._fail()
        key = by_index if by_index is not None else by_id
        if key is not None:
            existing_id = self._parts[key].get("id")
            if tcid and existing_id and tcid != existing_id:
                self._fail()
            if index is not None and any(i != index and k == key for i, k in self._indices.items()):
                self._fail()
        elif index is None and not tcid:
            if len(self._parts) > 1:
                self._fail()
            key = next(iter(self._parts), None)
        if key is None:
            # An anonymous unindexed call cannot be distinguished from a new
            # call whose ID/index has just appeared. Never guess.
            if any(
                not p.get("id") and (index is None or k not in self._indices.values())
                for k, p in self._parts.items()
            ):
                self._fail()
            key = (0, index) if index is not None else (1, len(self._parts))
            if index is None:
                self._has_indexless_call = True
        if tcid:
            if key in self._preview_ids and self._preview_ids[key] != tcid:
                self._fail()
            if any(k != key and value == tcid for k, value in self._preview_ids.items()):
                self._fail()
        part = self._parts.setdefault(key, {"id": "", "name": "", "arguments": ""})
        if index is not None:
            self._indices[index] = key
        if tcid:
            self._ids[tcid] = key
            part["id"] = tcid
        self._last_key = key
        self._last_index = index if index is not None else 0

        # Gemini's OpenAI-compatible endpoint adds ``extra_content`` to the
        # tool-call delta. The OpenAI SDK keeps unknown response fields on the
        # model, so preserve the extension as an opaque object and replay it on
        # the assistant tool-call message. Assign rather than merge: like the
        # id/name fields, the provider sends this metadata as a complete value.
        extra_content = getattr(tc_delta, "extra_content", None)
        if isinstance(extra_content, dict) and extra_content:
            if part.get("extra_content") and part["extra_content"] != extra_content:
                self._fail()
            part["extra_content"] = extra_content

        fn = getattr(tc_delta, "function", None)
        if fn is None:
            return 0

        chars = 0
        name = getattr(fn, "name", None)
        if name:
            name = str(name)
            if part["name"] and part["name"] != name:
                self._fail()
            part["name"] = name
            chars += len(name)
        arguments = getattr(fn, "arguments", None)
        if arguments:
            part["arguments"] += str(arguments)
            chars += len(str(arguments))
        return chars

    def part_at(self, index: int) -> dict[str, Any] | None:
        """Return the part associated with an explicit provider index."""
        if self._failed:
            return None
        key = self._indices.get(int(index))
        return self._parts.get(key) if key is not None else None

    def last_part(self) -> dict[str, Any] | None:
        """Return the last resolved part, reserving any visible preview ID."""
        if self._failed or self._last_key is None:
            return None
        key = self._last_key
        index = self._last_index or 0
        part = self._parts[key]
        # The caller invokes this after every chunk, but its draft emitter
        # ignores non-ask_user tools and unrenderable ask_user fragments.
        # Reserve the fallback only when a card can actually be published.
        previewable = False
        if (
            key not in self._preview_ids
            and not part.get("id")
            and part.get("name") == "ask_user"
            and part.get("arguments")
        ):
            from deeptutor.tools.ask_user import build_ask_user_preview

            previewable = build_ask_user_preview(part["arguments"]) is not None
        if previewable:
            preview_id = self._preview_ids.get(key) or f"call_{index}"
            if (
                (key in self._preview_ids and self._preview_ids[key] != preview_id)
                or (preview_id in self._ids and self._ids[preview_id] != key)
                or any(k != key and value == preview_id for k, value in self._preview_ids.items())
            ):
                self._fail()
            self._preview_ids[key] = preview_id
        return part

    def last_preview_id(self) -> str | None:
        """Return the reserved fallback for the last preview, if any."""
        if self._failed or self._last_key is None:
            return None
        return self._preview_ids.get(self._last_key)

    def ordered(self) -> list[dict[str, Any]]:
        """Every accumulated part, in provider order, unfiltered."""
        return [self._parts[key] for key in self._ordered_keys()]

    def collected(self) -> list[dict[str, Any]]:
        """Dispatchable tool calls: named parts only, with defaults applied.

        A provider that streams arguments but never an ``id`` still needs one
        to correlate the result message, hence the positional fallback.
        """
        calls: list[dict[str, Any]] = []
        used_ids = set(self._ids) | set(self._preview_ids.values())
        for position, key in enumerate(self._ordered_keys()):
            part = self._parts[key]
            if not part.get("name"):
                continue
            index = next((i for i, k in self._indices.items() if k == key), position)
            fallback = self._preview_ids.get(key) or f"call_{index}"
            while not part.get("id") and key not in self._preview_ids and fallback in used_ids:
                index += 1
                fallback = f"call_{index}"
            used_ids.add(part.get("id") or fallback)
            call: dict[str, Any] = {
                "id": part.get("id") or fallback,
                "name": part.get("name", ""),
                "arguments": part.get("arguments") or "{}",
            }
            extra_content = part.get("extra_content")
            if isinstance(extra_content, dict) and extra_content:
                call["extra_content"] = extra_content
            calls.append(call)
        return calls
