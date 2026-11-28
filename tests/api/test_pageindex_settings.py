"""PageIndex engine settings preserve independent Cloud and OSS values."""

from __future__ import annotations

from pydantic import ValidationError
import pytest

from deeptutor.api.routers import knowledge
from deeptutor.services.config.runtime_settings import RuntimeSettingsService


@pytest.fixture
def settings(tmp_path, monkeypatch):
    service = RuntimeSettingsService(tmp_path, process_env={})
    service.save_pageindex({"api_key": "cloud-secret", "oss_summary_concurrency": 2})
    monkeypatch.setattr("deeptutor.services.config.get_runtime_settings_service", lambda: service)
    return service


@pytest.mark.asyncio
async def test_pageindex_settings_updates_preserve_other_engine_values(settings):
    result = await knowledge.update_pageindex_pipeline_config(
        knowledge.PageIndexConfigUpdate(oss_summary_concurrency=3)
    )
    assert result == {"api_key_set": True, "configured": True, "oss_summary_concurrency": 3}
    assert settings.load_pageindex()["api_key"] == "cloud-secret"

    result = await knowledge.update_pageindex_pipeline_config(
        knowledge.PageIndexConfigUpdate(api_key="replacement")
    )
    assert result["oss_summary_concurrency"] == 3
    assert settings.load_pageindex()["api_key"] == "replacement"

    result = await knowledge.update_pageindex_pipeline_config(
        knowledge.PageIndexConfigUpdate(oss_summary_concurrency=None)
    )
    assert result["oss_summary_concurrency"] is None
    assert result["api_key_set"] is True
    assert "api_key" not in result


@pytest.mark.parametrize("value", [0, -1, 129, 1.5, "2", True])
def test_pageindex_settings_reject_invalid_concurrency(value):
    with pytest.raises(ValidationError):
        knowledge.PageIndexConfigUpdate(oss_summary_concurrency=value)
