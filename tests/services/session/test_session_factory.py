from __future__ import annotations

import deeptutor.services.session as session_package
import deeptutor.services.session.turn_runtime as turn_runtime_module


def test_pocketbase_store_and_runtime_factories_are_stable(
    monkeypatch,
) -> None:
    """One configured PocketBase scope must resolve to one process-local runtime."""

    monkeypatch.setattr(
        "deeptutor.services.pocketbase_client.is_pocketbase_enabled",
        lambda: True,
    )
    monkeypatch.setattr(
        "deeptutor.services.config.load_integrations_settings",
        lambda: {"pocketbase_url": "http://pocketbase:8090"},
    )
    session_package._pocketbase_store_instances.clear()
    turn_runtime_module._runtime_instances.clear()

    first_store = session_package.get_session_store()
    second_store = session_package.get_session_store()
    first_runtime = turn_runtime_module.get_turn_runtime_manager()
    second_runtime = turn_runtime_module.get_turn_runtime_manager()

    assert first_store is second_store
    assert first_runtime is second_runtime
    assert first_runtime.store is first_store
    assert len(turn_runtime_module._runtime_instances) == 1
