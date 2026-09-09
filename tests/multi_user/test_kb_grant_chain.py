"""The grants → retrieval authorization chain for knowledge bases.

Reproduction of the 2026-09-09 production 404: a teacher's grant carried the
KB under ``kb_id`` (the key the admin grant editor writes), the retrieval
consumers only read ``resource_id``/``name``, the assignment matched nothing,
and ``resolve_kb`` answered 404 for a KB that was both real and granted. The
chain is pinned end-to-end here: whatever key the grant uses, an assigned
admin KB resolves for RAG, and an unassigned one stays closed.
"""

from __future__ import annotations

import json

import pytest


def _stage_admin_kb(name: str) -> None:
    from pathlib import Path

    from deeptutor.knowledge.manager import KnowledgeBaseManager
    from deeptutor.multi_user.knowledge_access import admin_kb_base_dir

    manager = KnowledgeBaseManager(base_dir=admin_kb_base_dir())
    raw = Path(manager.base_dir) / name / "raw"
    raw.mkdir(parents=True, exist_ok=True)
    (raw / "chapter-1.pdf").write_bytes(b"x" * 512)
    manager.register_knowledge_base(name, description="subject textbook")


def _write_raw_grant(user_id: str, grant: dict) -> None:
    """Persist a grant exactly as it arrived, bypassing normalization."""
    from deeptutor.multi_user.grants import GRANTS_DIR, ensure_system_dirs

    ensure_system_dirs()
    GRANTS_DIR.mkdir(parents=True, exist_ok=True)
    (GRANTS_DIR / f"{user_id}.json").write_text(
        json.dumps(grant, ensure_ascii=False), encoding="utf-8"
    )


KB_ID = "admin:kb:教材-v2-数学"
KB_NAME = "教材-v2-数学"


@pytest.mark.parametrize(
    "kb_item",
    [
        {"kb_id": KB_ID},  # what the admin grant editor wrote in the incident
        {"resource_id": KB_ID, "name": KB_NAME},  # canonical v2 shape
        {"name": KB_NAME},  # bare-name grant
    ],
    ids=["kb_id", "canonical", "bare-name"],
)
def test_assigned_kb_resolves_under_every_grant_spelling(
    mu_isolated_root, as_user, kb_item
) -> None:
    from deeptutor.multi_user.knowledge_access import (
        KnowledgeResource,
        list_visible_knowledge_bases,
        resolve_for_rag,
        resolve_kb,
    )

    _stage_admin_kb(KB_NAME)
    _write_raw_grant("u_teacher", {"knowledge_bases": [kb_item]})

    with as_user("u_teacher", role="user"):
        resource = resolve_kb(KB_NAME)
        assert isinstance(resource, KnowledgeResource)
        assert resource.id == KB_ID
        assert resource.source == "admin"
        assert resource.assigned is True
        assert resource.read_only is True

        # Same answer through the exact-prefixed ref and the RAG seam.
        assert resolve_kb(KB_ID).id == KB_ID
        assert resolve_for_rag(KB_NAME).id == KB_ID

        # And the KB shows up in the user's visible list as assigned.
        visible = [item for item in list_visible_knowledge_bases() if item["id"] == KB_ID]
        assert visible and visible[0]["assigned"] is True


def test_kb_id_grant_survives_a_raw_payload_without_normalization_keys(
    mu_isolated_root, as_user
) -> None:
    """The exact incident payload, written to disk verbatim, still resolves."""
    from deeptutor.multi_user.knowledge_access import resolve_kb

    _stage_admin_kb(KB_NAME)
    _write_raw_grant(
        "u_teacher",
        {
            "version": 2,
            "user_id": "u_teacher",
            "models": {"llm": []},
            "knowledge_bases": [{"kb_id": KB_ID}],
        },
    )

    with as_user("u_teacher", role="user"):
        resource = resolve_kb(KB_NAME)
        assert resource.id == KB_ID


def test_unassigned_admin_kb_stays_closed(mu_isolated_root, as_user) -> None:
    from fastapi import HTTPException

    from deeptutor.multi_user.knowledge_access import resolve_kb

    _stage_admin_kb(KB_NAME)

    with as_user("u_teacher", role="user"):
        with pytest.raises(HTTPException) as exc:
            resolve_kb(KB_NAME)
        assert exc.value.status_code == 404
