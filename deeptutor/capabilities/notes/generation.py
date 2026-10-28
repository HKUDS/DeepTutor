"""A standalone action's result, turned into the learning block it was run for.

When a learning block's "Generate" runs a pipeline that cannot call
``note_suggest`` (Research, Quiz, Visualize, Podcast), its result comes back
here and lands on the page as a replace suggestion on that block — reviewed
like any other edit. It happens on the server so a closed side panel, a
switched conversation or a closed tab cannot lose it.
"""

from __future__ import annotations

import json
import logging
from typing import Any
import uuid

from deeptutor.co_writer.storage import get_co_writer_storage
from deeptutor.notes.blocks import walk_blocks

logger = logging.getLogger(__name__)


def result_learning_block(result: dict[str, Any], response: str = "") -> dict | None:
    """The learning block a pipeline's result renders as, or None for plain text."""
    kind = ""
    payload: dict[str, Any] = result
    summary = result.get("summary") if isinstance(result.get("summary"), dict) else {}
    if result.get("outline_preview") and isinstance(result.get("sub_topics"), list):
        kind = "research"
    elif isinstance(summary.get("results"), list):
        kind = "quiz"
        payload = {
            "questions": [
                row["qa_pair"]
                for row in summary["results"]
                if isinstance(row, dict) and isinstance(row.get("qa_pair"), dict)
            ]
        }
    elif result.get("renderer") and result.get("payload"):
        kind = "visualization"
    elif isinstance(result.get("artifacts"), list) and result["artifacts"]:
        kind = "animation"
    elif isinstance(result.get("workspace_items"), list) and result["workspace_items"]:
        kind = "media"
    if not kind:
        return None
    questions = payload.get("questions") if kind == "quiz" else None
    if questions is not None:
        markdown = "\n\n".join(
            f"{i + 1}. {q.get('question') or ''}\n\n{q.get('explanation') or ''}"
            for i, q in enumerate(questions)
        )
    else:
        markdown = response or str(result.get("response") or "")
    return {
        "id": uuid.uuid4().hex,
        "type": "learning",
        "props": {
            "kind": kind,
            "prompt": "",
            "markdown": markdown,
            "data": json.dumps(payload, ensure_ascii=False, default=str),
            "sourceUrl": "",
        },
        "children": [],
    }


def _json(value: Any) -> dict:
    try:
        parsed = json.loads(str(value or "{}"))
    except ValueError:
        return {}
    return parsed if isinstance(parsed, dict) else {}


def propose_generated_block(
    *,
    note_document_id: str,
    generation: dict,
    events: list[dict],
    response: str,
    turn_id: str,
    explanation: str,
) -> None:
    """File the turn's result as a replace suggestion on its learning block."""
    from deeptutor.notes.proposals import propose

    block_id = str(generation.get("block_id") or "")
    if not note_document_id or not block_id:
        return
    result_event = next((e for e in reversed(events) if e.get("type") == "result"), None)
    result = dict((result_event or {}).get("metadata") or {})
    response = str(
        result.get("response")
        or result.get("report")
        or (result_event or {}).get("content")
        or response
        or ""
    )
    block = result_learning_block(result, response) if result_event else None
    if not (block or response.strip()):
        return
    storage = get_co_writer_storage()
    doc = storage.load_document(note_document_id)
    target = next(
        (b for b in walk_blocks((doc.blocks if doc else None) or []) if b["id"] == block_id), None
    )
    if target is None:
        return
    blocks = None
    if block:
        props = target.get("props") or {}
        data = _json(block["props"]["data"])
        generation_settings = _json(props.get("data")).get("generation")
        if generation_settings is not None:
            data["generation"] = generation_settings
        blocks = [
            {
                **block,
                "id": block_id,
                "props": {
                    **block["props"],
                    "kind": props.get("kind") or block["props"]["kind"],
                    "prompt": props.get("prompt") or "",
                    "data": json.dumps(data, ensure_ascii=False, default=str),
                },
            }
        ]
    try:
        propose(
            storage,
            note_document_id,
            operation="replace",
            block_id=block_id,
            source_turn_id=turn_id,
            markdown=response,
            blocks=blocks,
            explanation=explanation,
        )
    except ValueError:
        logger.warning("Could not file the generated block for %s", block_id, exc_info=True)
