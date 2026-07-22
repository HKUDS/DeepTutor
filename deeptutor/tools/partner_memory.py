"""Partner-only memory + history tools.

A partner has a *split* memory model that the product chat does not:

* its OWN long-term memory lives in the partner's synthetic workspace
  (``data/partners/<id>/workspace/memory``) and is the only thing
  ``partner_memorize`` ever writes to — a partner can never mutate the
  owner's memory;
* the OWNER's shared memory (the admin L3) is read-only context the
  partner inherits, so ``partner_read`` returns *both* layers concatenated.

These three tools replace the product chat's ``read_memory`` / ``write_memory``
for partners (which are suppressed on partner turns) and add a keyword search
over the partner's own conversation history. They are force-mounted by the
partner runtime and never available in product chat, so — unlike the chat
memory tools — they don't gate on ``user_has_memory`` and aren't configurable.
"""

from __future__ import annotations

from typing import Any

from deeptutor.core.tool_protocol import BaseTool, ToolDefinition, ToolParameter, ToolResult

# Force-mounted on every partner turn (see ``compose_enabled_tools`` /
# ``agentic_pipeline``). Single source of truth for the partner memory surface.
PARTNER_BUILTIN_TOOL_NAMES: tuple[str, ...] = (
    "partner_read",
    "partner_memorize",
    "partner_search",
)

_SNIPPET_WIDTH = 140
_MAX_SCAN_MATCHES = 300


def _concat_l3() -> str:
    """Concatenate the active scope's L3 docs, or ``""`` when empty.

    Resolves through ``memory_root()`` like the chat ``read_memory`` tool, so a
    ``memory_path_service_override`` around the call decides whose memory this
    reads. Unlike ``MemoryStore.read_l3_concat`` it returns an empty string
    (not the chat placeholder) when nothing is stored, so the caller can label
    the empty layer cleanly.
    """
    from deeptutor.services.memory import get_memory_store, paths

    store = get_memory_store()
    parts: list[str] = []
    for slot in paths.L3_SLOTS:
        body = store.read_raw("L3", slot).strip()
        if body:
            parts.append(body)
    return "\n\n---\n\n".join(parts)


def _resolve_partner_id() -> str | None:
    """The active partner id, or ``None`` when not inside a partner scope."""
    from deeptutor.multi_user.context import get_current_user_or_none
    from deeptutor.services.partners.scope import PARTNER_USER_PREFIX

    user = get_current_user_or_none()
    user_id = user.scope.user_id if user and user.scope else ""
    if not user_id.startswith(PARTNER_USER_PREFIX):
        return None
    return user_id[len(PARTNER_USER_PREFIX) :]


def _snippet_around(content: str, needle_lower: str) -> str:
    """A one-line window of *content* centred on the first match of *needle*."""
    low = content.lower()
    idx = low.find(needle_lower)
    flat = " ".join(content.split())
    if idx < 0:
        return flat[:_SNIPPET_WIDTH]
    # Re-find in the flattened text so offsets line up with what we slice.
    flat_idx = flat.lower().find(needle_lower)
    if flat_idx < 0:
        return flat[:_SNIPPET_WIDTH]
    half = _SNIPPET_WIDTH // 2
    start = max(0, flat_idx - half)
    end = min(len(flat), flat_idx + len(needle_lower) + half)
    prefix = "…" if start > 0 else ""
    suffix = "…" if end < len(flat) else ""
    return f"{prefix}{flat[start:end].strip()}{suffix}"


class PartnerReadTool(BaseTool):
    """Read the partner's combined memory: the owner's shared L3 + the
    partner's own L3. Partner-only; force-mounted by the partner runtime."""

    def get_definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="partner_read",
            description=(
                "Read your memory: the owner's shared long-term memory plus your "
                "own accumulated notes about this person. Use it to personalise "
                "tone, depth, and examples — not on every turn, and not for "
                "purely factual questions."
            ),
            parameters=[],
        )

    async def execute(self, **kwargs: Any) -> ToolResult:
        from deeptutor.multi_user.paths import (
            get_admin_path_service,
            get_current_path_service,
        )
        from deeptutor.services.memory import memory_path_service_override

        with memory_path_service_override(get_admin_path_service()):
            shared = _concat_l3()
        with memory_path_service_override(get_current_path_service()):
            own = _concat_l3()

        sections = [
            "## Shared memory (the owner's — read-only)\n\n" + (shared or "(none yet)"),
            "## Your own memory\n\n" + (own or "(none yet — use partner_memorize to add)"),
        ]
        text = "\n\n".join(sections)
        return ToolResult(
            content=text,
            metadata={"char_count": len(text), "has_shared": bool(shared), "has_own": bool(own)},
        )


class PartnerMemorizeTool(BaseTool):
    """Persist a note into the partner's OWN ``preferences`` doc. Never touches
    the owner's memory. Partner-only; force-mounted by the partner runtime."""

    def get_definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="partner_memorize",
            description=(
                "Save something worth remembering about this person to your own "
                "long-term memory — a lasting preference, a recurring need, a "
                "durable fact. Writes ONLY to your own memory, never the owner's. "
                "Call when the user clearly states a preference or you learn "
                "something durable — never speculate."
            ),
            parameters=[
                ToolParameter(
                    name="op",
                    type="string",
                    description="`add` for a new note, `edit` to revise an existing one.",
                    enum=["add", "edit"],
                    required=True,
                ),
                ToolParameter(
                    name="text",
                    type="string",
                    description="The note, in the user's own words where possible. ≤ 240 chars.",
                    required=True,
                ),
                ToolParameter(
                    name="target_id",
                    type="string",
                    description="Existing entry id (form `m_xxx`). Required for `edit`.",
                    required=False,
                ),
                ToolParameter(
                    name="reason",
                    type="string",
                    description="Optional one-line note recorded in the memory log.",
                    required=False,
                ),
            ],
        )

    async def execute(self, **kwargs: Any) -> ToolResult:
        from deeptutor.multi_user.paths import get_current_path_service
        from deeptutor.services.memory import get_memory_store, memory_path_service_override
        from deeptutor.services.memory.trace import TraceEvent

        op = str(kwargs.get("op") or "").strip().lower()
        text = str(kwargs.get("text") or "").strip()
        target_id = kwargs.get("target_id")
        reason = kwargs.get("reason")

        if op not in {"add", "edit"}:
            return ToolResult(
                content=f"Error: op must be 'add' or 'edit', got {op!r}.", success=False
            )
        if not text:
            return ToolResult(
                content="Error: text is required and must be non-empty.", success=False
            )

        store = get_memory_store()
        # Trace + preference both land in the partner's own memory scope, so the
        # footnote ref resolves inside the same tree it's stored in.
        with memory_path_service_override(get_current_path_service()):
            event = TraceEvent.new(
                "partner",
                "preference_stated",
                {"op": op, "text": text, "target_id": target_id, "reason": reason},
            )
            await store.emit(event)
            report = await store.write_preference(
                op=op,  # type: ignore[arg-type]
                text=text,
                target_id=str(target_id).strip() if target_id else None,
                reason=str(reason).strip() if reason else None,
                trace_id=event.id,
            )
        if not report.accepted:
            return ToolResult(
                content=f"partner_memorize rejected: {report.reason}",
                success=False,
                metadata={"op": op},
            )
        entry_id = report.results[0].entry_id if report.results else None
        return ToolResult(
            content=f"noted ({op}, entry={entry_id or target_id}).",
            metadata={"op": op, "entry_id": entry_id or target_id},
        )


class PartnerSearchTool(BaseTool):
    """Keyword-search the partner's own past conversations (all sessions).
    Partner-only; force-mounted by the partner runtime."""

    def get_definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="partner_search",
            description=(
                "Search your past conversations with this person by keyword. "
                "Returns matching message snippets with their session and time. "
                "Use it to recall what you discussed before when memory isn't enough."
            ),
            parameters=[
                ToolParameter(
                    name="query",
                    type="string",
                    description="Keyword or phrase to search for (case-insensitive).",
                    required=True,
                ),
                ToolParameter(
                    name="limit",
                    type="integer",
                    description="Max snippets to return (default 30, max 100).",
                    required=False,
                ),
            ],
        )

    async def execute(self, **kwargs: Any) -> ToolResult:
        from deeptutor.partners.config.paths import get_partner_sessions_dir
        from deeptutor.services.partners.sessions import PartnerSessionStore

        query = str(kwargs.get("query") or "").strip()
        if not query:
            return ToolResult(content="Error: query is required.", success=False)
        try:
            limit = int(kwargs.get("limit") or 30)
        except (TypeError, ValueError):
            limit = 30
        limit = max(1, min(limit, 100))

        partner_id = _resolve_partner_id()
        if partner_id is None:
            return ToolResult(
                content="Error: partner_search is only available inside a partner.",
                success=False,
            )

        store = PartnerSessionStore(get_partner_sessions_dir(partner_id))
        needle = query.lower()
        # (timestamp, formatted_line) — collected across all sessions, then
        # sorted most-recent-first and truncated to ``limit``.
        matches: list[tuple[str, str]] = []
        for summary in store.list_sessions():
            key = str(summary.get("session_key") or "")
            title = str(summary.get("title") or "") or "(untitled)"
            for record in store.messages(key, limit=10000):
                role = str(record.get("role") or "")
                if role == "tool":
                    continue
                content = str(record.get("content") or "")
                if needle not in content.lower():
                    continue
                ts = str(record.get("timestamp") or "")
                snippet = _snippet_around(content, needle)
                matches.append((ts, f"[{title} · {role} · {ts[:19]}] {snippet}"))
                if len(matches) >= _MAX_SCAN_MATCHES:
                    break
            if len(matches) >= _MAX_SCAN_MATCHES:
                break

        if not matches:
            return ToolResult(
                content=f"No past messages matched {query!r}.",
                metadata={"query": query, "count": 0},
            )
        matches.sort(key=lambda m: m[0], reverse=True)
        lines = [line for _, line in matches[:limit]]
        text = "\n".join(lines)
        return ToolResult(content=text, metadata={"query": query, "count": len(lines)})


__all__ = [
    "PARTNER_BUILTIN_TOOL_NAMES",
    "PartnerMemorizeTool",
    "PartnerReadTool",
    "PartnerSearchTool",
]
