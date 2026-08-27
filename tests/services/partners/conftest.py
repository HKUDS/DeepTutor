"""Fixtures for the partners service suite — isolate all paths under tmp_path.

Also holds the scripted-orchestrator scaffolding every runtime-level test
needs: a partner turn is a chat-loop run, and the tests care about what the
runner does with the loop's events, not about the loop itself.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from deeptutor.core.stream import StreamEvent


@pytest.fixture
def partners_root(tmp_path, monkeypatch) -> Path:
    """Redirect the admin workspace (and multi-user roots) under ``tmp_path``.

    Everything the partners layer touches resolves through
    ``deeptutor.multi_user.paths`` — the partners data dir is anchored at the
    admin workspace root and partner scopes are synthetic ``UserScope``s — so
    patching that module covers the partners layer itself.

    ``identity`` is a second front, and patching ``paths`` does *not* reach it:
    it binds ``AUTH_DIR = SYSTEM_ROOT / "auth"`` at import, so a later
    ``setattr`` on ``paths.SYSTEM_ROOT`` leaves its module-level file constants
    pointing at the real ``data/system/auth/``. Any test that saves a user was
    therefore writing into the developer's own account store, and reading it
    back — which made the outcome depend on who already had an account there,
    since the first account in a store is force-promoted to admin.
    """
    from deeptutor.multi_user import identity, paths

    project_root = tmp_path
    admin_root = (project_root / "data").resolve()
    monkeypatch.setattr(paths, "PROJECT_ROOT", project_root)
    monkeypatch.setattr(paths, "ADMIN_WORKSPACE_ROOT", admin_root)
    monkeypatch.setattr(paths, "USERS_ROOT", admin_root / "users")
    monkeypatch.setattr(paths, "SYSTEM_ROOT", admin_root / "system")
    monkeypatch.setattr(paths, "_path_services", {})

    auth_dir = admin_root / "system" / "auth"
    monkeypatch.setattr(identity, "AUTH_DIR", auth_dir)
    monkeypatch.setattr(identity, "USERS_FILE", auth_dir / "users.json")
    monkeypatch.setattr(identity, "SECRET_FILE", auth_dir / "auth_secret")
    monkeypatch.setattr(identity, "LEGACY_USERS_FILE", project_root / "legacy_users.json")
    monkeypatch.setattr(identity, "LEGACY_SECRET_FILE", project_root / "legacy_secret")

    admin_root.mkdir(parents=True, exist_ok=True)
    return admin_root / "partners"


class _FakeOrchestrator:
    """Yields a scripted event sequence instead of running the chat loop."""

    script: list[StreamEvent] = []
    # Optional queue of per-turn scripts; when non-empty, each handle() call
    # pops the next one (lets tests model a failed turn + a backup retry).
    scripts: list[list[StreamEvent]] = []
    seen_contexts: list[Any] = []
    activated_selections: list[Any] = []
    # The memory root in effect while the turn runs — proves the partner reads
    # the owner's (admin) memory via memory_path_service_override, not its own.
    seen_memory_roots: list[Any] = []

    def __init__(self) -> None:
        pass

    async def handle(self, context):
        from deeptutor.services.memory.paths import memory_root

        type(self).seen_contexts.append(context)
        type(self).seen_memory_roots.append(memory_root())
        script = type(self).scripts.pop(0) if type(self).scripts else type(self).script
        for event in script:
            yield event


@pytest.fixture
def fake_orchestrator(monkeypatch):
    import deeptutor.runtime.orchestrator as orch_mod
    from deeptutor.services.model_selection import runtime as selection_runtime

    _FakeOrchestrator.script = []
    _FakeOrchestrator.scripts = []
    _FakeOrchestrator.seen_contexts = []
    _FakeOrchestrator.activated_selections = []
    _FakeOrchestrator.seen_memory_roots = []
    monkeypatch.setattr(orch_mod, "ChatOrchestrator", _FakeOrchestrator)

    def _record_activate(selection):
        _FakeOrchestrator.activated_selections.append(selection)
        return (None, None)

    monkeypatch.setattr(selection_runtime, "activate_llm_selection", _record_activate)
    monkeypatch.setattr(selection_runtime, "reset_llm_selection", lambda token: None)
    return _FakeOrchestrator
