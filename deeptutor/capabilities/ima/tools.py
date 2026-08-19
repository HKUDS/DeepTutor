"""IMA tools — the agentic surface over a connected Tencent IMA library.

Five tools, auto-mounted only when a ``type: ima`` knowledge base is selected
(see :class:`~deeptutor.capabilities.ima.capability.ImaCapability`). They cover
the questions retrieval structurally cannot answer, plus the two additive writes:

* ``ima_list`` — browse what the library holds, folder by folder. "What's in
  here", "did I add X", "show me the folder Y" are inventory questions; a
  similarity search cannot answer them.
* ``ima_read`` — the full source text of one item, when a retrieved snippet is
  not enough.
* ``ima_note_search`` — search or list IMA notes, newest first. Notes are the
  only IMA objects carrying timestamps, so this is what answers "my most recent
  notes".
* ``ima_add_url`` — collect a web page / WeChat article into the library.
* ``ima_write_note`` — create a note, or append to one the user named.

The turn's available libraries are injected server-side as ``_ima_bindings``;
the model supplies at most a ``kb_name`` to pick between them, and credentials
are loaded per call from the KB's own config (never passed through kwargs).
"""

from __future__ import annotations

import json
from typing import Any

from deeptutor.capabilities.ima.binding import ImaBinding, resolve_client, select_binding
from deeptutor.core.tool_protocol import BaseTool, ToolDefinition, ToolParameter, ToolResult

# The IMA service modules are imported lazily inside the methods that need them:
# this module is imported while ``deeptutor.tools.builtin`` builds the global tool
# table, and reaching into ``deeptutor.services.rag`` at import time would close
# a cycle through the runtime tool registry.

# Tool names mounted together when an IMA library is selected. Single source of
# truth so the mount policy and the registration list can't disagree.
IMA_TOOL_NAMES: tuple[str, ...] = (
    "ima_list",
    "ima_read",
    "ima_note_search",
    "ima_add_url",
    "ima_write_note",
)

# Injected by the capability: the turn's selected IMA libraries.
BINDINGS_KWARG = "_ima_bindings"

_KB_NAME_PARAM = ToolParameter(
    name="kb_name",
    type="string",
    description=("Which attached IMA knowledge base to use. Optional when only one is attached."),
    required=False,
)


def _note_sort(name: Any) -> int:
    """Map a tool-level sort name onto IMA's numeric ``sort_type``."""
    from deeptutor.services.rag.pipelines.ima.notes import (
        SORT_BY_CREATED,
        SORT_BY_TITLE,
        SORT_BY_UPDATED,
    )

    return {
        "updated": SORT_BY_UPDATED,
        "created": SORT_BY_CREATED,
        "title": SORT_BY_TITLE,
    }.get(str(name or "updated"), SORT_BY_UPDATED)


class _ImaTool(BaseTool):
    """Shared binding resolution and uniform error handling for IMA tools."""

    #: Writes re-check the user's write access to the knowledge base.
    writes = False

    async def execute(self, **kwargs: Any) -> ToolResult:
        from deeptutor.services.rag.pipelines.ima.config import ImaNotConfiguredError
        from deeptutor.services.rag.pipelines.ima.envelope import (
            ImaAPIError,
            ImaAuthError,
            ImaRateLimitError,
        )

        bindings = _bindings(kwargs)
        binding = select_binding(bindings, kwargs.get("kb_name"))
        if binding is None:
            return _err(_no_binding_message(bindings))
        try:
            client = resolve_client(binding.kb_ref, for_write=self.writes)
        except ImaNotConfiguredError as exc:
            return _err(str(exc))
        except Exception:
            return _err(
                f"'{binding.name}' is not available on this turn"
                f"{' with write access' if self.writes else ''}."
            )
        try:
            return await self._run(client, binding, kwargs)
        except ImaAuthError:
            return _err("Tencent IMA rejected the credentials for this knowledge base.")
        except ImaRateLimitError:
            return _err("Tencent IMA is rate-limiting requests. Try again shortly.")
        except ImaAPIError as exc:
            return _err(str(exc))
        except ValueError as exc:
            return _err(str(exc))

    async def _run(
        self,
        client: Any,
        binding: ImaBinding,
        kwargs: dict[str, Any],
    ) -> ToolResult:  # pragma: no cover - abstract
        raise NotImplementedError


class ImaListTool(_ImaTool):
    """Browse a connected IMA library's contents."""

    def get_definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="ima_list",
            description=(
                "List what a connected Tencent IMA knowledge base actually holds: its "
                "documents and folders. Use this for inventory questions ('what is in "
                "here', 'is document X present', 'show me folder Y') — retrieval only "
                "reports what a query matched. Pass a folder_id from a previous call to "
                "look inside that folder."
            ),
            parameters=[
                _KB_NAME_PARAM,
                ToolParameter(
                    name="folder_id",
                    type="string",
                    description="Folder to open, from an earlier listing. Omit for the top level.",
                    required=False,
                ),
                ToolParameter(
                    name="limit",
                    type="integer",
                    description="Max entries to return (1-50, default 50).",
                    required=False,
                ),
                ToolParameter(
                    name="cursor",
                    type="string",
                    description="Continuation cursor from an earlier call's next_cursor.",
                    required=False,
                ),
            ],
        )

    async def _run(self, client, binding, kwargs):
        page = await client.get_knowledge_list(
            folder_id=str(kwargs.get("folder_id") or ""),
            cursor=str(kwargs.get("cursor") or ""),
            limit=kwargs.get("limit") or 50,
        )
        return _ok(
            {
                "knowledge_base": binding.name,
                "path": list(page.path),
                "folders": [
                    {
                        "folder_id": folder.folder_id,
                        "name": folder.name,
                        "documents": folder.file_number,
                        "subfolders": folder.folder_number,
                    }
                    for folder in page.folders
                ],
                "documents": [
                    {"media_id": document.media_id, "title": document.title}
                    for document in page.documents
                ],
                "next_cursor": page.next_cursor,
                "is_end": page.is_end,
            }
        )


class ImaReadTool(_ImaTool):
    """Read one IMA item's full source text."""

    def get_definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="ima_read",
            description=(
                "Read the full text of one item in a connected Tencent IMA knowledge "
                "base, identified by the media_id from ima_list or a retrieval citation. "
                "Use it when a retrieved snippet is too short to answer from."
            ),
            parameters=[
                ToolParameter(
                    name="media_id",
                    type="string",
                    description="Item id from ima_list or a retrieval result.",
                ),
                _KB_NAME_PARAM,
            ],
        )

    async def _run(self, client, binding, kwargs):
        from deeptutor.services.rag.pipelines.ima import media as media_ops
        from deeptutor.services.rag.pipelines.ima import sources as source_policy

        media_id = str(kwargs.get("media_id") or "").strip()
        if not media_id:
            raise ValueError("media_id is required.")
        media = await client.get_media_content(media_id)
        text = await media_ops.extract_text(
            media,
            max_chars=source_policy.MAX_FULLTEXT_CHARS,
        )
        if not text:
            return _err(
                "That item has no readable text — it may be an image, an audio file, "
                "or a format Tencent IMA does not expose over the API."
            )
        return _ok(
            {
                "knowledge_base": binding.name,
                "media_id": media_id,
                "truncated": len(text) >= source_policy.MAX_FULLTEXT_CHARS,
                "content": text,
            }
        )


class ImaNoteSearchTool(_ImaTool):
    """Search or list the user's IMA notes."""

    def get_definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="ima_note_search",
            description=(
                "Search the user's Tencent IMA notes, or list them newest-first when no "
                "query is given. Notes are the only IMA objects with timestamps, so this "
                "is how to answer 'my latest notes' or 'what did I write about X'."
            ),
            parameters=[
                ToolParameter(
                    name="query",
                    type="string",
                    description="Text to match. Omit to list notes in sort order.",
                    required=False,
                ),
                ToolParameter(
                    name="in_content",
                    type="boolean",
                    description="Search note bodies instead of titles (default false).",
                    required=False,
                ),
                ToolParameter(
                    name="sort",
                    type="string",
                    description="Order: updated (default), created, or title.",
                    required=False,
                    enum=["updated", "created", "title"],
                ),
                ToolParameter(
                    name="limit",
                    type="integer",
                    description="Max notes to return (1-50, default 20).",
                    required=False,
                ),
                _KB_NAME_PARAM,
            ],
        )

    async def _run(self, client, binding, kwargs):
        notes, is_end = await client.notes.search_notes(
            str(kwargs.get("query") or ""),
            by_content=bool(kwargs.get("in_content")),
            sort_type=_note_sort(kwargs.get("sort")),
            limit=kwargs.get("limit") or 20,
        )
        return _ok(
            {
                "notes": [
                    {
                        "note_id": note.note_id,
                        "title": note.title,
                        "summary": note.summary,
                        "notebook": note.folder_name,
                        "created_at": note.created_at,
                        "updated_at": note.updated_at,
                    }
                    for note in notes
                ],
                "is_end": is_end,
            }
        )


class ImaAddUrlTool(_ImaTool):
    """Collect web pages into a connected IMA library."""

    writes = True

    def get_definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="ima_add_url",
            description=(
                "Add web pages or WeChat articles (up to 10 URLs) to a connected Tencent "
                "IMA knowledge base, so IMA indexes them for later retrieval. Only call "
                "this when the user asked to save or collect something — it modifies "
                "their library. Video pages (Bilibili / YouTube) and local files are not "
                "supported by IMA's API."
            ),
            parameters=[
                ToolParameter(
                    name="urls",
                    type="array",
                    description="1-10 http(s) URLs to add.",
                    items={"type": "string"},
                ),
                _KB_NAME_PARAM,
                ToolParameter(
                    name="folder_id",
                    type="string",
                    description="Target folder from ima_list. Omit for the library root.",
                    required=False,
                ),
            ],
        )

    async def _run(self, client, binding, kwargs):
        urls = _string_list(kwargs.get("urls"))
        unsupported = [url for url in urls if not _is_supported_url(url)]
        if unsupported:
            return _err(
                "Tencent IMA cannot add these over its API (video pages and local files "
                f"must be added in the IMA desktop app): {', '.join(unsupported)}"
            )
        results = await client.import_urls(urls, folder_id=str(kwargs.get("folder_id") or ""))
        added = [result for result in results if result.ok]
        failed = [result for result in results if not result.ok]
        return ToolResult(
            content=json.dumps(
                {
                    "knowledge_base": binding.name,
                    "added": [{"url": item.url, "media_id": item.media_id} for item in added],
                    "failed": [{"url": item.url, "code": item.code} for item in failed],
                },
                ensure_ascii=False,
            ),
            success=bool(added),
        )


class ImaWriteNoteTool(_ImaTool):
    """Create an IMA note, or append to an existing one."""

    writes = True

    def get_definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="ima_write_note",
            description=(
                "Write a Markdown note into the user's Tencent IMA account. Creates a new "
                "note by default; pass note_id to append to that note instead. Appending "
                "cannot be undone, so only append to a note the user explicitly named — "
                "otherwise create a new one. Only call this when the user asked to save "
                "something."
            ),
            parameters=[
                ToolParameter(
                    name="content",
                    type="string",
                    description="Markdown body. Start with a '# Heading' to title a new note.",
                ),
                ToolParameter(
                    name="note_id",
                    type="string",
                    description=(
                        "Append to this note (from ima_note_search) instead of creating one."
                    ),
                    required=False,
                ),
                ToolParameter(
                    name="notebook_id",
                    type="string",
                    description="Notebook for a new note. Omit for the default location.",
                    required=False,
                ),
                _KB_NAME_PARAM,
            ],
        )

    async def _run(self, client, binding, kwargs):
        content = str(kwargs.get("content") or "").strip()
        note_id = str(kwargs.get("note_id") or "").strip()
        if note_id:
            written = await client.notes.append_note(note_id, content)
            return _ok({"note_id": written, "action": "appended"})
        written = await client.notes.create_note(
            content,
            folder_id=str(kwargs.get("notebook_id") or ""),
        )
        if not written:
            return _err("Tencent IMA did not return a note id; the note may not have been saved.")
        return _ok({"note_id": written, "action": "created"})


def _bindings(kwargs: dict[str, Any]) -> tuple[ImaBinding, ...]:
    raw = kwargs.get(BINDINGS_KWARG)
    if not raw:
        return ()
    return tuple(item for item in raw if isinstance(item, ImaBinding))


def _no_binding_message(bindings: tuple[ImaBinding, ...]) -> str:
    if not bindings:
        return "No Tencent IMA knowledge base is attached to this turn; IMA tools are unavailable."
    names = ", ".join(binding.name for binding in bindings)
    return f"Specify which IMA knowledge base to use with kb_name. Attached: {names}."


def _string_list(value: Any) -> list[str]:
    if isinstance(value, str):
        candidates = [value]
    elif isinstance(value, (list, tuple)):
        candidates = [str(item) for item in value]
    else:
        raise ValueError("urls must be a list of strings.")
    urls = [item.strip() for item in candidates if str(item).strip()]
    if not urls:
        raise ValueError("At least one URL is required.")
    return urls


# IMA's API refuses these; failing locally keeps the model from reporting a
# confusing upstream error for something that was never going to work.
_UNSUPPORTED_URL_MARKERS: tuple[str, ...] = (
    "bilibili.com/video/",
    "youtube.com/watch",
    "youtu.be/",
)


def _is_supported_url(url: str) -> bool:
    lowered = url.lower()
    if not lowered.startswith(("http://", "https://")):
        return False
    return not any(marker in lowered for marker in _UNSUPPORTED_URL_MARKERS)


def _ok(payload: Any) -> ToolResult:
    return ToolResult(content=json.dumps(payload, ensure_ascii=False), success=True)


def _err(message: str) -> ToolResult:
    return ToolResult(content=message, success=False)


IMA_TOOL_TYPES: tuple[type[BaseTool], ...] = (
    ImaListTool,
    ImaReadTool,
    ImaNoteSearchTool,
    ImaAddUrlTool,
    ImaWriteNoteTool,
)

__all__ = [
    "BINDINGS_KWARG",
    "IMA_TOOL_NAMES",
    "IMA_TOOL_TYPES",
    "ImaAddUrlTool",
    "ImaListTool",
    "ImaNoteSearchTool",
    "ImaReadTool",
    "ImaWriteNoteTool",
]
