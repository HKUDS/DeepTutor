"""Fallback parser for DeepSeek's text-format ("DSML") tool calls.

Some DeepSeek deployments (notably local/source setups whose OpenAI-compatible
endpoint doesn't advertise native function calling) emit tool calls as markup in
the assistant *content* channel instead of as structured ``delta.tool_calls``.
The markup mirrors the ``invoke`` / ``parameter`` dialect but wraps each tag in
DeepSeek's fullwidth special-token bars, e.g.::

    <｜｜DSML｜｜tool_calls>
      <｜｜DSML｜｜invoke name="exec">
        <｜｜DSML｜｜parameter name="command" string="true">python -c "..."</｜｜DSML｜｜parameter>
      </｜｜DSML｜｜invoke>
    </｜｜DSML｜｜tool_calls>

Left unparsed, this markup streams to the user as the final answer and the tool
never runs (issue #666). :func:`extract_dsml_tool_calls` turns the markup back
into structured tool calls so the normal dispatch path executes them.

Pure functions — no I/O, no LLM. The tag prefix is matched leniently
(``<[^>]*?invoke ...>``) so the exact special-token bytes don't matter; only the
stable ``invoke name="..."`` / ``parameter name="..."`` structure does.
"""

from __future__ import annotations

import json
import re
from typing import Any, Iterable

# A real DSML tool-call tag (not prose that merely mentions "tool_calls"): an
# opening ``<...invoke name="`` or any ``<...DSML...>`` tag. Used to decide
# whether the content channel is carrying tool-call markup.
DSML_SIGNAL_RE = re.compile(
    r"<[^>]*DSML[^>]*>|<[^>]*?invoke\s+name\s*=\s*\"",
    re.IGNORECASE,
)

_INVOKE_RE = re.compile(
    r"<[^>]*?invoke\s+name\s*=\s*\"(?P<name>[^\"]+)\"[^>]*>(?P<body>.*?)</[^>]*?invoke\s*>",
    re.IGNORECASE | re.DOTALL,
)
_PARAM_RE = re.compile(
    r"<[^>]*?parameter\s+name\s*=\s*\"(?P<pname>[^\"]+)\"(?P<attrs>[^>]*)>(?P<pval>.*?)</[^>]*?parameter\s*>",
    re.IGNORECASE | re.DOTALL,
)
# The ``<...tool_calls>`` open/close wrapper, stripped from the cleaned text once
# we have extracted the invokes inside it.
_TOOLCALLS_WRAP_RE = re.compile(r"</?[^>]*?tool_calls\s*>", re.IGNORECASE)
_INVOKE_OPEN_TAG_RE = re.compile(
    r"<[^>]*?invoke\s+name\s*=\s*\"[^\"]+\"[^>]*>",
    re.IGNORECASE,
)
_INVOKE_CLOSE_TAG_RE = re.compile(r"</[^>]*?invoke\s*>", re.IGNORECASE)
_TOOLCALLS_OPEN_TAG_RE = re.compile(r"<(?!/)[^>]*?tool_calls\s*>", re.IGNORECASE)
_TOOLCALLS_CLOSE_TAG_RE = re.compile(r"</[^>]*?tool_calls\s*>", re.IGNORECASE)

# A malformed HTML-ish fragment should not make the live stream wait forever
# for a closing ``>``. Real DSML tags are much shorter than this ceiling.
_MAX_PARTIAL_TAG_CHARS = 512


class DSMLStreamFilter:
    """Incrementally remove complete DSML calls from streamed text.

    Only the DSML envelope and ``invoke`` blocks are suppressed. Text before,
    between, and after calls is returned immediately, so one tool call cannot
    redirect the rest of the round into a different output channel. Incomplete
    invokes are released verbatim by :meth:`flush` instead of silently losing
    provider output.
    """

    def __init__(self) -> None:
        self._buffer = ""
        self._pending_close: re.Pattern[str] | None = None

    @staticmethod
    def _clean_block(block: str) -> str:
        calls, _ = extract_dsml_tool_calls(block)
        if not calls:
            return block
        cleaned = block
        for match in reversed(list(_INVOKE_RE.finditer(block))):
            cleaned = cleaned[: match.start()] + cleaned[match.end() :]
        return _TOOLCALLS_WRAP_RE.sub("", cleaned)

    def feed(self, chunk: str) -> str:
        self._buffer += chunk
        visible: list[str] = []

        while self._buffer:
            if self._pending_close is not None:
                close = self._pending_close.search(self._buffer)
                if close is None:
                    break
                block = self._buffer[: close.end()]
                self._buffer = self._buffer[close.end() :]
                self._pending_close = None
                visible.append(self._clean_block(block))
                continue

            tag_start = self._buffer.find("<")
            if tag_start < 0:
                visible.append(self._buffer)
                self._buffer = ""
                break
            if tag_start:
                visible.append(self._buffer[:tag_start])
                self._buffer = self._buffer[tag_start:]

            tag_end = self._buffer.find(">")
            if tag_end < 0:
                if len(self._buffer) <= _MAX_PARTIAL_TAG_CHARS:
                    break
                # This is ordinary prose containing ``<``, not a plausible
                # DSML tag. Release one character and keep scanning.
                visible.append(self._buffer[0])
                self._buffer = self._buffer[1:]
                continue

            tag = self._buffer[: tag_end + 1]
            if _TOOLCALLS_OPEN_TAG_RE.fullmatch(tag):
                self._pending_close = _TOOLCALLS_CLOSE_TAG_RE
                # Keep the entire envelope buffered. We only suppress it once
                # a complete invoke was parsed; malformed provider output is
                # released unchanged instead of losing text at the boundary.
                continue
            if _INVOKE_OPEN_TAG_RE.fullmatch(tag):
                self._pending_close = _INVOKE_CLOSE_TAG_RE
                continue
            self._buffer = self._buffer[tag_end + 1 :]
            if _TOOLCALLS_WRAP_RE.fullmatch(tag):
                continue
            visible.append(tag)

        return "".join(visible)

    def flush(self) -> str:
        """Release buffered text, cleaning any complete unwrapped call."""
        remaining = self._buffer
        self._buffer = ""
        self._pending_close = None
        return self._clean_block(remaining)


def _looks_like_string(attrs: str) -> bool:
    normalized = attrs.replace("'", '"')
    return 'string="true"' in normalized.lower()


def _schema_types(schema: dict[str, Any] | None) -> set[str]:
    if not isinstance(schema, dict):
        return set()
    value = schema.get("type")
    if isinstance(value, str):
        types = {value}
    elif isinstance(value, list):
        types = {item for item in value if isinstance(item, str)}
    else:
        types = set()
    if "properties" in schema:
        types.add("object")
    if "items" in schema:
        types.add("array")
    for keyword in ("anyOf", "oneOf", "allOf"):
        alternatives = schema.get(keyword)
        if isinstance(alternatives, list):
            for alternative in alternatives:
                types.update(_schema_types(alternative))
    return {str(item) for item in types}


def _coerce_param_value(
    raw: str,
    attrs: str,
    schema: dict[str, Any] | None = None,
) -> Any:
    stripped = raw.strip()
    schema_types = _schema_types(schema)
    expects_container = bool(schema_types & {"array", "object"})
    explicitly_string = schema_types == {"string"}

    # DeepSeek commonly marks every DSML parameter ``string=true``, including
    # JSON arrays and objects. A declared container schema wins over that wire
    # hint. Without a schema, retain the provider's explicit string contract.
    if expects_container:
        try:
            parsed = json.loads(stripped)
        except (TypeError, ValueError):
            pass
        else:
            matches_array = "array" in schema_types and isinstance(parsed, list)
            matches_object = "object" in schema_types and isinstance(parsed, dict)
            if matches_array or matches_object:
                return parsed

    if _looks_like_string(attrs) or explicitly_string:
        return raw
    # Unmarked scalars (numbers, bools, JSON objects/arrays) are parsed; on any
    # failure the raw string is kept verbatim.
    try:
        return json.loads(raw.strip())
    except Exception:
        return raw


def has_dsml_tool_calls(text: str | None) -> bool:
    """Cheap check for whether ``text`` carries DSML tool-call markup."""
    if not text:
        return False
    return bool(DSML_SIGNAL_RE.search(text))


def _parameter_schemas(
    tool_schemas: Iterable[dict[str, Any]] | None,
) -> dict[str, dict[str, dict[str, Any]]]:
    by_tool: dict[str, dict[str, dict[str, Any]]] = {}
    for tool in tool_schemas or []:
        function = tool.get("function") if isinstance(tool, dict) else None
        if not isinstance(function, dict):
            continue
        name = str(function.get("name") or "").strip()
        parameters = function.get("parameters")
        properties = parameters.get("properties") if isinstance(parameters, dict) else None
        if not name or not isinstance(properties, dict):
            continue
        by_tool[name] = {
            str(param_name): param_schema
            for param_name, param_schema in properties.items()
            if isinstance(param_schema, dict)
        }
    return by_tool


def extract_dsml_tool_calls(
    text: str | None,
    tool_schemas: Iterable[dict[str, Any]] | None = None,
) -> tuple[list[dict[str, Any]], str]:
    """Parse DSML tool-call markup out of ``text``.

    ``tool_schemas`` supplies JSON-Schema types for parameters. Container
    schemas deliberately override DeepSeek's blanket ``string=true`` hint.
    Returns ``(tool_calls, cleaned_text)``. ``tool_calls`` is empty and
    ``cleaned_text is text`` when no well-formed invoke block is present, so the
    caller can treat "no calls" as "not a DSML round" and fall through
    unchanged.
    """
    raw_text = text or ""
    if not has_dsml_tool_calls(raw_text):
        return [], raw_text

    schemas_by_tool = _parameter_schemas(tool_schemas)
    tool_calls: list[dict[str, Any]] = []
    spans: list[tuple[int, int]] = []
    for idx, match in enumerate(_INVOKE_RE.finditer(raw_text)):
        name = match.group("name").strip()
        if not name:
            continue
        args: dict[str, Any] = {}
        parameter_schemas = schemas_by_tool.get(name, {})
        for param in _PARAM_RE.finditer(match.group("body")):
            param_name = param.group("pname").strip()
            args[param_name] = _coerce_param_value(
                param.group("pval"),
                param.group("attrs") or "",
                parameter_schemas.get(param_name),
            )
        tool_calls.append(
            {
                "id": f"dsml_{idx}",
                "name": name,
                "arguments": json.dumps(args, ensure_ascii=False),
            }
        )
        spans.append((match.start(), match.end()))

    if not tool_calls:
        return [], raw_text

    cleaned = raw_text
    for start, end in reversed(spans):
        cleaned = cleaned[:start] + cleaned[end:]
    cleaned = _TOOLCALLS_WRAP_RE.sub("", cleaned).strip()
    return tool_calls, cleaned


__all__ = [
    "DSMLStreamFilter",
    "extract_dsml_tool_calls",
    "has_dsml_tool_calls",
    "DSML_SIGNAL_RE",
]
