from datetime import datetime, timedelta

from deeptutor.api.utils.task_id_manager import TaskIDManager


def _manager() -> TaskIDManager:
    manager = TaskIDManager()
    manager._task_ids = {}
    manager._task_metadata = {}
    return manager


def test_generate_prunes_expired_completed_tasks() -> None:
    manager = _manager()
    old_id = manager.generate_task_id("kb", "old")
    manager.update_task_status(old_id, "completed")
    manager._task_metadata[old_id]["finished_at"] = (
        datetime.now() - timedelta(hours=25)
    ).isoformat()

    manager.generate_task_id("kb", "new")

    assert old_id not in manager._task_metadata
    assert "old" not in manager._task_ids


def test_completed_task_metadata_has_hard_count_bound() -> None:
    manager = _manager()
    manager._MAX_COMPLETED_TASKS = 3

    for index in range(8):
        task_id = manager.generate_task_id("kb", f"task-{index}")
        manager.update_task_status(task_id, "completed")

    manager.cleanup_old_tasks()

    assert len(manager._task_metadata) == 3
    assert len(manager._task_ids) == 3
