"""Stable references to knowledge catalogs without copying existing indexes."""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import replace
import json
from pathlib import Path

from fastapi import HTTPException

library_request: ContextVar[bool] = ContextVar("knowledge_library_request", default=False)


def qualified_kb_id(name: str, workspace_id: str = "") -> str:
    return f"workspace:{workspace_id}:kb:{name}" if workspace_id else f"account:kb:{name}"


def workspace_id_for_kb_base_dir(base_dir: str | Path) -> str | None:
    """Find the owned storage scope for a KB directory used by a background job."""
    from deeptutor.multi_user.paths import get_account_path_service
    from deeptutor.services.path_service import get_path_service
    from deeptutor.services.workspace import get_content_workspace_service
    from deeptutor.services.workspace.context import workspace_context

    root = Path(base_dir).resolve()
    if root == get_account_path_service().get_knowledge_bases_root().resolve():
        return ""
    for row in get_content_workspace_service()._catalog():
        if row.get("kind") != "workspace":
            continue
        with workspace_context(row["workspace_id"]):
            if root == get_path_service().get_knowledge_bases_root().resolve():
                return str(row["workspace_id"])
    return None


def parse_kb_id(value: str) -> tuple[str, str] | None:
    if value.startswith("account:kb:"):
        return "", value[len("account:kb:") :]
    if value.startswith("workspace:"):
        prefix, separator, name = value.partition(":kb:")
        if separator and prefix[len("workspace:") :]:
            return prefix[len("workspace:") :], name
        raise HTTPException(status_code=404, detail="Invalid knowledge resource reference")
    return None


def _move_aliases_path():
    from deeptutor.multi_user.paths import get_account_path_service

    return get_account_path_service().get_runtime_state_dir() / "knowledge-move-aliases.json"


def move_aliases() -> dict[str, str]:
    """Old qualified IDs remain valid in saved sessions and learning sources."""
    path = _move_aliases_path()
    if not path.exists():
        return {}
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("Knowledge move aliases are damaged.")
    return {str(key): str(target) for key, target in value.items()}


def canonical_kb_id(value: str) -> str:
    aliases = move_aliases()
    seen = set()
    while value in aliases:
        if value in seen:
            raise ValueError("Knowledge move aliases contain a cycle.")
        seen.add(value)
        value = aliases[value]
    return value


def resolve_qualified(kb_ref: str, *, require_write=False):
    from deeptutor.multi_user.knowledge_access import _resolve_kb
    from deeptutor.services.workspace.context import workspace_context

    kb_ref = canonical_kb_id(kb_ref)
    parsed = parse_kb_id(kb_ref)
    if parsed is None:
        return _resolve_kb(kb_ref, require_write=require_write)
    workspace_id, name = parsed
    # Catalog lookup validates the current account's ownership. Do not accept
    # filesystem paths or switch authenticated users based on a reference.
    try:
        from deeptutor.services.workspace.models import WorkspaceError

        token = library_request.set(False)
        try:
            with workspace_context(workspace_id) as scope:
                if require_write and scope.archived:
                    raise WorkspaceError("Restore this workspace before changing its resources.")
                # Explicit own prefix prevents fallback to a granted admin KB.
                resource = _resolve_kb(f"user:kb:{name}", require_write=require_write)
        finally:
            library_request.reset(token)
    except WorkspaceError as exc:
        raise HTTPException(
            status_code=404, detail="Knowledge resource workspace is unavailable"
        ) from exc
    return replace(resource, id=kb_ref)


def knowledge_catalog() -> list[dict]:
    from deeptutor.multi_user.knowledge_access import _list_visible_knowledge_bases
    from deeptutor.services.workspace import get_content_workspace_service
    from deeptutor.services.workspace.context import workspace_context

    rows = [{"workspace_id": "", "display_name": "Account library", "kind": "general"}]
    rows += [
        r
        for r in get_content_workspace_service()._catalog()
        if r["kind"] == "workspace" and not r.get("archived")
    ]
    items, seen = [], set()
    token = library_request.set(False)
    try:
        for row in rows:
            # One missing folder must not hide the rest of the resource library.
            from deeptutor.services.workspace.models import WorkspaceError

            try:
                with workspace_context(row["workspace_id"]):
                    entries = _list_visible_knowledge_bases()
            except (WorkspaceError, OSError):
                continue
            for entry in entries:
                rid = (
                    entry["id"]
                    if entry.get("assigned")
                    else qualified_kb_id(entry["name"], row["workspace_id"])
                )
                if rid in seen:
                    continue
                seen.add(rid)
                items.append(
                    {
                        **entry,
                        "id": rid,
                        "workspace_id": row["workspace_id"],
                        "provenance_label": entry.get("provenance_label")
                        if entry.get("assigned")
                        else row["display_name"],
                    }
                )
    finally:
        library_request.reset(token)
    return items


def resolve_selected(kb_ref: str, selected: list[str], *, require_write=False):
    from deeptutor.multi_user.knowledge_access import DEFAULT_KB_ALIASES, _strip_resource_prefix

    selected = list(dict.fromkeys(canonical_kb_id(ref) for ref in selected))
    kb_ref = canonical_kb_id(kb_ref)
    _, name = _strip_resource_prefix(kb_ref)
    if kb_ref in selected:
        return resolve_qualified(kb_ref, require_write=require_write)
    # Old conversations store bare names. Preserve these only if the selection
    # identifies one unambiguous resource; never guess between same-name KBs.
    matches = [
        rid for rid in selected if (parse_kb_id(rid) or _strip_resource_prefix(rid))[1] == name
    ]
    if not matches and name.lower() in DEFAULT_KB_ALIASES:
        matches = selected[:1]
    if len(matches) == 1 and parse_kb_id(kb_ref) is None and not kb_ref.startswith("admin:kb:"):
        return resolve_qualified(matches[0], require_write=require_write)
    raise HTTPException(status_code=403, detail="Knowledge base is not assigned to this workspace")


# Explicit learning-source choices add read access within the current account;
# they never grant writes or change the workspace receiving generated content.
learning_source_kbs: ContextVar[frozenset[str]] = ContextVar(
    "learning_source_kbs", default=frozenset()
)


@contextmanager
def learning_source_access(refs):
    chosen = frozenset(str(ref) for ref in refs if ref)
    token = learning_source_kbs.set(learning_source_kbs.get() | chosen)
    try:
        yield
    finally:
        learning_source_kbs.reset(token)
