"""Durable, reviewable edits with per-block conflict detection."""

from __future__ import annotations

import copy
import time
import uuid

from deeptutor.co_writer.storage import RevisionConflict, _atomic_write_json, _read_json
from deeptutor.notes.blocks import blocks_to_markdown, validate_blocks, walk_blocks

_UNSET = object()


def list_proposals(storage, doc_id):
    return _read_json(storage.doc_root(doc_id) / "suggestions.json") or []


def review_anchors(blocks, block_id):
    """Keep nearby, stable anchors if the reviewed block is later removed."""
    for index, block in enumerate(blocks):
        nested = None
        if block["id"] != block_id:
            nested = review_anchors(block.get("children", []), block_id)
            if nested is None:
                continue
        neighbors = [
            *({"id": b["id"], "side": "before"} for b in blocks[index + 1 :]),
            *({"id": b["id"], "side": "after"} for b in reversed(blocks[:index])),
        ]
        if block["id"] == block_id:
            return neighbors
        if nested is not None:
            return nested + [{"id": block["id"], "side": "after"}] + neighbors
    return None


def refresh_review_anchors(storage, doc_id, blocks, previous_blocks):
    proposals = list_proposals(storage, doc_id)
    changed = False
    for proposal in proposals:
        if proposal["status"] != "pending" or not proposal["block_id"]:
            continue
        anchors = review_anchors(blocks, proposal["block_id"])
        if anchors is None:
            anchors = review_anchors(previous_blocks, proposal["block_id"])
        if anchors is not None and anchors != proposal.get("anchors"):
            proposal["anchors"] = anchors
            changed = True
    if changed:
        _atomic_write_json(storage.doc_root(doc_id) / "suggestions.json", proposals)


def preserves_children(operation, original, blocks):
    """A text-only parent edit must not implicitly delete its subtree."""
    return bool(
        operation == "replace"
        and original
        and original.get("children")
        and (blocks is None or (blocks and not blocks[0].get("children")))
    )


def propose(
    storage,
    doc_id,
    *,
    operation,
    block_id="",
    markdown="",
    explanation="",
    blocks=None,
    expected_original=_UNSET,
    workspace_id="",
    source_turn_id="",
):
    if operation not in {"insert", "replace", "delete", "comment"}:
        raise ValueError("Unknown note operation")
    if len(markdown) > 200000 or len(explanation) > 10000:
        raise ValueError("Suggestion is too long")
    from deeptutor.notes.resources import normalize_note_resources

    with storage.locked():
        doc = storage.load_document(doc_id)
        if doc is None:
            raise ValueError("Page not found")
        if doc.blocks is None:
            raise ValueError("Open this page in the block editor before suggesting changes")
        proposals = list_proposals(storage, doc_id)
        if source_turn_id:
            existing = next(
                (
                    p
                    for p in proposals
                    if p.get("source_turn_id") == source_turn_id and p["block_id"] == block_id
                ),
                None,
            )
            if existing is not None:
                return existing
        target = next((b for b in walk_blocks(doc.blocks) if b["id"] == block_id), None)
        if (block_id or operation in {"replace", "delete"}) and target is None:
            raise ValueError("Block no longer exists; read the page again")
        if expected_original is not _UNSET and not same_block(target, expected_original):
            raise RevisionConflict(
                "The block changed after it was read. Read it again before suggesting an edit."
            )
        if operation == "comment" and not (explanation.strip() or markdown.strip()):
            raise ValueError("A comment needs feedback text")
        markdown, blocks = normalize_note_resources(markdown, blocks, workspace_id=workspace_id)
        if blocks is not None:
            validate_blocks(blocks)
        proposal = dict(
            id=uuid.uuid4().hex,
            operation=operation,
            block_id=block_id,
            markdown=markdown,
            blocks=blocks,
            explanation=explanation,
            original=copy.deepcopy(target),
            preserve_children=preserves_children(operation, target, blocks),
            anchors=review_anchors(doc.blocks, block_id) or [],
            status="pending",
            source_turn_id=source_turn_id,
            created_at=time.time(),
        )
        if sum(p["status"] == "pending" for p in proposals) >= 100:
            raise ValueError("Review pending suggestions before creating more")
        proposals.append(proposal)
        _atomic_write_json(storage.doc_root(doc_id) / "suggestions.json", proposals[-500:])
        return proposal


def review(storage, doc_id, proposal_id, *, accept, blocks=None):
    with storage.locked():
        doc = storage.load_document(doc_id)
        if doc is None:
            raise ValueError("Page not found")
        proposals = list_proposals(storage, doc_id)
        proposal = next((p for p in proposals if p["id"] == proposal_id), None)
        if proposal is None:
            raise ValueError("Suggestion not found")
        if proposal["status"] != "pending":
            return doc
        if (
            accept
            and proposal["operation"] != "comment"
            and proposal_id not in doc.applied_suggestion_ids
        ):
            current = next(
                (b for b in walk_blocks(doc.blocks) if b["id"] == proposal["block_id"]), None
            )
            keep_children = preserves_children(
                proposal["operation"], proposal["original"], proposal.get("blocks")
            )
            before, after = proposal["original"], current
            if keep_children:
                before = {**before, "children": []} if before else None
                after = {**after, "children": []} if after else None
            if not same_block(after, before):
                raise RevisionConflict(
                    "The suggested block changed. Ask Dito to revise the suggestion."
                )
            replacement = blocks if blocks is not None else proposal.get("blocks")
            if proposal["operation"] != "delete" and replacement is None:
                raise ValueError("Convert the suggestion to blocks before accepting")
            replacement = copy.deepcopy(replacement or [])
            if keep_children:
                if not replacement:
                    raise ValueError("A replacement must contain at least one block")
                # Compose independent parent/child edits in either review order.
                replacement[0]["children"] = copy.deepcopy(current.get("children", []))
            if proposal["operation"] == "replace" and replacement:
                # Keep the anchor stable for links and other reviews at this position.
                replacement[0]["id"] = proposal["block_id"]

            def apply(items):
                for index, block in enumerate(items):
                    if block["id"] == proposal["block_id"]:
                        if proposal["operation"] == "insert":
                            items[index + 1 : index + 1] = replacement
                        else:
                            items[index : index + 1] = replacement
                        return True
                    if apply(block.get("children", [])):
                        return True
                return False

            if proposal["block_id"]:
                apply(doc.blocks)
            else:
                doc.blocks.extend(replacement)
            validate_blocks(doc.blocks)
            doc.content = blocks_to_markdown(doc.blocks)
            doc.revision += 1
            doc.updated_at = time.time()
            doc.applied_suggestion_ids = (doc.applied_suggestion_ids + [proposal_id])[-1000:]
            storage._write(doc)
        proposal["status"] = "accepted" if accept else "dismissed"
        _atomic_write_json(storage.doc_root(doc_id) / "suggestions.json", proposals)
        return doc


def same_block(left, right):
    """Ignore editor-added defaults while still rejecting real content/format edits."""

    def canonical(block):
        if block is None:
            return None
        result = copy.deepcopy(block)
        props = result.setdefault("props", {})
        for key, default in (
            ("backgroundColor", "default"),
            ("textColor", "default"),
            ("textAlignment", "left"),
        ):
            if props.get(key) == default:
                props.pop(key)
        children = result.get("children") or []
        result["children"] = [canonical(child) for child in children]
        if result.get("content") == []:
            result.pop("content")
        return result

    return canonical(left) == canonical(right)
