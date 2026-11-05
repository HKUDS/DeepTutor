"""Persistent review scheduling for flashcards embedded in notebook pages."""

import hashlib
import json
import time

from deeptutor.co_writer.storage import _atomic_write_json, _read_json
from deeptutor.notes.blocks import walk_blocks


def page_cards(doc):
    for block in walk_blocks(doc.blocks):
        props = block.get("props", {})
        if block.get("type") != "learning" or props.get("kind") != "flashcards":
            continue
        try:
            cards = json.loads(props.get("data", "{}")).get("cards", [])
        except (ValueError, AttributeError, TypeError):
            continue
        if not isinstance(cards, list):
            continue
        for card in cards:
            if not isinstance(card, dict) or not card.get("front"):
                continue
            key = (
                block["id"]
                + ":"
                + hashlib.sha256(json.dumps(card, sort_keys=True).encode()).hexdigest()[:16]
            )
            yield dict(
                page_id=doc.id,
                page_title=doc.title,
                block_id=block["id"],
                card_id=key,
                front=str(card.get("front", "")),
                back=str(card.get("back", "")),
            )


def due_cards(storage, now=None):
    now = time.time() if now is None else now
    result = []
    for summary in storage.list_documents():
        doc = storage.load_document(summary.id)
        if doc is None:
            continue
        progress = _read_json(storage.doc_root(doc.id) / "review.json") or {}
        for card in page_cards(doc):
            due = progress.get(card["card_id"], {}).get("due_at", 0)
            if due <= now:
                result.append({**card, "due_at": due})
    return sorted(result, key=lambda card: card["due_at"])[:200]


def grade_card(storage, page_id, card_id, remembered):
    with storage.locked():
        doc = storage.load_document(page_id)
        if doc is None:
            raise ValueError("Page not found")
        valid = {card["card_id"] for card in page_cards(doc)}
        if card_id not in valid:
            raise ValueError("This flashcard has changed or no longer exists")
        path = storage.doc_root(page_id) / "review.json"
        progress = {key: value for key, value in (_read_json(path) or {}).items() if key in valid}
        previous = progress.get(card_id, {})
        interval = min(180, max(1, previous.get("interval_days", 0) * 2 + 1)) if remembered else 0
        result = {
            "interval_days": interval,
            "due_at": time.time() + (interval * 86400 if remembered else 600),
            "reviewed_at": time.time(),
        }
        progress[card_id] = result
        _atomic_write_json(path, progress)
        return result
