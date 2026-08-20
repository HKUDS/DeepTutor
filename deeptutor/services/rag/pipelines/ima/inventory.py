"""What a connected IMA library actually contains — its document inventory.

Retrieval answers "what does the material say"; it cannot answer "what is in
here" or "did I add X". For an indexed KB the answer is a directory walk. For an
IMA library the equivalent is ``get_knowledge_list``, which browses the library's
folder tree, and this module turns that into the same flat list of relative paths
:mod:`deeptutor.knowledge.manifest` produces for a local KB — so "list what's in
this knowledge base" works the same whether the documents sit on disk or in IMA.

Two properties make it usable from the manifest layer:

* **Blocking.** The manifest is deliberately synchronous (it is called from a
  worker thread, and from the chat pipeline's prompt assembly), so the traversal
  uses the transport's blocking flavour instead of forcing that whole path async.
* **Cached.** A manifest is rebuilt on every turn's system prompt; without a
  cache that would be a fresh IMA round-trip per turn. Entries expire after
  :data:`CACHE_TTL_SECONDS`, which is short enough that a document added in IMA
  shows up almost immediately and long enough that a burst of turns costs one
  traversal.

The traversal is bounded on purpose (:data:`MAX_REQUESTS`): a huge library must
not stall prompt assembly. When the budget runs out the result is marked
incomplete and the count it reports is a lower bound, never a confident total.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
import logging
import threading
import time
from typing import Any, Mapping, Optional

from .config import ImaNotConfiguredError, resolve_kb_config

logger = logging.getLogger(__name__)

# Requests one traversal may spend. With IMA's 50-item pages this covers the
# first few hundred documents, including a level or two of folders.
MAX_REQUESTS = 8

PAGE_SIZE = 50

CACHE_TTL_SECONDS = 60.0

# Failures are cached too, briefly. Without this, an unreachable library would be
# retried on every single turn's prompt assembly — paying the timeout each time.
FAILURE_TTL_SECONDS = 30.0

# This runs while a turn's system prompt is being assembled, so it must never be
# what makes a turn feel slow: a stalled IMA gives up quickly rather than holding
# the default 30 s.
TIMEOUT_SECONDS = 6.0

# Folder nesting to descend. Deep trees are truncated rather than walked
# exhaustively — the inventory is an overview, not a mirror.
MAX_DEPTH = 3


@dataclass(frozen=True, slots=True)
class ImaInventory:
    """A connected IMA library's documents, as folder-relative paths."""

    documents: tuple[str, ...] = ()
    complete: bool = True
    """False when the request budget ran out — ``documents`` is then a prefix."""


# key -> (expires_at, inventory or None). ``None`` is a cached *failure*.
_CACHE: dict[str, tuple[float, Optional[ImaInventory]]] = {}
_CACHE_LOCK = threading.Lock()

# Distinguishes "nothing cached" from "a cached failure", which is itself a
# ``None`` result worth honouring.
_MISS = object()


def read_inventory(
    entry: Mapping[str, Any],
    *,
    client_factory=None,
    use_cache: bool = True,
) -> Optional[ImaInventory]:
    """Return the inventory of the IMA library *entry* points at.

    ``None`` means "cannot be determined" (missing credentials, or IMA
    unreachable) — distinct from an empty library, which is an empty inventory.
    ``client_factory`` (config → client) is the test seam.
    """
    try:
        config = resolve_kb_config(dict(entry))
    except ImaNotConfiguredError:
        return None

    cache_key = f"{config.client_id}:{config.knowledge_base_id}"
    if use_cache:
        cached = _cached(cache_key)
        if cached is not _MISS:
            return cached  # type: ignore[return-value]

    if client_factory is not None:
        client = client_factory(config)
    else:
        from .client import ImaClient

        client = ImaClient(config, timeout=TIMEOUT_SECONDS)

    try:
        inventory = _traverse(client, config.knowledge_base_id)
    except Exception as exc:
        logger.warning(
            "Could not read the IMA document inventory for '%s' (%s)",
            config.knowledge_base_id,
            type(exc).__name__,
        )
        if use_cache:
            _store(cache_key, None, ttl=FAILURE_TTL_SECONDS)
        return None

    if use_cache:
        _store(cache_key, inventory, ttl=CACHE_TTL_SECONDS)
    return inventory


def clear_cache() -> None:
    """Drop every cached inventory (used by tests and after a KB is re-bound)."""
    with _CACHE_LOCK:
        _CACHE.clear()


def _traverse(client, root_id: str) -> ImaInventory:
    """Breadth-first walk of the library, folder paths flattened like a local KB.

    ``truncated`` records whether anything was left unvisited — a folder still
    queued, a page still to fetch, or a subtree below :data:`MAX_DEPTH`. It is
    tracked explicitly rather than inferred from the request count so a traversal
    that happens to finish on its last allowed request is still reported as
    complete.
    """
    documents: list[str] = []
    seen_folders: set[str] = set()
    # (folder_id, path prefix, depth); the root folder's id is the library id.
    queue: deque[tuple[str, str, int]] = deque([(root_id, "", 0)])
    requests = 0
    truncated = False

    while queue:
        folder_id, prefix, depth = queue.popleft()
        cursor = ""
        while True:
            if requests >= MAX_REQUESTS:
                truncated = True
                break
            page = client.get_knowledge_list_sync(
                folder_id=folder_id,
                cursor=cursor,
                limit=PAGE_SIZE,
            )
            requests += 1
            for document in page.documents:
                documents.append(f"{prefix}{document.title}" if prefix else document.title)
            for folder in page.folders:
                if folder.folder_id in seen_folders or folder.folder_id == folder_id:
                    continue
                seen_folders.add(folder.folder_id)
                if depth >= MAX_DEPTH:
                    truncated = True
                    continue
                queue.append((folder.folder_id, f"{prefix}{folder.name}/", depth + 1))
            cursor = page.next_cursor
            if page.is_end or not cursor:
                break
        if truncated and requests >= MAX_REQUESTS:
            break

    return ImaInventory(documents=tuple(documents), complete=not truncated and not queue)


def _cached(key: str) -> Any:
    """The cached value, or :data:`_MISS` when absent or expired."""
    now = time.monotonic()
    with _CACHE_LOCK:
        hit = _CACHE.get(key)
        if hit is None:
            return _MISS
        expires_at, inventory = hit
        if now >= expires_at:
            _CACHE.pop(key, None)
            return _MISS
        return inventory


def _store(key: str, inventory: Optional[ImaInventory], *, ttl: float) -> None:
    with _CACHE_LOCK:
        _CACHE[key] = (time.monotonic() + ttl, inventory)


__all__ = [
    "CACHE_TTL_SECONDS",
    "FAILURE_TTL_SECONDS",
    "MAX_DEPTH",
    "MAX_REQUESTS",
    "PAGE_SIZE",
    "TIMEOUT_SECONDS",
    "ImaInventory",
    "clear_cache",
    "read_inventory",
]
