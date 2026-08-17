"""Normalize real PageIndex page reads into DeepTutor source rows."""

from __future__ import annotations

import json
from typing import Any


def pageindex_sources_from_text(
    text: str,
    *,
    provider: str,
    kb_name: str = "",
    doc_ids: dict[str, str] | None = None,
) -> list[dict[str, Any]]:
    try:
        payload = json.loads(text)
    except (TypeError, ValueError):
        return []
    if not isinstance(payload, dict) or payload.get("success") is False or payload.get("errorCode"):
        return []
    document_name = str(payload.get("doc_name") or "").strip()
    content = payload.get("content")
    if not document_name or not isinstance(content, list):
        return []

    rows: list[dict[str, Any]] = []
    seen: set[tuple[str, str]] = set()
    for item in content:
        if not isinstance(item, dict) or item.get("page") in (None, ""):
            continue
        page = item["page"]
        block_id = str(item.get("block_id") or "").strip()
        key = (str(page), block_id)
        if key in seen:
            continue
        seen.add(key)
        row: dict[str, Any] = {
            "type": "pageindex",
            "provider": provider,
            "document_name": document_name,
            "source": document_name,
            "page": page,
        }
        if kb_name:
            row["kb_name"] = kb_name
        if doc_ids and document_name in doc_ids:
            row["doc_id"] = doc_ids[document_name]
        if block_id:
            row["block_id"] = block_id
        rows.append(row)
    return rows


__all__ = ["pageindex_sources_from_text"]
