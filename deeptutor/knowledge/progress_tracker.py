"""
Progress Tracker - Tracks knowledge base initialization progress
"""

import asyncio
from collections.abc import Callable
from datetime import datetime
from enum import Enum
import json
import logging
from pathlib import Path

# Use unified logging system
from deeptutor.logging import get_logger

_logger = get_logger("KnowledgeInit")


def _get_logger():
    return _logger


class ProgressStage(Enum):
    """Initialization stage"""

    INITIALIZING = "initializing"  # Initializing
    PROCESSING_DOCUMENTS = "processing_documents"  # Processing documents
    PROCESSING_FILE = "processing_file"  # Processing single file
    EXTRACTING_ITEMS = "extracting_items"  # Extracting numbered items
    COMPLETED = "completed"  # Completed
    ERROR = "error"  # Error


class ProgressTracker:
    """Progress tracker"""

    def __init__(self, kb_name: str, base_dir: Path):
        self.kb_name = kb_name
        self.base_dir = base_dir
        self.kb_dir = base_dir / kb_name
        self.progress_file = self.kb_dir / ".progress.json"
        self._callbacks: list = []  # Support multiple callbacks
        self.task_id: str | None = None  # Task ID (for log identification)

    def set_callback(self, callback: Callable[[dict], None]):
        """Set progress callback function (can be called multiple times to add multiple callbacks)"""
        if callback not in self._callbacks:
            self._callbacks.append(callback)

    def remove_callback(self, callback: Callable[[dict], None]):
        """Remove progress callback function"""
        if callback in self._callbacks:
            self._callbacks.remove(callback)

    def _notify(self, progress: dict):
        """Notify progress update (call all callbacks)"""
        from deeptutor.runtime.mode import is_server

        if is_server():
            try:
                from deeptutor.api.utils.progress_broadcaster import ProgressBroadcaster

                broadcaster = ProgressBroadcaster.get_instance()

                try:
                    asyncio.get_running_loop()
                    asyncio.create_task(broadcaster.broadcast(self.kb_name, progress))
                except RuntimeError:
                    try:
                        loop = asyncio.get_event_loop()
                        if loop.is_running():
                            asyncio.create_task(broadcaster.broadcast(self.kb_name, progress))
                    except RuntimeError:
                        pass
            except (ImportError, Exception):
                pass

        for callback in self._callbacks:
            try:
                callback(progress)
            except Exception as e:
                _get_logger().debug("Progress callback error: %s", e)

    def _save_progress(self, progress: dict):
        """Save progress to kb_config.json and local .progress.json file"""
        # Save to kb_config.json (centralized config)
        try:
            from deeptutor.knowledge.manager import KnowledgeBaseManager

            manager = KnowledgeBaseManager(base_dir=str(self.base_dir))

            # Determine status based on stage
            stage = progress.get("stage", "")
            if stage == "completed":
                status = "ready"
            elif stage == "error":
                status = "error"
            elif stage in [
                "initializing",
                "processing_documents",
                "processing_file",
                "extracting_items",
            ]:
                status = "processing"
            else:
                status = "initializing"

            # Update kb_config.json with status and progress
            manager.update_kb_status(
                name=self.kb_name,
                status=status,
                progress={
                    "stage": progress.get("stage"),
                    "message": progress.get("message"),
                    "percent": progress.get("progress_percent", 0),
                    "current": progress.get("current", 0),
                    "total": progress.get("total", 0),
                    "file_name": progress.get("file_name"),
                    "error": progress.get("error"),
                    "timestamp": progress.get("timestamp"),
                    "task_id": progress.get("task_id"),
                },
            )
        except Exception as e:
            _get_logger().warning("Failed to save progress to kb_config.json: %s", e)

        # Persist the last seen progress snapshot so websocket subscribers and
        # page reloads can recover the live state without relying on in-memory callbacks.
        try:
            self.kb_dir.mkdir(parents=True, exist_ok=True)
            temp_progress_file = self.progress_file.parent / f"{self.progress_file.name}.tmp"
            with open(temp_progress_file, "w", encoding="utf-8") as f:
                json.dump(progress, f, indent=2, ensure_ascii=False)
                f.flush()
            temp_progress_file.replace(self.progress_file)
        except Exception as e:
            _get_logger().warning(
                "Failed to persist progress snapshot for '%s': %s", self.kb_name, e
            )

    def update(
        self,
        stage: ProgressStage,
        message: str = "",
        current: int = 0,
        total: int = 0,
        file_name: str = "",
        error: str | None = None,
    ):
        """Update progress"""
        progress = {
            "kb_name": self.kb_name,
            "task_id": self.task_id,
            "stage": stage.value,
            "message": message,
            "current": current,
            "total": total,
            "file_name": file_name,
            "progress_percent": int(current / total * 100) if total > 0 else 0,
            "timestamp": datetime.now().isoformat(),
        }

        if error:
            progress["error"] = error
            progress["stage"] = ProgressStage.ERROR.value

        # Output to logger (terminal and log file)
        try:
            logger = _get_logger()
            prefix = f"[{self.task_id}]" if self.task_id else ""

            if total > 0:
                percent = progress["progress_percent"]
                progress_msg = f"{prefix} {message} ({current}/{total}, {percent}%)"
                if file_name:
                    progress_msg += f" - File: {file_name}"
            else:
                progress_msg = f"{prefix} {message}"
                if file_name:
                    progress_msg += f" - File: {file_name}"

            if error:
                logger.error(f"{progress_msg} - Error: {error}")
            else:
                logger.progress(progress_msg)
        except Exception:
            # If unified logging fails unexpectedly, use stdlib logger as fallback.
            fallback_logger = logging.getLogger("deeptutor.ProgressTracker")
            prefix = f"[{self.task_id}]" if self.task_id else ""
            fallback_logger.warning(
                "%s [ProgressTracker] %s (%s/%s)",
                prefix,
                message,
                current,
                total if total > 0 else "?",
            )
            if error:
                fallback_logger.error("%s [ProgressTracker] Error: %s", prefix, error)

        self._save_progress(progress)

        if self.task_id:
            try:
                from deeptutor.api.utils.task_log_stream import get_task_stream_manager

                get_task_stream_manager().emit(self.task_id, "progress", progress)
            except Exception as e:
                _get_logger().debug("Failed to emit task progress event: %s", e)

        self._notify(progress)

    def get_progress(self) -> dict | None:
        """Get current progress"""
        if self.progress_file.exists():
            try:
                with open(self.progress_file, encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                _get_logger().debug(f"Failed to read progress file for '{self.kb_name}': {e}")

        try:
            from deeptutor.knowledge.manager import KnowledgeBaseManager

            manager = KnowledgeBaseManager(base_dir=str(self.base_dir))
            status = manager.get_kb_status(self.kb_name)
            if status and status.get("progress"):
                return status.get("progress")
        except Exception as e:
            _get_logger().debug(
                "Failed to recover progress snapshot from kb_config for '%s': %s",
                self.kb_name,
                e,
            )

        return None

    def clear(self):
        """Clear progress file"""
        if self.progress_file.exists():
            try:
                self.progress_file.unlink()
            except Exception as e:
                _get_logger().debug(f"Failed to clear progress file for '{self.kb_name}': {e}")
