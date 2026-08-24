"""Tests for the MinerU content-list policy at the LightRAG boundary."""

from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path

import pytest

from deeptutor.services.rag.pipelines.lightrag import block_policy


def test_mineru_policy_filters_layout_and_preserves_semantic_order() -> None:
    blocks = [
        {"type": "header", "text": "chapter", "page_idx": 0},
        {"type": "text", "text": "body", "page_idx": 0, "meta": {"rank": 1}},
        {"type": "aside_text", "text": "aside", "page_idx": 0},
        {"type": "image", "img_path": "images/a.png", "page_idx": 1},
        {"type": "page_footnote", "text": "note", "page_idx": 1},
        {"type": "footer", "text": "publisher", "page_idx": 1},
        {"type": "page_number", "text": "2", "page_idx": 1},
    ]
    original = deepcopy(blocks)

    decision = block_policy.prepare_content_list(
        blocks,
        engine="mineru",
        source_hash="source-hash",
        parser_signature="parser-signature",
    )

    assert [item["type"] for item in decision.content_list] == [
        "text",
        "aside_text",
        "image",
        "page_footnote",
    ]
    assert decision.ledger is not None
    assert decision.ledger["counts"] == {
        "raw_total": 7,
        "raw_by_type": {
            "aside_text": 1,
            "footer": 1,
            "header": 1,
            "image": 1,
            "page_footnote": 1,
            "page_number": 1,
            "text": 1,
        },
        "filtered_total": 3,
        "filtered_by_type": {"footer": 1, "header": 1, "page_number": 1},
        "eligible_total": 4,
        "eligible_by_type": {
            "aside_text": 1,
            "image": 1,
            "page_footnote": 1,
            "text": 1,
        },
        "eligible_multimodal_total": 3,
        "eligible_multimodal_by_type_and_page": {
            "aside_text:0": 1,
            "image:1": 1,
            "page_footnote:1": 1,
        },
        "unknown_total": 0,
        "unknown_by_type": {},
    }
    decision.content_list[0]["meta"]["rank"] = 99
    assert blocks == original


def test_mineru_policy_indexes_unknown_types_and_never_logs_their_content() -> None:
    """An unrecognized block type is content, not chrome, and not a failure.

    A MinerU release that adds a block type must not silently drop the block
    (the user loses text they can see in the document) nor abort the ingest
    (the whole KB stops working over a layout label). It is counted so the
    policy can be extended, and the count is all the ledger may ever hold —
    document text must never reach an audit file.
    """
    blocks = [
        {"type": "future_widget", "text": "prompt-secret", "page_idx": 0},
        {"type": "Prompt secret invalid type", "text": "token-secret", "page_idx": 0},
    ]

    decision = block_policy.prepare_content_list(
        blocks,
        engine="mineru",
        source_hash="source-hash",
        parser_signature="parser-signature",
    )

    assert [item["text"] for item in decision.content_list] == [
        "prompt-secret",
        "token-secret",
    ]
    assert decision.ledger is not None
    serialized = json.dumps(decision.ledger)
    assert "prompt-secret" not in serialized
    assert "token-secret" not in serialized
    assert decision.ledger["counts"]["unknown_by_type"] == {
        "<invalid>": 1,
        "future_widget": 1,
    }
    assert decision.unknown_summary() == "<invalid>=1, future_widget=1"


def test_mineru_v2_auxiliary_names_are_normalized_to_the_policy_vocabulary() -> None:
    """Upgrading MinerU must not turn every layout block into an unknown type.

    The newer parser emits ``page_header`` where the legacy ``content_list``
    emitted ``header``. Without normalizing, page chrome would stop being
    filtered and would instead be reported as unrecognized on every document.
    """
    blocks = [
        {"type": "page_header", "text": "chapter", "page_idx": 0},
        {"type": "text", "text": "body", "page_idx": 0},
        {"type": "page_aside_text", "text": "aside", "page_idx": 0},
        {"type": "page_footer", "text": "publisher", "page_idx": 0},
        {"type": "page_number", "text": "2", "page_idx": 0},
        {"type": "page_footnote", "text": "note", "page_idx": 0},
    ]

    decision = block_policy.prepare_content_list(
        blocks,
        engine="mineru",
        source_hash="source-hash",
        parser_signature="parser-signature",
    )

    assert [item["type"] for item in decision.content_list] == [
        "text",
        "page_aside_text",
        "page_footnote",
    ]
    assert decision.ledger is not None
    assert decision.ledger["counts"]["filtered_by_type"] == {
        "footer": 1,
        "header": 1,
        "page_number": 1,
    }
    assert decision.ledger["counts"]["unknown_by_type"] == {}


def test_non_mineru_blocks_keep_the_existing_pipeline_contract() -> None:
    blocks = [{"type": "header", "text": "Docling heading", "page_idx": 0}]

    decision = block_policy.prepare_content_list(
        blocks,
        engine="docling",
        source_hash="source-hash",
        parser_signature="parser-signature",
    )

    assert decision.content_list is blocks
    assert decision.ledger is None


def test_decision_ledger_uses_a_hashed_document_identifier(tmp_path: Path) -> None:
    decision = block_policy.prepare_content_list(
        [{"type": "text", "text": "body", "page_idx": 0}],
        engine="mineru",
        source_hash="source-hash",
        parser_signature="parser-signature",
    )
    assert decision.ledger is not None

    path = block_policy.write_decision_ledger(
        tmp_path,
        "private-document-name",
        decision.ledger,
    )

    assert path.parent.name == block_policy.LEDGER_DIRNAME
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert path.stem == payload["document_id_sha256"][:16]
    assert payload["decision"] == {
        "ledger_role": "current-index",
        "policy_outcome": "accepted",
    }
    assert "private-document-name" not in path.read_text(encoding="utf-8")


def test_attempt_ledger_is_unique_and_does_not_expose_identifiers(tmp_path: Path) -> None:
    decision = block_policy.prepare_content_list(
        [{"type": "future_widget", "text": "secret", "page_idx": 0}],
        engine="mineru",
        source_hash="source-hash",
        parser_signature="private-parser-signature",
    )
    assert decision.ledger is not None

    first_path, first_id = block_policy.write_attempt_ledger(
        tmp_path,
        "private-document-name",
        decision.ledger,
        outcome="unknown_types",
    )
    second_path, second_id = block_policy.write_attempt_ledger(
        tmp_path,
        "private-document-name",
        decision.ledger,
        outcome="unknown_types",
    )

    assert first_path != second_path
    assert first_id != second_id
    assert first_path.parent.name == block_policy.ATTEMPT_LEDGER_DIRNAME
    payload = json.loads(first_path.read_text(encoding="utf-8"))
    assert first_path.stem == payload["decision"]["attempt_key_sha256"]
    assert payload["decision"]["attempt_id"] == first_id
    assert payload["decision"]["ledger_role"] == "attempt"
    assert payload["decision"]["policy_outcome"] == "unknown_types"
    assert "private-document-name" not in first_path.name
    assert "private-parser-signature" not in first_path.name
