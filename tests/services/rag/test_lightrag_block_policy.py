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
    decision.require_accepted()

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


def test_mineru_policy_rejects_unknown_types_without_retaining_content() -> None:
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

    assert decision.content_list == []
    assert decision.ledger is not None
    serialized = json.dumps(decision.ledger)
    assert "prompt-secret" not in serialized
    assert "token-secret" not in serialized
    assert decision.ledger["counts"]["unknown_by_type"] == {
        "<invalid>": 1,
        "future_widget": 1,
    }
    with pytest.raises(
        block_policy.MinerUBlockPolicyError,
        match=r"<invalid>=1, future_widget=1",
    ):
        decision.require_accepted()


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
    decision.require_accepted()


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
    assert "private-document-name" not in path.read_text(encoding="utf-8")
