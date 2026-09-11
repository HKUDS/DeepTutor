from __future__ import annotations

import pytest

from deeptutor.runtime.coordination import (
    CoordinationSettings,
    RuntimeConfigurationError,
)


def test_multi_worker_requires_redis() -> None:
    with pytest.raises(RuntimeConfigurationError, match="requires"):
        CoordinationSettings.from_runtime_settings(
            {"backend_workers": 4},
            {"turn_coordination": {"backend": "memory"}},
        )


def test_redis_requires_url() -> None:
    with pytest.raises(RuntimeConfigurationError, match="redis_url"):
        CoordinationSettings.from_runtime_settings(
            {"backend_workers": 2},
            {"turn_coordination": {"backend": "redis", "redis_url": ""}},
        )


def test_runtime_report_never_exposes_redis_credentials() -> None:
    settings = CoordinationSettings.from_runtime_settings(
        {"backend_workers": 4},
        {
            "turn_coordination": {
                "backend": "redis",
                "redis_url": "redis://:secret@redis:6379/0",
            }
        },
    )

    report = settings.runtime_report()
    assert report["redis_configured"] is True
    assert "secret" not in repr(report)
    assert "redis_url" not in report
