"""Probe an external folder before mounting it as a *linked* knowledge base.

Linking reuses a self-contained index a user already built — no copy, no
re-index (see :data:`deeptutor.knowledge.kb_types.LINKED_KB_TYPE`). Before we
register a pointer we must answer two questions for the user:

1. **Does this folder actually hold a ready index for the chosen engine?**
   We reuse the standard version discovery (``list_kb_versions``) so the same
   "is this KB ready?" logic that lists ordinary KBs decides linkability.
2. **Was that index built with a compatible embedding model?** A local vector /
   graph index is only queryable by the embedding model that built it. A
   mismatch makes LlamaIndex error loudly and the graph engines fail silently,
   so we surface a clear verdict the UI can confirm.

PageIndex is deliberately not linkable: its index lives in the cloud (the local
folder holds only a doc-id manifest), so there is nothing self-contained to
mount.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import os
from pathlib import Path
from typing import Any, Optional

# Optional ops-set allowlist of filesystem roots a linked folder must live
# under, as an ``os.pathsep``-separated list. Unset (the default) means no
# restriction, which is correct for the local/self-hosted single-trust-domain
# deployments this feature targets. Shared multi-user servers should set it so a
# non-admin cannot point a KB at another user's data or system paths.
LINK_ROOTS_ENV = "DEEPTUTOR_LINKED_FOLDER_ROOTS"

from deeptutor.services.rag.factory import (
    DEFAULT_PROVIDER,
    GRAPHRAG_PROVIDER,
    LIGHTRAG_PROVIDER,
    PAGEINDEX_PROVIDER,
    normalize_provider_name,
)

# Engines whose index is self-contained on disk and therefore mountable. The
# cloud-backed PageIndex is excluded — see module docstring.
LINKABLE_PROVIDERS = frozenset({DEFAULT_PROVIDER, GRAPHRAG_PROVIDER, LIGHTRAG_PROVIDER})


@dataclass
class EmbeddingCompat:
    # True/False once both signatures are known; None when it can't be verified.
    compatible: Optional[bool] = None
    index_model: Optional[str] = None
    current_model: Optional[str] = None


@dataclass
class ProbeResult:
    provider: str
    external_path: str
    ok: bool = False
    version: Optional[str] = None
    doc_count: Optional[int] = None
    embedding: EmbeddingCompat = field(default_factory=EmbeddingCompat)
    warnings: list[str] = field(default_factory=list)
    error: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        return data


def provider_is_linkable(provider: str) -> bool:
    return normalize_provider_name(provider) in LINKABLE_PROVIDERS


def allowed_link_roots() -> list[Path]:
    """Resolved allowlist of roots a linked folder may live under (may be empty)."""
    raw = os.environ.get(LINK_ROOTS_ENV, "").strip()
    if not raw:
        return []
    roots: list[Path] = []
    for chunk in raw.split(os.pathsep):
        chunk = chunk.strip()
        if not chunk:
            continue
        try:
            roots.append(Path(chunk).expanduser().resolve())
        except OSError:
            continue
    return roots


def assert_path_allowed(folder_path: str) -> Path:
    """Resolve ``folder_path`` and enforce the optional root allowlist.

    Returns the resolved absolute path. Raises ``ValueError`` if the folder is
    missing/not a directory, or escapes the configured allowlist (symlinks are
    resolved first so they can't tunnel out). With no allowlist set, any
    existing directory is permitted — the self-hosted default.
    """
    folder = Path(folder_path).expanduser()
    if not folder.exists():
        raise ValueError(f"Folder does not exist: {folder}")
    if not folder.is_dir():
        raise ValueError(f"Not a directory: {folder}")
    resolved = folder.resolve()

    roots = allowed_link_roots()
    if roots and not any(_is_within(resolved, root) for root in roots):
        raise ValueError("This folder is outside the locations allowed for linking.")
    return resolved


def _is_within(path: Path, root: Path) -> bool:
    try:
        return path == root or root in path.parents
    except OSError:
        return False


def probe_linked_folder(folder_path: str, provider: str) -> ProbeResult:
    """Inspect ``folder_path`` for a ready ``provider`` index.

    Always returns a :class:`ProbeResult` (never raises): ``error`` set means
    the folder cannot be linked; ``warnings`` are non-fatal cautions the user
    confirms. The caller is responsible for any path-jail / access checks.
    """
    provider = normalize_provider_name(provider)
    folder = Path(folder_path).expanduser()
    result = ProbeResult(provider=provider, external_path=str(folder))

    if provider == PAGEINDEX_PROVIDER:
        result.error = (
            "PageIndex indexes live in the cloud, not in a local folder, so they "
            "cannot be linked. Create a PageIndex knowledge base instead."
        )
        return result
    if provider not in LINKABLE_PROVIDERS:
        result.error = f"Engine '{provider}' does not support linking an existing folder."
        return result

    if not folder.exists():
        result.error = f"Folder does not exist: {folder}"
        return result
    if not folder.is_dir():
        result.error = f"Not a directory: {folder}"
        return result

    result.external_path = str(folder.resolve())

    from deeptutor.services.rag.index_probe import inspect_kb_versions

    versions = inspect_kb_versions(folder, provider)
    ready = [v for v in versions if v.get("ready")]
    if not ready:
        failure = next(
            (str(v.get("failure_summary") or "") for v in versions if v.get("failure_summary")),
            "",
        )
        result.error = (
            failure
            or "No ready index found in this folder. Point at a knowledge base folder "
            "that contains a built index (a 'version-N' directory)."
        )
        return result

    latest = ready[0]  # inspect_kb_versions preserves newest-first ordering.
    result.version = str(latest.get("version") or "")
    _check_embedding(provider, latest, result)
    doc_count = latest.get("doc_count")
    result.doc_count = (
        int(doc_count) if isinstance(doc_count, int) else _best_effort_doc_count(folder)
    )
    result.ok = result.error is None
    return result


def _check_embedding(provider: str, version: dict, result: ProbeResult) -> None:
    """Compare the index's embedding identity against the active config."""
    from deeptutor.services.rag.embedding_signature import signature_from_embedding_config

    current = signature_from_embedding_config()
    compat = result.embedding
    compat.current_model = current.model if current else None

    # LlamaIndex stores the embedding hash in the version signature; the graph
    # engines stamp it separately (see embedding_meta_fields).
    if provider == DEFAULT_PROVIDER:
        index_hash = str(version.get("signature") or "")
    else:
        index_hash = str(version.get("embedding_signature") or "")
    compat.index_model = version.get("embedding_model") or version.get("model")

    if current is None:
        compat.compatible = None
        result.warnings.append(
            "No embedding model is configured, so embedding compatibility could not "
            "be verified. Configure one under Settings before querying."
        )
        return
    if not index_hash:
        compat.compatible = None
        result.warnings.append(
            "This index does not record which embedding model built it. Make sure it "
            "matches your current embedding model, or retrieval may fail."
        )
        return

    compat.compatible = index_hash == current.hash()
    if not compat.compatible:
        built_with = compat.index_model or "a different model"
        result.warnings.append(
            f"This index was built with {built_with}, which differs from your current "
            f"embedding model ({compat.current_model}). Retrieval will not work until "
            "you switch back to the matching embedding model."
        )


def _best_effort_doc_count(folder: Path) -> Optional[int]:
    """Count source files under ``raw/`` if the linked folder ships them."""
    raw = folder / "raw"
    if not raw.is_dir():
        return None
    try:
        return sum(1 for p in raw.rglob("*") if p.is_file())
    except OSError:
        return None


__all__ = [
    "LINKABLE_PROVIDERS",
    "EmbeddingCompat",
    "ProbeResult",
    "probe_linked_folder",
    "provider_is_linkable",
    "allowed_link_roots",
    "assert_path_allowed",
]
