import copy
import json

from deeptutor.co_writer.storage import get_co_writer_storage
from deeptutor.core.tool_protocol import BaseTool, ToolDefinition, ToolParameter, ToolResult
from deeptutor.notes.proposals import propose


class NoteReadTool(BaseTool):
    def get_definition(self):
        return ToolDefinition(
            name="note_read",
            description="Read the open notebook page with block IDs, structure and Markdown. Large pages return an outline; read a specific block_id to inspect its body.",
            parameters=[
                ToolParameter(
                    name="block_id",
                    type="string",
                    description="Optional block ID to read",
                    required=False,
                )
            ],
        )

    async def execute(self, **kwargs):
        if not kwargs.get("_note_document_id"):
            return ToolResult(content="No notebook page is bound to this turn", success=False)
        try:
            doc = get_co_writer_storage().load_document(kwargs["_note_document_id"])
            if doc is None:
                raise ValueError("Page not found")
            from deeptutor.notes.blocks import walk_blocks

            state = kwargs.get("_note_read_state")
            if isinstance(state, dict):
                for block in walk_blocks(doc.blocks):
                    if not kwargs.get("block_id") or block["id"] == kwargs["block_id"]:
                        state[block["id"]] = copy.deepcopy(block)

            if kwargs.get("block_id"):
                target = next(
                    (b for b in walk_blocks(doc.blocks) if b["id"] == kwargs["block_id"]), None
                )
                if target is None:
                    raise ValueError("Block not found")
                payload = {"page_id": doc.id, "revision": doc.revision, "block": target}
            elif len(json.dumps(doc.blocks)) > 80000:
                payload = {
                    "id": doc.id,
                    "title": doc.title,
                    "revision": doc.revision,
                    "outline": [
                        {
                            "id": b["id"],
                            "type": b["type"],
                            "preview": str(b.get("content", b.get("props", {})))[:300],
                        }
                        for b in walk_blocks(doc.blocks)
                    ],
                }
            else:
                payload = doc.model_dump()
            return ToolResult(content=json.dumps(payload, ensure_ascii=False), success=True)
        except ValueError as exc:
            return ToolResult(content=str(exc), success=False)


class NoteSuggestTool(BaseTool):
    def get_definition(self):
        return ToolDefinition(
            name="note_suggest",
            description="Propose a block edit or teaching comment for user review. Does not change the page until accepted. Text-only parent replacements preserve existing child blocks; propose deletions of children separately.",
            parameters=[
                ToolParameter(
                    name="operation",
                    type="string",
                    description="Edit operation",
                    enum=["insert", "replace", "delete", "comment"],
                ),
                ToolParameter(
                    name="block_id",
                    type="string",
                    description="Target block ID; empty inserts at the end",
                    required=False,
                ),
                ToolParameter(
                    name="markdown",
                    type="string",
                    description="Suggested content in Markdown",
                    required=False,
                ),
                ToolParameter(
                    name="blocks",
                    type="array",
                    items={"type": "object"},
                    description="Optional complete BlockNote blocks, each with unique id, type, props, content and children. For interactive learning blocks use type learning, props kind (quiz or flashcards), data (JSON string with questions [{question, options, correct_answer, explanation}] or cards [{front, back}]), markdown (plain text projection), prompt. Timeline data uses events [{date,title,description}]; concept_map uses nodes and edges. Visualizations use kind=visualization and the complete validated visualization result in data. Media uses kind=media and workspace_items from the producing tool. Run code with exec only if mounted and report real output as a comment. Use Markdown for ordinary prose.",
                    required=False,
                ),
                ToolParameter(
                    name="explanation",
                    type="string",
                    description="Why this edit, or teaching feedback with sources",
                    required=False,
                ),
            ],
        )

    async def execute(self, **kwargs):
        if not kwargs.get("_note_document_id"):
            return ToolResult(content="No notebook page is bound to this turn", success=False)
        try:
            block_id = kwargs.get("block_id", "")
            expected = {}
            if block_id:
                state = kwargs.get("_note_read_state", {})
                if block_id not in state:
                    raise ValueError(
                        "Use note_read to read the target block before suggesting changes"
                    )
                expected["expected_original"] = state[block_id]
            result = propose(
                get_co_writer_storage(),
                kwargs["_note_document_id"],
                operation=kwargs["operation"],
                block_id=kwargs.get("block_id", ""),
                markdown=kwargs.get("markdown", ""),
                explanation=kwargs.get("explanation", ""),
                blocks=kwargs.get("blocks"),
                workspace_id=str(kwargs.get("_workspace_id") or ""),
                **expected,
            )
            return ToolResult(
                content=json.dumps(
                    {"suggestion_id": result["id"], "status": "pending_user_review"}
                ),
                success=True,
            )
        except (ValueError, KeyError) as exc:
            return ToolResult(content=str(exc), success=False)


class WriteNoteTool(BaseTool):
    def get_definition(self):
        return ToolDefinition(
            name="write_note",
            description="Create an authored notebook page. To preserve an original conversation use save_favorite. Existing pages are edited through reviewable note_suggest in their editor.",
            parameters=[
                ToolParameter(name="title", type="string", description="Page title"),
                ToolParameter(
                    name="content",
                    type="string",
                    description="Full authored Markdown, preserving citations and source links",
                ),
            ],
        )

    async def execute(self, **kwargs):
        title, content = str(kwargs.get("title", "")), str(kwargs.get("content", ""))
        if not title.strip() or not content.strip() or len(content) > 200000:
            return ToolResult(
                content="Provide a title and content (up to 200000 characters)", success=False
            )
        doc = get_co_writer_storage().create_document(title=title[:200], content=content)
        return ToolResult(
            content=json.dumps(
                {"id": doc.id, "title": doc.title, "url": f"/co-writer/{doc.id}"},
                ensure_ascii=False,
            ),
            success=True,
        )


class SearchNotesTool(BaseTool):
    def get_definition(self):
        return ToolDefinition(
            name="search_notes",
            description="Find authored notebook pages by title or full text; returns excerpts and page links. Empty query lists recent pages. Read a whole page with page_id.",
            parameters=[
                ToolParameter(
                    name="query", type="string", description="Text to find", required=False
                ),
                ToolParameter(
                    name="page_id", type="string", description="Page ID to read", required=False
                ),
            ],
        )

    async def execute(self, **kwargs):
        storage = get_co_writer_storage()
        try:
            if kwargs.get("page_id"):
                doc = storage.load_document(kwargs["page_id"])
                return ToolResult(
                    content=json.dumps(
                        {"title": doc.title, "content": doc.content}
                        if doc
                        else {"error": "Page not found"},
                        ensure_ascii=False,
                    ),
                    success=doc is not None,
                )
            query = str(kwargs.get("query", "")).casefold()
            results = []
            for summary in storage.list_documents():
                doc = storage.load_document(summary.id)
                if doc is None:
                    continue
                text = doc.title + "\n" + doc.content
                pos = text.casefold().find(query)
                if pos >= 0:
                    results.append(
                        {
                            "id": doc.id,
                            "title": doc.title,
                            "excerpt": text[max(0, pos - 100) : pos + 600],
                            "url": f"/co-writer/{doc.id}",
                        }
                    )
                if len(results) >= 20:
                    break
            return ToolResult(content=json.dumps(results, ensure_ascii=False), success=True)
        except ValueError as exc:
            return ToolResult(content=str(exc), success=False)
