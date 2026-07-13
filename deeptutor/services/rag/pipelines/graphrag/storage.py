"""On-disk layout for a GraphRAG-backed knowledge base.

A GraphRAG KB keeps a self-contained project inside the KB's flat ``version-N``
directory (reused from ``index_versioning`` with a ``None`` signature, exactly
like the PageIndex pipeline). The version dir doubles as GraphRAG's project
root::

    <kb_dir>/version-N/
        settings.yaml        # generated from DeepTutor config (see config.py)
        input/               # parsed *.txt fed to the indexer
        output/              # GraphRAG's parquet artefacts + lancedb
        cache/  logs/
        meta.json            # synthetic "ready" marker (see write_meta)

The synthetic ``meta.json`` is what makes the existing "is this KB initialised?"
and Index-versions UI checks treat a GraphRAG KB as ready, without teaching the
manager about GraphRAG internals.
"""

from __future__ import annotations

from datetime import datetime, timezone
import json
import logging
from pathlib import Path
import tempfile
from typing import Any

logger = logging.getLogger(__name__)

META_FILENAME = "meta.json"
PROVIDER = "graphrag"

INPUT_DIRNAME = "input"
OUTPUT_DIRNAME = "output"

# Parquet artefacts GraphRAG writes on a successful index; their presence is our
# "the index actually built" signal (independent of the synthetic meta marker).
OUTPUT_TABLES = (
    "entities",
    "communities",
    "community_reports",
    "text_units",
    "relationships",
)


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=str(path.parent), delete=False
    ) as handle:
        json.dump(payload, handle, indent=2, ensure_ascii=False)
        handle.write("\n")
        tmp_path = Path(handle.name)
    tmp_path.replace(path)


def input_dir(root_dir: Path) -> Path:
    return Path(root_dir) / INPUT_DIRNAME


def output_dir(root_dir: Path) -> Path:
    return Path(root_dir) / OUTPUT_DIRNAME


def has_output(root_dir: Path | None) -> bool:
    """True when GraphRAG has produced at least its core parquet tables."""
    if root_dir is None:
        return False
    out = output_dir(root_dir)
    if not out.is_dir():
        return False
    return any((out / f"{name}.parquet").exists() for name in OUTPUT_TABLES)


def write_meta(root_dir: Path) -> None:
    """Write a flat-layout ``meta.json`` so the version is listed as ready.

    Mirrors ``index_versioning.write_version_meta`` but carries a synthetic
    ``graphrag`` signature instead of an embedding hash. The embedding identity
    is stamped alongside so an externally-linked index can be checked for
    embedding compatibility at connect time (GraphRAG otherwise fails retrieval
    silently on a dimension mismatch).
    """
    from deeptutor.services.rag.embedding_signature import embedding_meta_fields

    target = Path(root_dir)
    payload = {
        "version": target.name,
        "signature": PROVIDER,
        "provider": PROVIDER,
        "layout": "flat",
        "created_at": datetime.now(timezone.utc).replace(tzinfo=None).isoformat() + "Z",
        **embedding_meta_fields(),
    }
    _atomic_write_json(target / META_FILENAME, payload)


__all__ = [
    "META_FILENAME",
    "PROVIDER",
    "INPUT_DIRNAME",
    "OUTPUT_DIRNAME",
    "OUTPUT_TABLES",
    "input_dir",
    "output_dir",
    "has_output",
    "write_meta",
]
