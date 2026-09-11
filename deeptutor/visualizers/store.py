"""Per-user installation state and safe declarative visualizer imports."""

from __future__ import annotations

import json
from pathlib import Path
import shutil
import tempfile
import zipfile

from .protocol import VisualizerManifest

_MAX_ARCHIVE_BYTES = 25 * 1024 * 1024
_MAX_ENTRY_BYTES = 10 * 1024 * 1024
_MAX_MANIFEST_BYTES = 128 * 1024
_MAX_ENTRIES = 200
_MAX_RATIO = 100.0
_ALLOWED_SUFFIXES = {
    ".json",
    ".html",
    ".js",
    ".mjs",
    ".css",
    ".svg",
    ".png",
    ".jpg",
    ".jpeg",
    ".webp",
    ".woff2",
    ".wasm",
}


class VisualizerStoreError(ValueError):
    pass


class VisualizerStore:
    """Owns the mutable layer; registry composition remains read-only."""

    def __init__(
        self,
        *,
        root: Path | None = None,
        state_file: Path | None = None,
    ) -> None:
        from deeptutor.services.path_service import get_path_service

        service = get_path_service()
        self.root = (root or (service.get_user_root() / "visualizers")).resolve()
        self.state_file = (state_file or service.get_settings_file("visualizers.json")).resolve()

    def state(self) -> dict[str, list[str]]:
        try:
            raw = json.loads(self.state_file.read_text(encoding="utf-8"))
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            raw = {}
        return {
            "installed": _string_list(raw.get("installed")),
            "disabled": _string_list(raw.get("disabled")),
            "uninstalled": _string_list(raw.get("uninstalled")),
        }

    def save_state(self, state: dict[str, list[str]]) -> None:
        normalized = {
            "installed": sorted(set(_string_list(state.get("installed")))),
            "disabled": sorted(set(_string_list(state.get("disabled")))),
            "uninstalled": sorted(set(_string_list(state.get("uninstalled")))),
        }
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        temp = self.state_file.with_suffix(self.state_file.suffix + ".tmp")
        temp.write_text(
            json.dumps(normalized, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        temp.replace(self.state_file)

    def set_enabled(self, visualizer_id: str, enabled: bool) -> None:
        state = self.state()
        disabled = set(state["disabled"])
        if enabled:
            disabled.discard(visualizer_id)
        else:
            disabled.add(visualizer_id)
        state["disabled"] = sorted(disabled)
        self.save_state(state)

    def set_bundled_installed(self, visualizer_id: str, installed: bool) -> None:
        state = self.state()
        explicitly_installed = set(state["installed"])
        uninstalled = set(state["uninstalled"])
        disabled = set(state["disabled"])
        if installed:
            explicitly_installed.add(visualizer_id)
            uninstalled.discard(visualizer_id)
            disabled.discard(visualizer_id)
        else:
            explicitly_installed.discard(visualizer_id)
            uninstalled.add(visualizer_id)
            disabled.discard(visualizer_id)
        state["installed"] = sorted(explicitly_installed)
        state["uninstalled"] = sorted(uninstalled)
        state["disabled"] = sorted(disabled)
        self.save_state(state)

    def user_packages(self) -> list[tuple[VisualizerManifest, Path]]:
        if not self.root.is_dir():
            return []
        packages: list[tuple[VisualizerManifest, Path]] = []
        for child in sorted(self.root.iterdir()):
            manifest_file = child / "visualizer.json"
            if not child.is_dir() or not manifest_file.is_file():
                continue
            try:
                if manifest_file.stat().st_size > _MAX_MANIFEST_BYTES:
                    continue
                manifest = VisualizerManifest.model_validate_json(
                    manifest_file.read_text(encoding="utf-8")
                )
                self._validate_imported_manifest(manifest, child)
            except Exception:
                # A broken package is ignored by discovery. The API installer
                # validates eagerly, so this is primarily crash recovery.
                continue
            packages.append((manifest, child.resolve()))
        return packages

    def install_archive(
        self,
        archive_path: Path,
        *,
        reserved_ids: set[str] | None = None,
    ) -> VisualizerManifest:
        self.root.mkdir(parents=True, exist_ok=True)
        if archive_path.stat().st_size > _MAX_ARCHIVE_BYTES:
            raise VisualizerStoreError("visualizer package exceeds 25 MB")
        with tempfile.TemporaryDirectory(prefix="dtviz-") as tmp_name:
            extracted = Path(tmp_name)
            self._extract_archive(archive_path, extracted)
            package_root = self._locate_package_root(extracted)
            manifest_path = package_root / "visualizer.json"
            try:
                if manifest_path.stat().st_size > _MAX_MANIFEST_BYTES:
                    raise VisualizerStoreError("visualizer.json exceeds 128 KB")
                manifest = VisualizerManifest.model_validate_json(
                    manifest_path.read_text(encoding="utf-8")
                )
            except Exception as exc:
                raise VisualizerStoreError(f"invalid visualizer.json: {exc}") from exc
            self._validate_imported_manifest(manifest, package_root)
            if manifest.id in (reserved_ids or set()):
                raise VisualizerStoreError(f"visualizer id is reserved by the host: {manifest.id}")
            destination = (self.root / manifest.id).resolve()
            if not destination.is_relative_to(self.root):
                raise VisualizerStoreError("visualizer id escapes the installation root")
            if destination.exists():
                raise VisualizerStoreError(f"visualizer already installed: {manifest.id}")
            staging = Path(tempfile.mkdtemp(prefix=f".{manifest.id}-", dir=self.root))
            try:
                for item in package_root.iterdir():
                    target = staging / item.name
                    if item.is_dir():
                        shutil.copytree(item, target)
                    else:
                        shutil.copy2(item, target)
                staging.replace(destination)
            finally:
                if staging.exists():
                    shutil.rmtree(staging, ignore_errors=True)
        self.set_enabled(manifest.id, True)
        return manifest

    def uninstall_user(self, visualizer_id: str) -> None:
        target = (self.root / visualizer_id).resolve()
        if not target.is_relative_to(self.root) or target == self.root:
            raise VisualizerStoreError("invalid visualizer id")
        if not (target / "visualizer.json").is_file():
            raise VisualizerStoreError(f"user visualizer not found: {visualizer_id}")
        shutil.rmtree(target)
        state = self.state()
        state["disabled"] = [item for item in state["disabled"] if item != visualizer_id]
        state["installed"] = [item for item in state["installed"] if item != visualizer_id]
        self.save_state(state)

    def asset_path(self, visualizer_id: str, relative_path: str) -> Path:
        package = (self.root / visualizer_id).resolve()
        candidate = (package / relative_path).resolve()
        if not package.is_dir() or not candidate.is_relative_to(package) or not candidate.is_file():
            raise VisualizerStoreError("visualizer asset not found")
        return candidate

    @staticmethod
    def _validate_imported_manifest(manifest: VisualizerManifest, root: Path) -> None:
        if manifest.core or manifest.default_installed:
            # Installation policy is host-owned. Imported packages cannot make
            # themselves immutable or silently default-enabled for other users.
            manifest.core = False
            manifest.default_installed = False
        if manifest.render_target != "iframe":
            raise VisualizerStoreError(
                "imported visualizers must use the sandboxed iframe render target"
            )
        entry = (root / manifest.renderer_entry).resolve()
        if not entry.is_relative_to(root.resolve()) or not entry.is_file():
            raise VisualizerStoreError("renderer_entry does not exist in the package")
        if entry.suffix.lower() != ".html":
            raise VisualizerStoreError("renderer_entry must be an HTML file")

    @staticmethod
    def _locate_package_root(extracted: Path) -> Path:
        if (extracted / "visualizer.json").is_file():
            return extracted
        subdirs = [item for item in extracted.iterdir() if item.is_dir()]
        if len(subdirs) == 1 and (subdirs[0] / "visualizer.json").is_file():
            return subdirs[0]
        raise VisualizerStoreError("package must contain visualizer.json at its root")

    @staticmethod
    def _extract_archive(archive_path: Path, destination: Path) -> None:
        total = 0
        try:
            archive = zipfile.ZipFile(archive_path)
        except zipfile.BadZipFile as exc:
            raise VisualizerStoreError("package is not a valid zip archive") from exc
        with archive:
            members = [item for item in archive.infolist() if not item.is_dir()]
            if len(members) > _MAX_ENTRIES:
                raise VisualizerStoreError("package contains too many files")
            root = destination.resolve()
            for info in members:
                raw = info.filename.replace("\\", "/")
                rel = Path(raw)
                if rel.is_absolute() or ".." in rel.parts:
                    raise VisualizerStoreError(f"illegal package path: {raw}")
                if raw.startswith("__MACOSX/") or rel.name.startswith("."):
                    continue
                if rel.suffix.lower() not in _ALLOWED_SUFFIXES:
                    raise VisualizerStoreError(f"unsupported package file type: {raw}")
                if info.file_size > _MAX_ENTRY_BYTES:
                    raise VisualizerStoreError(f"package entry is too large: {raw}")
                if info.compress_size and info.file_size / info.compress_size > _MAX_RATIO:
                    raise VisualizerStoreError(f"suspicious compression ratio: {raw}")
                total += info.file_size
                if total > _MAX_ARCHIVE_BYTES:
                    raise VisualizerStoreError("expanded package exceeds 25 MB")
                target = (root / rel).resolve()
                if not target.is_relative_to(root):
                    raise VisualizerStoreError(f"illegal package path: {raw}")
                target.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(info) as source, open(target, "wb") as sink:
                    shutil.copyfileobj(source, sink, length=1 << 16)


def _string_list(value: object) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item) for item in value if str(item).strip()]


__all__ = ["VisualizerStore", "VisualizerStoreError"]
