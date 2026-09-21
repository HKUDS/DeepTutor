"""Move conversations with the same verified, recoverable data migration path."""

from __future__ import annotations

import json
import sqlite3

from deeptutor.services.path_service import get_path_service
from deeptutor.services.workspace.context import current_workspace_id, workspace_context
from deeptutor.services.workspace.data_migration import (
    _journal_root,
    _sessions,
    migrate_data,
    preview,
)
from deeptutor.services.workspace.models import WorkspaceError


def move_chat(session_id: str, target_id: str) -> dict:
    source_id = current_workspace_id()
    rows = _sessions(get_path_service())
    if session_id not in {row["id"] for row in rows}:
        raise WorkspaceError("Conversation not found.")
    if source_id != target_id:
        plan = preview(source_id, target_id, ["chat"], session_ids={session_id})
        learning = set(plan["features"]) - {"chat", "outputs", "presentations", "attachments"}
        if learning:
            raise WorkspaceError(
                "This conversation is linked to learning data. Move its complete bundle from Settings → Data migration."
            )
        migrate_data(source_id, target_id, ["chat"], session_ids={session_id})
    with workspace_context(target_id):
        from deeptutor.services.workspace.data_migration import _backend

        if _backend() == "pocketbase":
            from deeptutor.services.session.pocketbase_store import (
                PocketBaseSessionStore,
                _current_user_id,
                _find_session_record,
                _pb,
            )

            return PocketBaseSessionStore()._session_record_to_dict(
                _find_session_record(_pb(), session_id, _current_user_id())
            )
        from deeptutor.services.session.sqlite_store import SQLiteSessionStore

        return SQLiteSessionStore(get_path_service().get_chat_history_db())._get_session_sync(
            session_id
        )


def migrate_legacy_bindings() -> int:
    """Adopt pre-isolation history in the default workspace, without moving files.

    The old binding selected a tool folder, not a data partition. Splitting it
    would sever learning references. Preserve the original binding for audit
    and normalize once; users can move complete bundles with migration preview.
    """
    from deeptutor.services.file_io import atomic_write_json
    from deeptutor.services.workspace.activity import data_activity
    from deeptutor.services.workspace.data_migration import _backend

    marker = _journal_root() / "default-adoption-v1.json"
    if marker.exists():
        return 0
    with data_activity(exclusive=True), workspace_context():
        from deeptutor.services.workspace.data_migration import assert_no_pending_recovery

        assert_no_pending_recovery()
        if marker.exists():
            return 0
        paths = get_path_service()
        original = []
        backup = marker.with_name("default-adoption-backup.json")

        def save_original(rows):
            # A PocketBase retry must preserve entries already normalized by
            # the previous attempt, including their original preferences.
            previous = json.loads(backup.read_text()) if backup.exists() else []
            merged = {row["id"]: row for row in rows}
            merged.update({row["id"]: row for row in previous})
            atomic_write_json(backup, list(merged.values()))

        if _backend() == "pocketbase":
            from deeptutor.services.session.pocketbase_store import (
                _current_user_id,
                _json_loads,
                _pb,
            )

            collection = _pb().collection("sessions")
            rows = collection.get_full_list(
                query_params={"filter": f"user_id={json.dumps(_current_user_id())}"}
            )
            for row in rows:
                prefs = _json_loads(getattr(row, "preferences_json", None), {})
                if prefs.get("workspace_id"):
                    original.append({"id": row.id, "preferences": prefs})
            save_original(original)
            for row in original:
                prefs = row["preferences"]
                collection.update(
                    row["id"],
                    {
                        "preferences_json": {
                            **prefs,
                            "legacy_workspace_id": prefs["workspace_id"],
                            "workspace_id": "",
                        }
                    },
                )
        else:
            db = paths.get_chat_history_db()
            if db.exists():
                with sqlite3.connect(db) as conn:
                    for sid, raw in conn.execute("SELECT id,preferences_json FROM sessions"):
                        prefs = json.loads(raw or "{}")
                        if prefs.get("workspace_id"):
                            original.append({"id": sid, "preferences": prefs})
                    save_original(original)
                    for row in original:
                        prefs = row["preferences"]
                        conn.execute(
                            "UPDATE sessions SET preferences_json=? WHERE id=?",
                            (
                                json.dumps(
                                    {
                                        **prefs,
                                        "legacy_workspace_id": prefs["workspace_id"],
                                        "workspace_id": "",
                                    }
                                ),
                                row["id"],
                            ),
                        )
        atomic_write_json(marker, {"version": 1, "sessions": len(original)})
        return len(original)
