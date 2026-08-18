from __future__ import annotations

from types import SimpleNamespace

import pytest

from deeptutor.services.rag.pipelines.pageindex.selection import validate_pageindex_oss_selection


def _patch_selection(monkeypatch, providers: dict[str, str]) -> None:
    monkeypatch.setattr(
        "deeptutor.multi_user.knowledge_access.resolve_kb",
        lambda name, **_kwargs: SimpleNamespace(base_dir="/kb", name=name),
    )
    monkeypatch.setattr(
        "deeptutor.services.rag.provider_binding.resolve_bound_provider",
        lambda _base, name: providers[name],
    )


def test_rejects_two_oss_kbs(monkeypatch) -> None:
    _patch_selection(monkeypatch, {"one": "pageindex-oss", "two": "pageindex-oss"})
    with pytest.raises(ValueError, match="at most one"):
        validate_pageindex_oss_selection(["one", "two"])


def test_cloud_and_oss_can_coexist(monkeypatch) -> None:
    _patch_selection(
        monkeypatch,
        {"cloud": "pageindex", "oss": "pageindex-oss", "vectors": "llamaindex"},
    )
    validate_pageindex_oss_selection(["cloud", "oss", "vectors"])
