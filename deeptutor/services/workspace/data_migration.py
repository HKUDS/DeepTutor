"""Discover, preview, export and migrate workspace data with recoverable copies.

The unit of selection is a feature's store, not an arbitrary filesystem path.
Related sessions and source stores are included in the preview. Nothing reads
outside the authenticated account's known roots, and source snapshots are kept
in an account-private recovery directory after a successful transfer.
"""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import uuid
import zipfile

from deeptutor.multi_user.paths import get_account_path_service
from deeptutor.services.file_io import atomic_write_json
from deeptutor.services.path_service import get_path_service
from deeptutor.services.workspace.activity import data_activity
from deeptutor.services.workspace.context import workspace_context
from deeptutor.services.workspace.models import WorkspaceError

FEATURES = {
    "chat": "Conversations",
    "book": "Books",
    "learning": "Mastery Path",
    "reading": "Immersive Reading",
    "timed_media": "Immersive Watching",
    "notebook": "Notebooks",
    "co-writer": "Writing",
    "courses": "Courses",
    "files": "File library",
    "knowledge_bases": "Knowledge bases",
    "parse_cache": "Document cache",
    "outputs": "Generated outputs",
    "presentations": "Presented files",
    "attachments": "Conversation attachments",
    "historical_chat": "Historical conversation database",
    "historical_agent": "Historical agent outputs",
    "historical_output": "Historical output folder",
    "historical_archive": "Historical archives",
}


def _feature_path(paths, feature: str) -> Path:
    if feature == "attachments":
        if hasattr(paths, "scope"):
            return paths.get_chat_workspace_root() / "attachments"
        from deeptutor.services.storage.attachment_store import _attachment_root

        with workspace_context():
            return _attachment_root()
    if feature.startswith("historical_"):
        if hasattr(paths, "scope"):
            return paths.get_workspace_dir() / "historical" / feature
        return {
            "historical_chat": paths.workspace_root / "chat_history.db",
            "historical_agent": paths.workspace_root / "agent",
            "historical_output": paths.workspace_root / "output",
            "historical_archive": paths.get_user_root() / "archive",
        }[feature]
    if feature == "presentations":
        base = (
            paths.get_workspace_dir() if hasattr(paths, "scope") else paths.get_runtime_state_dir()
        )
        return base / "workspace_presentations"
    if feature == "knowledge_bases":
        return paths.get_knowledge_bases_root()
    if feature == "parse_cache":
        return paths.get_parse_cache_root()
    if feature == "files":
        return paths.get_workspace_dir() / "library"
    if feature == "outputs":
        from deeptutor.services.workspace import get_content_workspace_service

        if hasattr(paths, "scope"):
            return paths.scope.content_root / "outputs"
        return get_content_workspace_service().general_binding().root / "outputs"
    return paths.get_workspace_dir() / feature


def _journal_root() -> Path:
    root = get_account_path_service().get_runtime_state_dir() / "data-migrations"
    root.mkdir(parents=True, exist_ok=True)
    return root


def _files(root: Path):
    if not root.exists():
        return
    if root.is_symlink():
        raise WorkspaceError(f"Symbolic links cannot be migrated: {root.name}")
    if root.is_file():
        yield root
        return
    for directory, dirs, names in os.walk(root, followlinks=False):
        for name in dirs + names:
            child = Path(directory) / name
            if child.is_symlink():
                raise WorkspaceError(
                    f"Symbolic links cannot be migrated: {child.relative_to(root)}"
                )
        for name in names:
            child = Path(directory) / name
            if not child.is_file():
                raise WorkspaceError("Special files cannot be migrated.")
            yield child


def _hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _empty_scaffold(root: Path) -> bool:
    """Only schema-only databases and empty initialization markers are disposable."""
    for path in _files(root):
        if path.name.endswith(("-wal", "-shm", ".lock")):
            continue
        with path.open("rb") as handle:
            database = handle.read(16) == b"SQLite format 3\x00"
        if not database:
            return False
        with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as conn:
            for (name,) in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            ).fetchall():
                if path.name == "_catalog.sqlite3" and name == "reading_schema":
                    continue
                quoted = '"' + name.replace('"', '""') + '"'
                if conn.execute(f"SELECT 1 FROM {quoted} LIMIT 1").fetchone():  # nosec B608 - quoted schema identifier
                    return False
    return True


def _snapshot(source: Path, target: Path, *, included: set[str] | None = None) -> dict[str, str]:
    """SQLite backup includes WAL data; never copy a live database as bytes."""
    manifest = {}
    for path in _files(source):
        if path.name.endswith(("-wal", "-shm", ".lock")):
            continue
        relative = path.relative_to(source).as_posix() if source.is_dir() else path.name
        if included is not None and relative not in included:
            continue
        destination = target / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        with path.open("rb") as handle:
            database = handle.read(16) == b"SQLite format 3\x00"
        if database:
            with (
                sqlite3.connect(f"file:{path}?mode=ro", uri=True) as original,
                sqlite3.connect(destination) as copy,
            ):
                original.backup(copy)
                if copy.execute("PRAGMA integrity_check").fetchone()[0] != "ok":
                    raise WorkspaceError(f"Database verification failed: {relative}")
        else:
            before = _hash(path)
            shutil.copy2(path, destination)
            if _hash(destination) != before or _hash(path) != before:
                raise WorkspaceError(
                    "Source files changed during the copy. Retry after tasks finish."
                )
        manifest[relative] = _hash(destination)
    return manifest


def _sqlite_sessions(paths) -> list[dict]:
    db = paths.get_chat_history_db()
    if not db.exists():
        return []
    with sqlite3.connect(f"file:{db}?mode=ro", uri=True) as conn:
        conn.row_factory = sqlite3.Row
        return [dict(row) for row in conn.execute("SELECT id,title,preferences_json FROM sessions")]


def _sessions(paths) -> list[dict]:
    if _backend() == "pocketbase":
        from deeptutor.services.session.pocketbase_store import (
            _current_user_id,
            _in_workspace,
            _pb,
            _workspace_filter,
        )

        records = (
            _pb()
            .collection("sessions")
            .get_full_list(
                query_params={"filter": _workspace_filter(f'user_id="{_current_user_id()}"')}
            )
        )
        remote = [
            {
                "id": row.session_id,
                "title": row.title,
                "preferences_json": json.dumps(getattr(row, "preferences_json", {}) or {}),
                "record_id": row.id,
            }
            for row in records
            if _in_workspace(row)
        ]
        # Quizzes and older learning sessions still use the local SQLite
        # repository when conversations use PocketBase. Preserve both.
        merged = {row["id"]: row for row in _sqlite_sessions(paths)}
        merged.update({row["id"]: row for row in remote})
        return list(merged.values())
    return _sqlite_sessions(paths)


def discover(workspace_id: str = "") -> dict:
    with workspace_context(workspace_id):
        paths = get_path_service()
        rows = []
        for feature, label in FEATURES.items():
            root = _feature_path(paths, feature)
            try:
                count = size = 0
                for path in _files(root):
                    count += 1
                    size += path.stat().st_size
                rows.append(
                    {
                        "feature": feature,
                        "label": label,
                        "path": str(root),
                        "files": count,
                        "bytes": size,
                        "error": "",
                    }
                )
            except (OSError, WorkspaceError) as exc:
                rows.append(
                    {
                        "feature": feature,
                        "label": label,
                        "path": str(root),
                        "files": 0,
                        "bytes": 0,
                        "error": str(exc),
                    }
                )
        sessions = _sessions(paths)
        rows[0]["sessions"] = len(sessions)
        # Known historical roots are surfaced separately. Never silently import
        # backups over current data or scan another user's home directory.
        legacy = []
        if not workspace_id:
            base = get_account_path_service()
            candidates = [
                base.get_workspace_dir() / "learning" / "archive",
            ]
            for path in candidates:
                if path.exists():
                    legacy.append({"path": str(path), "kind": "historical", "export_only": True})
        return {
            "workspace_id": workspace_id,
            "features": rows,
            "historical": legacy,
            "session_backend": _backend(),
        }


def _backend() -> str:
    from deeptutor.services.pocketbase_client import is_pocketbase_enabled

    return "pocketbase" if is_pocketbase_enabled() else "sqlite"


def _shared_source_blockers(source_id: str, selected: set[str]) -> list[str]:
    """The admin default catalogue remains the canonical shared resource store."""
    from deeptutor.multi_user.context import get_current_user
    from deeptutor.services.auth import AUTH_ENABLED

    if source_id or not AUTH_ENABLED or not get_current_user().is_admin:
        return []
    from deeptutor.multi_user.book_permission import normalize_book_permission
    from deeptutor.multi_user.grants import load_grant
    from deeptutor.multi_user.identity import list_user_info

    blockers = set()
    for user in list_user_info():
        if user.get("role") == "admin":
            continue
        permission = normalize_book_permission(user.get("book_permission"))
        if "book" in selected and (
            permission.default != "none" or any(level != "none" for _, level in permission.books)
        ):
            blockers.add(
                "Books are shared with other accounts. Remove those grants before moving the shared catalogue, or export a copy."
            )
        if "knowledge_bases" in selected and load_grant(user["id"]).get("knowledge_bases"):
            blockers.add(
                "Knowledge bases are shared with other accounts. Remove those grants before migrating, or export a copy."
            )
    return sorted(blockers)


def preview(
    source_id: str, target_id: str, features: list[str], *, session_ids: set[str] | None = None
) -> dict:
    if not features or any(feature not in FEATURES for feature in features):
        raise WorkspaceError("Select at least one supported feature.")
    with workspace_context(source_id):
        source = get_path_service()
        sessions = _sessions(source)
        from deeptutor.services.workspace.dependencies import dependency_closure

        selected, session_ids = dependency_closure(
            source, sessions, features, session_ids=session_ids
        )
        # Legacy capability artifacts may be keyed by turn IDs. Preserve a
        # copy of the chat/output trees while transferring only selected rows.
        if session_ids:
            selected |= {"chat", "outputs", "presentations", "attachments"}
        with workspace_context(target_id) as target_scope:
            target = get_path_service()
        data = discover(source_id)
        source_id = getattr(getattr(source, "scope", None), "workspace_id", "")
        target_id = target_scope.workspace_id
        rows = [row for row in data["features"] if row["feature"] in selected]
        blockers = [row["error"] for row in rows if row["error"]]
        blockers.extend(_shared_source_blockers(source_id, selected))
        if "knowledge_bases" in selected:
            from deeptutor.services.workspace.resources import knowledge_migration_blockers

            blockers.extend(knowledge_migration_blockers(source_id))
        if target_scope.archived:
            blockers.append("Restore the destination workspace before migrating data.")
        if not target_scope.workspace_id and any(
            name.startswith("historical_") for name in selected
        ):
            blockers.append("Choose a custom workspace to retain historical archives.")
        for paths in (source, target):
            if paths.get_chat_history_db().exists():
                with sqlite3.connect(paths.get_chat_history_db()) as conn:
                    if conn.execute(
                        "SELECT 1 FROM turns WHERE status IN ('queued','running','waiting_input') LIMIT 1"
                    ).fetchone():
                        blockers.append("Wait for active conversations before migrating data.")
        if source_id == target_id:
            blockers.append("Choose a different destination workspace.")
        if _backend() == "pocketbase" and session_ids:
            from deeptutor.services.session.pocketbase_store import _pb

            for sid in session_ids:
                turns = (
                    _pb()
                    .collection("turns")
                    .get_full_list(query_params={"filter": f"session_id={json.dumps(sid)}"})
                )
                if any(
                    getattr(row, "status", "") in {"queued", "running", "waiting_input"}
                    for row in turns
                ):
                    blockers.append("Wait for active conversations before migrating data.")
                    break
        artifacts = _selected_artifact_files(source, session_ids)
        # An explicitly selected artifact store includes orphaned outputs too.
        for feature in set(features) & {"outputs", "presentations", "attachments"}:
            root = _feature_path(source, feature)
            artifacts[feature] = [path.relative_to(root).as_posix() for path in _files(root)]
        if _backend() == "sqlite" and session_ids and target.get_chat_history_db().exists():
            with sqlite3.connect(source.get_chat_history_db()) as conn:
                conn.execute("ATTACH DATABASE ? AS target", (str(target.get_chat_history_db()),))
                placeholders = ",".join("?" for _ in session_ids)
                for table, owner in (
                    ("sessions", "id"),
                    ("messages", "session_id"),
                    ("notebook_entries", "session_id"),
                ):
                    if conn.execute(
                        f"SELECT 1 FROM main.{table} a JOIN target.{table} b ON a.id=b.id WHERE a.{owner} IN ({placeholders}) LIMIT 1",  # nosec B608 - fixed tables and placeholders
                        list(session_ids),
                    ).fetchone():
                        blockers.append(
                            "The destination contains conflicting conversation or question IDs. Choose an empty workspace."
                        )
                        break
        for row in rows:
            destination = _feature_path(target, row["feature"])
            if row["feature"] in artifacts:
                # Existing workspaces can receive nonconflicting chat files.
                conflicts = [
                    name for name in artifacts[row["feature"]] if (destination / name).exists()
                ]
                if conflicts:
                    blockers.append(
                        f"Destination already contains {FEATURES[row['feature']]} files with the same IDs."
                    )
            elif row["files"] and destination.exists() and not _empty_scaffold(destination):
                blockers.append(
                    f"Destination already contains {FEATURES[row['feature']]} data. Choose an empty workspace."
                )
        for row in rows:
            if row["feature"] in artifacts:
                root = _feature_path(source, row["feature"])
                row["files"] = len(artifacts[row["feature"]])
                row["bytes"] = sum(
                    (root / relative).stat().st_size for relative in artifacts[row["feature"]]
                )
        return {
            "source_workspace_id": source_id,
            "target_workspace_id": target_id,
            "requested_features": features,
            "features": sorted(selected),
            "dependencies": sorted(selected - set(features)),
            "session_ids": sorted(session_ids),
            "sessions": len(session_ids),
            "files": sum(row["files"] for row in rows),
            "bytes": sum(row["bytes"] for row in rows),
            "blockers": blockers,
            "rows": rows,
            "artifact_files": artifacts,
        }


def _selected_artifact_files(paths, session_ids: set[str]) -> dict[str, list[str]]:
    import re
    from urllib.parse import unquote, urlsplit

    identifiers = set(session_ids)
    referenced_urls = set()
    if _backend() == "pocketbase" and session_ids:
        snapshot = _pocketbase_snapshot(sorted(session_ids))
        identifiers.update(row.get("turn_id", "") for row in snapshot["turns"])
        for table in ("messages", "turn_events"):
            for row in snapshot[table]:
                referenced_urls.update(
                    re.findall(
                        r'/files/(?:outputs|workspace-items)/[^\s"\'<>\\)\]]+',
                        json.dumps(row, ensure_ascii=False),
                    )
                )
    db = paths.get_chat_history_db()
    if db.exists():
        with sqlite3.connect(db) as conn:
            identifiers.update(
                row[0]
                for row in conn.execute("SELECT id,session_id FROM turns")
                if row[1] in session_ids
            )
            for table in ("messages", "turn_events"):
                conn.row_factory = sqlite3.Row
                rows = conn.execute(f"SELECT * FROM {table}")  # nosec B608 - fixed table allowlist
                for row in rows:
                    if (
                        row["session_id"] if table == "messages" else row["turn_id"]
                    ) not in identifiers:
                        continue
                    for value in row:
                        if isinstance(value, str):
                            referenced_urls.update(
                                re.findall(
                                    r'/files/(?:outputs|workspace-items)/[^\s"\'<>\\)\]]+', value
                                )
                            )
    result = {}
    for feature in ("chat", "outputs", "attachments"):
        root = _feature_path(paths, feature)
        result[feature] = [
            p.relative_to(root).as_posix()
            for p in _files(root)
            if identifiers.intersection(p.relative_to(root).parts)
            and not (feature == "chat" and p.relative_to(root).parts[0] == "attachments")
        ]
    for url in referenced_urls:
        relative = unquote(urlsplit(url).path.removeprefix("/files/outputs/"))
        if not url.startswith("/files/outputs/"):
            continue
        candidate = paths.resolve_public_output_path(relative)
        chat_root = _feature_path(paths, "chat")
        if candidate is not None and candidate.is_relative_to(chat_root):
            name = candidate.relative_to(chat_root).as_posix()
            if name not in result["chat"]:
                result["chat"].append(name)
    root = _feature_path(paths, "presentations")
    presented = set()
    for path in root.glob("*/items/*.json"):
        item = json.loads(path.read_text())
        if identifiers.intersection(Path(item.get("relative_path", "")).parts) or any(
            path.stem in url for url in referenced_urls
        ):
            presented.add(path.relative_to(root).as_posix())
            blob = path.parent.parent / "blobs" / item["sha256"]
            if not blob.is_file():
                raise WorkspaceError("A presented file is missing. Restore it before migrating.")
            presented.add(blob.relative_to(root).as_posix())
    result["presentations"] = sorted(presented)
    return result


def export_data(source_id: str, features: list[str], *, include_historical: bool = False) -> dict:
    operation_id = uuid.uuid4().hex
    root = _journal_root() / operation_id
    root.mkdir()
    with data_activity(exclusive=True), workspace_context(source_id):
        assert_no_pending_recovery()
        plan = preview(source_id, "", features)
        paths = get_path_service()
        manifests = {}
        for feature in plan["features"]:
            included = plan["artifact_files"].get(feature)
            manifests[feature] = _snapshot(
                _feature_path(paths, feature),
                root / "snapshot" / feature,
                included=set(included) if included is not None else None,
            )
        if plan["session_ids"] and paths.get_chat_history_db().exists():
            manifests["sessions"] = _snapshot(
                paths.get_chat_history_db(), root / "snapshot" / "sessions"
            )
            database = root / "snapshot" / "sessions" / paths.get_chat_history_db().name
            _prune_session_snapshot(database, set(plan["session_ids"]))
            manifests["sessions"][database.name] = _hash(database)
        if _backend() == "pocketbase":
            atomic_write_json(
                root / "snapshot" / "pocketbase.json", _pocketbase_snapshot(plan["session_ids"])
            )
        if include_historical:
            for index, row in enumerate(discover(source_id)["historical"]):
                manifests[f"historical-{index}"] = _snapshot(
                    Path(row["path"]), root / "snapshot" / f"historical-{index}"
                )
        atomic_write_json(
            root / "snapshot" / "manifest.json", {"version": 1, "plan": plan, "sha256": manifests}
        )
        archive = root / "export.zip"
        with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED, allowZip64=True) as handle:
            for path in _files(root / "snapshot"):
                handle.write(path, path.relative_to(root / "snapshot"))
        result = {
            "id": operation_id,
            "status": "exported",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "plan": plan,
            "download_url": f"/api/settings/workspace/data/exports/{operation_id}",
        }
        atomic_write_json(root / "operation.json", result)
        return result


def migrate_data(
    source_id: str, target_id: str, features: list[str], *, session_ids: set[str] | None = None
) -> dict:
    from deeptutor.services.workspace.session_transfer import transfer_sessions

    with data_activity(exclusive=True):
        assert_no_pending_recovery()
        plan = preview(source_id, target_id, features, session_ids=session_ids)
        if plan["blockers"]:
            raise WorkspaceError(" ".join(plan["blockers"]))
        source_id, target_id = plan["source_workspace_id"], plan["target_workspace_id"]
        with workspace_context(source_id):
            source = get_path_service()
        with workspace_context(target_id):
            target = get_path_service()
        operation_id = uuid.uuid4().hex
        root = _journal_root() / operation_id
        root.mkdir()
        result = {
            "id": operation_id,
            "status": "preparing",
            "created_at": datetime.now(timezone.utc).isoformat(),
            "plan": plan,
            "recovery_path": str(root),
        }
        journal = root / "operation.json"
        atomic_write_json(journal, result)
        installed = []
        try:
            manifests = {}
            for feature in plan["features"]:
                included = plan["artifact_files"].get(feature)
                manifests[feature] = _snapshot(
                    _feature_path(source, feature),
                    root / "snapshot" / feature,
                    included=set(included) if included is not None else None,
                )
            if plan["session_ids"] and source.get_chat_history_db().exists():
                manifests["sessions"] = _snapshot(
                    source.get_chat_history_db(), root / "snapshot" / "sessions"
                )
            if target.get_chat_history_db().exists():
                _snapshot(target.get_chat_history_db(), root / "target-sessions")
            if _backend() == "pocketbase":
                with workspace_context(source_id):
                    atomic_write_json(
                        root / "pocketbase.json", _pocketbase_snapshot(plan["session_ids"])
                    )
            atomic_write_json(root / "manifest.json", manifests)
            result["status"] = "copying"
            atomic_write_json(journal, result)
            for feature in plan["features"]:
                staged = root / "snapshot" / feature
                if not staged.exists():
                    continue
                destination = _feature_path(target, feature)
                destination.parent.mkdir(parents=True, exist_ok=True)
                partial = feature in plan["artifact_files"]
                if destination.exists() and not partial:
                    # Empty generated feature scaffolding may contain nested
                    # empty directories. No files passed the preview gate.
                    shutil.rmtree(destination)
                # Persist the cleanup intent BEFORE creating any destination.
                paths_to_install = (
                    [str(destination / relative) for relative in manifests[feature]]
                    if partial
                    else [str(destination)]
                )
                installed.extend(paths_to_install)
                result["installed_paths"] = installed[:]
                atomic_write_json(journal, result)
                shutil.copytree(staged, destination, dirs_exist_ok=partial)
                if any(
                    _hash(destination / relative) != digest
                    for relative, digest in manifests[feature].items()
                ):
                    raise WorkspaceError(
                        "Destination verification failed; source data was retained."
                    )
                if not feature.startswith("historical_"):
                    _rebind_feature_urls(
                        destination,
                        target_id,
                        included=set(manifests[feature]) if partial else None,
                    )
            result["status"] = "transferring"
            atomic_write_json(journal, result)
            if plan["session_ids"]:
                if _backend() == "pocketbase":
                    _pocketbase_rebind(root / "pocketbase.json", target_id)
                local_ids = set(plan["session_ids"]) & {
                    row["id"] for row in _sqlite_sessions(source)
                }
                if local_ids:
                    transfer_sessions(
                        source.get_chat_history_db(),
                        target.get_chat_history_db(),
                        local_ids,
                        target_id,
                    )
            result["status"] = "committed"
            atomic_write_json(journal, result)
            # The verified snapshot remains available for recovery. Remove
            # source feature trees only after the session transfer commits.
            for feature in plan["features"]:
                original = _feature_path(source, feature)
                if original.exists():
                    if feature in plan["artifact_files"]:
                        for relative in manifests[feature]:
                            if feature == "presentations" and "/blobs/" in relative:
                                continue  # Immutable blobs may serve other retained items.
                            (original / relative).unlink(missing_ok=True)
                    elif original.is_file():
                        original.unlink()
                    else:
                        shutil.rmtree(original)
            result["status"] = "completed"
            atomic_write_json(journal, result)
            _clear_store_caches()
            return result
        except Exception as exc:
            if result["status"] != "committed":
                if result["status"] == "transferring":
                    try:
                        _restore_sessions(root, source, target)
                    except Exception as restore_error:
                        result["status"] = "recovery_required"
                        result["error"] = f"{exc}; recovery: {restore_error}"
                        atomic_write_json(journal, result)
                        raise WorkspaceError(
                            "Migration interrupted; use Recover to restore the retained copies."
                        ) from restore_error
                try:
                    _remove_installed(result, target)
                    result["status"] = "failed"
                except Exception as cleanup_error:
                    result["status"] = "recovery_required"
                    result["error"] = f"{exc}; recovery: {cleanup_error}"
                    atomic_write_json(journal, result)
                    raise WorkspaceError(
                        "Migration interrupted; use Recover to remove partial copies."
                    ) from cleanup_error
            else:
                result["status"] = "cleanup_required"
            result["error"] = str(exc)
            atomic_write_json(journal, result)
            raise


def _pocketbase_snapshot(session_ids: list[str]) -> dict:
    from deeptutor.services.session.pocketbase_store import (
        _current_user_id,
        _find_session_record,
        _pb,
    )

    pb = _pb()
    result: dict[str, list[dict]] = {"sessions": [], "messages": [], "turns": [], "turn_events": []}

    def serialize(row):
        # PocketBase Record exports public collection fields in __dict__.
        return {
            key: value
            for key, value in vars(row).items()
            if not key.startswith("_") and key != "expand"
        }

    for sid in session_ids:
        session = _find_session_record(pb, sid, _current_user_id())
        if session is None:
            if sid in {row["id"] for row in _sqlite_sessions(get_path_service())}:
                continue
            raise WorkspaceError("A source conversation changed during export.")
        result["sessions"].append(serialize(session))
        for table in ("messages", "turns"):
            rows = pb.collection(table).get_full_list(
                query_params={"filter": f"session_id={json.dumps(sid)}"}
            )
            result[table].extend(serialize(row) for row in rows)
            if table == "turns":
                for row in rows:
                    events = pb.collection("turn_events").get_full_list(
                        query_params={"filter": f"turn_id={json.dumps(row.turn_id)}"}
                    )
                    result["turn_events"].extend(serialize(event) for event in events)
    # Normalize dates/record values without including client credentials.
    return json.loads(json.dumps(result, default=str))


def _pocketbase_rebind(snapshot: Path, target_id: str | None) -> None:
    from deeptutor.services.session.pocketbase_store import _json_loads, _pb
    from deeptutor.services.workspace.references import rebind_local_urls

    saved = json.loads(snapshot.read_text())
    collection = _pb().collection("sessions")
    for row in saved["sessions"]:
        prefs = _json_loads(row.get("preferences_json"), {})
        if target_id is not None:
            prefs["workspace_id"] = target_id
        collection.update(
            row["id"],
            {"preferences_json": prefs, "session_updated_at": row.get("session_updated_at", 0)},
        )
        current = collection.get_one(row["id"])
        if _json_loads(getattr(current, "preferences_json", None), {}) != prefs:
            raise WorkspaceError("PocketBase conversation migration could not be verified.")
    for table in ("messages", "turn_events"):
        collection = _pb().collection(table)
        for row in saved[table]:
            fields = {
                key: value
                for key, value in row.items()
                if key in {"content", "attachments_json", "metadata_json", "events_json"}
            }
            if target_id is not None:
                fields = {
                    key: rebind_local_urls(value, target_id)
                    if isinstance(value, str)
                    else json.loads(rebind_local_urls(json.dumps(value), target_id))
                    for key, value in fields.items()
                }
            collection.update(row["id"], fields)
            current = collection.get_one(row["id"])
            if any(getattr(current, key, None) != value for key, value in fields.items()):
                raise WorkspaceError("PocketBase file references could not be verified.")


def _rebind_feature_urls(root: Path, target_id: str, *, included: set[str] | None = None) -> None:
    from deeptutor.services.file_io import atomic_write_text
    from deeptutor.services.workspace.references import rebind_local_urls

    for path in _files(root):
        if included is not None and path.relative_to(root).as_posix() not in included:
            continue
        if path.suffix in {".json", ".md", ".html"}:
            try:
                original = path.read_text(encoding="utf-8")
            except UnicodeError:
                continue
            updated = rebind_local_urls(original, target_id)
            if (
                path.suffix == ".json"
                and path.parent.name == "items"
                and path.name.startswith("wsi_")
            ):
                item = json.loads(updated)
                item["data_workspace_id"] = target_id
                updated = json.dumps(item, ensure_ascii=False)
            if original != updated:
                atomic_write_text(path, updated)
        elif path.suffix in {".sqlite3", ".sqlite", ".db"}:
            with sqlite3.connect(path) as conn:
                tables = conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
                ).fetchall()
                for (table,) in tables:
                    quoted = '"' + table.replace('"', '""') + '"'
                    columns = conn.execute(f"PRAGMA table_info({quoted})").fetchall()
                    names = [row[1] for row in columns if str(row[2]).upper() in {"TEXT", "JSON"}]
                    for name in names:
                        column = '"' + name.replace('"', '""') + '"'
                        values = conn.execute(
                            f"SELECT DISTINCT {column} FROM {quoted} WHERE {column} LIKE '%/files/%' OR {column} LIKE '%/api/reading/%' OR {column} LIKE '%/api/video-learning/%'"  # nosec B608 - quoted schema identifiers
                        ).fetchall()
                        for (value,) in values:
                            updated = rebind_local_urls(value, target_id)
                            if updated != value:
                                conn.execute(
                                    f"UPDATE {quoted} SET {column}=? WHERE {column}=?",  # nosec B608 - quoted identifiers; values bound
                                    (updated, value),
                                )


def _restore_database(snapshot: Path, destination: Path) -> None:
    if not snapshot.exists():
        return
    destination.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(snapshot) as original, sqlite3.connect(destination) as restored:
        original.backup(restored)


def _remove_installed(result: dict, target) -> None:
    allowed: set[str] = set()
    plan = result["plan"]
    for feature in plan["features"]:
        root = _feature_path(target, feature)
        if feature in plan.get("artifact_files", {}):
            allowed.update(str(root / name) for name in plan["artifact_files"][feature])
        else:
            allowed.add(str(root))
    for value in result.get("installed_paths", []):
        if value not in allowed:
            raise WorkspaceError(
                "Recovery paths do not match this workspace. No files were removed."
            )
        path = Path(value)
        if path.is_dir():
            shutil.rmtree(path)
        else:
            path.unlink(missing_ok=True)


def _prune_session_snapshot(database: Path, session_ids: set[str]) -> None:
    with sqlite3.connect(database) as conn:
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("CREATE TEMP TABLE retained_sessions (id TEXT PRIMARY KEY)")
        conn.executemany(
            "INSERT INTO retained_sessions VALUES (?)", [(sid,) for sid in session_ids]
        )
        conn.execute("DELETE FROM sessions WHERE id NOT IN (SELECT id FROM retained_sessions)")
        conn.execute(
            "DELETE FROM notebook_categories WHERE id NOT IN (SELECT category_id FROM notebook_entry_categories)"
        )
        conn.commit()
        conn.execute("VACUUM")


def _restore_sessions(root: Path, source, target) -> None:
    if (root / "pocketbase.json").exists():
        _pocketbase_rebind(root / "pocketbase.json", None)
    _restore_database(
        root / "snapshot" / "sessions" / source.get_chat_history_db().name,
        source.get_chat_history_db(),
    )
    target_backup = root / "target-sessions" / target.get_chat_history_db().name
    if target_backup.exists():
        _restore_database(target_backup, target.get_chat_history_db())
    elif target.get_chat_history_db().exists():
        # The destination did not have a database at admission. The migration
        # lease prevents another writer from populating the new database.
        for suffix in ("", "-wal", "-shm"):
            Path(str(target.get_chat_history_db()) + suffix).unlink(missing_ok=True)


def operations() -> list[dict]:
    rows = []
    for path in _journal_root().glob("*/operation.json"):
        try:
            rows.append(json.loads(path.read_text()))
        except (OSError, ValueError):
            continue
    return sorted(rows, key=lambda row: row.get("created_at", ""), reverse=True)


def assert_no_pending_recovery() -> None:
    pending = {
        "preparing",
        "copying",
        "transferring",
        "committed",
        "cleanup_required",
        "recovery_required",
    }
    for row in operations():
        if row.get("status") in pending:
            raise WorkspaceError(
                "A data migration needs recovery. Open Settings → Data migration before changing learning data."
            )


def recover_operation(operation_id: str) -> dict:
    """Finish committed cleanup, or restore an interrupted precommit transfer."""
    if len(operation_id) != 32 or any(c not in "0123456789abcdef" for c in operation_id):
        raise WorkspaceError("Migration not found.")
    root = _journal_root() / operation_id
    journal = root / "operation.json"
    if not journal.exists():
        raise WorkspaceError("Migration not found.")
    with data_activity(exclusive=True):
        result = json.loads(journal.read_text())
        if result["status"] in {"completed", "exported", "recovered"}:
            return result
        plan = result["plan"]
        with workspace_context(plan["source_workspace_id"]):
            source = get_path_service()
        with workspace_context(plan["target_workspace_id"]):
            target = get_path_service()
        if result["status"] in {"committed", "cleanup_required"}:
            for feature in plan["features"]:
                original = _feature_path(source, feature)
                snapshot = root / "snapshot" / feature
                if original.exists() and snapshot.exists():
                    manifest = json.loads((root / "manifest.json").read_text())[feature]
                    # Back up databases through SQLite again: byte hashes of
                    # a source with WAL pages cannot match the backup file.
                    check = root / "cleanup-check" / feature
                    if check.exists():
                        shutil.rmtree(check)
                    actual = _snapshot(original, check, included=set(manifest))
                    manifest = {
                        key: value
                        for key, value in manifest.items()
                        if original.is_file() or (original / key).exists()
                    }
                    if actual != manifest:
                        raise WorkspaceError(
                            "Source data changed after migration; retain both copies and reconcile manually."
                        )
                    if feature in plan.get("artifact_files", {}):
                        for relative in manifest:
                            if feature == "presentations" and "/blobs/" in relative:
                                continue
                            (original / relative).unlink(missing_ok=True)
                    elif original.is_file():
                        original.unlink()
                    else:
                        shutil.rmtree(original)
            result["status"] = "completed"
        else:
            if result["status"] in {"transferring", "recovery_required"}:
                _restore_sessions(root, source, target)
            _remove_installed(result, target)
            result["status"] = "recovered"
        result.pop("error", None)
        atomic_write_json(journal, result)
        _clear_store_caches()
        return result


def _clear_store_caches() -> None:
    from deeptutor.learning import storage as learning
    from deeptutor.services.session import sqlite_store
    from deeptutor.services.storage import file_library

    learning._initialized_db_paths.clear()
    sqlite_store._instances.clear()
    file_library.reset_file_library_store()


def export_path(operation_id: str) -> Path:
    if len(operation_id) != 32 or any(c not in "0123456789abcdef" for c in operation_id):
        raise WorkspaceError("Export not found.")
    path = _journal_root() / operation_id / "export.zip"
    if not path.is_file():
        raise WorkspaceError("Export not found.")
    return path
