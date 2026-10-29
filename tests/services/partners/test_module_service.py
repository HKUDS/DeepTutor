from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from deeptutor.services.partners import manager as manager_module
from deeptutor.services.partners.manager import PartnerManager
from deeptutor.services.partners.module_service import start_partners, stop_partners


@pytest.mark.asyncio
async def test_module_starts_real_manager_and_preserves_autostart_on_shutdown(monkeypatch):
    # Exercise the real public method (an unrestricted mock hid the name mismatch).
    manager = PartnerManager()
    monkeypatch.setattr(manager_module, "_manager", manager)
    import deeptutor.services.partners as partners

    monkeypatch.setattr(partners, "get_partner_manager", lambda: manager)
    monkeypatch.setattr(manager, "_discover_partner_ids", lambda: ["enabled", "disabled"])
    monkeypatch.setattr(manager, "_load_auto_start", lambda pid, **kw: pid == "enabled")
    config = object()
    monkeypatch.setattr(manager, "load_config", lambda pid: config)
    start = AsyncMock()
    monkeypatch.setattr(manager, "start_partner", start)
    stop = AsyncMock()
    monkeypatch.setattr(manager, "stop_all", stop)
    owner = SimpleNamespace(worker_id="test-worker")
    await start_partners(owner)
    assert manager.runtime_owner_id == "test-worker"
    start.assert_awaited_once_with("enabled", config)
    await stop_partners(owner)
    stop.assert_awaited_once_with(preserve_auto_start=True)
