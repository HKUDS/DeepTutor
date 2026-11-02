"""Validate portable BlockNote JSON and derive a read-only Markdown projection."""

from __future__ import annotations

import json
import re
from typing import Any

MAX_BLOCK_BYTES = 4 * 1024 * 1024
# Blocks with no inline content of their own (BlockNote ``content: "none"``).
LEAF_BLOCK_TYPES = frozenset(
    {
        "learning",
        "noteUpload",
        "clip",
        "math",
        "divider",
        "image",
        "video",
        "audio",
        "file",
        "noteColumn",
        "noteColumns",
        "tableOfContents",
        "webCard",
        "htmlEmbed",
        "taskView",
    }
)


def safe_link(value: str) -> bool:
    """Only links the editor can display without executing page-provided code."""
    return isinstance(value, str) and (
        not value or bool(re.match(r"^(https?://|mailto:|/(?!/)|#)", value, re.I))
    )


def validate_blocks(blocks: list[dict[str, Any]]) -> list[dict[str, Any]]:
    if len(json.dumps(blocks, ensure_ascii=False).encode()) > MAX_BLOCK_BYTES:
        raise ValueError("Page exceeds the 4 MB block limit")
    ids: set[str] = set()

    def inline(items, depth=0):
        if depth > 16:
            raise ValueError("Inline nesting exceeds 16 levels")
        if isinstance(items, str):
            return
        if not isinstance(items, list):
            raise ValueError("Invalid inline content")
        for item in items:
            if not isinstance(item, dict):
                raise ValueError("Invalid inline content")
            kind = item.get("type")
            if kind == "text":
                if not isinstance(item.get("text"), str) or not isinstance(
                    item.get("styles", {}), dict
                ):
                    raise ValueError("Invalid styled text")
            elif kind == "link":
                if not safe_link(item.get("href")):
                    raise ValueError("Unsupported link URL")
                inline(item.get("content", []), depth + 1)
            elif kind in {"pageLink", "inlineMath", "noteDate"}:
                props = item.get("props", {})
                if not isinstance(props, dict) or any(
                    not isinstance(v, str) for v in props.values()
                ):
                    raise ValueError("Invalid inline properties")
                if kind == "pageLink" and not re.fullmatch(
                    r"[0-9a-f]{8,32}", props.get("pageId", "")
                ):
                    raise ValueError("Invalid linked page ID")
            else:
                raise ValueError("Unsupported inline content")

    def visit(items, depth=0, parent=None):
        if not isinstance(items, list) or depth > 16:
            raise ValueError("Invalid block tree or nesting exceeds 16 levels")
        for block in items:
            if not isinstance(block, dict):
                raise ValueError("Each block must be an object")
            bid = block.get("id")
            if not isinstance(bid, str) or not re.fullmatch(r"[\w-]{1,128}", bid) or bid in ids:
                raise ValueError("Blocks require unique, valid IDs")
            ids.add(bid)
            if len(ids) > 10000:
                raise ValueError("Page exceeds 10000 blocks")
            supported = {
                "paragraph",
                "heading",
                "bulletListItem",
                "numberedListItem",
                "checkListItem",
                "toggleListItem",
                "quote",
                "codeBlock",
                "table",
                "image",
                "video",
                "audio",
                "file",
                "divider",
                "math",
                "clip",
                "learning",
                "noteUpload",
                "callout",
                "toggleHeading",
                "noteColumn",
                "noteColumns",
                "tableOfContents",
                "webCard",
                "htmlEmbed",
                "taskView",
            }
            if block.get("type") not in supported:
                raise ValueError("Unsupported block type")
            if not isinstance(block.get("type"), str) or not isinstance(
                block.get("props", {}), dict
            ):
                raise ValueError("Invalid block type or properties")
            if block["type"] == "noteColumn" and parent != "noteColumns":
                raise ValueError("Column blocks must belong to a columns layout")
            props = block.get("props", {})
            if any(not isinstance(v, (str, int, float, bool)) for v in props.values()):
                raise ValueError("Block properties must be scalar values")
            for name in ("url", "sourceUrl"):
                if name in props and not safe_link(props[name]):
                    raise ValueError("Unsupported block URL")
            if block["type"] in {"heading", "toggleHeading"} and props.get("level", 1) not in {
                1,
                2,
                3,
                4,
                5,
                6,
            }:
                raise ValueError("Heading level must be between 1 and 6")
            if block["type"] == "learning":
                try:
                    data = json.loads(props.get("data", "{}"))
                    if not isinstance(data, dict):
                        raise ValueError()
                except (ValueError, TypeError):
                    raise ValueError("Learning data must be a JSON object") from None
                for name in (
                    "questions",
                    "cards",
                    "events",
                    "nodes",
                    "edges",
                    "workspace_items",
                    "artifacts",
                ):
                    if name in data and (
                        not isinstance(data[name], list)
                        or any(not isinstance(row, dict) for row in data[name])
                    ):
                        raise ValueError(f"Learning {name} must be a list of objects")
            if block["type"] in LEAF_BLOCK_TYPES:
                # Models often echo the kind as text content ("timeline"); a
                # block without inline content cannot hold it, and the editor
                # refuses the whole page if it is kept.
                block.pop("content", None)
            content = block.get("content", [])
            if block["type"] == "table":
                if not isinstance(content, dict) or not isinstance(content.get("rows"), list):
                    raise ValueError("Invalid table")
                for row in content["rows"]:
                    if not isinstance(row, dict) or not isinstance(row.get("cells"), list):
                        raise ValueError("Invalid table row")
                    for cell in row["cells"]:
                        inline(cell.get("content", []) if isinstance(cell, dict) else cell)
            elif block["type"] not in LEAF_BLOCK_TYPES:
                inline(content)
            if block["type"] == "noteColumns":
                columns = block.get("children", [])
                if (
                    not isinstance(columns, list)
                    or not 2 <= len(columns) <= 5
                    or any(c.get("type") != "noteColumn" for c in columns if isinstance(c, dict))
                ):
                    raise ValueError("Columns require between 2 and 5 column blocks")
            visit(block.get("children", []), depth + 1, block["type"])

    visit(blocks)
    return blocks


def inline_markdown(content: Any) -> str:
    if isinstance(content, str):
        return content
    if not isinstance(content, list):
        return ""
    result = []
    for item in content:
        if not isinstance(item, dict):
            continue
        text = (
            str(item.get("text", ""))
            if item.get("type") == "text"
            else inline_markdown(item.get("content"))
        )
        if item.get("type") in {"math", "inlineMath"}:
            text = "$" + str(item.get("props", {}).get("formula", "")) + "$"
        if item.get("type") == "pageLink":
            props = item.get("props", {})
            text = f"[{props.get('title', 'Page')}](/co-writer/{props.get('pageId', '')})"
        if item.get("type") == "noteDate":
            text = str(item.get("props", {}).get("date", ""))
        styles = item.get("styles") or {}
        for key, marker in (("code", "`"), ("bold", "**"), ("italic", "*"), ("strike", "~~")):
            if styles.get(key):
                text = marker + text + marker
        if item.get("type") == "link":
            text = f"[{text}]({item.get('href', '')})"
        result.append(text)
    return "".join(result)


def blocks_to_markdown(blocks: list[dict[str, Any]], depth: int = 0) -> str:
    parts = []
    for block in blocks:
        kind, props = block.get("type"), block.get("props") or {}
        text = inline_markdown(block.get("content"))
        if kind in {"heading", "toggleHeading"}:
            text = "#" * max(1, min(6, int(props.get("level", 1)))) + " " + text
        elif kind in ("bulletListItem", "numberedListItem", "checkListItem", "toggleListItem"):
            prefix = {
                "bulletListItem": "- ",
                "numberedListItem": "1. ",
                "toggleListItem": "- ",
                "checkListItem": "- [x] " if props.get("checked") else "- [ ] ",
            }[kind]
            text = prefix + text
        elif kind in {"quote", "callout"}:
            text = "\n".join("> " + line for line in text.splitlines())
        elif kind == "codeBlock":
            fence = "`" * max(3, max((len(m[0]) + 1 for m in re.finditer(r"`+", text)), default=3))
            text = f"{fence}{props.get('language', '')}\n{text}\n{fence}"
        elif kind in ("image", "video", "audio", "file"):
            text = f"{'!' if kind == 'image' else ''}[{props.get('caption') or props.get('name', kind)}]({props.get('url', '')})"
        elif kind == "table":
            rows = (block.get("content") or {}).get("rows", [])
            lines = [
                "| "
                + " | ".join(
                    inline_markdown(c.get("content") if isinstance(c, dict) else c)
                    .replace("|", "\\|")
                    .replace("\n", "<br>")
                    for c in row.get("cells", [])
                )
                + " |"
                for row in rows
            ]
            if lines:
                lines.insert(1, "| " + " | ".join("---" for _ in rows[0].get("cells", [])) + " |")
            text = "\n".join(lines)
        elif kind == "webCard":
            text = f"[{props.get('title') or props.get('url', '')}]({props.get('url', '')})\n\n{props.get('description', '')}"
        elif kind == "htmlEmbed":
            source = str(props.get("source", ""))
            fence = "`" * max(
                3, max((len(m[0]) + 1 for m in re.finditer(r"`+", source)), default=3)
            )
            text = f"{fence}html\n{source}\n{fence}"
        elif kind == "taskView":
            text = "[Workspace tasks](/kanban)"
        elif kind == "tableOfContents":
            text = ""
        elif kind == "divider":
            text = "---"
        elif kind == "math":
            text = "$$\n" + str(props.get("formula", "")) + "\n$$"
        elif kind in ("learning", "clip"):
            text = str(props.get("markdown") or props.get("prompt") or props.get("title") or "")
            if kind == "learning":
                data = json.loads(props.get("data", "{}"))
                if props.get("kind") == "flashcards" and data.get("cards"):
                    text = "\n\n".join(
                        f"**{c.get('front', '')}**\n\n{c.get('back', '')}" for c in data["cards"]
                    )
                if props.get("kind") == "quiz" and data.get("questions"):
                    questions = []
                    for q in data["questions"]:
                        options = q.get("options") or {}
                        option_text = (
                            "\n".join(f"- {k}: {v}" for k, v in options.items())
                            if isinstance(options, dict)
                            else ""
                        )
                        questions.append(
                            f"{q.get('question', '')}\n\n{option_text}\n\nAnswer: {q.get('correct_answer', '')}\n\n{q.get('explanation', '')}"
                        )
                    text = "\n\n".join(questions)
                if props.get("kind") == "timeline" and data.get("events"):
                    text = "\n\n".join(
                        f"{e.get('date', '')} — {e.get('title', '')}\n{e.get('description', '')}"
                        for e in data["events"]
                    )
                for item in data.get("workspace_items", []) or data.get("artifacts", []):
                    if safe_link(item.get("url", "")) and item.get("url"):
                        text += f"\n\n[{item.get('filename') or item.get('title') or 'Media'}]({item['url']})"
            if props.get("sourceUrl"):
                text += f"\n\n[Source]({props['sourceUrl']})"
        if text:
            parts.append("\n".join("  " * depth + line for line in text.splitlines()))
        if block.get("children"):
            parts.append(
                blocks_to_markdown(
                    block["children"], depth if kind in {"noteColumns", "noteColumn"} else depth + 1
                )
            )
    return "\n\n".join(parts)


def walk_blocks(blocks):
    for block in blocks or []:
        yield block
        yield from walk_blocks(block.get("children", []))
