"""Workspace identities, built-in roots, configuration snapshots and migration.

The filesystem service supplies path confinement and file presentation; this
mixin owns the persistent catalog, keeping content operations independent of
workspace management.
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import shutil
import socket
import sqlite3
from typing import TYPE_CHECKING, Any
import uuid

from deeptutor.multi_user.context import get_current_user
from deeptutor.services.workspace.models import WorkspaceBinding, WorkspaceError
from deeptutor.utils.secret_files import ensure_private_directory

_INTERNAL_DIR = ".deeptutor"


def _owner_id() -> str:
    # Administrators share the same runtime settings and scope directory.
    # Token/account IDs must not create different system roots in that scope.
    return get_current_user().scope.user_id


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class WorkspaceCatalogMixin:
    if TYPE_CHECKING:
        # Supplied by ContentWorkspaceService, which owns filesystem access.
        @staticmethod
        def _paths() -> Any: ...
        def _default_root(self) -> Path: ...
        def _deployment_root(self) -> Path | None: ...
        def _assert_allowed_root(self, root: Path) -> None: ...
        def binding_by_id(self, workspace_id: str) -> WorkspaceBinding: ...
        def current_binding(self, *, ensure_output: bool = False) -> WorkspaceBinding: ...
        def _read_settings(self) -> dict[str, Any]: ...
        def validate(self, path: str | Path | None) -> dict[str, Any]: ...
        def _ensure_ready(self, binding: WorkspaceBinding) -> None: ...

    def _catalog_file(self) -> Path:
        return self._paths().get_runtime_state_dir() / "workspaces.sqlite3"

    def _managed_root(self) -> Path:
        configured = self._catalog_metadata("root")
        if configured:
            return Path(configured).expanduser().resolve()
        if root := self._deployment_content_root():
            return root / "workspaces"
        return self._default_root().parent / "workspaces"

    def _session_root(self) -> Path:
        # Retain access to previously registered session roots and artifacts.
        if root := self._deployment_content_root():
            return root / "sessions"
        return self._paths().get_runtime_state_dir() / "session_workspaces"

    def _deployment_content_root(self) -> Path | None:
        # The sidecar already shares /workspace/outputs read-write. Keep
        # content there without mounting application settings or databases.
        # The internal directory is excluded from the legacy workspace's
        # discovery tools; each chat receives only its own leaf as its root.
        deployment = self._deployment_root()
        if deployment is None:
            return None
        owner = uuid.uuid5(uuid.NAMESPACE_URL, _owner_id()).hex
        return deployment / "outputs" / _INTERNAL_DIR / "chat" / owner

    @contextmanager
    def _catalog_connection(self):
        path = self._catalog_file()
        ensure_private_directory(path.parent)
        conn = sqlite3.connect(path, timeout=30)
        try:
            conn.execute(
                "CREATE TABLE IF NOT EXISTS workspaces (id TEXT PRIMARY KEY, payload TEXT NOT NULL)"
            )
            conn.execute(
                "CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL)"
            )
            with conn:
                yield conn
        finally:
            conn.close()

    def _catalog(self) -> list[dict[str, Any]]:
        if not self._catalog_file().exists():
            return []
        try:
            with self._catalog_connection() as conn:
                rows = [
                    json.loads(row[0])
                    for row in conn.execute("SELECT payload FROM workspaces ORDER BY rowid")
                ]
        except (sqlite3.Error, ValueError) as exc:
            raise WorkspaceError("The workspace registry could not be read.") from exc
        return [row for row in rows if row.get("owner_id") == _owner_id()]

    def _save_registration(self, row: dict[str, Any]) -> dict[str, Any]:
        # Serialize first registration across processes, including two requests
        # registering the same physical folder under different display names.
        with self._catalog_connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            existing = conn.execute(
                "SELECT payload FROM workspaces WHERE id = ? OR "
                "(json_extract(payload, '$.owner_id') = ? AND json_extract(payload, '$.path') = ?)",
                (row["workspace_id"], row["owner_id"], row["path"]),
            ).fetchone()
            if existing:
                saved = json.loads(existing[0])
                if saved.get("owner_id") != row["owner_id"]:
                    raise WorkspaceError("Workspace identity belongs to another user.")
                return saved
            conn.execute(
                "INSERT INTO workspaces VALUES (?, ?)",
                (row["workspace_id"], json.dumps(row, ensure_ascii=False)),
            )
        return row

    def _registered_binding(self, row: dict[str, Any]) -> WorkspaceBinding:
        root = Path(row["path"]).expanduser().resolve()
        self._assert_allowed_root(root)
        return WorkspaceBinding(row["workspace_id"], root, row["display_name"])

    def _catalog_metadata(self, key: str) -> Any:
        if not self._catalog_file().exists():
            return None
        with self._catalog_connection() as conn:
            row = conn.execute("SELECT value FROM metadata WHERE key = ?", (key,)).fetchone()
        return json.loads(row[0]) if row else None

    def _builtin_id(self, kind: str) -> str:
        return f"ws_{uuid.uuid5(uuid.NAMESPACE_URL, f'{_owner_id()}:workspace:{kind}').hex}"

    def _ensure_builtin_workspaces(self) -> None:
        rows = {row["workspace_id"]: row for row in self._catalog()}
        for kind, name in (("system", "System workspace"), ("general", "General workspace")):
            workspace_id = self._builtin_id(kind)
            if workspace_id in rows:
                continue
            root = self._managed_root() / workspace_id
            # Publish a built-in only after its initial files are ready.
            # Concurrent requests must not race the one-time skill import.
            with self._catalog_connection() as conn:
                conn.execute("BEGIN IMMEDIATE")
                if conn.execute(
                    "SELECT id FROM workspaces WHERE id = ?", (workspace_id,)
                ).fetchone():
                    continue
                ensure_private_directory(root)
                if kind == "system":
                    legacy_skills = self._default_root() / "skills"
                    skills = root / "skills"
                    if legacy_skills.is_dir() and not skills.exists():
                        temporary = root / f".skills-import-{uuid.uuid4().hex}"
                        try:
                            shutil.copytree(legacy_skills, temporary, symlinks=True)
                            temporary.rename(skills)
                        finally:
                            if temporary.exists():
                                shutil.rmtree(temporary)
                    else:
                        skills.mkdir(exist_ok=True)
                    self._write_system_snapshot(root)
                row = {
                    "workspace_id": workspace_id,
                    "owner_id": _owner_id(),
                    "path": str(root),
                    "display_name": name,
                    "kind": kind,
                    "follows_root": True,
                    "archived": False,
                    "created_at": _utc_now(),
                }
                conn.execute(
                    "INSERT INTO workspaces VALUES (?, ?)",
                    (workspace_id, json.dumps(row, ensure_ascii=False)),
                )

    def _write_system_snapshot(self, root: Path) -> dict[str, Any]:
        from deeptutor.multi_user.paths import SYSTEM_ROOT
        from deeptutor.services.workspace.snapshot import write_snapshot

        paths = [self._paths().get_settings_dir() / "mcp.json"]
        owner = _owner_id()
        if re.fullmatch(r"[A-Za-z0-9_-]+", owner):
            paths.append(SYSTEM_ROOT / "user-mcp" / f"{owner}.json")
        return write_snapshot(root, self._paths().get_settings_dir(), mcp_paths=paths)

    def system_binding(self) -> WorkspaceBinding:
        self.assert_available()
        self._ensure_builtin_workspaces()
        return self.binding_by_id(self._builtin_id("system"))

    def general_binding(self) -> WorkspaceBinding:
        self.assert_available()
        self._ensure_builtin_workspaces()
        return self.binding_by_id(self._builtin_id("general"))

    def refresh_system_snapshot(self) -> dict[str, Any]:
        self.assert_available()
        return self._write_system_snapshot(self.system_binding().root)

    def describe_catalog(self) -> dict[str, Any]:
        return {
            "root": str(self._managed_root()),
            "workspaces": self.list_workspaces(),
            "migration": self._catalog_metadata("migration"),
        }

    def list_workspaces(self) -> list[dict[str, Any]]:
        self._ensure_builtin_workspaces()
        # Preserve explicitly selected legacy directories, without making the
        # old runtime directory the new default conversation workspace.
        legacy = []
        current = self.current_binding()
        if not current.is_default:
            legacy.append(current)
        for row in self._read_settings().get("bindings") or []:
            try:
                legacy.append(self.binding_by_id(str(row.get("id") or "")))
            except WorkspaceError:
                continue
        registered = {row["workspace_id"] for row in self._catalog()}
        for binding in legacy:
            if binding.workspace_id not in registered:
                self._save_registration(
                    {
                        "workspace_id": binding.workspace_id,
                        "owner_id": _owner_id(),
                        "path": str(binding.root),
                        "display_name": binding.display_name,
                        "kind": "workspace",
                        "follows_root": False,
                        "archived": False,
                        "created_at": _utc_now(),
                    }
                )
        result = []
        for row in self._catalog():
            if row.get("kind") == "session":
                continue
            status = self.validate(row["path"])
            result.append(
                {
                    "workspace_id": row["workspace_id"],
                    "display_name": row["display_name"],
                    "path": row["path"],
                    "kind": row["kind"],
                    "follows_root": bool(row.get("follows_root", False)),
                    "archived": bool(row.get("archived")),
                    "created_at": row["created_at"],
                    "status": status["status"],
                    "error": status.get("error", ""),
                    "resources": row.get("resources")
                    or {"skills": None, "mcp": None, "knowledge_bases": None},
                }
            )
        return sorted(result, key=lambda row: {"system": 0, "general": 1}.get(row["kind"], 2))

    def create_workspace(
        self, name: str, path: str | None = None, *, resources: dict | None = None
    ) -> dict[str, Any]:
        self.assert_available()
        name = name.strip()
        if not name or len(name) > 100:
            raise WorkspaceError("A workspace name must contain 1 to 100 characters.")
        if resources is not None:
            from deeptutor.services.workspace.resources import validate_resources

            resources = validate_resources(resources)
        workspace_id = f"ws_{uuid.uuid4().hex}"
        root = Path(path).expanduser().resolve() if path else self._managed_root() / workspace_id
        self._assert_allowed_root(root)
        if path:
            if not root.is_dir():
                raise WorkspaceError("The selected workspace folder does not exist.")
        else:
            ensure_private_directory(root)
        # Reusing a folder must reuse its identity, including legacy artifacts.
        for row in self.list_workspaces():
            if Path(row["path"]).resolve() == root:
                return self.update_workspace(
                    row["workspace_id"], name=name, archived=False, resources=resources
                )
        binding = WorkspaceBinding(workspace_id, root, name)
        self._ensure_ready(binding)
        saved = self._save_registration(
            {
                "workspace_id": workspace_id,
                "owner_id": _owner_id(),
                "path": str(root),
                "display_name": name,
                "kind": "workspace",
                "follows_root": path is None,
                "archived": False,
                "created_at": _utc_now(),
                "resources": resources or {},
            }
        )
        if saved["kind"] != "workspace":
            raise WorkspaceError("This folder belongs to a private conversation.")
        return next(
            row for row in self.list_workspaces() if row["workspace_id"] == saved["workspace_id"]
        )

    def update_workspace(
        self,
        workspace_id: str,
        *,
        name: str | None = None,
        archived: bool | None = None,
        resources: dict | None = None,
    ) -> dict[str, Any]:
        self.assert_available()
        if name is not None and (not name.strip() or len(name.strip()) > 100):
            raise WorkspaceError("A workspace name must contain 1 to 100 characters.")
        if resources is not None:
            from deeptutor.services.workspace.resources import validate_resources

            previous = next((r for r in self._catalog() if r["workspace_id"] == workspace_id), {})
            resources = validate_resources(
                resources, previous=previous.get("resources"), workspace_id=workspace_id
            )
        with self._catalog_connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            record = conn.execute(
                "SELECT payload FROM workspaces WHERE id = ?", (workspace_id,)
            ).fetchone()
            row = json.loads(record[0]) if record else None
            if (
                not row
                or row.get("owner_id") != _owner_id()
                or row.get("kind") not in {"workspace", "general"}
            ):
                raise WorkspaceError("Workspace not found.")
            if row["kind"] == "general" and (name is not None or archived is not None):
                raise WorkspaceError("The default workspace cannot be renamed or archived.")
            if resources is not None:
                row["resources"] = resources
            if name is not None:
                row["display_name"] = name.strip()
            if archived is not None:
                row["archived"] = archived
            conn.execute(
                "UPDATE workspaces SET payload = ? WHERE id = ?",
                (json.dumps(row, ensure_ascii=False), workspace_id),
            )
        return next(row for row in self.list_workspaces() if row["workspace_id"] == workspace_id)

    def validate_chat_binding(
        self, workspace_id: str, *, existing: bool = False
    ) -> WorkspaceBinding:
        self.assert_available()
        self._ensure_builtin_workspaces()
        rows = self._catalog()
        row = next(
            (
                row
                for row in rows
                if row["workspace_id"] == workspace_id and row["kind"] in {"workspace", "general"}
            ),
            None,
        )
        if row is None:
            # Legacy folder ids can still arrive from an older client.
            self.binding_by_id(workspace_id)
            row = next(
                (item for item in self.list_workspaces() if item["workspace_id"] == workspace_id),
                None,
            )
        if row is None or row.get("kind") == "system" or (row["archived"] and not existing):
            raise WorkspaceError("Workspace not found or archived.")
        binding = self.binding_by_id(workspace_id)
        self._ensure_ready(binding)
        return binding

    def session_binding(self, session_id: str) -> WorkspaceBinding:
        # Unbound sessions share the general workspace; output directories are
        # still separated by capability, session and turn.
        self.assert_available()
        return self.general_binding()

    def assert_available(self) -> None:
        migration = self._catalog_metadata("migration")
        if not migration:
            return
        if migration.get("host") == socket.gethostname():
            try:
                os.kill(int(migration["pid"]), 0)
            except ProcessLookupError:
                # Copies never replace source data and the catalog commit is
                # atomic, so an interrupted process can be safely unlocked.
                with self._catalog_connection() as conn:
                    conn.execute(
                        "DELETE FROM metadata WHERE key = 'migration' AND value = ?",
                        (json.dumps(migration),),
                    )
                return
        raise WorkspaceError(
            "Workspace storage is being migrated. Try again when migration finishes."
        )

    @contextmanager
    def maintenance(self):
        self.assert_available()
        token = {"id": uuid.uuid4().hex, "pid": os.getpid(), "host": socket.gethostname()}
        with self._catalog_connection() as conn:
            conn.execute("BEGIN IMMEDIATE")
            if conn.execute("SELECT value FROM metadata WHERE key = 'migration'").fetchone():
                raise WorkspaceError("Another workspace migration is already running.")
            conn.execute("INSERT INTO metadata VALUES ('migration', ?)", (json.dumps(token),))
        try:
            yield
        finally:
            with self._catalog_connection() as conn:
                conn.execute(
                    "DELETE FROM metadata WHERE key = 'migration' AND value = ?",
                    (json.dumps(token),),
                )

    def migrate_workspace(self, workspace_id: str, destination: str) -> dict[str, Any]:
        from deeptutor.services.workspace.migration import migrate_locations

        row = next((row for row in self._catalog() if row["workspace_id"] == workspace_id), None)
        if row is None or row.get("kind") == "session":
            raise WorkspaceError("Workspace not found.")
        if not destination.strip():
            raise WorkspaceError("A destination folder is required.")
        migrate_locations(self, [(row, Path(destination).expanduser().resolve())])
        return self.describe_catalog()

    def migrate_root(self, destination: str) -> dict[str, Any]:
        from deeptutor.services.workspace.migration import migrate_locations

        if not destination.strip():
            raise WorkspaceError("A root folder is required.")
        target = Path(destination).expanduser().resolve()
        self._assert_allowed_root(target)
        self._ensure_builtin_workspaces()
        moves = [
            (row, target / row["workspace_id"])
            for row in self._catalog()
            if row.get("follows_root") and row.get("kind") != "session"
        ]
        migrate_locations(self, moves, new_root=target)
        return self.describe_catalog()
