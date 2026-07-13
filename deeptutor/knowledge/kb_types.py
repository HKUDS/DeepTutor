"""Knowledge-base kind discriminators.

A KB entry's ``type`` field tells the rest of the system how to treat it.
Most KBs are the default *indexed* kind (chunk → embed → retrieve via an RAG
provider) and carry no ``type``. *Connected* KBs are pointers: their content
lives outside ``data/knowledge_bases`` and we never copy or re-index it. Two
flavours exist today:

* ``obsidian`` — a pointer (``vault_path``) to a folder of Markdown the user
  owns. No index at all; the Obsidian capability navigates the live files and
  the chat loop routes the KB to that capability instead of ``rag``.
* ``linked`` — a pointer (``external_path``) to a folder that already holds an
  engine index the user built elsewhere (LlamaIndex / GraphRAG / LightRAG).
  Retrieval reads that index in place — the indexing step is skipped, and the
  KB is queried by its bound ``rag_provider`` exactly like an ordinary KB.
* ``subagent`` — a pointer to a connected agent the capability drives live
  through the ``consult_subagent`` tool. ``agent_kind`` names the backend: a
  *local* CLI (Claude Code / Codex), keyed by an optional ``cwd``; or a
  ``partner`` (one of the user's own partners), keyed by ``partner_id``. It has
  no path on disk and nothing to index or retrieve. See ``capabilities/subagent``.
* ``lightrag_server`` — a pointer (``server_url`` + optional ``api_key``) to an
  external, standalone LightRAG server the user already runs and indexed. We
  never index or store anything locally: retrieval is offloaded to that server's
  ``/query`` endpoint and the bound ``rag_provider`` (``lightrag-server``) shapes
  the result for the ``rag`` tool. One server instance = one workspace = one KB.
  See ``services/rag/pipelines/lightrag_server``.

All connected flavours share the same lifecycle quirks: no on-disk folder under
``base_dir``, no embedding reconcile, and deletion must never touch the
external resource. The :func:`is_connected_kb` / :func:`external_root_of` helpers
let the manager treat them uniformly without sprinkling ``type`` literals
across the codebase. ``subagent`` and ``lightrag_server`` are connected but point
at no folder, so :func:`external_root_of` returns ``None`` for them — a subagent
is driven by its capability and a LightRAG server is reached over HTTP; neither
resolves to a local path.

Kept in its own low-level module so both :mod:`deeptutor.knowledge.manager`
and the capability layer can import it without a cycle.
"""

from __future__ import annotations

from typing import Any

# A connected Obsidian vault: a pointer (``vault_path``) to a folder of
# Markdown the user already owns. No index, no embeddings — the Obsidian
# capability navigates the live files. See ``capabilities/obsidian``.
OBSIDIAN_KB_TYPE = "obsidian"

# A linked engine index: a pointer (``external_path``) to a folder that already
# contains a self-contained index built by one of our local providers. We mount
# it in place and retrieve via the bound provider — no copy, no re-index.
LINKED_KB_TYPE = "linked"

# A connected subagent: a pointer to a local agent CLI (Claude Code / Codex).
# No path on disk — ``agent_kind`` names the backend, optional ``cwd`` is the
# working directory. Driven live via ``consult_subagent``; never indexed.
SUBAGENT_KB_TYPE = "subagent"

# A connected external LightRAG server: a pointer (``server_url`` + optional
# ``api_key``) to a standalone LightRAG instance the user runs. No path on disk
# and no local index — retrieval is offloaded over HTTP to the server's
# ``/query`` endpoint by the ``lightrag-server`` provider.
LIGHTRAG_SERVER_KB_TYPE = "lightrag_server"

# Every pointer/connected KB type. Membership here is what makes the manager
# skip the index pipeline, the orphan prune and the embedding reconcile.
CONNECTED_KB_TYPES = frozenset(
    {OBSIDIAN_KB_TYPE, LINKED_KB_TYPE, SUBAGENT_KB_TYPE, LIGHTRAG_SERVER_KB_TYPE}
)


def is_connected_kb(entry: Any) -> bool:
    """True for pointer KBs whose data lives outside ``data/knowledge_bases``."""
    return isinstance(entry, dict) and entry.get("type") in CONNECTED_KB_TYPES


def external_root_of(entry: Any) -> str | None:
    """Absolute path a connected KB points at, or ``None`` for ordinary KBs.

    ``linked`` KBs store it under ``external_path``; ``obsidian`` vaults under
    the older ``vault_path`` field. One accessor so callers don't care which.
    """
    if not isinstance(entry, dict):
        return None
    return entry.get("external_path") or entry.get("vault_path")


__all__ = [
    "OBSIDIAN_KB_TYPE",
    "LINKED_KB_TYPE",
    "SUBAGENT_KB_TYPE",
    "LIGHTRAG_SERVER_KB_TYPE",
    "CONNECTED_KB_TYPES",
    "is_connected_kb",
    "external_root_of",
]
