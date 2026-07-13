"""M6 regression — /system/status hides admin model name from non-admin users."""

from __future__ import annotations

import asyncio


def test_status_redacts_model_for_non_admin(mu_isolated_root, as_user, monkeypatch):
    """Run get_system_status() under a non-admin context and assert that the
    model / provider fields are stripped from the response."""

    from deeptutor.api.routers import system as system_router

    # Stub the heavy bits so the handler returns predictable shape.
    class _FakeLLM:
        model = "gpt-test"

    class _FakeEmbedding:
        model = "embed-test"

    class _FakeSearch:
        requested_provider = "brave"
        provider = "brave"
        unsupported_provider = False
        deprecated_provider = False
        missing_credentials = False
        fallback_reason = None

    monkeypatch.setattr(system_router, "get_llm_config", lambda: _FakeLLM())
    monkeypatch.setattr(system_router, "get_embedding_config", lambda: _FakeEmbedding())
    monkeypatch.setattr(system_router, "resolve_search_runtime_config", lambda: _FakeSearch())

    with as_user("u_alice", role="user"):
        result = asyncio.run(system_router.get_system_status())
    assert result["llm"].get("model") is None
    assert result["embeddings"].get("model") is None
    assert "provider" not in result["search"] or result["search"].get("provider") is None
    # Status itself stays, just the identifying fields are gone.
    assert result["llm"]["status"] == "configured"


def test_status_keeps_model_for_admin(mu_isolated_root, as_user, monkeypatch):
    from deeptutor.api.routers import system as system_router

    class _FakeLLM:
        model = "gpt-test"

    class _FakeEmbedding:
        model = "embed-test"

    class _FakeSearch:
        requested_provider = "brave"
        provider = "brave"
        unsupported_provider = False
        deprecated_provider = False
        missing_credentials = False
        fallback_reason = None

    monkeypatch.setattr(system_router, "get_llm_config", lambda: _FakeLLM())
    monkeypatch.setattr(system_router, "get_embedding_config", lambda: _FakeEmbedding())
    monkeypatch.setattr(system_router, "resolve_search_runtime_config", lambda: _FakeSearch())

    with as_user("u_admin", role="admin"):
        result = asyncio.run(system_router.get_system_status())
    assert result["llm"]["model"] == "gpt-test"
    assert result["embeddings"]["model"] == "embed-test"
    assert result["search"]["provider"] == "brave"
