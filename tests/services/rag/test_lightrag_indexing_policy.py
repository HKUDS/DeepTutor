from __future__ import annotations

import json
from pathlib import Path

import pytest

from deeptutor.multi_user.models import CurrentUser, UserScope
from deeptutor.services.llm.config import LLMConfig
from deeptutor.services.rag.pipelines.lightrag import indexing_policy, storage


def _user(tmp_path: Path) -> CurrentUser:
    return CurrentUser(
        id="user-1",
        username="person",
        role="user",
        scope=UserScope(kind="user", user_id="user-1", root=tmp_path / "workspace"),
    )


def _config(*, key: str = "secret-a", reasoning: str | None = "high") -> LLMConfig:
    return LLMConfig(
        model="model-v1",
        api_key=key,
        base_url="https://name:password@example.test/v1?token=secret",
        binding="openai",
        provider_name="openai",
        api_version="2026-01-01",
        reasoning_effort=reasoning,
        extra_headers={"Authorization": "private"},
    )


def _freeze(monkeypatch, tmp_path: Path, config: LLMConfig):
    monkeypatch.setattr(indexing_policy, "get_current_user_or_none", lambda: _user(tmp_path))
    monkeypatch.setattr(indexing_policy, "apply_allowed_llm_selection", lambda value: value)
    monkeypatch.setattr(
        indexing_policy, "resolve_llm_config_for_selection", lambda _selection: config
    )
    monkeypatch.setattr(indexing_policy, "supports_vision", lambda binding, model: True)
    return indexing_policy.freeze_snapshot(
        {"profile_id": "profile-1", "model_id": "model-1", "reasoning_effort": "high"}
    )


def test_fingerprint_excludes_credentials_and_endpoint_secrets(monkeypatch, tmp_path: Path) -> None:
    first = _freeze(monkeypatch, tmp_path, _config(key="secret-a"))
    second = _freeze(monkeypatch, tmp_path, _config(key="secret-b"))

    assert first.fingerprint == second.fingerprint
    serialized = json.dumps(first.persisted_policy(), sort_keys=True)
    assert "secret" not in serialized
    assert "password" not in serialized
    assert "Authorization" not in serialized
    assert "user-1" not in serialized
    assert first.descriptor["endpoint"] == "https://example.test/v1"


def test_reasoning_drift_changes_fingerprint_and_blocks_append(monkeypatch, tmp_path: Path) -> None:
    original = _freeze(monkeypatch, tmp_path, _config(reasoning="high"))
    drifted = _config(reasoning=None)
    monkeypatch.setattr(
        indexing_policy, "resolve_llm_config_for_selection", lambda _selection: drifted
    )

    with pytest.raises(indexing_policy.IndexingModelChangedError, match="full re-index"):
        indexing_policy.snapshot_from_persisted(original.persisted_policy())


def test_reasoning_none_and_literal_none_have_distinct_identity(
    monkeypatch, tmp_path: Path
) -> None:
    unset = _freeze(monkeypatch, tmp_path, _config(reasoning=None))
    literal_none = _freeze(monkeypatch, tmp_path, _config(reasoning="none"))

    assert unset.fingerprint != literal_none.fingerprint
    assert unset.descriptor["reasoning_effort"] is None
    assert literal_none.descriptor["reasoning_effort"] == "none"


def test_vision_capability_drift_changes_fingerprint_and_blocks_append(
    monkeypatch, tmp_path: Path
) -> None:
    original = _freeze(monkeypatch, tmp_path, _config())
    assert original.vision_available is True
    assert original.descriptor["vision_available"] is True
    monkeypatch.setattr(indexing_policy, "supports_vision", lambda _binding, _model: False)

    with pytest.raises(indexing_policy.IndexingModelChangedError, match="full re-index"):
        indexing_policy.snapshot_from_persisted(original.persisted_policy())


def test_published_policy_wins_over_residual_pending(tmp_path: Path) -> None:
    kb_dir = tmp_path / "kb"
    version = kb_dir / "version-1"
    version.mkdir(parents=True)
    (version / "kv_store_doc_status.json").write_text(
        json.dumps({"doc": {"status": "processed", "chunks_list": ["chunk"]}}),
        encoding="utf-8",
    )
    published = {
        "policy": "pinned",
        "selection": {"profile_id": "published", "model_id": "model"},
        "fingerprint": "a" * 64,
    }
    (version / "meta.json").write_text(
        json.dumps(
            {
                "provider": "lightrag",
                "signature": "lightrag",
                "lightrag_adapter_schema": storage.ADAPTER_SCHEMA,
                "parser_bridge_schema": 1,
                "state": "published",
                "indexing_policy": published,
            }
        ),
        encoding="utf-8",
    )
    (tmp_path / "kb_config.json").write_text(
        json.dumps(
            {
                "knowledge_bases": {
                    "kb": {
                        "path": "kb",
                        "pending_indexing_policy": {
                            "policy": "pending_pinned",
                            "selection": {"profile_id": "pending", "model_id": "model"},
                        },
                    }
                }
            }
        ),
        encoding="utf-8",
    )

    assert (
        indexing_policy.effective_policy(kb_dir, base_dir=str(tmp_path), kb_name="kb") == published
    )


def test_owner_bound_model_requires_explicit_scope(monkeypatch) -> None:
    monkeypatch.setattr(indexing_policy, "get_current_user_or_none", lambda: None)
    monkeypatch.setattr(indexing_policy, "apply_allowed_llm_selection", lambda value: value)
    monkeypatch.setattr(
        indexing_policy,
        "resolve_llm_config_for_selection",
        lambda _selection: LLMConfig(
            model="gpt",
            api_key="",
            binding="openai_codex",
            provider_name="openai_codex",
        ),
    )

    with pytest.raises(indexing_policy.IndexingPolicyError, match="explicit initiating user"):
        indexing_policy.freeze_snapshot({"profile_id": "personal", "model_id": "gpt"})


def test_default_snapshot_prefers_released_lightrag_selection(monkeypatch) -> None:
    from deeptutor.services.rag.pipelines.lightrag import config

    selection = {"profile_id": "dedicated", "model_id": "indexer"}
    expected = object()
    calls: list[tuple[object, str | None, bool]] = []
    monkeypatch.setattr(config, "lightrag_indexing_selection_from_settings", lambda: selection)
    monkeypatch.setattr(
        indexing_policy,
        "freeze_snapshot",
        lambda value, *, policy=None, require_explicit_user=True: (
            calls.append((value, policy, require_explicit_user)) or expected
        ),
    )

    assert indexing_policy.freeze_default_snapshot() is expected
    assert calls == [(selection, indexing_policy.POLICY_PINNED, False)]


def test_default_snapshot_rejects_unreadable_released_setting(monkeypatch) -> None:
    from deeptutor.services.rag.pipelines.lightrag import config

    def fail():
        raise OSError("settings unreadable")

    monkeypatch.setattr(config, "lightrag_indexing_selection_from_settings", fail)

    with pytest.raises(indexing_policy.IndexingPolicyError, match="could not be resolved"):
        indexing_policy.freeze_default_snapshot()


def test_latest_published_root_ignores_newer_unpublished_candidate(tmp_path: Path) -> None:
    kb_dir = tmp_path / "kb"
    published = kb_dir / "version-1"
    candidate = kb_dir / "version-2"
    for root in (published, candidate):
        root.mkdir(parents=True)
        (root / "kv_store_doc_status.json").write_text(
            json.dumps({"doc": {"status": "processed", "chunks_list": ["chunk"]}}),
            encoding="utf-8",
        )
    (published / "meta.json").write_text(
        json.dumps(
            {
                "provider": "lightrag",
                "signature": "lightrag",
                "lightrag_adapter_schema": storage.ADAPTER_SCHEMA,
                "parser_bridge_schema": 1,
                "state": "published",
            }
        ),
        encoding="utf-8",
    )

    assert storage.latest_published_root(kb_dir) == published
