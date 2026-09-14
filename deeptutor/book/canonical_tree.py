"""canonical KP tree auto-cache (P0).

doc_intel (B2-a) stamps each parsed document's 目级 KP tree into the KB
docstore as ``doc_tree`` metadata; import-from-book (B2-b) reads the cached
canonical tree from the book manifest. This module is the missing write
half: when a parsed textbook is canonicalized into a Book, the doc_intel
tree from its source knowledge bases is cached into
``manifest.metadata.canonical_kp_tree`` so the import path takes the 目级
modules instead of the chapter-level mechanical fallback.

Everything here is best-effort: a missing KB, a degraded (downgraded tier)
doc_tree, or an unreadable manifest must never block canonicalization — the
caller only gets ``False`` and a warning log.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from .storage import BookStorage, get_book_storage

logger = logging.getLogger(__name__)

#: The only node type that matters downstream: import-from-book groups
#: ``type: "mu"`` nodes under their nearest structural ancestor.
MU_TYPE = "mu"

#: Bridge keys the canonical tree carries — the doc_intel slim-tree shape.
_CANONICAL_KEYS = ("title", "level", "struct_path", "node_id", "type", "children")


def _canonical_copy(node: Any) -> dict[str, Any]:
    """Copy a doc_tree node down to the bridge keys, recursing into children."""
    kept: dict[str, Any] = {
        key: node[key] for key in _CANONICAL_KEYS if node.get(key) not in (None, "")
    }
    children = node.get("children")
    if isinstance(children, list):
        kept["children"] = [
            _canonical_copy(child) for child in children if isinstance(child, dict)
        ]
    return kept


def _tree_has_mu(node: dict[str, Any]) -> bool:
    if node.get("type") == MU_TYPE:
        return True
    return any(_tree_has_mu(child) for child in node.get("children") or [])


def _is_valid_root(node: Any) -> bool:
    """Full-shape gate: title present, children well-formed, and at least one
    mu node carrying its textbook-tree bridge (node_id + struct_path).

    Degraded doc_tree tiers (目名压缩列表 / chapter-title list) fail this by
    construction — caching them would shadow nothing useful and their mu
    names have no node ids to bridge with.
    """

    def valid(node: Any) -> bool:
        if not isinstance(node, dict) or not isinstance(node.get("title"), str):
            return False
        # mu leaves legitimately carry no children key (slim doc_tree shape).
        children = node.get("children") or []
        if not isinstance(children, list) or any(
            not isinstance(child, dict) for child in children
        ):
            return False
        return all(valid(child) for child in children)

    if not valid(node) or not _tree_has_mu(node):
        return False

    def mus_have_bridges(node: dict[str, Any]) -> bool:
        if node.get("type") == MU_TYPE:
            if not node.get("node_id") or not node.get("struct_path"):
                return False
        return all(mus_have_bridges(child) for child in node.get("children") or [])

    return mus_have_bridges(node)


def canonical_tree_from_doc_trees(roots: list[dict[str, Any]] | None) -> dict[str, Any] | None:
    """Merge the KB's doc_intel trees into one canonical KP tree, or ``None``.

    A single valid root is used verbatim (slimmed to the bridge keys); several
    valid roots — one per parsed document — are merged under a synthetic
    root, which import-from-book walks the same way.
    """
    valid = [
        _canonical_copy(root)
        for root in (roots or [])
        if isinstance(root, dict) and _is_valid_root(root)
    ]
    if not valid:
        return None
    if len(valid) == 1:
        return valid[0]
    return {"title": "", "children": valid}


def load_kb_doc_trees(kb_names: list[str] | None) -> list[dict[str, Any]]:
    """Aggregate full-shape ``doc_tree`` roots from the KBs' LlamaIndex docstores.

    Mirrors the reader in the textbook-tree API (and the ingest pipeline's
    loader) without importing the god router: one KB failing to resolve or
    having no docstore contributes nothing rather than raising.
    """
    trees: list[dict[str, Any]] = []
    seen_doc_ids: set[str] = set()
    for kb_name in kb_names or []:
        try:
            trees.extend(_doc_trees_for_kb(str(kb_name), seen_doc_ids))
        except Exception:  # noqa: BLE001 — one unreadable KB must not stop the run
            logger.warning("canonical KP tree: docstore unreadable for KB %s", kb_name)
    return trees


def _doc_trees_for_kb(kb_name: str, seen_doc_ids: set[str]) -> list[dict[str, Any]]:
    from deeptutor.multi_user.knowledge_access import manager_for_resource, resolve_kb

    resource = resolve_kb(kb_name)
    manager = manager_for_resource(resource)
    try:
        storage_dir = manager.get_rag_storage_path(resource.name)
    except ValueError:
        return []
    if not (Path(storage_dir) / "docstore.json").is_file():
        return []

    from llama_index.core.storage.docstore import SimpleDocumentStore

    docstore = SimpleDocumentStore.from_persist_dir(str(storage_dir))
    trees: list[dict[str, Any]] = []
    for node in list(docstore.docs.values()):
        metadata = getattr(node, "metadata", {}) or {}
        raw_tree = metadata.get("doc_tree")
        if not raw_tree:
            continue
        if isinstance(raw_tree, str):
            try:
                tree = json.loads(raw_tree)
            except (TypeError, ValueError):
                continue
        elif isinstance(raw_tree, dict):
            tree = raw_tree
        else:
            continue
        if not isinstance(tree, dict):
            continue
        # Degraded tiers store no children list at all — the full-shape gate
        # in canonical_tree_from_doc_trees rejects them, so drop them here.
        if not isinstance(tree.get("children"), list):
            continue
        doc_id = str(
            getattr(node, "ref_doc_id", None)
            or metadata.get("doc_id")
            or getattr(node, "node_id", "")
        )
        if doc_id in seen_doc_ids:
            continue
        seen_doc_ids.add(doc_id)
        trees.append(tree)
    return trees


def _content_list_from_layout(layout: dict[str, Any]) -> list[dict[str, Any]]:
    """Flatten a MinerU layout dict into content_list-style blocks.

    ``doc_intel.build_tree`` consumes the MinerU v1 content_list shape —
    blocks with ``type`` / ``text`` / ``text_level``. The layout dict a
    canonicalize request carries instead nests that text one level down
    (``pdf_info[].para_blocks`` with ``lines[].spans[].content``, heading
    level in ``level`` rather than ``text_level``). This re-flattens it so
    the inline tree rebuild (P7【1】) can feed ``doc_intel.enrich`` directly
    with what the canonicalize request already has in hand.
    """

    from deeptutor.textbook_struct.chapter_rebuild import block_text

    blocks: list[dict[str, Any]] = []
    for page in layout.get("pdf_info") or []:
        if not isinstance(page, dict):
            continue
        for para in page.get("para_blocks") or []:
            if not isinstance(para, dict):
                continue
            # Group blocks (figure captions etc.) wrap their children in
            # ``blocks`` — walk one level down, the shape MinerU emits.
            children = (
                para.get("blocks") if isinstance(para.get("blocks"), list) else [para]
            )
            for block in children:
                if not isinstance(block, dict) or block.get("type") == "image":
                    continue
                text = block_text(block)
                if not text:
                    continue
                item: dict[str, Any] = {
                    "type": "title" if block.get("type") == "title" else "text",
                    "text": text,
                }
                level = block.get("level") or block.get("text_level")
                if isinstance(level, (int, float)) and int(level) > 0:
                    item["text_level"] = int(level)
                blocks.append(item)
    return blocks


def rebuild_canonical_tree_from_layout(
    book_id: str,
    layout: dict[str, Any],
    *,
    filename: str = "",
    markdown: str = "",
    storage: BookStorage | None = None,
) -> bool:
    """P7【1】inline canonical KP tree rebuild from the canonicalize layout.

    The P0 auto-cache reads the KB docstore's ``doc_tree`` metadata, which a
    大部头 downgraded-tier doc_tree can fail to produce. The canonicalize
    request itself carries the MinerU layout, so this productizes the old
    p1-cache-tree patch: rebuild the doc_intel tree from the layout's
    ``para_blocks`` right here in the request path and cache it.

    Best-effort like the P0 hook: returns ``False`` — never raises — when the
    layout yields no usable tree, so canonicalization is never interrupted.
    """
    try:
        blocks = _content_list_from_layout(layout)
        if not blocks:
            logger.warning("canonical KP tree inline rebuild: no para_blocks for %s", book_id)
            return False
        from deeptutor.knowledge.doc_intel.enrich import enrich

        result = enrich(
            blocks,
            markdown=markdown,
            filename=filename or f"{book_id}.pdf",
            doc_id="",
        )
        tree = result.get("tree") if isinstance(result, dict) else None
        # The full-shape gate rejects degraded trees — caching one would
        # shadow a future good rebuild the same way a degraded doc_tree would.
        slim = canonical_tree_from_doc_trees([tree] if isinstance(tree, dict) else None)
        if slim is None:
            logger.warning("canonical KP tree inline rebuild: no usable tree for %s", book_id)
            return False
        store = storage or get_book_storage()
        return store.save_canonical_kp_tree(book_id, slim)
    except Exception:  # noqa: BLE001 — inline rebuild is best-effort, never fatal
        logger.warning("canonical KP tree inline rebuild failed for %s", book_id, exc_info=True)
        return False


def cache_canonical_tree_for_book(
    book_id: str, kb_names: list[str] | None, *, storage: BookStorage | None = None
) -> bool:
    """Cache the source KBs' canonical KP tree into the book manifest.

    Best-effort by contract: returns ``False`` — after a warning, never an
    exception — when no tree is derivable or no manifest exists, so the
    canonicalization pipeline is never interrupted. Re-running with the same
    inputs overwrites the same value (idempotent).
    """
    try:
        store = storage or get_book_storage()
        tree = canonical_tree_from_doc_trees(load_kb_doc_trees(kb_names))
        if tree is None:
            logger.warning(
                "canonical KP tree auto-cache: no usable doc_tree for %s (KBs: %s)",
                book_id,
                kb_names,
            )
            return False
        return store.save_canonical_kp_tree(book_id, tree)
    except Exception:  # noqa: BLE001 — cache is best-effort, never fatal
        logger.warning("canonical KP tree auto-cache failed for %s", book_id, exc_info=True)
        return False
