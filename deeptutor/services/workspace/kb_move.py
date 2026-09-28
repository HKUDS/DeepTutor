"""Move one owned knowledge base between account-local storage roots.

The index and raw documents are copied as a unit. The source remains intact
until the destination, catalog entries, and redirects have been published.
"""

from __future__ import annotations

from copy import deepcopy
import hashlib
import json
import os
from pathlib import Path
import shutil
from typing import Any, cast
import uuid

from deeptutor.knowledge.kb_types import MARGINNOTE4_KB_TYPE, is_connected_kb
from deeptutor.multi_user.context import get_current_user
from deeptutor.services.file_io import atomic_write_json
from deeptutor.services.path_service import get_path_service
from deeptutor.services.rag.factory import has_ready_provider_index
from deeptutor.services.workspace.activity import data_activity
from deeptutor.services.workspace.context import workspace_context
from deeptutor.services.workspace.data_migration import (
    _files,
    _snapshot,
    assert_no_pending_recovery,
)
from deeptutor.services.workspace.knowledge import (
    _move_aliases_path,
    canonical_kb_id,
    move_aliases,
    parse_kb_id,
    qualified_kb_id,
    resolve_qualified,
)
from deeptutor.services.workspace.models import WorkspaceError


def _config(root: Path) -> dict:
    path = root / "kb_config.json"
    if path.is_symlink():
        raise WorkspaceError("Knowledge configuration cannot be a symbolic link.")
    if not path.exists():
        return {"knowledge_bases": {}}
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict) or not isinstance(value.get("knowledge_bases"), dict):
        raise WorkspaceError("Knowledge configuration is damaged.")
    return value


def _root(workspace_id: str) -> tuple[Path, bool]:
    with workspace_context(workspace_id) as scope:
        return get_path_service().get_knowledge_bases_root(), scope.archived


def _shared_grants(name: str) -> list[str]:
    from deeptutor.services.auth import AUTH_ENABLED

    if not AUTH_ENABLED or not get_current_user().is_admin:
        return []
    from deeptutor.multi_user.grants import load_grant
    from deeptutor.multi_user.identity import list_user_info

    return [
        user["id"]
        for user in list_user_info()
        if user.get("role") != "admin"
        and any(
            str(item.get("name") or item.get("kb_name") or "") == name
            or str(item.get("resource_id") or item.get("id") or "") == f"admin:kb:{name}"
            for item in load_grant(user["id"]).get("knowledge_bases", []) or []
        )
    ]


def _legacy_account_id(name: str) -> str:
    # Historical general-chat selections used a role-specific prefix. Keep
    # that alias only for the owning account; custom workspaces can have
    # same-name KBs, so their legacy IDs cannot be redirected globally.
    role = "admin" if get_current_user().is_admin else "user"
    return f"{role}:kb:{name}"


def preview_kb_move(source_id: str, target_workspace_id: str) -> dict:
    """Return a collision and assignment preview without changing either store."""
    from deeptutor.services.workspace import get_content_workspace_service

    source_id = canonical_kb_id(str(source_id or ""))
    parsed = parse_kb_id(source_id)
    if parsed is None or not parsed[1]:
        raise WorkspaceError("Choose a knowledge base from the library.")
    source_workspace_id, name = parsed
    target_workspace_id = str(target_workspace_id or "")
    # Move is a library operation. Chat selection is a read ceiling for turns,
    # not an ownership check for managing a different stored KB.
    resolve_qualified(source_id, require_write=True)
    source_root, source_archived = _root(source_workspace_id)
    target_root, target_archived = _root(target_workspace_id)
    source_config = _config(source_root)
    target_config = _config(target_root)
    entry = source_config["knowledge_bases"].get(name)
    source_dir = source_root / name
    target_dir = target_root / name
    blockers: list[str] = []
    if source_workspace_id == target_workspace_id or source_root == target_root:
        blockers.append("Choose a different storage workspace.")
    if source_archived or target_archived:
        blockers.append("Restore the workspace before moving its knowledge base.")
    if not isinstance(entry, dict):
        blockers.append("The source knowledge base is missing from its configuration.")
    elif entry.get("type") == MARGINNOTE4_KB_TYPE:
        blockers.append(
            "MarginNote 4 stores its synced database outside the knowledge-base folder. "
            "Move is unavailable until that database can be transferred safely."
        )
    elif not is_connected_kb(entry):
        if entry.get("path", name) != name:
            blockers.append(
                "This knowledge base has a nonstandard storage path and cannot be moved safely."
            )
        if not source_dir.is_dir() or source_dir.is_symlink():
            blockers.append("The source knowledge base directory is unavailable.")
        if str(entry.get("status") or "ready") not in {"ready", "error", "needs_reindex"}:
            blockers.append("Wait for this knowledge base to finish processing before moving it.")
    if name in target_config["knowledge_bases"] or target_dir.exists() or target_dir.is_symlink():
        blockers.append(f"Destination already contains a knowledge base named '{name}'.")
    target_id = qualified_kb_id(name, target_workspace_id)
    if target_id in move_aliases():
        blockers.append("Destination ID is reserved by an earlier knowledge-base move.")
    if not source_workspace_id and _shared_grants(name):
        blockers.append(
            "This knowledge base is shared with other accounts. Remove those grants before moving it."
        )
    if source_dir.is_dir() and not source_dir.is_symlink():
        try:
            files = list(_files(source_dir))
            file_count = len(files)
            byte_count = sum(path.stat().st_size for path in files)
        except (OSError, WorkspaceError) as exc:
            blockers.append(str(exc))
            file_count = byte_count = 0
    else:
        file_count = byte_count = 0
    aliases = move_aliases()
    old_ids = {source_id, *(key for key in aliases if canonical_kb_id(key) == source_id)}
    if not source_workspace_id:
        old_ids.add(_legacy_account_id(name))
    assignments = [
        {"workspace_id": row["workspace_id"], "display_name": row["display_name"]}
        for row in get_content_workspace_service()._catalog()
        if any(ref in old_ids for ref in (row.get("resources") or {}).get("knowledge_bases") or [])
    ]
    return {
        "source_id": source_id,
        "target_id": target_id,
        "source_workspace_id": source_workspace_id,
        "target_workspace_id": target_workspace_id,
        "name": name,
        "files": file_count,
        "bytes": byte_count,
        "assignments": assignments,
        "blockers": blockers,
    }


def _rewrite_assignments(old_ids: set[str], target_id: str) -> None:
    from deeptutor.services.workspace import get_content_workspace_service

    service = get_content_workspace_service()
    owner = get_current_user().scope.user_id
    with service._catalog_connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        for workspace_id, payload in conn.execute("SELECT id,payload FROM workspaces"):
            row = json.loads(payload)
            if row.get("owner_id") != owner:
                continue
            resources = row.get("resources") or {}
            selected = resources.get("knowledge_bases")
            if not isinstance(selected, list) or not any(ref in old_ids for ref in selected):
                continue
            resources["knowledge_bases"] = list(
                dict.fromkeys(target_id if ref in old_ids else ref for ref in selected)
            )
            row["resources"] = resources
            conn.execute(
                "UPDATE workspaces SET payload = ? WHERE id = ?",
                (json.dumps(row, ensure_ascii=False), workspace_id),
            )


def _restore_assignments(previous: dict[str, dict]) -> None:
    from deeptutor.services.workspace import get_content_workspace_service

    service = get_content_workspace_service()
    owner = get_current_user().scope.user_id
    with service._catalog_connection() as conn:
        conn.execute("BEGIN IMMEDIATE")
        for workspace_id, resources in previous.items():
            record = conn.execute(
                "SELECT payload FROM workspaces WHERE id = ?", (workspace_id,)
            ).fetchone()
            if record is None:
                continue
            row = json.loads(record[0])
            if row.get("owner_id") != owner:
                continue
            row["resources"] = resources
            conn.execute(
                "UPDATE workspaces SET payload = ? WHERE id = ?",
                (json.dumps(row, ensure_ascii=False), workspace_id),
            )


def _copy_kb(source: Path, destination: Path) -> None:
    destination.mkdir(parents=True)
    # _snapshot verifies every byte and backs up SQLite with WAL state.
    _snapshot(source, destination)
    for directory, dirs, _ in os.walk(source, followlinks=False):
        for name in dirs:
            candidate = Path(directory) / name
            if candidate.is_symlink():
                raise WorkspaceError("Knowledge base contains a symbolic link.")
            (destination / candidate.relative_to(source)).mkdir(parents=True, exist_ok=True)


def _parse_cache_root(workspace_id: str) -> Path:
    with workspace_context(workspace_id):
        return get_path_service().get_parse_cache_root()


def _rebase_llamaindex_paths(
    stage: Path, source: Path, target: Path, source_cache_root: Path
) -> None:
    """Rebase persisted citations and keep indexed parse-cache images with the KB.

    FAISS vector files are binary and contain no paths. LlamaIndex stores node
    paths in docstore JSON and, for older simple indexes, vector-store JSON.
    BM25 sidecars can contain serialized nodes, so discard them; retrieval
    rebuilds BM25 from the corrected docstore when needed.
    """
    copied_images: dict[str, str] = {}
    source_prefix = str(source) + os.sep
    cache_root = source_cache_root.resolve()

    def rewrite_path(value: str, key: str) -> str:
        if value.startswith(source_prefix):
            relative = Path(value).relative_to(source)
            if not (stage / relative).is_file():
                raise WorkspaceError(f"Indexed source is missing: {relative}")
            return str(target / relative)
        if key != "image_path" or not Path(value).is_absolute():
            return value
        if value in copied_images:
            return copied_images[value]
        image = Path(value)
        try:
            resolved = image.resolve(strict=True)
            relative = resolved.relative_to(cache_root)
        except (OSError, ValueError) as exc:
            raise WorkspaceError(
                "An indexed image is outside the movable knowledge base and parse cache."
            ) from exc
        path_parts = [image, *list(image.parents)[: len(image.parts) - len(cache_root.parts)]]
        if (
            resolved != image
            or not image.is_file()
            or any(part.is_symlink() for part in path_parts)
        ):
            raise WorkspaceError("An indexed image cannot be copied safely.")
        digest = hashlib.sha256(value.encode("utf-8")).hexdigest()
        asset = Path(".index_assets") / digest / image.name
        _snapshot(image, stage / asset.parent)
        copied_images[value] = str(target / asset)
        return copied_images[value]

    def rewrite(value: object, key: str = "") -> tuple[object, bool]:
        if isinstance(value, dict):
            changed = False
            result = {}
            for child_key, child_value in value.items():
                result[child_key], child_changed = rewrite(child_value, child_key)
                changed |= child_changed
            return result, changed
        if isinstance(value, list):
            children = [rewrite(child) for child in value]
            return [child for child, _ in children], any(changed for _, changed in children)
        if isinstance(value, str):
            if value.startswith(source_prefix) or key == "image_path":
                updated = rewrite_path(value, key)
                return updated, updated != value
            # Some LlamaIndex stores embed node objects as serialized JSON.
            if key == "__data__" and value.startswith("{") and source_prefix in value:
                parsed = json.loads(value)
                rebased_data, changed = rewrite(parsed)
                if changed:
                    return json.dumps(rebased_data, ensure_ascii=False), True
        return value, False

    for docstore in list(stage.rglob("docstore.json")):
        relative = docstore.relative_to(stage)
        if relative.parts[0] != "llamaindex_storage" and not (
            relative.parts[0].startswith("version-") or relative.parts[0] == "index_versions"
        ):
            continue
        storage = docstore.parent
        if not (storage / "index_store.json").is_file():
            continue
        for path in (docstore, *storage.glob("*vector_store.json")):
            # The FAISS store keeps binary bytes under a .json filename.
            if path != docstore:
                with path.open("rb") as handle:
                    if handle.read(1) != b"{":
                        continue
            try:
                payload = json.loads(path.read_text(encoding="utf-8"))
                updated, changed = rewrite(payload)
            except (ValueError, UnicodeError) as exc:
                raise WorkspaceError(f"Cannot rebase LlamaIndex paths in {path.name}.") from exc
            if changed:
                atomic_write_json(path, cast(dict[str, Any], updated))
        shutil.rmtree(storage / "bm25_retriever", ignore_errors=True)


def move_kb(source_id: str, target_workspace_id: str) -> dict:
    """Publish one verified KB copy and preserve qualified saved references."""
    with data_activity(exclusive=True):
        assert_no_pending_recovery()
        plan = preview_kb_move(source_id, target_workspace_id)
        if plan["blockers"]:
            raise WorkspaceError(" ".join(plan["blockers"]))
        name = plan["name"]
        source_root, _ = _root(plan["source_workspace_id"])
        target_root, _ = _root(plan["target_workspace_id"])
        source_path = source_root / name
        target_path = target_root / name
        source_before = _config(source_root)
        target_before = _config(target_root)
        aliases_before = move_aliases()
        aliases_path = _move_aliases_path()
        aliases_existed = aliases_path.exists()
        source_config_path = source_root / "kb_config.json"
        target_config_path = target_root / "kb_config.json"
        source_config_existed = source_config_path.exists()
        target_config_existed = target_config_path.exists()
        old_ids = {
            plan["source_id"],
            *(key for key in aliases_before if canonical_kb_id(key) == plan["source_id"]),
        }
        if not plan["source_workspace_id"]:
            old_ids.add(_legacy_account_id(name))
        stage = target_root / f".kb-move-{uuid.uuid4().hex}"
        published = False
        source_hidden = None
        from deeptutor.services.workspace import get_content_workspace_service

        catalog = get_content_workspace_service()
        assignment_before = {
            row["workspace_id"]: deepcopy(row.get("resources") or {})
            for row in catalog._catalog()
            if any(
                ref in old_ids for ref in (row.get("resources") or {}).get("knowledge_bases") or []
            )
        }
        try:
            if source_path.is_dir():
                _copy_kb(source_path, stage)
                entry = source_before["knowledge_bases"][name]
                provider = entry.get("rag_provider")
                if provider in {None, "", "llamaindex"}:
                    _rebase_llamaindex_paths(
                        stage,
                        source_path,
                        target_path,
                        _parse_cache_root(plan["source_workspace_id"]),
                    )
                if (
                    not is_connected_kb(entry)
                    and has_ready_provider_index(source_path, provider)
                    and not has_ready_provider_index(stage, provider)
                ):
                    raise WorkspaceError(
                        "The copied index did not pass its provider readiness check."
                    )
                if target_path.exists():
                    raise WorkspaceError(
                        f"Destination already contains a knowledge base named '{name}'."
                    )
                stage.rename(target_path)
                published = True
            target_next = deepcopy(target_before)
            target_next["knowledge_bases"][name] = deepcopy(source_before["knowledge_bases"][name])
            source_next = deepcopy(source_before)
            del source_next["knowledge_bases"][name]
            source_defaults = source_next.get("defaults") or {}
            if source_defaults.get("default_kb") == name:
                source_defaults["default_kb"] = None
                source_next["defaults"] = source_defaults
                target_defaults = target_next.setdefault("defaults", {})
                if not target_defaults.get("default_kb"):
                    target_defaults["default_kb"] = name
            atomic_write_json(target_config_path, target_next)
            _rewrite_assignments(old_ids, plan["target_id"])
            aliases_next = {
                key: (plan["target_id"] if value in old_ids else value)
                for key, value in aliases_before.items()
            }
            aliases_next[plan["source_id"]] = plan["target_id"]
            if not plan["source_workspace_id"]:
                aliases_next[_legacy_account_id(name)] = plan["target_id"]
            atomic_write_json(aliases_path, aliases_next)
            atomic_write_json(source_config_path, source_next)
            if source_path.is_dir():
                source_hidden = source_root / f".kb-moved-{uuid.uuid4().hex}"
                source_path.rename(source_hidden)
        except BaseException:
            if source_hidden is not None and source_hidden.exists():
                source_hidden.rename(source_path)
            if source_config_existed:
                atomic_write_json(source_config_path, source_before)
            else:
                source_config_path.unlink(missing_ok=True)
            if target_config_existed:
                atomic_write_json(target_config_path, target_before)
            else:
                target_config_path.unlink(missing_ok=True)
            _restore_assignments(assignment_before)
            if aliases_existed:
                atomic_write_json(aliases_path, aliases_before)
            else:
                aliases_path.unlink(missing_ok=True)
            if published:
                shutil.rmtree(target_path)
            if stage.exists():
                shutil.rmtree(stage)
            raise
        if source_hidden is not None:
            try:
                shutil.rmtree(source_hidden)
            except OSError:
                # The hidden original remains available for manual recovery;
                # it does not appear as an active knowledge base.
                plan["cleanup_path"] = str(source_hidden)
        plan["status"] = "moved"
        return plan
