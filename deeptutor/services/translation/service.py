"""Generic translation task queue and board.

The queue is deliberately independent of the producers. Book paragraphs and
knowledge-base documents only provide source adapters; task state, priority,
execution, retries, and the board contract live here.
"""

from __future__ import annotations

import asyncio
from collections import Counter, deque
import html
import json
from pathlib import Path
import re
import time
from typing import Any, Literal
import uuid

from deeptutor.knowledge.naming import validate_knowledge_base_name
from deeptutor.services.file_io import atomic_write_json
from deeptutor.services.path_service import get_path_service

from .glossary import (
    extract_glossary_candidates,
    merge_glossary,
    review_glossary_candidates,
    terms_for_text,
)
from .repository import TranslationStateRepository

TranslationSourceType = Literal["bilingual", "kb_document"]
_PRIORITY_RANK = {"high": 0, "normal": 1, "low": 2}
_TEXT_SUFFIXES = {".html", ".htm", ".md", ".markdown", ".txt"}
_MAX_SOURCE_ID_LENGTH = 300


def _read_json(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return default


def _write_json(path: Path, value: Any) -> None:
    atomic_write_json(path, value)


def _validate_pairing_id(pairing_id: str) -> str:
    normalized = pairing_id.strip()
    if not normalized or len(normalized) > _MAX_SOURCE_ID_LENGTH:
        raise ValueError("Invalid bilingual pairing id")
    if (
        normalized in {".", ".."}
        or any(separator in normalized for separator in ("/", "\\", ":"))
        or any(ord(char) < 32 or ord(char) == 127 for char in normalized)
    ):
        raise ValueError("Invalid bilingual pairing id")
    return normalized


def _resolve_under_root(root: Path, relative: str | Path, *, label: str) -> Path:
    root = root.resolve()
    candidate = (root / relative).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise ValueError(f"Invalid {label} path") from exc
    return candidate


def _pairing_root(pairing_id: str) -> Path:
    normalized = _validate_pairing_id(pairing_id)
    path_service = get_path_service()
    bilingual_root = path_service.get_immersive_reading_bilingual_dir().resolve()
    root = path_service.get_immersive_reading_pairing_root(normalized).resolve()
    if not root.is_relative_to(bilingual_root):
        raise ValueError("Invalid bilingual pairing id")
    return root


def _html_to_text(markup: str) -> str:
    text = re.sub(r"(?is)<(script|style)\b.*?</\1>", " ", markup)
    text = re.sub(r"(?i)<br\s*/?>", "\n", text)
    text = re.sub(r"(?i)</p\s*>", "\n\n", text)
    return html.unescape(re.sub(r"<[^>]+>", " ", text)).strip()


def _is_technical_chapter(title: str, text: str) -> bool:
    sample = f"{title}\n{text}".lower()
    markers = (
        "api",
        "algorithm",
        "compiler",
        "database",
        "deployment",
        "framework",
        "function",
        "http",
        "kubernetes",
        "library",
        "model",
        "network",
        "protocol",
        "runtime",
        "server",
        "software",
        "system",
        "test",
        "架构",
        "接口",
        "算法",
        "部署",
    )
    return any(marker in sample for marker in markers)


class TranslationTaskService:
    """Persistent, process-local task board shared by all translation sources."""

    def __init__(self, state_path: Path | None = None):
        state_path = state_path or (
            get_path_service().workspace_root / "translation" / "tasks.json"
        )
        self._repository = TranslationStateRepository(state_path)
        self._execution_lock = asyncio.Lock()
        self._run_tasks: dict[str, asyncio.Task[Any]] = {}
        self._listeners: set[asyncio.Queue[dict[str, Any]]] = set()
        self._run_events: dict[str, deque[dict[str, Any]]] = {}
        self._recover_interrupted_tasks()

    def _load(self) -> dict[str, Any]:
        state = self._repository.read()
        if state.get("version", 1) < 2:
            state["version"] = 2
        return state

    @property
    def _state_path(self) -> Path:
        return self._repository.path

    def _save(self, state: dict[str, Any]) -> None:
        state["version"] = 2
        with self._repository.transaction() as current:
            current.clear()
            current.update(state)

    def _recover_interrupted_tasks(self) -> None:
        with self._repository.transaction() as state:
            changed = False
            if state.get("is_running"):
                state["is_running"] = False
                changed = True
            for task in state["tasks"]:
                if task.get("status") != "running":
                    continue
                task.update(status="queued", started_at=None, updated_at=time.time())
                changed = True
            for run in state.setdefault("runs", {}).values():
                if run.get("status") in {"queued", "running"}:
                    run.update(
                        status="failed",
                        completed_at=time.time(),
                        error="Interrupted by service restart",
                    )
            if changed or state.get("version", 1) < 2:
                state["version"] = 2
                changed = True

    def _board(
        self,
        *,
        source_type: str | None = None,
        source_id: str | None = None,
        chapter_id: str | None = None,
        status: str | None = None,
        limit: int = 200,
        offset: int = 0,
    ) -> dict[str, Any]:
        state = self._load()
        tasks = [
            task
            for task in state["tasks"]
            if (source_type is None or task.get("source_type") == source_type)
            and (source_id is None or task.get("source_id") == source_id)
            and (
                chapter_id is None or str(task.get("chapter_id") or task.get("title")) == chapter_id
            )
            and (status is None or task.get("status") == status)
        ]
        tasks.sort(
            key=lambda task: (
                _PRIORITY_RANK.get(task.get("priority"), 3),
                int(task.get("chapter_index", 0)),
                int(task.get("group_index", 0)),
                str(task.get("created_at", 0)),
            )
        )
        selected = tasks[offset : offset + max(1, min(limit, 500))]
        counts = Counter(task.get("status", "queued") for task in state["tasks"])
        filtered_counts = Counter(task.get("status", "queued") for task in tasks)
        board = {
            "tasks": [self._public_task(task) for task in selected],
            "summary": {
                "total": len(state["tasks"]),
                "queued": counts["queued"],
                "running": counts["running"],
                "completed": counts["completed"],
                "failed": counts["failed"],
                "cancelled": counts["cancelled"],
                "filtered_total": len(tasks),
                "filtered_queued": filtered_counts["queued"],
                "filtered_running": filtered_counts["running"],
                "filtered_completed": filtered_counts["completed"],
                "filtered_failed": filtered_counts["failed"],
                "filtered_cancelled": filtered_counts["cancelled"],
                "is_running": bool(state.get("is_running")),
                "last_run_at": float(state.get("last_run_at") or 0),
            },
            "sources": self.list_sources(),
        }
        if source_type == "bilingual" and source_id:
            board["chapters"] = self._bilingual_chapter_summaries(source_id)
        if source_type == "kb_document" and source_id:
            board["documents"] = self._kb_document_summaries(source_id)
        glossary_key = f"{source_type}:{source_id}"
        if glossary_key in state.get("glossaries", {}):
            board["glossary"] = state["glossaries"][glossary_key]
        return board

    @staticmethod
    def _bilingual_chapter_summaries(pairing_id: str) -> list[dict[str, Any]]:
        root = _pairing_root(pairing_id)
        chapter_map = _read_json(root / "chapter_map.json", [])
        result = []
        for index, entry in enumerate(chapter_map):
            chapter_id = str(entry[0])
            groups = _read_json(root / "sections" / f"{chapter_id}.json", {}).get("groups", [])
            total = len(groups)
            translated = sum(
                1 for group in groups if any(str(text).strip() for text in group.get("zh", []))
            )
            result.append(
                {
                    "chapter_id": chapter_id,
                    "chapter_index": index,
                    "title": str(entry[3] or chapter_id),
                    "total_units": total,
                    "translated_units": translated,
                    "completed": total > 0 and translated == total,
                }
            )
        return result

    def _kb_document_summaries(self, kb_name: str) -> list[dict[str, Any]]:
        document_root = self._kb_document_root(kb_name)
        result = []
        for document in sorted(
            path
            for path in document_root.rglob("*")
            if path.is_file()
            and path.suffix.lower() in _TEXT_SUFFIXES
            and not any(part.startswith(".") for part in path.relative_to(document_root).parts)
        ):
            relative = document.relative_to(document_root).as_posix()
            completed = bool(
                _read_json(document.parent / ".translations" / f"{document.name}.json")
            )
            result.append(
                {
                    "document_path": relative,
                    "title": relative,
                    "completed": completed,
                }
            )
        return result

    @staticmethod
    def _public_task(task: dict[str, Any]) -> dict[str, Any]:
        public = dict(task)
        public["source_text"] = public.get("source_text", "")[:300]
        public.pop("translation", None)
        return public

    def list_sources(self) -> list[dict[str, Any]]:
        state = self._load()
        result: list[dict[str, Any]] = []
        for key, stats in state.get("sources", {}).items():
            source_type, source_id = key.split(":", 1)
            live_stats = self._live_source_stats(source_type, source_id)
            result.append(
                {
                    "source_type": source_type,
                    "source_id": source_id,
                    **(live_stats or stats),
                }
            )
        return sorted(result, key=lambda item: (item["source_type"], item["source_id"]))

    def _live_source_stats(self, source_type: str, source_id: str) -> dict[str, Any] | None:
        """Recompute coverage from sinks so completed runs refresh immediately."""
        try:
            if source_type == "bilingual":
                chapters = self._bilingual_chapter_summaries(source_id)
                total_units = sum(item["total_units"] for item in chapters)
                translated_units = sum(item["translated_units"] for item in chapters)
            elif source_type == "kb_document":
                documents = self._kb_document_summaries(source_id)
                total_units = len(documents)
                translated_units = sum(1 for item in documents if item["completed"])
            else:
                return None
        except (OSError, ValueError):
            return None
        return {
            "total_units": total_units,
            "translated_units": translated_units,
            "all_translated": total_units > 0 and translated_units == total_units,
        }

    def _update_source_stats(
        self,
        state: dict[str, Any],
        source_type: str,
        source_id: str,
        label: str,
        total_units: int,
        translated_units: int,
    ) -> None:
        state["sources"][f"{source_type}:{source_id}"] = {
            "label": label,
            "total_units": total_units,
            "translated_units": translated_units,
            "all_translated": total_units > 0 and translated_units == total_units,
            "updated_at": time.time(),
        }

    def _preserve_task_state(self, old: dict[str, Any], task: dict[str, Any]) -> None:
        if not old:
            return
        status = old.get("status") if old.get("status") != "running" else "queued"
        task.update(
            status=status,
            attempts=int(old.get("attempts", 0)),
            error=str(old.get("error", "")),
            created_at=float(old.get("created_at", task["created_at"])),
            updated_at=float(old.get("updated_at", task["updated_at"])),
            started_at=old.get("started_at"),
            completed_at=old.get("completed_at"),
        )

    @staticmethod
    def _refresh_glossary(
        state: dict[str, Any],
        source_type: str,
        source_id: str,
        texts: list[str],
        reviewed_glossary: list[dict[str, Any]] | None = None,
    ) -> list[dict[str, Any]]:
        key = f"{source_type}:{source_id}"
        existing = state.setdefault("glossaries", {}).get(key, [])
        candidates = (
            reviewed_glossary
            if reviewed_glossary is not None
            else extract_glossary_candidates(texts)
        )
        merged = merge_glossary(existing, candidates)
        state["glossaries"][key] = merged
        return merged

    def _plan_bilingual_unlocked(
        self,
        pairing_id: str,
        *,
        force: bool = False,
        reviewed_glossary: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        root = _pairing_root(pairing_id)
        pairing = _read_json(root / "pairing.json")
        if not pairing:
            raise ValueError("Bilingual pairing not found")
        if not pairing.get("aligned"):
            raise ValueError("Pairing has not been aligned yet")
        chapter_map = _read_json(root / "chapter_map.json", [])
        position = _read_json(root / "reading_position.json") or {}
        annotations = _read_json(root / "annotations.json", [])
        flagged = {
            (item.get("chapter_id"), int(item.get("group_index", -1)))
            for item in annotations
            if item.get("status") == "open"
        }
        current_chapter = max(
            0, min(int(position.get("chapter_index", 0)), max(0, len(chapter_map) - 1))
        )
        state = self._load()
        old_tasks = {
            item.get("id"): item
            for item in state["tasks"]
            if item.get("source_type") == "bilingual" and item.get("source_id") == pairing_id
        }
        if force:
            state["tasks"] = [item for item in state["tasks"] if item.get("id") not in old_tasks]
            old_tasks = {}
        new_tasks: list[dict[str, Any]] = []
        total_units = 0
        translated_units = 0
        glossary = self._refresh_glossary(
            state,
            "bilingual",
            pairing_id,
            [
                str(text)
                for section in (
                    _read_json(root / "sections" / f"{str(entry[0])}.json", {})
                    for entry in chapter_map
                )
                for group in section.get("groups", [])
                for text in group.get("en", [])
            ],
            reviewed_glossary,
        )

        for chapter_index, entry in enumerate(chapter_map):
            chapter_id = str(entry[0])
            section_path = root / "sections" / f"{chapter_id}.json"
            section = _read_json(section_path, {})
            groups = section.get("groups", [])
            chapter_text = "\n".join(text for group in groups for text in group.get("en", []))
            technical = _is_technical_chapter(str(entry[3] or ""), chapter_text)
            priority_window = (
                chapter_index >= current_chapter
                if technical
                else chapter_index < 3 or chapter_index >= current_chapter
            )
            for group_index, group in enumerate(groups):
                total_units += 1
                source_text = "\n\n".join(str(text) for text in group.get("en", []))
                has_translation = any(str(text).strip() for text in group.get("zh", []))
                if has_translation:
                    translated_units += 1
                reasons = []
                if (chapter_id, group_index) in flagged:
                    reasons.append("flagged")
                if not has_translation:
                    reasons.append("missing_translation")
                elif group.get("low_confidence"):
                    reasons.append("low_confidence")
                if not reasons:
                    continue
                task_id = f"bilingual:{pairing_id}:{chapter_id}:{group_index}"
                now = time.time()
                task = {
                    "id": task_id,
                    "source_type": "bilingual",
                    "source_id": pairing_id,
                    "source_label": pairing.get("en_title", pairing_id),
                    "title": str(entry[3] or chapter_id),
                    "chapter_index": chapter_index,
                    "chapter_id": chapter_id,
                    "group_index": group_index,
                    "source_text": source_text[:12_000],
                    "glossary": terms_for_text(glossary, source_text),
                    "target_language": pairing.get("target_lang", "Chinese"),
                    "reason": reasons[0],
                    "priority": "high" if priority_window or "flagged" in reasons else "normal",
                    "book_type": "technical" if technical else "general",
                    "priority_window": priority_window,
                    "status": "queued",
                    "attempts": 0,
                    "error": "",
                    "created_at": now,
                    "updated_at": now,
                    "started_at": None,
                    "completed_at": None,
                }
                self._preserve_task_state(old_tasks.get(task_id, {}), task)
                new_tasks.append(task)

        state["tasks"] = [item for item in state["tasks"] if item.get("id") not in old_tasks]
        state["tasks"].extend(new_tasks)
        self._update_source_stats(
            state,
            "bilingual",
            pairing_id,
            pairing.get("en_title", pairing_id),
            total_units,
            translated_units,
        )
        self._save(state)
        return self._board(source_type="bilingual", source_id=pairing_id)

    def plan_bilingual(
        self,
        pairing_id: str,
        *,
        force: bool = False,
        reviewed_glossary: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        with self._repository.locked():
            return self._plan_bilingual_unlocked(
                pairing_id,
                force=force,
                reviewed_glossary=reviewed_glossary,
            )

    def _kb_document_root(self, kb_name: str) -> Path:
        normalized = validate_knowledge_base_name(kb_name)
        knowledge_root = get_path_service().get_knowledge_bases_root().resolve()
        root = (knowledge_root / normalized).resolve()
        if not root.is_dir() or not root.is_relative_to(knowledge_root):
            raise ValueError("Knowledge base not found")
        raw_root = (root / "raw").resolve()
        if not raw_root.is_dir() or not raw_root.is_relative_to(root):
            raise ValueError("Knowledge base not found")
        return raw_root

    def _plan_kb_unlocked(
        self,
        kb_name: str,
        *,
        force: bool = False,
        limit: int = 200,
        reviewed_glossary: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        document_root = self._kb_document_root(kb_name)
        documents = sorted(
            path
            for path in document_root.rglob("*")
            if path.is_file()
            and not any(part.startswith(".") for part in path.relative_to(document_root).parts)
            and path.suffix.lower() in _TEXT_SUFFIXES
        )
        state = self._load()
        old_tasks = {
            item.get("id"): item
            for item in state["tasks"]
            if item.get("source_type") == "kb_document" and item.get("source_id") == kb_name
        }
        if force:
            state["tasks"] = [item for item in state["tasks"] if item.get("id") not in old_tasks]
            old_tasks = {}
        new_tasks: list[dict[str, Any]] = []
        translated_units = 0
        source_documents: list[tuple[str, str]] = []
        glossary = self._refresh_glossary(
            state, "kb_document", kb_name, [], reviewed_glossary
        )
        for document in documents[: max(1, min(limit, 500))]:
            relative = document.relative_to(document_root).as_posix()
            task_id = f"kb:{kb_name}:{relative}"
            sidecar = document.parent / ".translations" / f"{document.name}.json"
            if _read_json(sidecar):
                translated_units += 1
                continue
            try:
                raw = document.read_text(encoding="utf-8", errors="replace")
            except OSError as exc:
                raise ValueError(f"Could not read KB document {relative}: {exc}") from exc
            source_text = (
                _html_to_text(raw) if document.suffix.lower() in {".html", ".htm"} else raw
            )
            source_documents.append((relative, source_text))
            if not source_text.strip() or len(source_text) > 12_000:
                continue
            now = time.time()
            task = {
                "id": task_id,
                "source_type": "kb_document",
                "source_id": kb_name,
                "source_label": kb_name,
                "title": relative,
                "chapter_index": 0,
                "group_index": 0,
                "source_text": source_text[:12_000],
                "glossary": terms_for_text(glossary, source_text),
                "target_language": "Chinese",
                "reason": "missing_translation",
                "priority": "normal",
                "status": "queued",
                "attempts": 0,
                "error": "",
                "created_at": now,
                "updated_at": now,
                "started_at": None,
                "completed_at": None,
                "document_path": relative,
            }
            self._preserve_task_state(old_tasks.get(task_id, {}), task)
            new_tasks.append(task)
        total_units = min(len(documents), 500)
        state["tasks"] = [item for item in state["tasks"] if item.get("id") not in old_tasks]
        state["tasks"].extend(new_tasks)
        state["glossaries"][f"kb_document:{kb_name}"] = (
            merge_glossary(
                glossary, extract_glossary_candidates([text for _, text in source_documents])
            )
            if reviewed_glossary is None
            else glossary
        )
        glossary = state["glossaries"][f"kb_document:{kb_name}"]
        for task in new_tasks:
            task["glossary"] = terms_for_text(glossary, str(task["source_text"]))
        self._update_source_stats(
            state, "kb_document", kb_name, kb_name, total_units, translated_units
        )
        self._save(state)
        return self._board(source_type="kb_document", source_id=kb_name)

    def plan_kb(
        self,
        kb_name: str,
        *,
        force: bool = False,
        limit: int = 200,
        reviewed_glossary: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        with self._repository.locked():
            return self._plan_kb_unlocked(
                kb_name,
                force=force,
                limit=limit,
                reviewed_glossary=reviewed_glossary,
            )

    def plan(
        self,
        source_type: str,
        source_id: str,
        *,
        force: bool = False,
        reviewed_glossary: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        if source_type == "bilingual":
            return self.plan_bilingual(
                source_id, force=force, reviewed_glossary=reviewed_glossary
            )
        if source_type == "kb_document":
            return self.plan_kb(
                source_id, force=force, reviewed_glossary=reviewed_glossary
            )
        raise ValueError("Unsupported translation source type")

    async def plan_with_review(
        self, source_type: str, source_id: str, *, force: bool = False
    ) -> dict[str, Any]:
        texts: list[str] = []
        target_language = "Chinese"
        if source_type == "bilingual":
            root = _pairing_root(source_id)
            pairing = _read_json(root / "pairing.json") or {}
            target_language = str(pairing.get("target_lang", "Chinese"))
            texts = [
                str(text)
                for entry in _read_json(root / "chapter_map.json", [])
                for group in _read_json(
                    root / "sections" / f"{str(entry[0])}.json", {}
                ).get("groups", [])
                for text in group.get("en", [])
            ]
        elif source_type == "kb_document":
            document_root = self._kb_document_root(source_id)
            texts = [
                path.read_text(encoding="utf-8", errors="replace")
                for path in sorted(document_root.rglob("*"))
                if path.is_file()
                and path.suffix.lower() in _TEXT_SUFFIXES
                and not any(
                    part.startswith(".") for part in path.relative_to(document_root).parts
                )
            ]
        else:
            raise ValueError("Unsupported translation source type")
        reviewed = await review_glossary_candidates(
            extract_glossary_candidates(texts), target_language
        )
        return await asyncio.to_thread(
            self.plan,
            source_type,
            source_id,
            force=force,
            reviewed_glossary=reviewed,
        )

    def retry(self, task_id: str) -> dict[str, Any]:
        with self._repository.transaction() as state:
            task = next(
                (item for item in state["tasks"] if item.get("id") == task_id), None
            )
            if task is None:
                raise ValueError("Translation task not found")
            task.update(status="queued", error="", run_id=None, updated_at=time.time())
        return self._board(source_type=task["source_type"], source_id=task["source_id"])

    def get_glossary(self, source_type: str, source_id: str) -> list[dict[str, Any]]:
        if source_type not in {"bilingual", "kb_document"}:
            raise ValueError("Unsupported translation source type")
        state = self._load()
        return list(state.get("glossaries", {}).get(f"{source_type}:{source_id}", []))

    def update_glossary(
        self, source_type: str, source_id: str, entries: list[dict[str, Any]]
    ) -> dict[str, Any]:
        if source_type not in {"bilingual", "kb_document"}:
            raise ValueError("Unsupported translation source type")
        normalized: list[dict[str, Any]] = []
        for entry in entries[:500]:
            term = str(entry.get("term", "")).strip()
            translation = str(entry.get("translation", "")).strip()
            if not term or len(term) > 300 or len(translation) > 500:
                raise ValueError("Each glossary term is required and must be bounded")
            decision = str(
                entry.get("decision")
                or ("approved" if entry.get("approved") else "candidate")
            )
            if decision not in {"candidate", "approved", "rejected"}:
                decision = "candidate"
            normalized.append(
                {
                    "term": term,
                    "translation": translation or term,
                    "kind": str(entry.get("kind") or "custom")[:50],
                    "frequency": max(0, int(entry.get("frequency", 0))),
                    "protected": bool(entry.get("protected")),
                    "decision": decision,
                    "approved": decision == "approved",
                }
            )
        key = f"{source_type}:{source_id}"
        with self._repository.transaction() as state:
            state.setdefault("glossaries", {})[key] = sorted(
                normalized, key=lambda item: item["term"].casefold()
            )
        return self._board(source_type=source_type, source_id=source_id)

    def retry_failed(
        self, source_type: str | None = None, source_id: str | None = None
    ) -> dict[str, Any]:
        with self._repository.transaction() as state:
            for task in state["tasks"]:
                if task.get("status") != "failed":
                    continue
                if source_type and task.get("source_type") != source_type:
                    continue
                if source_id and task.get("source_id") != source_id:
                    continue
                task.update(status="queued", error="", updated_at=time.time())
        return self._board(source_type=source_type, source_id=source_id)

    def _apply_translation(self, task: dict[str, Any], translation: str) -> None:
        if task["source_type"] == "bilingual":
            root = _pairing_root(task["source_id"])
            sections_root = (root / "sections").resolve()
            path = _resolve_under_root(sections_root, f"{task['chapter_id']}.json", label="chapter")
            section = _read_json(path)
            if not section:
                raise ValueError("Bilingual section disappeared during translation")
            group = section["groups"][int(task["group_index"])]
            group["zh"] = [translation]
            group["translation_source"] = "translation_task"
            group["translation_task_id"] = task["id"]
            group["low_confidence"] = False
            _write_json(path, section)
            return
        if task["source_type"] == "kb_document":
            document_root = self._kb_document_root(task["source_id"])
            document = _resolve_under_root(
                document_root, str(task["document_path"]), label="document"
            )
            sidecar = document.parent / ".translations" / f"{document.name}.json"
            _write_json(
                sidecar,
                {
                    "source_type": "kb_document",
                    "kb_name": task["source_id"],
                    "document_path": task["document_path"],
                    "target_language": task.get("target_language", "Chinese"),
                    "translation": translation,
                    "task_id": task["id"],
                    "completed_at": time.time(),
                },
            )
            return
        raise ValueError("Unsupported translation sink")

    def start_run(
        self,
        limit: int = 4,
        *,
        source_type: str | None = None,
        source_id: str | None = None,
        chapter_id: str | None = None,
    ) -> dict[str, Any]:
        run_id = uuid.uuid4().hex
        now = time.time()
        if len(self._run_events) >= 64:
            self._run_events.pop(next(iter(self._run_events)))
        with self._repository.transaction() as state:
            if state.get("version", 1) < 2:
                state["version"] = 2
            state.setdefault("runs", {})
            candidates = [
                task
                for task in state["tasks"]
                if task.get("status") == "queued"
                and (source_type is None or task.get("source_type") == source_type)
                and (source_id is None or task.get("source_id") == source_id)
                and (
                    chapter_id is None
                    or str(task.get("chapter_id") or task.get("title")) == chapter_id
                )
            ]
            selected = sorted(
                candidates,
                key=lambda task: (
                    _PRIORITY_RANK.get(task.get("priority"), 3),
                    int(task.get("chapter_index", 0)),
                    int(task.get("group_index", 0)),
                ),
            )[: max(1, min(int(limit), 8))]
            selected_ids = [task["id"] for task in selected]
            state["runs"][run_id] = {
                "run_id": run_id,
                "source_type": source_type,
                "source_id": source_id,
                "chapter_id": chapter_id,
                "task_ids": selected_ids,
                "status": "queued",
                "sequence": 0,
                "completed": 0,
                "failed": 0,
                "created_at": now,
                "updated_at": now,
                "started_at": None,
                "completed_at": None,
                "error": "",
            }
            for task in selected:
                task.update(run_id=run_id, updated_at=now)
        self._publish_run_event(run_id, "run_started", {"selected_task_ids": selected_ids})
        return self.get_run(run_id)

    def get_run(self, run_id: str) -> dict[str, Any]:
        run = self._load()["runs"].get(run_id)
        if run is None:
            raise ValueError("Translation run not found")
        return dict(run)

    def _is_run_cancelled(self, run_id: str) -> bool:
        return (
            self._load().get("runs", {}).get(run_id, {}).get("status", "")
            == "cancelled"
        )

    def _mark_run_cancelled(self, run_id: str, error: str = "Cancelled by user") -> None:
        with self._repository.transaction() as state:
            run = state.get("runs", {}).get(run_id)
            if not run:
                return
            if run.get("status") in {"completed", "failed", "cancelled"}:
                return
            task_ids = set(run.get("task_ids", []))
            completed = 0
            failed = 0
            for task in state["tasks"]:
                if task.get("id") not in task_ids:
                    continue
                if task.get("status") == "completed":
                    completed += 1
                if task.get("status") == "failed":
                    failed += 1
            run.update(
                status="cancelled",
                error=error,
                updated_at=time.time(),
                completed_at=time.time(),
                completed=completed,
                failed=failed,
            )
            for task in state["tasks"]:
                if task.get("id") not in task_ids:
                    continue
                if task.get("status") in {"queued", "running"}:
                    task.update(
                        status="failed",
                        error=error,
                        updated_at=time.time(),
                    )

    def cancel_run(self, run_id: str) -> dict[str, Any]:
        run = self.get_run(run_id)
        if run.get("status") in {"completed", "failed", "cancelled"}:
            return self._board(
                source_type=run.get("source_type"),
                source_id=run.get("source_id"),
                chapter_id=run.get("chapter_id"),
            )
        self._mark_run_cancelled(run_id)
        run = self.get_run(run_id)
        active_task = self._run_tasks.get(run_id)
        if active_task is not None and not active_task.done():
            active_task.cancel()
        else:
            self._publish_run_event(
                run_id,
                "run_cancelled",
                {
                    "completed": int(run.get("completed", 0)),
                    "failed": int(run.get("failed", 0)),
                },
                terminal=True,
            )
        return self._board(
            source_type=run.get("source_type"),
            source_id=run.get("source_id"),
            chapter_id=run.get("chapter_id"),
        )

    async def run(
        self,
        limit: int = 4,
        *,
        source_type: str | None = None,
        source_id: str | None = None,
        chapter_id: str | None = None,
        run_id: str | None = None,
    ) -> dict[str, Any]:
        from deeptutor.immersive_reading import get_immersive_reading_service

        if run_id is None:
            created = self.start_run(
                limit,
                source_type=source_type,
                source_id=source_id,
                chapter_id=chapter_id,
            )
            if not created["task_ids"]:
                return self._board(
                    source_type=source_type, source_id=source_id, chapter_id=chapter_id
                )
            run_id = created["run_id"]
        run_task = asyncio.current_task()
        if run_task is not None:
            self._run_tasks[run_id] = run_task
        try:
            async with self._execution_lock:
                run = self.get_run(run_id)
                task_ids = list(run.get("task_ids", []))
                if not task_ids or run.get("status") in {"completed", "failed", "cancelled"}:
                    return self._run_board(run)
                with self._repository.transaction() as state:
                    state["is_running"] = True
                    state["last_run_at"] = time.time()
                    state["runs"][run_id].update(status="running", started_at=time.time())
                # Give newly created SSE subscribers a chance to register before the
                # first model call, especially in fast tests and local fake models.
                await asyncio.sleep(0)
                try:
                    translator = get_immersive_reading_service()
                    for task_id in task_ids:
                        if self._is_run_cancelled(run_id):
                            break
                        with self._repository.transaction() as state:
                            task = next(
                                item for item in state["tasks"] if item.get("id") == task_id
                            )
                            if task.get("status") not in {"queued", "running"}:
                                continue
                            key = f"{task.get('source_type')}:{task.get('source_id')}"
                            current_glossary = state.get("glossaries", {}).get(key, [])
                            if current_glossary:
                                task["glossary"] = terms_for_text(
                                    current_glossary, str(task.get("source_text", ""))
                                )
                            task.update(
                                status="running",
                                started_at=time.time(),
                                updated_at=time.time(),
                            )
                        task_snapshot = dict(task)
                        self._publish(task_snapshot, run_id=run_id, task_updated=True)
                        translation: str | None = None
                        error = ""
                        try:
                            selected_glossary = task.get("glossary") or []
                            translation = (
                                await translator.translate(
                                    str(task["source_text"]),
                                    str(task.get("target_language", "Chinese")),
                                    glossary=selected_glossary,
                                )
                                if selected_glossary
                                else await translator.translate(
                                    str(task["source_text"]),
                                    str(task.get("target_language", "Chinese")),
                                )
                            )
                            await asyncio.to_thread(self._apply_translation, task, translation)
                            task_snapshot = self._repository.update_task(
                                task_id,
                                dict(
                                    status="completed",
                                    translation=translation,
                                    error="",
                                    completed_at=time.time(),
                                    updated_at=time.time(),
                                ),
                            )
                        except asyncio.CancelledError:
                            task_snapshot = self._repository.update_task(
                                task_id,
                                dict(
                                    status="failed",
                                    error="Cancelled by user",
                                    attempts=int(task.get("attempts", 0)) + 1,
                                    updated_at=time.time(),
                                ),
                            )
                            self._publish(task_snapshot, run_id=run_id, task_updated=True)
                            raise
                        except Exception as exc:
                            translation = None
                            error = str(exc)[:1000]
                            task_snapshot = self._repository.update_task(
                                task_id,
                                dict(
                                    status="failed",
                                    error=error,
                                    attempts=int(task.get("attempts", 0)) + 1,
                                    updated_at=time.time(),
                                ),
                            )
                        self._publish(
                            task_snapshot,
                            translation=translation,
                            run_id=run_id,
                        )
                except asyncio.CancelledError:
                    self._mark_run_cancelled(run_id)
                finally:
                    run_status = self.get_run(run_id).get("status")
                    cancelled = run_status == "cancelled"
                    state = self._load()
                    completed = sum(
                        1
                        for task in state["tasks"]
                        if task.get("id") in task_ids and task.get("status") == "completed"
                    )
                    failed = sum(
                        1
                        for task in state["tasks"]
                        if task.get("id") in task_ids and task.get("status") == "failed"
                    )
                    with self._repository.transaction() as current:
                        current["is_running"] = False
                        current["runs"][run_id].update(
                            status=(
                                "cancelled"
                                if cancelled
                                else (
                                    "failed"
                                    if failed and completed + failed < len(task_ids)
                                    else "completed"
                                )
                            ),
                            completed=completed,
                            failed=failed,
                            completed_at=time.time(),
                            updated_at=time.time(),
                            error="" if not cancelled else "Cancelled by user",
                        )
                    if not any(
                        event.get("type") in {"run_completed", "run_cancelled"}
                        for event in self._run_events.get(run_id, [])
                    ):
                        self._publish_run_event(
                            run_id,
                            "run_cancelled" if cancelled else "run_completed",
                            {"completed": completed, "failed": failed},
                            terminal=True,
                        )
                return self._run_board(self.get_run(run_id))
        finally:
            if run_id in self._run_tasks:
                self._run_tasks.pop(run_id, None)

    def _run_board(self, run: dict[str, Any]) -> dict[str, Any]:
        return self._board(
            source_type=run.get("source_type"),
            source_id=run.get("source_id"),
            chapter_id=run.get("chapter_id"),
        )

    def _publish(
        self,
        task: dict[str, Any],
        translation: str | None = None,
        *,
        run_id: str | None = None,
        task_updated: bool = False,
    ) -> None:
        if not self._listeners:
            return
        public_task = self._public_task(task)
        if translation is not None:
            public_task["translation"] = translation
        sequence = self._next_sequence(run_id or task.get("run_id"))
        event = {
            "type": (
                "group_translated"
                if translation is not None
                else "task_updated"
                if task_updated
                else "task_updated"
            ),
            "task": public_task,
            "run_id": run_id or task.get("run_id"),
            "sequence": sequence,
        }
        run_key = run_id or task.get("run_id")
        if run_key:
            self._run_events.setdefault(run_key, deque(maxlen=512)).append(event)
        for queue in list(self._listeners):
            if queue.full():
                try:
                    queue.get_nowait()
                except asyncio.QueueEmpty:
                    pass
            queue.put_nowait(event)

    def _publish_run_event(
        self,
        run_id: str,
        event_type: str,
        payload: dict[str, Any] | None = None,
        *,
        terminal: bool = False,
    ) -> None:
        sequence = self._next_sequence(run_id)
        event = {
            "type": event_type,
            "run_id": run_id,
            "sequence": sequence,
            **(payload or {}),
        }
        self._run_events.setdefault(run_id, deque(maxlen=512)).append(event)
        for queue in list(self._listeners):
            if queue.full():
                try:
                    queue.get_nowait()
                except asyncio.QueueEmpty:
                    pass
            queue.put_nowait(event)

    def _next_sequence(self, run_id: str | None) -> int:
        if not run_id:
            return 0
        with self._repository.transaction() as state:
            run = state["runs"].get(run_id)
            if run is None:
                return 0
            run["sequence"] = int(run.get("sequence", 0)) + 1
            return int(run["sequence"])

    def subscribe(
        self,
        *,
        run_id: str | None = None,
        source_type: str | None = None,
        source_id: str | None = None,
        chapter_id: str | None = None,
    ):
        """Yield task transitions for one filtered board without busy polling."""

        async def iterator():
            queue: asyncio.Queue[dict[str, Any]] = asyncio.Queue(maxsize=256)
            self._listeners.add(queue)
            try:
                replay = (
                    list(self._run_events.get(run_id, [])) if run_id else []
                )
                for event in replay:
                    queue.put_nowait(event)
                yield {
                    "type": "snapshot",
                    "run_id": run_id,
                    "sequence": 0,
                    "board": self._board(
                        source_type=source_type,
                        source_id=source_id,
                        chapter_id=chapter_id,
                    ),
                }
                terminal_run = self.get_run(run_id) if run_id else None
                if (
                    terminal_run
                    and terminal_run.get("status") in {"completed", "failed", "cancelled"}
                    and not any(
                        event.get("type") in {"run_completed", "run_cancelled"}
                        for event in replay
                    )
                ):
                    yield {
                        "type": (
                            "run_cancelled"
                            if terminal_run.get("status") == "cancelled"
                            else "run_completed"
                        ),
                        "run_id": run_id,
                        "sequence": int(terminal_run.get("sequence", 0)),
                        "completed": int(terminal_run.get("completed", 0)),
                        "failed": int(terminal_run.get("failed", 0)),
                    }
                    return
                while True:
                    try:
                        event = await asyncio.wait_for(queue.get(), timeout=15.0)
                    except asyncio.TimeoutError:
                        yield {"type": "heartbeat"}
                        continue
                    task = event.get("task", {})
                    event_run_id = event.get("run_id")
                    source_match = (
                        source_type is None
                        or task.get("source_type") == source_type
                    ) and (source_id is None or task.get("source_id") == source_id)
                    chapter_match = chapter_id is None or str(
                        task.get("chapter_id") or task.get("title")
                    ) == chapter_id
                    if run_id is not None and event_run_id != run_id:
                        continue
                    if not task and event_run_id and run_id and event_run_id != run_id:
                        continue
                    if task and not (source_match and chapter_match):
                        continue
                    yield event
                    if event.get("type") in {"run_completed", "run_cancelled"}:
                        break
            finally:
                self._listeners.discard(queue)

        return iterator()


_translation_task_service: TranslationTaskService | None = None


def get_translation_task_service() -> TranslationTaskService:
    global _translation_task_service
    if _translation_task_service is None:
        _translation_task_service = TranslationTaskService()
    return _translation_task_service
