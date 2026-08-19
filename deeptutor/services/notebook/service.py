"""
Shared notebook manager.

This module keeps the notebook storage format unchanged so Web and CLI
can operate on the same files under ``data/user``.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from enum import Enum
import json
import logging
from pathlib import Path
import threading
import time
import uuid

from pydantic import BaseModel

from deeptutor.services.file_io import atomic_write_json
from deeptutor.services.llm import clean_thinking_tags
from deeptutor.services.path_service import get_path_service

logger = logging.getLogger(__name__)


class RecordType(str, Enum):
    """Notebook record type."""

    SOLVE = "solve"
    QUESTION = "question"
    RESEARCH = "research"
    CHAT = "chat"
    CO_WRITER = "co_writer"
    TUTORBOT = "tutorbot"


class NotebookRecord(BaseModel):
    """Single record stored in a notebook."""

    id: str
    type: RecordType
    title: str
    summary: str = ""
    user_query: str
    output: str
    metadata: dict = {}
    created_at: float
    kb_name: str | None = None


class Notebook(BaseModel):
    """Notebook model."""

    id: str
    name: str
    description: str = ""
    created_at: float
    updated_at: float
    records: list[NotebookRecord] = []
    color: str = "#3B82F6"
    icon: str = "book"


_UNSET = object()


class NotebookCorruptedError(RuntimeError):
    """A notebook file exists on disk but its JSON could not be parsed.

    Raised instead of silently reporting "no such notebook" so a damaged
    file surfaces as a real error the caller can show, rather than as a
    notebook that appears to have vanished while its data is still there.
    """

    def __init__(self, notebook_id: str, path: Path, cause: Exception) -> None:
        super().__init__(f"Notebook {notebook_id!r} is unreadable ({path}): {cause}")
        self.notebook_id = notebook_id
        self.path = path
        self.cause = cause


def _clean_record_summary(summary: str) -> str:
    """Remove private model scratchpads before notebook summaries are persisted."""
    return clean_thinking_tags(str(summary or "")).strip()


class NotebookManager:
    """Manage notebook files stored under ``data/user/workspace/notebook``."""

    def __init__(self, base_dir: str | None = None):
        if base_dir is None:
            path_service = get_path_service()
            base_dir_path = path_service.get_notebook_dir()
        else:
            base_dir_path = Path(base_dir)

        self.base_dir = base_dir_path
        self.base_dir.mkdir(parents=True, exist_ok=True)
        self.index_file = self.base_dir / "notebooks_index.json"
        # One re-entrant lock per notebook, plus one for the shared index.
        # Every read-modify-write cycle below runs under the matching lock so
        # two concurrent saves cannot both load the same revision and clobber
        # one another. Writes themselves go through ``atomic_write_json``, so
        # a reader never observes a half-written file even across processes;
        # the locks close the remaining same-process lost-update window.
        # Lock order is always notebook-then-index, never the reverse.
        self._locks_guard = threading.Lock()
        self._notebook_locks: dict[str, threading.RLock] = {}
        self._index_lock = threading.RLock()
        self._ensure_index()

    @contextmanager
    def _locked(self, notebook_id: str) -> Iterator[None]:
        """Hold the per-notebook lock for one read-modify-write cycle."""
        with self._locks_guard:
            lock = self._notebook_locks.get(notebook_id)
            if lock is None:
                lock = threading.RLock()
                self._notebook_locks[notebook_id] = lock
        with lock:
            yield

    def _ensure_index(self) -> None:
        if not self.index_file.exists():
            atomic_write_json(self.index_file, {"notebooks": []})

    def _load_index(self) -> dict:
        try:
            with open(self.index_file, encoding="utf-8") as f:
                return json.load(f)
        except FileNotFoundError:
            return {"notebooks": []}
        except Exception as exc:
            # The index is a derived cache: every entry can be rebuilt from the
            # notebook files themselves, so recovering here loses nothing.
            logger.warning("notebook index unreadable (%s); rebuilding", exc)
            return {"notebooks": self._rebuild_index_entries()}

    def _rebuild_index_entries(self) -> list[dict]:
        """Reconstruct index rows by scanning the notebook files on disk."""
        entries: list[dict] = []
        for path in sorted(self.base_dir.glob("*.json")):
            if path == self.index_file:
                continue
            try:
                with open(path, encoding="utf-8") as f:
                    notebook = json.load(f)
            except Exception:
                continue
            entries.append(self._index_row(notebook))
        return entries

    @staticmethod
    def _index_row(notebook: dict) -> dict:
        """Project a full notebook down to the fields the index carries."""
        return {
            "id": notebook["id"],
            "name": notebook.get("name", ""),
            "description": notebook.get("description", ""),
            "created_at": notebook.get("created_at", 0.0),
            "updated_at": notebook.get("updated_at", 0.0),
            "record_count": len(notebook.get("records", [])),
            "color": notebook.get("color", "#3B82F6"),
            "icon": notebook.get("icon", "book"),
        }

    def _save_index(self, index: dict) -> None:
        atomic_write_json(self.index_file, index)

    def _get_notebook_file(self, notebook_id: str) -> Path:
        return self.base_dir / f"{notebook_id}.json"

    def _load_notebook(self, notebook_id: str) -> dict | None:
        """Return the notebook, or ``None`` when no such file exists.

        A file that exists but cannot be parsed raises
        :class:`NotebookCorruptedError` rather than returning ``None`` —
        conflating the two is what made damaged notebooks look deleted.
        """
        filepath = self._get_notebook_file(notebook_id)
        if not filepath.exists():
            return None
        try:
            with open(filepath, encoding="utf-8") as f:
                notebook = json.load(f)
        except FileNotFoundError:
            return None
        except Exception as exc:
            logger.error("notebook %s failed to load from %s: %s", notebook_id, filepath, exc)
            raise NotebookCorruptedError(notebook_id, filepath, exc) from exc
        if self._sanitize_loaded_notebook(notebook):
            try:
                self._save_notebook(notebook)
            except Exception:
                logger.warning("could not persist sanitized notebook %s", notebook_id)
        return notebook

    def _sanitize_loaded_notebook(self, notebook: dict) -> bool:
        changed = False
        records = notebook.get("records", [])
        if not isinstance(records, list):
            return False
        for record in records:
            if not isinstance(record, dict):
                continue
            raw_summary = record.get("summary", "")
            cleaned = _clean_record_summary(raw_summary)
            if cleaned != raw_summary:
                record["summary"] = cleaned
                changed = True
        return changed

    def _save_notebook(self, notebook: dict) -> None:
        atomic_write_json(self._get_notebook_file(notebook["id"]), notebook)

    def _touch_index_entry(self, notebook_id: str, notebook: dict) -> None:
        """Refresh this notebook's index row, re-adding it if it went missing."""
        with self._index_lock:
            index = self._load_index()
            rows = index.setdefault("notebooks", [])
            row = self._index_row(notebook)
            for position, nb_info in enumerate(rows):
                if nb_info.get("id") == notebook_id:
                    # Keep created_at from the index when the file lacks it.
                    row["created_at"] = notebook.get("created_at", nb_info.get("created_at", 0.0))
                    rows[position] = row
                    break
            else:
                rows.append(row)
            self._save_index(index)

    # === Notebook Operations ===

    def create_notebook(
        self, name: str, description: str = "", color: str = "#3B82F6", icon: str = "book"
    ) -> dict:
        notebook_id = str(uuid.uuid4())[:8]
        now = time.time()

        notebook = {
            "id": notebook_id,
            "name": name,
            "description": description,
            "created_at": now,
            "updated_at": now,
            "records": [],
            "color": color,
            "icon": icon,
        }

        with self._locked(notebook_id):
            self._save_notebook(notebook)
            self._touch_index_entry(notebook_id, notebook)
        return notebook

    def list_notebooks(self) -> list[dict]:
        """List every notebook on disk, newest first.

        Rows come from the index rather than from parsing each notebook in
        full, and the index is reconciled against the directory first, so a
        notebook whose index row was lost still shows up. A notebook whose
        file is damaged is reported with ``unreadable`` set instead of being
        dropped — silently omitting it is what made data look deleted.
        """
        damaged: list[dict] = []
        with self._index_lock:
            index = self._load_index()
            rows = {str(row.get("id")): row for row in index.get("notebooks", []) if row.get("id")}

            on_disk = {
                path.stem for path in self.base_dir.glob("*.json") if path != self.index_file
            }
            # Drop rows whose file is gone; adopt files the index never learned
            # about. Only the unknown files are parsed — indexed ones are taken
            # at their word, which keeps listing O(index) rather than O(content).
            changed = False
            for notebook_id in list(rows):
                if notebook_id not in on_disk:
                    rows.pop(notebook_id)
                    changed = True
            for notebook_id in sorted(on_disk - rows.keys()):
                try:
                    notebook = self._load_notebook(notebook_id)
                except NotebookCorruptedError:
                    # Surface it as a placeholder instead of dropping it: the
                    # file is still on disk and the user needs to know that.
                    damaged.append({"id": notebook_id, "unreadable": True})
                    continue
                if notebook:
                    rows[notebook_id] = self._index_row(notebook)
                    changed = True
            if changed:
                self._save_index({"notebooks": list(rows.values())})

        notebooks: list[dict] = [
            {
                "id": notebook_id,
                "name": row.get("name", ""),
                "description": row.get("description", ""),
                "created_at": row.get("created_at", 0.0),
                "updated_at": row.get("updated_at", 0.0),
                "record_count": row.get("record_count", 0),
                "color": row.get("color", "#3B82F6"),
                "icon": row.get("icon", "book"),
            }
            for notebook_id, row in rows.items()
        ]
        notebooks.sort(key=lambda x: x["updated_at"], reverse=True)

        # Damaged notebooks have no trustworthy metadata to sort by, so they
        # ride at the end with just enough for the UI to flag them.
        for entry in damaged:
            notebooks.append(
                {
                    "id": entry["id"],
                    "name": entry["id"],
                    "description": "",
                    "created_at": 0.0,
                    "updated_at": 0.0,
                    "record_count": 0,
                    "color": "#3B82F6",
                    "icon": "book",
                    "unreadable": True,
                }
            )
        return notebooks

    def get_notebook(self, notebook_id: str) -> dict | None:
        return self._load_notebook(notebook_id)

    def update_notebook(
        self,
        notebook_id: str,
        name: str | None = None,
        description: str | None = None,
        color: str | None = None,
        icon: str | None = None,
    ) -> dict | None:
        with self._locked(notebook_id):
            notebook = self._load_notebook(notebook_id)
            if not notebook:
                return None

            if name is not None:
                notebook["name"] = name
            if description is not None:
                notebook["description"] = description
            if color is not None:
                notebook["color"] = color
            if icon is not None:
                notebook["icon"] = icon

            notebook["updated_at"] = time.time()
            self._save_notebook(notebook)
            self._touch_index_entry(notebook_id, notebook)
            return notebook

    def delete_notebook(self, notebook_id: str) -> bool:
        with self._locked(notebook_id):
            filepath = self._get_notebook_file(notebook_id)
            if not filepath.exists():
                return False

            filepath.unlink()
            with self._index_lock:
                index = self._load_index()
                index["notebooks"] = [
                    nb for nb in index.get("notebooks", []) if nb.get("id") != notebook_id
                ]
                self._save_index(index)
            return True

    # === Record Operations ===

    def add_record(
        self,
        notebook_ids: list[str],
        record_type: RecordType | str,
        title: str,
        user_query: str,
        output: str,
        summary: str = "",
        metadata: dict | None = None,
        kb_name: str | None = None,
    ) -> dict:
        record_id = str(uuid.uuid4())[:8]
        now = time.time()
        # Accept both enum instances and plain string values from callers.
        resolved_type = (
            record_type if isinstance(record_type, RecordType) else RecordType(str(record_type))
        )

        record = {
            "id": record_id,
            "type": resolved_type,
            "title": title,
            "summary": _clean_record_summary(summary),
            "user_query": user_query,
            "output": output,
            "metadata": metadata or {},
            "created_at": now,
            "kb_name": kb_name,
        }

        added_to: list[str] = []
        for notebook_id in notebook_ids:
            # One lock per notebook rather than one around the whole loop:
            # the notebooks are independent files and nothing here reads two
            # of them at once, so a single wide lock would only add contention.
            with self._locked(notebook_id):
                try:
                    notebook = self._load_notebook(notebook_id)
                except NotebookCorruptedError:
                    logger.warning("skipping unreadable notebook %s while saving", notebook_id)
                    continue
                if not notebook:
                    continue
                # Each notebook stores its own copy. They share a record id so
                # the save is traceable, but editing one does not touch the
                # others — use ``copy_record`` for an explicit independent copy.
                notebook.setdefault("records", []).append(dict(record))
                notebook["updated_at"] = now
                self._save_notebook(notebook)
                self._touch_index_entry(notebook_id, notebook)
                added_to.append(notebook_id)

        return {"record": record, "added_to_notebooks": added_to}

    def get_records(self, notebook_id: str, record_ids: list[str] | None = None) -> list[dict]:
        notebook = self._load_notebook(notebook_id)
        if not notebook:
            return []

        records = list(notebook.get("records", []))
        if not record_ids:
            return records

        wanted = set(record_ids)
        return [record for record in records if str(record.get("id", "")) in wanted]

    def get_record(self, notebook_id: str, record_id: str) -> dict | None:
        records = self.get_records(notebook_id, [record_id])
        return records[0] if records else None

    def update_record(
        self,
        notebook_id: str,
        record_id: str,
        *,
        title: str | None = None,
        summary: str | None = None,
        user_query: str | None = None,
        output: str | None = None,
        metadata: dict | None = None,
        kb_name: str | None | object = _UNSET,
    ) -> dict | None:
        """Edit one record in place. Only this notebook's copy is affected.

        Every parameter defaults to "leave alone". ``kb_name`` additionally
        distinguishes *omitted* from an explicit ``None``, so a caller that
        only renames a record cannot accidentally drop its knowledge-base
        link — pass ``kb_name=None`` when clearing it is what you mean.
        """
        with self._locked(notebook_id):
            notebook = self._load_notebook(notebook_id)
            if not notebook:
                return None

            updated_record: dict | None = None
            for record in notebook.get("records", []):
                if str(record.get("id", "")) != str(record_id):
                    continue
                if title is not None:
                    record["title"] = title
                if summary is not None:
                    record["summary"] = _clean_record_summary(summary)
                if user_query is not None:
                    record["user_query"] = user_query
                if output is not None:
                    record["output"] = output
                if metadata is not None:
                    current_metadata = record.get("metadata", {}) or {}
                    record["metadata"] = {**current_metadata, **metadata}
                if kb_name is not _UNSET:
                    record["kb_name"] = kb_name
                updated_record = record
                break

            if updated_record is None:
                return None

            notebook["updated_at"] = time.time()
            self._save_notebook(notebook)
            self._touch_index_entry(notebook_id, notebook)
            return updated_record

    def get_records_by_references(self, notebook_references: list[dict]) -> list[dict]:
        resolved: list[dict] = []

        for ref in notebook_references:
            notebook_id = str(ref.get("notebook_id", "") or "").strip()
            if not notebook_id:
                continue
            record_ids = [
                str(record_id).strip()
                for record_id in (ref.get("record_ids") or [])
                if str(record_id).strip()
            ]
            try:
                notebook = self._load_notebook(notebook_id)
            except NotebookCorruptedError:
                # Resolving references feeds a chat turn; one damaged notebook
                # must not take the whole turn down with it.
                logger.warning("skipping unreadable notebook %s while resolving refs", notebook_id)
                continue
            if not notebook:
                continue

            notebook_name = str(notebook.get("name", "") or notebook_id)
            for record in self.get_records(notebook_id, record_ids):
                resolved.append(
                    {
                        **record,
                        "notebook_id": notebook_id,
                        "notebook_name": notebook_name,
                    }
                )

        return resolved

    def remove_record(self, notebook_id: str, record_id: str) -> bool:
        with self._locked(notebook_id):
            notebook = self._load_notebook(notebook_id)
            if not notebook:
                return False

            records = notebook.get("records", [])
            original_count = len(records)
            notebook["records"] = [r for r in records if str(r.get("id")) != str(record_id)]

            if len(notebook["records"]) == original_count:
                return False

            notebook["updated_at"] = time.time()
            self._save_notebook(notebook)
            self._touch_index_entry(notebook_id, notebook)
            return True

    def copy_record(
        self, source_notebook_id: str, record_id: str, target_notebook_id: str
    ) -> dict | None:
        """Duplicate a record into another notebook under a fresh id.

        The copy is independent from the moment it lands: editing either side
        leaves the other untouched. Returns ``None`` when the source record or
        the target notebook does not exist.
        """
        if source_notebook_id == target_notebook_id:
            return None

        source_record = self.get_record(source_notebook_id, record_id)
        if source_record is None:
            return None

        copied = dict(source_record)
        copied["id"] = str(uuid.uuid4())[:8]
        copied["metadata"] = {
            **(source_record.get("metadata") or {}),
            "copied_from": {"notebook_id": source_notebook_id, "record_id": record_id},
        }

        with self._locked(target_notebook_id):
            target = self._load_notebook(target_notebook_id)
            if not target:
                return None
            target.setdefault("records", []).append(copied)
            target["updated_at"] = time.time()
            self._save_notebook(target)
            self._touch_index_entry(target_notebook_id, target)
        return copied

    def move_record(
        self, source_notebook_id: str, record_id: str, target_notebook_id: str
    ) -> dict | None:
        """Move a record between notebooks.

        Writes the copy first and only then removes the original, so an
        interruption leaves the record duplicated rather than destroyed.
        """
        copied = self.copy_record(source_notebook_id, record_id, target_notebook_id)
        if copied is None:
            return None
        if not self.remove_record(source_notebook_id, record_id):
            # The copy already landed; report it rather than failing outright.
            logger.warning(
                "moved record %s into %s but could not remove the original from %s",
                record_id,
                target_notebook_id,
                source_notebook_id,
            )
        return copied

    def export_markdown(self, notebook_id: str) -> str | None:
        """Render a whole notebook as one Markdown document."""
        notebook = self._load_notebook(notebook_id)
        if not notebook:
            return None

        lines: list[str] = [f"# {notebook.get('name', notebook_id)}"]
        description = str(notebook.get("description") or "").strip()
        if description:
            lines.append("")
            lines.append(f"> {description}")

        for record in notebook.get("records", []):
            lines.append("")
            lines.append("---")
            lines.append("")
            lines.append(f"## {record.get('title') or '(untitled)'}")

            created_at = record.get("created_at")
            stamp = (
                time.strftime("%Y-%m-%d %H:%M", time.localtime(created_at)) if created_at else ""
            )
            meta_bits = [bit for bit in (str(record.get("type") or ""), stamp) if bit]
            if meta_bits:
                lines.append("")
                lines.append(f"*{' · '.join(meta_bits)}*")

            summary = str(record.get("summary") or "").strip()
            if summary:
                lines.append("")
                lines.append(f"> {summary}")

            output = str(record.get("output") or "").strip()
            if output:
                lines.append("")
                lines.append(output)

        return "\n".join(lines) + "\n"

    def get_statistics(self) -> dict:
        notebooks = self.list_notebooks()

        total_records = 0
        # Derived from the enum so a newly added record type is counted the
        # day it is introduced, instead of silently missing from the totals.
        type_counts = {member.value: 0 for member in RecordType}

        for nb_info in notebooks:
            try:
                notebook = self._load_notebook(nb_info["id"])
            except NotebookCorruptedError:
                continue
            if notebook:
                for record in notebook.get("records", []):
                    total_records += 1
                    record_type = record.get("type", "")
                    if record_type in type_counts:
                        type_counts[record_type] += 1

        return {
            "total_notebooks": len(notebooks),
            "total_records": total_records,
            "records_by_type": type_counts,
            "recent_notebooks": notebooks[:5],
        }


_instances: dict[str, NotebookManager] = {}


def get_notebook_manager() -> NotebookManager:
    base_dir = get_path_service().get_notebook_dir().resolve()
    key = str(base_dir)
    if key not in _instances:
        _instances[key] = NotebookManager(base_dir=str(base_dir))
    return _instances[key]


class _NotebookManagerProxy:
    def __getattr__(self, name: str):
        return getattr(get_notebook_manager(), name)


notebook_manager = _NotebookManagerProxy()
