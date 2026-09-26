"""Feature-level dependency closure over durable learning references."""

from __future__ import annotations

import json
import sqlite3

MODES = {
    "mastery_path": "learning",
    "immersive_reading": "reading",
    "immersive_watching": "timed_media",
}


def _preferences(row):
    prefs = json.loads(row.get("preferences_json") or "{}")
    for key, values in prefs.get("workspace_dependencies", {}).items():
        merged = list(prefs.get(key) or [])
        for value in values:
            if value not in merged:
                merged.append(value)
        prefs[key] = merged
    return prefs


def dependency_closure(
    paths, sessions: list[dict], features: list[str], *, session_ids: set[str] | None = None
) -> tuple[set[str], set[str]]:
    """Move connected stores together so sources left behind keep valid links."""
    sessions = _with_historical_references(paths, sessions)
    selected, ids = _forward_closure(paths, sessions, features, session_ids=session_ids)
    groups = [
        _forward_closure(paths, sessions, [feature])
        for feature in (
            "book",
            "learning",
            "reading",
            "timed_media",
            "notebook",
            "co-writer",
            "courses",
        )
    ]
    # Individual ordinary chats may cite a selected learning store or chat.
    prefs = {row["id"]: _preferences(row) for row in sessions}
    while True:
        previous = (selected.copy(), ids.copy())
        for related, related_ids in groups:
            shared_stores = (related & selected) - {
                "chat",
                "outputs",
                "presentations",
                "attachments",
                "parse_cache",
            }
            if shared_stores or related_ids & ids:
                selected |= related
                ids |= related_ids
        reverse_ids = set()
        for sid, value in prefs.items():
            refs = {ref for ref in value.get("history_references", []) if isinstance(ref, str)}
            refs.add(value.get("parent_session_id", ""))
            stores = {
                feature
                for key, feature in (
                    ("book_references", "book"),
                    ("reading_references", "reading"),
                    ("reading_material_id", "reading"),
                    ("timed_media_id", "timed_media"),
                    ("notebook_references", "notebook"),
                    ("knowledge_bases", "knowledge_bases"),
                    ("course_id", "courses"),
                    ("mastery_path_id", "learning"),
                )
                if value.get(key)
            }
            if refs & ids or stores & selected:
                reverse_ids.add(sid)
        if reverse_ids - ids:
            related, related_ids = _forward_closure(
                paths, sessions, list(selected - {"chat"}), session_ids=ids | reverse_ids
            )
            selected |= related
            ids |= related_ids
        if previous == (selected, ids):
            return selected, ids


def _forward_closure(
    paths, sessions: list[dict], features: list[str], *, session_ids: set[str] | None = None
) -> tuple[set[str], set[str]]:
    selected = set(features)
    all_chats = "chat" in selected and session_ids is None
    ids: set[str] = set(session_ids or ())
    prefs = {row["id"]: _preferences(row) for row in sessions}
    if set(features) & {"outputs", "presentations", "attachments"} and session_ids is None:
        ids.update(prefs)
    book_sessions = set()
    books = []
    for path in paths.get_book_dir().glob("book_*/*.json"):
        if path.name not in {"manifest.json", "inputs.json"}:
            continue
        try:
            book = json.loads(path.read_text())
        except (OSError, ValueError):
            continue
        books.append(book)
        if book.get("chat_session_id"):
            book_sessions.add(book["chat_session_id"])
        book_sessions.update((book.get("metadata") or {}).get("page_chat_sessions", {}).values())
    modes = {
        sid: "book" if sid in book_sessions else MODES.get(value.get("workspace_mode"), "chat")
        for sid, value in prefs.items()
    }
    scanned = set()
    while True:
        previous = (frozenset(selected), frozenset(ids))
        # A feature store is copied as an aggregate; include all conversations
        # that belong to it, plus tutor descendants and explicitly cited chats.
        ids.update(
            sid for sid, mode in modes.items() if mode in selected and (mode != "chat" or all_chats)
        )
        ids.update(sid for sid, value in prefs.items() if value.get("parent_session_id") in ids)
        for sid in list(ids):
            value = prefs.get(sid, {})
            selected.add(modes.get(sid, "chat"))
            ids.update(
                ref
                for ref in value.get("history_references", [])
                if isinstance(ref, str) and ref in prefs
            )
            if value.get("notebook_references"):
                selected.add("notebook")
            if value.get("course_id"):
                selected.add("courses")
            if value.get("mastery_path_id"):
                selected.add("learning")
            if value.get("book_references"):
                selected.add("book")
            if value.get("reading_references") or value.get("reading_material_id"):
                selected.add("reading")
            if value.get("timed_media_id"):
                selected.add("timed_media")
            if value.get("knowledge_bases") or value.get("kb_name"):
                selected |= {"knowledge_bases", "parse_cache"}
            if value.get("question_notebook_references"):
                ids.update(_question_sessions(paths, value["question_notebook_references"]))
        if "book" in selected and "book" not in scanned:
            scanned.add("book")
            ids |= book_sessions & prefs.keys()
            for book in books:
                ids.update(
                    row["session_id"]
                    for row in book.get("chat_selections", [])
                    if row.get("session_id") in prefs
                )
                if book.get("notebook_refs"):
                    selected.add("notebook")
                if book.get("knowledge_bases"):
                    selected |= {"knowledge_bases", "parse_cache"}
                if book.get("question_entries") or book.get("question_categories"):
                    ids.update(_question_sessions(paths))
        if "learning" in selected and "learning" not in scanned:
            scanned.add("learning")
            db = paths.get_workspace_dir() / "learning" / "mastery" / "mastery.sqlite3"
            if db.exists():
                with sqlite3.connect(db) as conn:
                    tables = {
                        row[0]
                        for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
                    }
                    if "mastery_path_sessions" in tables:
                        ids.update(
                            row[0]
                            for row in conn.execute("SELECT session_id FROM mastery_path_sessions")
                            if row[0] in prefs
                        )
                    if "mastery_topic_sources" in tables:
                        for kind, external_id in conn.execute(
                            "SELECT kind,external_id FROM mastery_topic_sources"
                        ):
                            if kind == "chat" and external_id in prefs:
                                ids.add(external_id)
                            elif kind == "question_bank":
                                ids.update(_question_sessions(paths))
                            elif kind in {"book", "notebook"}:
                                selected.add(kind)
                            elif kind in {"file", "knowledge_base"}:
                                selected |= {"files", "knowledge_bases", "parse_cache"}
                            elif kind == "cowriter":
                                selected.add("co-writer")
        if "reading" in selected and "reading" not in scanned:
            scanned.add("reading")
            db = paths.get_workspace_dir() / "reading" / "_catalog.sqlite3"
            if db.exists():
                with sqlite3.connect(db) as conn:
                    if conn.execute(
                        "SELECT 1 FROM sqlite_master WHERE name='reading_workspace_sessions'"
                    ).fetchone():
                        ids.update(
                            row[0]
                            for row in conn.execute(
                                "SELECT session_id FROM reading_workspace_sessions"
                            )
                            if row[0] in prefs
                        )
        for feature in ("notebook", "co-writer", "timed_media", "courses"):
            if feature not in selected or feature in scanned:
                continue
            scanned.add(feature)
            for path in (paths.get_workspace_dir() / feature).rglob("*.json"):
                try:
                    document = json.loads(path.read_text())
                except (OSError, ValueError):
                    continue
                _collect_references(document, prefs, ids, selected)
        if previous == (frozenset(selected), frozenset(ids)):
            break
    return selected, ids


def _collect_references(value, prefs, ids, selected):
    if isinstance(value, list):
        for child in value:
            _collect_references(child, prefs, ids, selected)
    elif isinstance(value, dict):
        if value.get("ref_id") and value.get("kind"):
            kind = value["kind"]
            if kind == "chat" and value["ref_id"] in prefs:
                ids.add(value["ref_id"])
            related = {
                "book": "book",
                "mastery_path": "learning",
                "reading": "reading",
                "reading_workspace": "reading",
                "notebook": "notebook",
                "knowledge_base": "knowledge_bases",
                "video": "timed_media",
                "cowriter": "co-writer",
            }.get(kind)
            if related:
                selected.add(related)
        for key, child in value.items():
            if (
                key in {"session_id", "source_session_id", "chat_session_id", "followup_session_id"}
                and isinstance(child, str)
                and child in prefs
            ):
                ids.add(child)
            if child and key in {"book_id", "reading_material_id", "timed_media_id", "notebook_id"}:
                selected.add(
                    {
                        "book_id": "book",
                        "reading_material_id": "reading",
                        "timed_media_id": "timed_media",
                        "notebook_id": "notebook",
                    }[key]
                )
            _collect_references(child, prefs, ids, selected)


def _question_sessions(paths, entry_ids=None) -> set[str]:
    db = paths.get_chat_history_db()
    if not db.exists():
        return set()
    with sqlite3.connect(db) as conn:
        if not conn.execute("SELECT 1 FROM sqlite_master WHERE name='notebook_entries'").fetchone():
            return set()
        if entry_ids:
            placeholders = ",".join("?" for _ in entry_ids)
            return {
                row[0]
                for row in conn.execute(
                    f"SELECT session_id FROM notebook_entries WHERE id IN ({placeholders})",  # nosec B608 - placeholders only
                    list(entry_ids),
                )
                if row[0]
            }
        return {
            row[0]
            for row in conn.execute("SELECT DISTINCT session_id FROM notebook_entries")
            if row[0]
        }


def _with_historical_references(paths, sessions: list[dict]) -> list[dict]:
    """Old request snapshots retain references no longer selected by the last turn."""
    prefs = {row["id"]: _preferences(row) for row in sessions}
    aliases = {
        "historyReferences": "history_references",
        "notebookReferences": "notebook_references",
        "bookReferences": "book_references",
        "readingReferences": "reading_references",
        "questionNotebookReferences": "question_notebook_references",
        "knowledgeBases": "knowledge_bases",
        "readingMaterialId": "reading_material_id",
        "timedMediaId": "timed_media_id",
        "masteryPathId": "mastery_path_id",
        "courseId": "course_id",
    }
    references = set(aliases.values())

    def collect(value, into):
        if isinstance(value, list):
            for child in value:
                collect(child, into)
        elif isinstance(value, dict):
            for key, child in value.items():
                key = aliases.get(key, key)
                if key in references and child:
                    if isinstance(child, list):
                        current = into.setdefault(key, [])
                        for item in child:
                            if item not in current:
                                current.append(item)
                    else:
                        into.setdefault(key, child)
                collect(child, into)

    db = paths.get_chat_history_db()
    if db.exists():
        with sqlite3.connect(db) as conn:
            for sid, raw in conn.execute("SELECT session_id,metadata_json FROM messages"):
                if sid in prefs and raw:
                    try:
                        collect(json.loads(raw), prefs[sid])
                    except (ValueError, TypeError):
                        continue
            for sid, followup in conn.execute(
                "SELECT session_id,followup_session_id FROM notebook_entries"
            ):
                if sid in prefs and followup in prefs:
                    refs = prefs[sid].setdefault("history_references", [])
                    if followup not in refs:
                        refs.append(followup)
    from deeptutor.services.workspace.data_migration import _backend, _pocketbase_snapshot

    if _backend() == "pocketbase" and prefs:
        snapshot = _pocketbase_snapshot(list(prefs))
        for row in snapshot["messages"]:
            value = row.get("metadata_json") or {}
            if isinstance(value, str):
                try:
                    value = json.loads(value)
                except ValueError:
                    continue
            if row.get("session_id") in prefs:
                collect(value, prefs[row["session_id"]])
    return [{**row, "preferences_json": json.dumps(prefs[row["id"]])} for row in sessions]
