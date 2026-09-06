"""Resolution, confinement, and publication for a user's content workspace."""

from __future__ import annotations

from collections import deque
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import json
import mimetypes
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import tempfile
from typing import Any, Iterable, Mapping
from urllib.parse import quote
import uuid

from deeptutor.core.context import WorkspaceRuntimeContext
from deeptutor.multi_user.context import get_current_user
from deeptutor.services.path_service import get_path_service
from deeptutor.services.settings.interface_settings import atomic_update
from deeptutor.utils.secret_files import ensure_private_directory

_SETTINGS_VERSION = 1
_SETTINGS_NAME = "content_workspace"
_DEPLOYMENT_ROOT_ENV = "DEEPTUTOR_WORKSPACE_ROOT"
_ALLOWED_ROOTS_ENV = "DEEPTUTOR_WORKSPACE_ALLOWED_ROOTS"
_INTERNAL_DIR = ".deeptutor"
_MAX_SEARCH_SCAN_ENTRIES = 10_000
_SAFE_COMPONENT = re.compile(r"[^A-Za-z0-9._-]+")


class WorkspaceError(ValueError):
    """A workspace path, binding, or operation is not allowed."""


@dataclass(frozen=True, slots=True)
class WorkspaceBinding:
    workspace_id: str
    root: Path
    display_name: str
    is_default: bool = False
    locked: bool = False

    def public_dict(self, *, security_level: str, status: str = "ready") -> dict[str, Any]:
        return {
            "workspace_id": self.workspace_id,
            "path": str(self.root),
            "display_name": self.display_name,
            "is_default": self.is_default,
            "locked": self.locked,
            "status": status,
            "security_level": security_level,
        }


@dataclass(frozen=True, slots=True)
class WorkspaceItem:
    workspace_id: str
    workspace_item_id: str
    relative_path: str
    filename: str
    mime_type: str
    size_bytes: int
    sha256: str
    url: str
    title: str = ""
    caption: str = ""
    generated: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _safe_component(value: str, fallback: str) -> str:
    cleaned = _SAFE_COMPONENT.sub("_", str(value or "").strip()).strip("._")
    return cleaned[:120] or fallback


def _workspace_id(user_id: str, root: Path) -> str:
    value = f"deeptutor-workspace:{user_id}:{root}"
    return f"ws_{uuid.uuid5(uuid.NAMESPACE_URL, value).hex}"


def _workspace_item_id(workspace_id: str, relative_path: str, sha256: str) -> str:
    """Stable id for one path+content version.

    Exec tools rescan their shared turn directory after each command. Reusing
    the id prevents the same unchanged file from producing duplicate cards,
    while a changed file necessarily receives a new immutable snapshot id.
    """
    value = f"deeptutor-workspace-item:{workspace_id}:{relative_path}:{sha256}"
    return f"wsi_{uuid.uuid5(uuid.NAMESPACE_URL, value).hex}"


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _normalise_relative(path: str) -> str:
    raw = str(path or "").strip().replace("\\", "/")
    candidate = PurePosixPath(raw)
    if not raw or candidate.is_absolute() or "\x00" in raw:
        raise WorkspaceError("Workspace paths must be non-empty relative paths.")
    parts = tuple(part for part in candidate.parts if part not in {"", "."})
    if not parts or any(part == ".." for part in parts):
        raise WorkspaceError("Workspace paths cannot leave the workspace.")
    return PurePosixPath(*parts).as_posix()


class ContentWorkspaceService:
    """Resolve the current user's one active content workspace."""

    def _settings_file(self) -> Path:
        return get_path_service().get_settings_file(_SETTINGS_NAME)

    def _default_root(self) -> Path:
        return get_path_service().get_workspace_dir().resolve()

    def _deployment_root(self) -> Path | None:
        raw = os.environ.get(_DEPLOYMENT_ROOT_ENV, "").strip()
        return Path(raw).expanduser().resolve() if raw else None

    def _allowed_roots(self) -> tuple[Path, ...]:
        raw = os.environ.get(_ALLOWED_ROOTS_ENV, "")
        roots = [
            Path(value).expanduser().resolve() for value in raw.split(os.pathsep) if value.strip()
        ]
        roots.append(self._default_root())
        deployment = self._deployment_root()
        if deployment is not None:
            roots.append(deployment)
        return tuple(dict.fromkeys(roots))

    @staticmethod
    def security_level() -> str:
        from deeptutor.services.sandbox.config import SandboxSettings, build_backend
        from deeptutor.services.sandbox.spec import IsolationLevel

        backend = build_backend(SandboxSettings.from_env())
        if backend is None:
            return "off"
        return "hard" if backend.level is IsolationLevel.SYSTEM else "best_effort"

    def _read_settings(self) -> dict[str, Any]:
        path = self._settings_file()
        if not path.exists():
            return {}
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
        return payload if isinstance(payload, dict) else {}

    def _binding(self, root: Path, *, is_default: bool, locked: bool = False) -> WorkspaceBinding:
        user = get_current_user()
        return WorkspaceBinding(
            workspace_id=_workspace_id(user.id, root),
            root=root,
            display_name=root.name or str(root),
            is_default=is_default,
            locked=locked,
        )

    def default_binding(self) -> WorkspaceBinding:
        root = self._default_root()
        return self._binding(root, is_default=True)

    def current_binding(self, *, ensure_output: bool = False) -> WorkspaceBinding:
        deployment = self._deployment_root()
        if deployment is not None:
            binding = self._binding(deployment, is_default=False, locked=True)
        else:
            settings = self._read_settings()
            active_id = str(settings.get("active_workspace_id") or "")
            binding = self.default_binding()
            for row in settings.get("bindings") or []:
                if not isinstance(row, dict) or str(row.get("id") or "") != active_id:
                    continue
                raw_path = str(row.get("path") or "").strip()
                if raw_path:
                    root = Path(raw_path).expanduser().resolve()
                    binding = self._binding(root, is_default=root == self._default_root())
                break
        if ensure_output:
            self._ensure_ready(binding)
        return binding

    def binding_by_id(self, workspace_id: str) -> WorkspaceBinding:
        current = self.current_binding()
        self._assert_allowed_root(current.root)
        if current.workspace_id == workspace_id:
            return current
        default = self.default_binding()
        if default.workspace_id == workspace_id:
            return default
        for row in self._read_settings().get("bindings") or []:
            if not isinstance(row, dict) or str(row.get("id") or "") != workspace_id:
                continue
            root = Path(str(row.get("path") or "")).expanduser().resolve()
            self._assert_allowed_root(root)
            binding = self._binding(root, is_default=root == self._default_root())
            # Binding ids are derived from both the user id and the physical
            # root.  Never trust a stored id by itself: a copied or tampered
            # settings row must not let one user resolve another user's
            # presentation manifest, even when both users can name the same
            # deployment path.
            if binding.workspace_id == workspace_id:
                return binding
        raise WorkspaceError("The workspace is no longer registered for this user.")

    def _assert_allowed_root(self, root: Path) -> None:
        user = get_current_user()
        if user.is_admin:
            return
        for allowed in self._allowed_roots():
            try:
                root.relative_to(allowed)
                return
            except ValueError:
                continue
        raise WorkspaceError(
            "This folder is outside the workspace roots allowed by the administrator."
        )

    def _ensure_ready(self, binding: WorkspaceBinding) -> None:
        root = binding.root
        if not root.exists() or not root.is_dir():
            raise WorkspaceError("The selected workspace folder does not exist.")
        self._assert_allowed_root(root)
        if not os.access(root, os.R_OK):
            raise WorkspaceError("The selected workspace folder is not readable.")
        output = root / "outputs"
        try:
            output.mkdir(parents=True, exist_ok=True)
            resolved_output = output.resolve()
            resolved_output.relative_to(root)
            probe = output / f".deeptutor-write-probe-{uuid.uuid4().hex}"
            probe.touch(exist_ok=False)
            probe.unlink()
        except ValueError as exc:
            raise WorkspaceError("The workspace outputs folder leaves the workspace.") from exc
        except OSError as exc:
            raise WorkspaceError("The workspace outputs folder is not writable.") from exc

    def validate(self, path: str | Path | None) -> dict[str, Any]:
        if path is not None and not str(path).strip():
            binding = self.default_binding()
            return {
                **binding.public_dict(security_level=self.security_level(), status="invalid"),
                "error": "The workspace folder path cannot be empty.",
            }
        binding = (
            self.default_binding()
            if path is None
            else self._binding(Path(path).expanduser().resolve(), is_default=False)
        )
        try:
            self._ensure_ready(binding)
        except WorkspaceError as exc:
            return {
                **binding.public_dict(security_level=self.security_level(), status="invalid"),
                "error": str(exc),
            }
        return binding.public_dict(security_level=self.security_level())

    def set_workspace(self, path: str | Path | None) -> WorkspaceBinding:
        if self._deployment_root() is not None:
            raise WorkspaceError("This deployment locks the workspace at startup.")
        if path is not None and not str(path).strip():
            raise WorkspaceError("The workspace folder path cannot be empty.")
        binding = (
            self.default_binding()
            if path is None
            else self._binding(Path(path).expanduser().resolve(), is_default=False)
        )
        self._ensure_ready(binding)

        def _mutate(stored: dict[str, Any]) -> dict[str, Any]:
            rows = [row for row in stored.get("bindings") or [] if isinstance(row, dict)]
            replacement = {
                "id": binding.workspace_id,
                "path": str(binding.root),
                "display_name": binding.display_name,
                "created_at": _utc_now(),
            }
            found = False
            for index, row in enumerate(rows):
                if str(row.get("id") or "") == binding.workspace_id:
                    replacement["created_at"] = str(row.get("created_at") or _utc_now())
                    rows[index] = replacement
                    found = True
                    break
            if not found:
                rows.append(replacement)
            return {
                "version": _SETTINGS_VERSION,
                "active_workspace_id": binding.workspace_id,
                "bindings": rows,
            }

        atomic_update(self._settings_file(), _mutate)
        return binding

    def describe_current(self) -> dict[str, Any]:
        binding = self.current_binding()
        status = self.validate(binding.root)
        status.update(
            {
                "workspace_id": binding.workspace_id,
                "is_default": binding.is_default,
                "locked": binding.locked,
            }
        )
        return status

    def create_runtime_context(
        self,
        *,
        capability: str,
        session_id: str,
        turn_id: str,
    ) -> WorkspaceRuntimeContext:
        binding = self.current_binding(ensure_output=True)
        logical = PurePosixPath(
            "outputs",
            _safe_component(capability, "chat"),
            _safe_component(session_id, "direct"),
            _safe_component(turn_id, "turn"),
        ).as_posix()
        output = self.resolve(binding, logical, write=True)
        output.mkdir(parents=True, exist_ok=True)
        return WorkspaceRuntimeContext(
            workspace_id=binding.workspace_id,
            root=str(binding.root),
            output_dir=str(output),
            logical_output_dir=logical,
            security_level=self.security_level(),
        )

    def resolve(
        self, binding: WorkspaceBinding, relative_path: str, *, write: bool = False
    ) -> Path:
        relative = _normalise_relative(relative_path)
        if write and PurePosixPath(relative).parts[0] != "outputs":
            raise WorkspaceError("Writes outside outputs require an explicit user grant.")
        candidate = (binding.root / Path(*PurePosixPath(relative).parts)).resolve()
        try:
            candidate.relative_to(binding.root)
        except ValueError as exc:
            raise WorkspaceError("The path leaves the selected workspace.") from exc
        return candidate

    def relative_path(self, binding: WorkspaceBinding, path: str | Path) -> str:
        candidate = Path(path).resolve()
        try:
            relative = candidate.relative_to(binding.root)
        except ValueError as exc:
            raise WorkspaceError("The path is outside the selected workspace.") from exc
        return PurePosixPath(*relative.parts).as_posix()

    @staticmethod
    def _assert_no_symlink_components(
        binding: WorkspaceBinding, relative_path: str, *, operation: str
    ) -> None:
        cursor = binding.root
        for part in PurePosixPath(relative_path).parts:
            cursor /= part
            if cursor.is_symlink():
                raise WorkspaceError(f"The {operation} path cannot contain symbolic links.")

    @staticmethod
    def _presentation_root(binding: WorkspaceBinding, *, create: bool = False) -> Path:
        """Return private snapshot storage for one user-scoped workspace id."""

        if not re.fullmatch(r"ws_[0-9a-f]{32}", binding.workspace_id):
            raise WorkspaceError("Invalid workspace id.")
        base = get_path_service().get_runtime_state_dir()
        presentations = base / "workspace_presentations"
        root = presentations / binding.workspace_id
        if create:
            for candidate in (base, presentations, root):
                if candidate.is_symlink():
                    raise WorkspaceError(
                        "The private workspace presentation path cannot contain symbolic links."
                    )
                ensure_private_directory(candidate)
        try:
            root.resolve().relative_to(base.resolve())
        except ValueError as exc:
            raise WorkspaceError("The private workspace presentation path is invalid.") from exc
        return root

    @staticmethod
    def _walk_workspace(
        binding: WorkspaceBinding,
        base: Path,
        *,
        max_depth: int | None,
        max_entries: int,
    ) -> tuple[list[Path], bool]:
        """Walk without following symlinks and stop at a hard scan budget."""

        budget = max(1, int(max_entries))
        queue: deque[tuple[Path, int]] = deque([(base, 0)])
        candidates: list[Path] = []
        truncated = False
        while queue:
            directory, directory_depth = queue.popleft()
            try:
                entries = os.scandir(directory)
            except OSError:
                continue
            with entries:
                for entry in entries:
                    if entry.name == _INTERNAL_DIR or entry.is_symlink():
                        continue
                    candidate = Path(entry.path)
                    try:
                        candidate.resolve().relative_to(binding.root)
                        is_dir = entry.is_dir(follow_symlinks=False)
                    except (OSError, ValueError):
                        continue
                    if len(candidates) >= budget:
                        truncated = True
                        queue.clear()
                        break
                    candidates.append(candidate)
                    candidate_depth = directory_depth + 1
                    if is_dir and (max_depth is None or candidate_depth < max_depth):
                        queue.append((candidate, candidate_depth))
        return candidates, truncated

    def list_entries_page(
        self,
        binding: WorkspaceBinding,
        path: str = ".",
        *,
        depth: int = 1,
        limit: int = 200,
    ) -> dict[str, Any]:
        """Return bounded directory rows plus explicit scan status."""

        if (
            path not in {"", "."}
            and _INTERNAL_DIR in PurePosixPath(_normalise_relative(path)).parts
        ):
            raise WorkspaceError("DeepTutor's internal workspace files are not listable.")
        base = binding.root if path in {"", "."} else self.resolve(binding, path)
        if not base.is_dir():
            raise WorkspaceError("The requested workspace path is not a directory.")
        max_depth = max(1, min(int(depth), 5))
        max_items = max(1, min(int(limit), 1000))
        candidates, truncated = self._walk_workspace(
            binding,
            base,
            max_depth=max_depth,
            max_entries=max_items,
        )
        rows: list[dict[str, Any]] = []
        for candidate in candidates:
            try:
                stat = candidate.stat()
                is_dir = candidate.is_dir()
            except OSError:
                continue
            rows.append(
                {
                    "path": self.relative_path(binding, candidate),
                    "name": candidate.name,
                    "kind": "directory" if is_dir else "file",
                    "size_bytes": stat.st_size if not is_dir else None,
                    "modified_at": stat.st_mtime,
                }
            )
        return {
            "entries": rows,
            "scanned_entries": len(candidates),
            "truncated": truncated,
        }

    def list_entries(
        self,
        binding: WorkspaceBinding,
        path: str = ".",
        *,
        depth: int = 1,
        limit: int = 200,
    ) -> list[dict[str, Any]]:
        page = self.list_entries_page(
            binding,
            path,
            depth=depth,
            limit=limit,
        )
        return list(page["entries"])

    def read_text(
        self,
        binding: WorkspaceBinding,
        path: str,
        *,
        offset: int = 0,
        limit: int = 20_000,
    ) -> dict[str, Any]:
        candidate = self.resolve(binding, path)
        if not candidate.is_file():
            raise WorkspaceError("The requested workspace path is not a file.")
        if _INTERNAL_DIR in PurePosixPath(_normalise_relative(path)).parts:
            raise WorkspaceError("DeepTutor's internal workspace files are not readable.")
        start = max(0, int(offset))
        max_chars = max(1, min(int(limit), 100_000))
        try:
            skipped = 0
            total = 0
            with candidate.open("r", encoding="utf-8") as handle:
                while skipped < start:
                    chunk = handle.read(min(64 * 1024, start - skipped))
                    if not chunk:
                        break
                    skipped += len(chunk)
                page_with_probe = handle.read(max_chars + 1)
                page = page_with_probe[:max_chars]
                total = skipped + len(page_with_probe)
                while chunk := handle.read(64 * 1024):
                    total += len(chunk)
        except (OSError, UnicodeDecodeError) as exc:
            raise WorkspaceError("This file could not be read as UTF-8 text.") from exc
        return {
            "path": self.relative_path(binding, candidate),
            "content": page,
            "offset": start,
            "truncated": skipped + len(page) < total,
            "total_chars": total,
        }

    def search(
        self,
        binding: WorkspaceBinding,
        query: str,
        *,
        path: str = ".",
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        return list(self.search_page(binding, query, path=path, limit=limit)["matches"])

    def search_page(
        self,
        binding: WorkspaceBinding,
        query: str,
        *,
        path: str = ".",
        limit: int = 50,
    ) -> dict[str, Any]:
        """Search within a hard traversal budget and report partial results."""

        needle = str(query or "").strip()
        if not needle:
            raise WorkspaceError("workspace_search requires a non-empty query.")
        if (
            path not in {"", "."}
            and _INTERNAL_DIR in PurePosixPath(_normalise_relative(path)).parts
        ):
            raise WorkspaceError("DeepTutor's internal workspace files are not searchable.")
        base = binding.root if path in {"", "."} else self.resolve(binding, path)
        if not base.is_dir():
            raise WorkspaceError("The requested workspace path is not a directory.")
        rows: list[dict[str, Any]] = []
        lowered = needle.lower()
        max_matches = max(1, min(int(limit), 200))
        candidates, traversal_truncated = self._walk_workspace(
            binding,
            base,
            max_depth=None,
            max_entries=_MAX_SEARCH_SCAN_ENTRIES,
        )
        scanned_entries = 0
        stopped_for_matches = False
        for candidate in candidates:
            scanned_entries += 1
            if not candidate.is_file():
                continue
            try:
                relative = self.relative_path(binding, candidate)
                size = candidate.stat().st_size
            except (OSError, WorkspaceError):
                continue
            if lowered in candidate.name.lower():
                rows.append({"path": relative, "line": None, "preview": candidate.name})
            elif size <= 2_000_000:
                try:
                    for line_no, line in enumerate(
                        candidate.read_text(encoding="utf-8").splitlines(), start=1
                    ):
                        if lowered in line.lower():
                            rows.append({"path": relative, "line": line_no, "preview": line[:500]})
                            break
                except (OSError, UnicodeDecodeError):
                    pass
            if len(rows) >= max_matches:
                stopped_for_matches = scanned_entries < len(candidates)
                break
        return {
            "matches": rows,
            "scanned_entries": scanned_entries,
            "truncated": traversal_truncated or stopped_for_matches,
        }

    def publish(
        self,
        binding: WorkspaceBinding,
        items: Iterable[Mapping[str, Any]],
    ) -> list[WorkspaceItem]:
        prepared: list[tuple[Mapping[str, Any], str, Path]] = []
        for raw in items:
            relative = _normalise_relative(str(raw.get("path") or ""))
            if _INTERNAL_DIR in PurePosixPath(relative).parts:
                raise WorkspaceError("DeepTutor's internal workspace files cannot be presented.")
            source = self.resolve(binding, relative)
            if not source.is_file():
                raise WorkspaceError(f"Workspace item is not a file: {relative}")
            prepared.append((raw, relative, source))
        if not prepared:
            raise WorkspaceError("workspace_present requires at least one file.")

        root = self._presentation_root(binding, create=True)
        blobs = root / "blobs"
        manifests = root / "items"
        for directory in (blobs, manifests):
            if directory.is_symlink():
                raise WorkspaceError(
                    "The private workspace presentation path cannot contain symbolic links."
                )
            ensure_private_directory(directory)
        published: list[WorkspaceItem] = []
        for raw, relative, source in prepared:
            digest = hashlib.sha256()
            fd, temp_name = tempfile.mkstemp(prefix=".publish-", dir=blobs)
            size = 0
            try:
                with os.fdopen(fd, "wb") as target, source.open("rb") as handle:
                    while chunk := handle.read(1024 * 1024):
                        target.write(chunk)
                        digest.update(chunk)
                        size += len(chunk)
                    target.flush()
                    os.fsync(target.fileno())
                sha256 = digest.hexdigest()
                blob = blobs / sha256
                if blob.exists():
                    Path(temp_name).unlink(missing_ok=True)
                else:
                    os.replace(temp_name, blob)
            finally:
                Path(temp_name).unlink(missing_ok=True)

            item_id = _workspace_item_id(binding.workspace_id, relative, sha256)
            mime_type = mimetypes.guess_type(source.name)[0] or "application/octet-stream"
            item = WorkspaceItem(
                workspace_id=binding.workspace_id,
                workspace_item_id=item_id,
                relative_path=relative,
                filename=source.name,
                mime_type=mime_type,
                size_bytes=size,
                sha256=sha256,
                url=(
                    f"/files/workspace-items/{quote(binding.workspace_id, safe='')}/"
                    f"{quote(item_id, safe='')}"
                ),
                title=str(raw.get("title") or "")[:200],
                caption=str(raw.get("caption") or "")[:1000],
                generated=relative.startswith("outputs/"),
            )
            manifest = manifests / f"{item_id}.json"
            atomic_update(manifest, lambda _stored, payload=item.to_dict(): payload)
            published.append(item)
        return published

    def validate_export(
        self,
        binding: WorkspaceBinding,
        *,
        source_path: str,
        destination_path: str,
        overwrite: bool = False,
    ) -> dict[str, Any]:
        """Validate one exact outputs → workspace copy without mutating state."""
        source_relative = _normalise_relative(source_path)
        destination_relative = _normalise_relative(destination_path)
        if PurePosixPath(source_relative).parts[0] != "outputs":
            raise WorkspaceError("Only files produced under outputs can be exported.")
        if PurePosixPath(destination_relative).parts[0] == "outputs":
            raise WorkspaceError("Files already under outputs do not need export authorization.")
        if _INTERNAL_DIR in PurePosixPath(destination_relative).parts:
            raise WorkspaceError("DeepTutor's internal workspace files cannot be overwritten.")
        self._assert_no_symlink_components(
            binding, destination_relative, operation="export destination"
        )
        source = self.resolve(binding, source_relative)
        destination = self.resolve(binding, destination_relative)
        if not source.is_file():
            raise WorkspaceError(f"Export source is not a file: {source_relative}")
        if destination.exists() and destination.is_dir():
            raise WorkspaceError("The export destination is a directory.")
        if destination.exists() and not overwrite:
            raise WorkspaceError(
                "The export destination already exists; an overwrite request is required."
            )
        return {
            "workspace_id": binding.workspace_id,
            "source_path": source_relative,
            "destination_path": destination_relative,
            "overwrite": bool(overwrite),
            "size_bytes": source.stat().st_size,
            "sha256": _sha256_file(source),
        }

    def export_once(
        self,
        binding: WorkspaceBinding,
        *,
        source_path: str,
        destination_path: str,
        overwrite: bool = False,
        expected_sha256: str = "",
    ) -> dict[str, Any]:
        """Perform one previously approved, exact copy inside the workspace."""
        request = self.validate_export(
            binding,
            source_path=source_path,
            destination_path=destination_path,
            overwrite=overwrite,
        )
        if expected_sha256 and request["sha256"] != expected_sha256:
            raise WorkspaceError("The export source changed after authorization was requested.")
        source = self.resolve(binding, request["source_path"])
        destination = self.resolve(binding, request["destination_path"])
        destination.parent.mkdir(parents=True, exist_ok=True)
        # Re-resolve after mkdir so a pre-existing symlink in the requested
        # parent chain cannot redirect the authorized write out of workspace.
        self._assert_no_symlink_components(
            binding, request["destination_path"], operation="export destination"
        )
        destination = self.resolve(binding, request["destination_path"])
        fd, temp_name = tempfile.mkstemp(prefix=".deeptutor-export-", dir=destination.parent)
        os.close(fd)
        temporary = Path(temp_name)
        try:
            shutil.copyfile(source, temporary)
            if expected_sha256 and _sha256_file(temporary) != expected_sha256:
                raise WorkspaceError("The export source changed while it was being copied.")
            if not overwrite and destination.exists():
                raise WorkspaceError("The export destination was created before the copy.")
            os.replace(temporary, destination)
        except OSError as exc:
            raise WorkspaceError("The approved workspace export could not be written.") from exc
        finally:
            temporary.unlink(missing_ok=True)
        return request

    def resolve_published_item(
        self, workspace_id: str, workspace_item_id: str
    ) -> tuple[Path, WorkspaceItem]:
        if not re.fullmatch(r"wsi_[0-9a-f]{32}", workspace_item_id):
            raise WorkspaceError("Invalid workspace item id.")
        binding = self.binding_by_id(workspace_id)
        root = self._presentation_root(binding)
        for directory in (root / "items", root / "blobs"):
            if directory.is_symlink():
                raise WorkspaceError(
                    "The private workspace presentation path cannot contain symbolic links."
                )
        manifest_path = root / "items" / f"{workspace_item_id}.json"
        try:
            payload = json.loads(manifest_path.read_text(encoding="utf-8"))
            item = WorkspaceItem(**payload)
        except (OSError, json.JSONDecodeError, TypeError) as exc:
            raise WorkspaceError("The presented workspace item is unavailable.") from exc
        if item.workspace_id != workspace_id or item.workspace_item_id != workspace_item_id:
            raise WorkspaceError("The workspace item manifest is invalid.")
        blob = (root / "blobs" / item.sha256).resolve()
        try:
            blob.relative_to(root.resolve())
        except ValueError as exc:
            raise WorkspaceError("The workspace item path is invalid.") from exc
        if not blob.is_file():
            raise WorkspaceError("The presented workspace item is unavailable.")
        return blob, item


_service = ContentWorkspaceService()


def get_content_workspace_service() -> ContentWorkspaceService:
    return _service


__all__ = [
    "ContentWorkspaceService",
    "WorkspaceBinding",
    "WorkspaceError",
    "WorkspaceItem",
    "get_content_workspace_service",
]
