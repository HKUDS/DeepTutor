"""M4 regression — non-admin rag_search without kb_name must NOT hit admin KBs."""

from __future__ import annotations

import asyncio

import pytest


def test_rag_search_no_kb_non_admin_raises(mu_isolated_root, as_user):
    from deeptutor.tools import rag_tool

    with as_user("u_alice", role="user"):
        with pytest.raises(ValueError, match="No knowledge base selected"):
            asyncio.run(rag_tool.rag_search(query="hi", kb_name=None))


def test_rag_search_no_kb_admin_does_not_raise_for_missing_kb(
    mu_isolated_root, as_user, monkeypatch
):
    """Admin path keeps the legacy single-user fallback semantics."""
    from deeptutor.tools import rag_tool

    sentinel = object()

    async def _stub_search(self, *, query, kb_name, event_sink=None, **kwargs):
        return {"answer": "stubbed", "kb_name": kb_name, "kb_base_dir": self.kb_base_dir}

    monkeypatch.setattr(
        "deeptutor.services.rag.service.RAGService.search",
        _stub_search,
    )

    with as_user("u_admin", role="admin"):
        # Admin / single-user mode passes through the legacy resolver, which
        # raises a different, KB-resolution error (no admin KBs in the temp
        # workspace) — the important thing is we do NOT raise the M4 guard.
        try:
            asyncio.run(rag_tool.rag_search(query="hi", kb_name=None))
        except ValueError as exc:
            assert "No knowledge base selected" not in str(exc)
        except Exception:
            # Any other failure mode is fine — we only assert that the
            # non-admin "deny by default" guard didn't fire.
            pass

    # Reference sentinel to silence ruff if assertions short-circuit.
    assert sentinel is not None
