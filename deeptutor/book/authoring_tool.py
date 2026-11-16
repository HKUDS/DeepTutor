"""A proposal-only tool bound by the server to one attached book page."""

import json

from deeptutor.core.tool_protocol import BaseTool, ToolDefinition, ToolParameter, ToolResult


def authoring_scope(context):
    refs = context.metadata.get("book_references") or []
    if len(refs) != 1 or not isinstance(refs[0], dict):
        return None
    ref = refs[0]
    pages = ref.get("page_ids") or []
    if len(pages) != 1 or not ref.get("book_id"):
        return None
    return {"book_id": ref["book_id"], "page_id": pages[0]}


class ProposeBookEditTool(BaseTool):
    def get_definition(self):
        return ToolDefinition(
            name="propose_book_edit",
            description=(
                "Propose an edit to the current attached book page based on this conversation. "
                "The user reviews a diff and explicitly applies it; this tool NEVER changes book content. "
                "Use add_page for a new section in the same chapter (include a learning objective in body), "
                "insert_block for a chosen position, or extend_page to append a text block. "
                "Ask about the learning objective first when it is unclear. Keep the book language and style."
            ),
            parameters=[
                ToolParameter(
                    name="action", type="string", enum=["add_page", "insert_block", "extend_page"]
                ),
                ToolParameter(name="title", type="string"),
                ToolParameter(name="body", type="string"),
                ToolParameter(
                    name="position",
                    type="integer",
                    minimum=0,
                    maximum=10000,
                    required=False,
                    default=0,
                ),
            ],
        )

    async def execute(self, **kwargs):
        from deeptutor.book.authoring import BookEdit, preview_edit
        from deeptutor.multi_user.book_access import resolve_book

        scope = kwargs.get("_book_scope")
        if not scope or not kwargs.get("_source_turn_id"):
            return ToolResult(
                content="No editable book page is attached to this turn.", success=False
            )
        try:
            resolved = resolve_book(scope["book_id"])
            if resolved is None or not resolved.can_edit:
                raise ValueError("The attached book is not editable")
            storage = resolved.engine.storage
            page = storage.load_page(scope["book_id"], scope["page_id"])
            if page is None:
                raise ValueError("The attached page is unavailable")
            if kwargs.get("action") not in {"add_page", "insert_block", "extend_page"}:
                raise ValueError("Only non-destructive proposals are available to the agent")
            edit = BookEdit(
                action=kwargs["action"],
                title=kwargs.get("title", ""),
                body=kwargs.get("body", ""),
                position=kwargs.get("position", 0),
                page_id=page.id,
                chapter_id=page.chapter_id,
            )
            proposal = preview_edit(
                storage,
                scope["book_id"],
                edit,
                source_session_id=kwargs.get("_source_session_id", ""),
                source_turn_id=kwargs["_source_turn_id"],
            )
            return ToolResult(
                content=json.dumps(
                    {"proposal_id": proposal["id"], "status": "awaiting_user_confirmation"}
                ),
                metadata={
                    "book_edit_id": proposal["id"],
                    "book_id": scope["book_id"],
                    "page_id": page.id,
                },
            )
        except (ValueError, PermissionError) as exc:
            return ToolResult(content=str(exc), success=False)
