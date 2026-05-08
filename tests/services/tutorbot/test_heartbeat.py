"""Tests for HeartbeatService and heartbeat config."""

from __future__ import annotations

import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from deeptutor.services.tutorbot.manager import BotConfig, TutorBotManager


# ---------------------------------------------------------------------------
# HeartbeatService._has_active_tasks
# ---------------------------------------------------------------------------


class TestHasActiveTasks:
    """Unit tests for _has_active_tasks parsing logic."""

    @pytest.fixture
    def hs(self) -> object:
        """Return a HeartbeatService instance with a dummy workspace."""
        from deeptutor.tutorbot.heartbeat.service import HeartbeatService

        return HeartbeatService(
            workspace=Path("/dev/null"),
            provider=MagicMock(),
            model="test-model",
            bot_id="test-bot",
        )

    def test_empty_content(self, hs: object) -> None:
        assert hs._has_active_tasks("") is False

    def test_only_headers_and_comments(self, hs: object) -> None:
        content = """# Heartbeat Tasks
## Active Tasks

<!-- Add your periodic tasks below this line -->

## Completed
"""
        assert hs._has_active_tasks(content) is False

    def test_real_task_lines(self, hs: object) -> None:
        content = """## Active Tasks

### Daily Reminder
**Status:** ACTIVE
**Schedule:** Every day at 09:00
"""
        assert hs._has_active_tasks(content) is True

    def test_real_task_with_html_comments(self, hs: object) -> None:
        content = """# Heartbeat Tasks
## Active Tasks

<!-- Add your periodic tasks below this line -->
### Morning Reminder
**Status:** ACTIVE

## Completed
"""
        assert hs._has_active_tasks(content) is True

    def test_no_active_tasks_section(self, hs: object) -> None:
        content = """# Heartbeat Tasks

## Completed
<!-- Move completed tasks here -->
"""
        assert hs._has_active_tasks(content) is False

    def test_case_insensitive_section_detection(self, hs: object) -> None:
        content = """## active tasks

### Task
**Status:** ACTIVE
"""
        assert hs._has_active_tasks(content) is True

    def test_multiple_tasks(self, hs: object) -> None:
        content = """## Active Tasks

### Task 1
**Status:** ACTIVE

### Task 2
**Status:** ACTIVE
"""
        assert hs._has_active_tasks(content) is True

    def test_tasks_in_completed_section_not_counted(self, hs: object) -> None:
        content = """## Active Tasks

<!-- empty -->

## Completed

### Old Task
**Status:** DONE
"""
        assert hs._has_active_tasks(content) is False


# ---------------------------------------------------------------------------
# BotConfig heartbeat_interval_s roundtrip
# ---------------------------------------------------------------------------


class TestHeartbeatIntervalRoundtrip:
    """Test that heartbeat_interval_s survives save/load roundtrip."""

    def test_save_load_preserves_heartbeat_interval(self, tmp_path: Path) -> None:
        mgr = TutorBotManager()
        mgr._path_service = SimpleNamespace(  # type: ignore[assignment]
            project_root=tmp_path,
            get_memory_dir=lambda: tmp_path / "memory",
        )

        cfg = BotConfig(
            name="hb-bot",
            heartbeat_interval_s=900,
        )
        mgr.save_bot_config("hb-bot", cfg)

        loaded = mgr.load_bot_config("hb-bot")
        assert loaded is not None
        assert loaded.heartbeat_interval_s == 900

    def test_save_load_uses_default_when_missing(self, tmp_path: Path) -> None:
        mgr = TutorBotManager()
        mgr._path_service = SimpleNamespace(  # type: ignore[assignment]
            project_root=tmp_path,
            get_memory_dir=lambda: tmp_path / "memory",
        )

        cfg = BotConfig(name="hb-bot-default")
        mgr.save_bot_config("hb-bot-default", cfg)

        # Simulate old config file without heartbeat_interval_s
        bot_dir = mgr._bot_dir("hb-bot-default")
        # Rewrite without heartbeat_interval_s
        (bot_dir / "config.yaml").write_text(
            f"name: {cfg.name}\ndescription: {cfg.description}\n"
        )

        loaded = mgr.load_bot_config("hb-bot-default")
        assert loaded is not None
        # Default value
        assert loaded.heartbeat_interval_s == 30 * 60


# ---------------------------------------------------------------------------
# reload_heartbeat
# ---------------------------------------------------------------------------


class TestReloadHeartbeat:
    """Test TutorBotManager.reload_heartbeat hot-update."""

    def test_reload_updates_interval(self, tmp_path: Path) -> None:
        mgr = TutorBotManager()
        mgr._path_service = SimpleNamespace(  # type: ignore[assignment]
            project_root=tmp_path,
            get_memory_dir=lambda: tmp_path / "memory",
        )

        original_cfg = BotConfig(name="reload-bot", heartbeat_interval_s=1800)
        mgr.save_bot_config("reload-bot", original_cfg)

        # Create a running instance with a heartbeat service
        class FakeHeartbeat:
            interval_s = 1800

        instance = SimpleNamespace()
        instance.config = original_cfg
        instance.running = True
        instance.heartbeat = FakeHeartbeat()
        instance.tasks = []
        mgr._bots["reload-bot"] = instance

        # Update config on disk
        new_cfg = BotConfig(name="reload-bot", heartbeat_interval_s=600)
        mgr.save_bot_config("reload-bot", new_cfg)

        async def run() -> None:
            await mgr.reload_heartbeat("reload-bot")

        asyncio.run(run())

        assert instance.heartbeat.interval_s == 600
