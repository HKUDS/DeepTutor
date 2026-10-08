"""Singleton reset failures during ``deeptutor init`` must be logged, not swallowed.

Regression coverage for the swallowed-error scan HIGH finding at
``deeptutor_cli/init_cmd.py``: a failed ``PathService`` reset leaves the
previous home's cached paths in place, so ``deeptutor init --home`` would
silently write into the *old* workspace. The reset helper must log every
failure explicitly instead of passing silently.
"""

from __future__ import annotations

import logging
from typing import Any

import pytest


class _ExplodingClearDict(dict):
    """Dict whose ``clear`` always fails, simulating a broken cache reset."""

    def clear(self) -> None:
        raise RuntimeError("cache clear exploded")


class _RecordingClearDict(dict):
    """Dict that records whether ``clear`` was actually attempted."""

    def __init__(self, *args: Any, calls: list[str], label: str) -> None:
        super().__init__(*args)
        self.calls = calls
        self.label = label

    def clear(self) -> None:
        self.calls.append(self.label)
        super().clear()


def _fail_reset(monkeypatch: pytest.MonkeyPatch, owner: type, name: str) -> None:
    """Replace ``owner.name`` with a callable that always raises."""

    def _boom(*_args: Any, **_kwargs: Any) -> None:
        raise RuntimeError("reset exploded")

    monkeypatch.setattr(owner, name, _boom)


def test_pathservice_reset_failure_is_logged(monkeypatch: pytest.MonkeyPatch, caplog) -> None:
    """A failed PathService reset must surface at ERROR level, not vanish."""
    from deeptutor.services.path_service import PathService
    from deeptutor_cli import init_cmd

    _fail_reset(monkeypatch, PathService, "reset_instance")

    with caplog.at_level(logging.ERROR):
        init_cmd._reset_runtime_singletons()

    records = [record for record in caplog.records if "PathService" in record.getMessage()]
    assert records, "failed PathService reset was swallowed silently"
    assert any(record.levelno >= logging.ERROR for record in records)


def test_runtime_settings_cache_reset_failure_is_logged(
    monkeypatch: pytest.MonkeyPatch, caplog
) -> None:
    """A failed RuntimeSettings cache clear must be logged, not swallowed."""
    from deeptutor.services.config.runtime_settings import RuntimeSettingsService
    from deeptutor_cli import init_cmd

    monkeypatch.setattr(
        RuntimeSettingsService, "_instances", _ExplodingClearDict({"stale": object()})
    )

    with caplog.at_level(logging.WARNING):
        init_cmd._reset_runtime_singletons()

    records = [record for record in caplog.records if "RuntimeSettings" in record.getMessage()]
    assert records, "failed RuntimeSettings cache clear was swallowed silently"
    assert any(record.levelno >= logging.WARNING for record in records)


def test_model_catalog_cache_reset_failure_is_logged(
    monkeypatch: pytest.MonkeyPatch, caplog
) -> None:
    """A failed ModelCatalog cache clear must be logged, not swallowed."""
    from deeptutor.services.config.model_catalog import ModelCatalogService
    from deeptutor_cli import init_cmd

    monkeypatch.setattr(ModelCatalogService, "_instances", _ExplodingClearDict({"stale": object()}))

    with caplog.at_level(logging.WARNING):
        init_cmd._reset_runtime_singletons()

    records = [record for record in caplog.records if "ModelCatalog" in record.getMessage()]
    assert records, "failed ModelCatalog cache clear was swallowed silently"
    assert any(record.levelno >= logging.WARNING for record in records)


def test_pathservice_failure_does_not_block_cache_resets(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Each reset is best-effort: one failure must not skip the other caches."""
    from deeptutor.services.config.model_catalog import ModelCatalogService
    from deeptutor.services.config.runtime_settings import RuntimeSettingsService
    from deeptutor.services.path_service import PathService
    from deeptutor_cli import init_cmd

    calls: list[str] = []
    _fail_reset(monkeypatch, PathService, "reset_instance")
    monkeypatch.setattr(
        RuntimeSettingsService,
        "_instances",
        _RecordingClearDict(calls=calls, label="runtime_settings"),
    )
    monkeypatch.setattr(
        ModelCatalogService,
        "_instances",
        _RecordingClearDict(calls=calls, label="model_catalog"),
    )

    init_cmd._reset_runtime_singletons()

    assert calls == ["runtime_settings", "model_catalog"]
