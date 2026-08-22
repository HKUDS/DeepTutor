"""Knowledge-base kind discriminators.

A KB entry's ``type`` field tells the rest of the system how to treat it.
Most KBs are the default *indexed* kind (chunk → embed → retrieve via an RAG
provider) and carry no ``type``. *Connected* KBs are pointers: their content
lives outside ``data/knowledge_bases`` and we never copy or re-index it. These
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
* ``ima`` — a pointer (``client_id`` + ``api_key`` + ``knowledge_base_id``) to a
  knowledge base the user keeps in Tencent IMA. Same shape as
  ``lightrag_server``: nothing indexed or stored locally, retrieval offloaded to
  IMA's ``search_knowledge`` OpenAPI by the bound ``ima`` provider, and one IMA
  library = one KB. See ``services/rag/pipelines/ima``.

All connected flavours share the same lifecycle quirks: no on-disk folder under
``base_dir``, no embedding reconcile, and deletion must never touch the
external resource. The :func:`is_connected_kb` / :func:`external_root_of` helpers
let the manager treat them uniformly without sprinkling ``type`` literals
across the codebase. ``subagent``, ``lightrag_server`` and ``ima`` are connected
but point at no folder, so :func:`external_root_of` returns ``None`` for them — a
subagent is driven by its capability and the two server-backed kinds are reached
over HTTP; none resolves to a local path.

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

# A connected Tencent IMA knowledge base: a pointer (``client_id`` + ``api_key``
# + ``knowledge_base_id``) to a library the user curates in IMA. No path on disk
# and no local index — retrieval is offloaded over HTTPS to IMA's
# ``search_knowledge`` OpenAPI by the ``ima`` provider.
IMA_KB_TYPE = "ima"

# A connected MarginNote 4 library: a pointer (``device_id`` + optional
# ``server_url``) to the user's MN4 study data synced via the official Add-on
# API. No path on disk and no local index — MN4 objects land in a dedicated
# SQLite store and are navigated by the MarginNote capability's own tools.
# See ``capabilities/marginnote4``.
MARGINNOTE4_KB_TYPE = "marginnote4"

# Every pointer/connected KB type. Membership here is what makes the manager
# skip the index pipeline, the orphan prune and the embedding reconcile.
CONNECTED_KB_TYPES = frozenset(
    {
        OBSIDIAN_KB_TYPE,
        LINKED_KB_TYPE,
        SUBAGENT_KB_TYPE,
        LIGHTRAG_SERVER_KB_TYPE,
        IMA_KB_TYPE,
        MARGINNOTE4_KB_TYPE,
    }
)


# Connected kinds the ``rag`` tool cannot retrieve from: an Obsidian vault has no
# index at all (its capability navigates the live files) and a subagent is not a
# document collection. The other connected kinds ARE retrievable — ``linked``
# mounts an index built elsewhere, while ``lightrag_server`` and ``ima`` offload
# retrieval over HTTP — so "connected" must never be used as a synonym for
# "unsearchable" (it once cost Book generation every one of those sources).
NON_RETRIEVABLE_KB_TYPES = frozenset({OBSIDIAN_KB_TYPE, SUBAGENT_KB_TYPE, MARGINNOTE4_KB_TYPE})


def is_connected_kb(entry: Any) -> bool:
    """True for pointer KBs whose data lives outside ``data/knowledge_bases``."""
    return isinstance(entry, dict) and entry.get("type") in CONNECTED_KB_TYPES


def supports_rag_retrieval(entry: Any) -> bool:
    """Whether the ``rag`` tool can retrieve from this KB.

    True for every ordinary indexed KB and for the connected kinds that resolve
    to an index or a retrieval API. Callers that need "can I sweep this KB with
    ``rag_search``?" must ask this rather than :func:`is_connected_kb`, whose
    answer is about where the *documents* live.
    """
    if not isinstance(entry, dict):
        return True
    return entry.get("type") not in NON_RETRIEVABLE_KB_TYPES


def supports_local_raw_files(entry: Any) -> bool:
    """Whether the KB owns a DeepTutor-managed local ``raw/`` directory.

    Connected KBs are pointers to external resources.  Some point at a local
    folder and others at a remote service, but neither kind participates in
    DeepTutor's raw-file upload and management API.
    """
    return isinstance(entry, dict) and not is_connected_kb(entry)


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
    "IMA_KB_TYPE",
    "MARGINNOTE4_KB_TYPE",
    "CONNECTED_KB_TYPES",
    "NON_RETRIEVABLE_KB_TYPES",
    "is_connected_kb",
    "supports_local_raw_files",
    "supports_rag_retrieval",
    "external_root_of",
]
