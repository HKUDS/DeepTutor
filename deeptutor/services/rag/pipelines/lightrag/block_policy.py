"""Versioned MinerU block policy for LightRAG indexing.

MinerU's legacy ``content_list.json`` mixes semantic document content with
page-layout helpers.  DeepTutor retains the raw parser cache for audit and
derives an independent, deep-copied list for indexing so RAG-Anything never
needs to decide which parser blocks are semantic.
"""

from __future__ import annotations

from collections import Counter
from copy import deepcopy
from dataclasses import dataclass
import hashlib
from pathlib import Path
import re
from typing import Any
import uuid

from deeptutor.services.file_io import atomic_write_json

POLICY_ID = "mineru-legacy-content-list-v1"
LEDGER_DIRNAME = "deeptutor_ingestion_audit"
ATTEMPT_LEDGER_DIRNAME = "deeptutor_ingestion_attempts"

FILTERED_LAYOUT_TYPES = frozenset({"footer", "header", "page_number"})
PRESERVED_AUXILIARY_TYPES = frozenset({"aside_text", "page_footnote"})
PRESERVED_SEMANTIC_TYPES = frozenset(
    {"chart", "code", "equation", "image", "list", "table", "text"}
)
PRESERVED_TYPES = PRESERVED_AUXILIARY_TYPES | PRESERVED_SEMANTIC_TYPES
MULTIMODAL_TYPES = PRESERVED_TYPES - {"text"}

# MinerU renamed its auxiliary block types between output schemas: what the
# legacy ``content_list.json`` calls ``header`` a newer parser emits as
# ``page_header``. Map the newer names back onto the vocabulary the policy is
# written in, so upgrading MinerU keeps classifying blocks instead of
# presenting every layout block as an unrecognized type.
V2_AUXILIARY_EQUIVALENTS = {
    "aside_text": "page_aside_text",
    "footer": "page_footer",
    "header": "page_header",
    "page_footnote": "page_footnote",
    "page_number": "page_number",
}
_V2_TO_LEGACY_TYPE = {
    v2_name: legacy_name
    for legacy_name, v2_name in V2_AUXILIARY_EQUIVALENTS.items()
    if v2_name != legacy_name
}

_SAFE_TYPE = re.compile(r"[a-z][a-z0-9_]{0,63}\Z")
_INVALID_TYPE = "<invalid>"


@dataclass(frozen=True)
class BlockPolicyDecision:
    """Sanitized policy outcome plus an independent list for indexing."""

    content_list: list[dict[str, Any]]
    ledger: dict[str, Any] | None
    unknown_type_counts: tuple[tuple[str, int], ...] = ()

    def unknown_summary(self) -> str:
        """``type=count`` rundown of block types the policy does not know."""
        return ", ".join(
            f"{content_type}={count}" for content_type, count in self.unknown_type_counts
        )


def _sanitized_type(block: dict[str, Any]) -> str:
    value = block.get("type")
    if isinstance(value, str) and _SAFE_TYPE.fullmatch(value):
        return value
    return _INVALID_TYPE


def _sorted_counts(counter: Counter[str]) -> dict[str, int]:
    return dict(sorted(counter.items()))


def _page_type_key(content_type: str, block: dict[str, Any]) -> str | None:
    page_idx = block.get("page_idx")
    if isinstance(page_idx, int) and page_idx >= 0:
        return f"{content_type}:{page_idx}"
    return None


def prepare_content_list(
    blocks: list[dict[str, Any]],
    *,
    engine: str,
    source_hash: str,
    parser_signature: str,
) -> BlockPolicyDecision:
    """Derive the indexable content list without mutating parser-owned blocks.

    Only MinerU's legacy structured output is classified. Other parse engines
    retain their existing behavior because their block vocabularies have
    independent contracts.
    """
    if engine != "mineru":
        return BlockPolicyDecision(content_list=blocks, ledger=None)

    raw_counts: Counter[str] = Counter()
    filtered_counts: Counter[str] = Counter()
    eligible_counts: Counter[str] = Counter()
    eligible_multimodal_page_counts: Counter[str] = Counter()
    unknown_counts: Counter[str] = Counter()
    indexable: list[dict[str, Any]] = []

    for raw_block in blocks:
        if not isinstance(raw_block, dict):
            raw_counts[_INVALID_TYPE] += 1
            unknown_counts[_INVALID_TYPE] += 1
            continue
        block = raw_block
        content_type = _sanitized_type(block)
        content_type = _V2_TO_LEGACY_TYPE.get(content_type, content_type)
        raw_counts[content_type] += 1
        if content_type in FILTERED_LAYOUT_TYPES:
            filtered_counts[content_type] += 1
            continue
        if content_type not in PRESERVED_TYPES:
            # Filter only what we positively recognize as page chrome; index
            # anything else. A MinerU release that adds a block type must not
            # silently drop its content, nor abort the whole ingest — before
            # this policy existed every block was indexed, and an unrecognized
            # type is far more likely to be new content than new chrome.
            unknown_counts[content_type] += 1

        eligible_counts[content_type] += 1
        if content_type in MULTIMODAL_TYPES:
            page_type_key = _page_type_key(content_type, block)
            if page_type_key is not None:
                eligible_multimodal_page_counts[page_type_key] += 1
        indexable.append(deepcopy(block))

    ledger: dict[str, Any] = {
        "schema_version": 1,
        "policy": {
            "id": POLICY_ID,
            "input_schema": "legacy-content-list",
            "filtered_layout_types": sorted(FILTERED_LAYOUT_TYPES),
            "preserved_auxiliary_types": sorted(PRESERVED_AUXILIARY_TYPES),
            "preserved_semantic_types": sorted(PRESERVED_SEMANTIC_TYPES),
            "v2_auxiliary_equivalents": dict(sorted(V2_AUXILIARY_EQUIVALENTS.items())),
            "v2_auxiliary_normalized": True,
        },
        "parser": {
            "engine": engine,
            "source_hash": source_hash,
            "parser_signature": parser_signature,
        },
        "counts": {
            "raw_total": len(blocks),
            "raw_by_type": _sorted_counts(raw_counts),
            "filtered_total": sum(filtered_counts.values()),
            "filtered_by_type": _sorted_counts(filtered_counts),
            "eligible_total": len(indexable),
            "eligible_by_type": _sorted_counts(eligible_counts),
            "eligible_multimodal_total": sum(
                count
                for content_type, count in eligible_counts.items()
                if content_type in MULTIMODAL_TYPES
            ),
            "eligible_multimodal_by_type_and_page": _sorted_counts(eligible_multimodal_page_counts),
            "unknown_total": sum(unknown_counts.values()),
            "unknown_by_type": _sorted_counts(unknown_counts),
        },
        "invariants": {
            "input_blocks_mutated": False,
            "eligible_order_preserved": True,
            "unknown_types_indexed": True,
            "raw_parser_artifacts_mutated": False,
        },
    }
    return BlockPolicyDecision(
        content_list=indexable,
        ledger=ledger,
        unknown_type_counts=tuple(sorted(unknown_counts.items())),
    )


def write_decision_ledger(
    working_dir: Path,
    document_id: str,
    ledger: dict[str, Any],
    *,
    attempt_id: str | None = None,
) -> Path:
    """Persist the accepted decision that corresponds to the current index."""
    document_id_sha256 = hashlib.sha256(document_id.encode()).hexdigest()
    path = Path(working_dir) / LEDGER_DIRNAME / f"{document_id_sha256[:16]}.json"
    decision = {
        "ledger_role": "current-index",
        "policy_outcome": "accepted",
    }
    if attempt_id is not None:
        decision["attempt_id"] = attempt_id
    atomic_write_json(
        path,
        {
            **ledger,
            "document_id_sha256": document_id_sha256,
            "decision": decision,
        },
    )
    return path


def write_attempt_ledger(
    kb_dir: Path,
    document_id: str,
    ledger: dict[str, Any],
    *,
    outcome: str,
) -> tuple[Path, str]:
    """Persist one immutable policy attempt outside a candidate version.

    ``unknown_types`` means the document indexed, but carried block types the
    policy has no entry for — the signal to extend ``PRESERVED_TYPES`` or
    ``FILTERED_LAYOUT_TYPES``, not an ingest failure.
    """
    if outcome not in {"accepted", "unknown_types"}:
        raise ValueError(f"Unsupported policy outcome: {outcome}")

    document_id_sha256 = hashlib.sha256(document_id.encode()).hexdigest()
    attempt_id = uuid.uuid4().hex
    policy = ledger.get("policy")
    parser = ledger.get("parser")
    policy_id = str(policy.get("id") or "") if isinstance(policy, dict) else ""
    parser_signature = str(parser.get("parser_signature") or "") if isinstance(parser, dict) else ""
    key_material = "\0".join((document_id_sha256, policy_id, parser_signature, outcome, attempt_id))
    attempt_key_sha256 = hashlib.sha256(key_material.encode()).hexdigest()
    path = Path(kb_dir) / ATTEMPT_LEDGER_DIRNAME / f"{attempt_key_sha256}.json"
    atomic_write_json(
        path,
        {
            **ledger,
            "document_id_sha256": document_id_sha256,
            "decision": {
                "attempt_id": attempt_id,
                "attempt_key_sha256": attempt_key_sha256,
                "ledger_role": "attempt",
                "policy_outcome": outcome,
            },
        },
    )
    return path, attempt_id


__all__ = [
    "ATTEMPT_LEDGER_DIRNAME",
    "BlockPolicyDecision",
    "FILTERED_LAYOUT_TYPES",
    "LEDGER_DIRNAME",
    "MULTIMODAL_TYPES",
    "POLICY_ID",
    "PRESERVED_AUXILIARY_TYPES",
    "PRESERVED_SEMANTIC_TYPES",
    "PRESERVED_TYPES",
    "prepare_content_list",
    "write_attempt_ledger",
    "write_decision_ledger",
]
