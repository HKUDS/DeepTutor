"""Local plugin package lifecycle with isolated environments and rollback."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import subprocess
import sys
import tempfile
import zipfile

from packaging.version import InvalidVersion, Version

from deeptutor.plugins.manifest import (
    MANIFEST_FILENAME,
    ManifestValidationError,
    PluginManifestData,
    parse_manifest,
)
from deeptutor.plugins.registry import (
    PluginInstallation,
    PluginRegistry,
    PluginStateError,
)
from deeptutor.services.path_service import get_path_service


class PluginLifecycleError(ValueError):
    """Raised when a package cannot be installed, upgraded, or rolled back."""


@dataclass(frozen=True, slots=True)
class LifecycleResult:
    plugin_id: str
    version: str
    action: str
    artifact_sha256: str
    venv_path: Path
    log: str = ""


class PluginLifecycleManager:
    """Install wheel packages without importing plugin code into this process.

    Manifest dependencies are an explicit, isolated closure. They are installed
    with ``--no-deps`` so pip cannot silently mutate the host environment or
    resolve a different transitive graph later.
    """

    def __init__(
        self,
        registry: PluginRegistry | None = None,
        *,
        root: Path | None = None,
        runner=None,
    ) -> None:
        self.registry = registry or PluginRegistry()
        if root is None:
            settings_path = get_path_service().get_settings_file("plugins")
            root = settings_path.parent.parent / "plugins"
        self.root = root
        self._runner = runner or _run_command

    def install(
        self,
        artifact: Path,
        *,
        expected_sha256: str = "",
        allow_reinstall: bool = False,
    ) -> LifecycleResult:
        artifact = Path(artifact).expanduser().resolve()
        if artifact.suffix != ".whl" or not artifact.is_file():
            raise PluginLifecycleError("artifact must be an existing local wheel")

        digest = _sha256(artifact)
        if expected_sha256 and digest != expected_sha256.lower():
            raise PluginLifecycleError("artifact SHA-256 does not match the reviewed pin")

        manifest, package_root_in_wheel = _manifest_from_wheel(artifact)
        existing = self.registry.get_plugin(manifest.id)
        if existing is not None and existing.installation is not None:
            self._validate_transition(
                existing.installation.version, str(manifest.version), allow_reinstall
            )

        plugin_root = self.root / manifest.id
        version_dir = plugin_root / "versions" / str(manifest.version)
        artifact_dir = plugin_root / "artifacts" / str(manifest.version)
        venv_dir = version_dir / "venv"
        staging_dir = version_dir / ".venv-staging"
        backup = None
        shutil.rmtree(staging_dir, ignore_errors=True)
        shutil.rmtree(artifact_dir, ignore_errors=True)
        artifact_dir.mkdir(parents=True, exist_ok=True)
        durable_artifact = artifact_dir / artifact.name
        shutil.copyfile(artifact, durable_artifact)

        chunks: list[str] = []
        try:
            code, output = self._runner([sys.executable, "-m", "venv", str(staging_dir)])
            chunks.append(f"$ {' '.join(('python', '-m', 'venv', str(staging_dir)))}\n{output}")
            if code != 0:
                raise PluginLifecycleError(f"virtual environment creation exited {code}")

            python_path = _venv_python(staging_dir)
            install_target = [*manifest.dependencies, str(durable_artifact)]
            argv = [
                str(python_path),
                "-m",
                "pip",
                "install",
                "--no-input",
                "--disable-pip-version-check",
                "--no-deps",
                *install_target,
            ]
            code, output = self._runner(argv, env=_clean_env())
            chunks.append(f"$ pip install --no-deps {', '.join(install_target)}\n{output}")
            if code != 0:
                raise PluginLifecycleError(f"isolated dependency install exited {code}")

            if venv_dir.exists():
                backup = version_dir / ".venv-old"
                shutil.rmtree(backup, ignore_errors=True)
                os.replace(venv_dir, backup)
            os.replace(staging_dir, venv_dir)
            package_path = _installed_package_path(venv_dir, package_root_in_wheel)
            installation = PluginInstallation(
                version=str(manifest.version),
                artifact_path=durable_artifact,
                artifact_sha256=digest,
                venv_path=venv_dir,
                python_path=_venv_python(venv_dir),
                installed_at=_timestamp(),
                dependencies=manifest.dependencies,
                package_path=package_path,
            )
            self._commit_installation(manifest, installation)
            if backup is not None:
                shutil.rmtree(backup, ignore_errors=True)
        except (OSError, PluginStateError, ValueError) as exc:
            shutil.rmtree(staging_dir, ignore_errors=True)
            shutil.rmtree(venv_dir, ignore_errors=True)
            if backup is not None:
                os.replace(backup, venv_dir)
            raise PluginLifecycleError(str(exc)) from exc

        return LifecycleResult(
            plugin_id=manifest.id,
            version=str(manifest.version),
            action="reinstalled" if allow_reinstall and existing is not None else "installed",
            artifact_sha256=digest,
            venv_path=venv_dir,
            log=_log(plugin_root, chunks),
        )

    def rollback(self, plugin_id: str) -> LifecycleResult:
        state = self.registry.state_snapshot()
        row = state.get("plugins", {}).get(plugin_id)
        if not isinstance(row, dict):
            raise PluginLifecycleError(f"plugin {plugin_id!r} has no managed installation")
        history = [item for item in row.get("history", []) if isinstance(item, dict)]
        if not history:
            raise PluginLifecycleError(f"plugin {plugin_id!r} has no rollback version")
        candidate = history[-1]
        installation = _installation_from_history(candidate)
        if installation is None or not installation.venv_path.is_dir():
            raise PluginLifecycleError(f"rollback environment for {plugin_id!r} is missing")

        previous_manifest_raw = row.get("manifest", {})
        manifest = parse_manifest(candidate.get("manifest"))
        current = PluginInstallation(
            version=row["installation"]["version"],
            artifact_path=Path(row["installation"]["artifact_path"]),
            artifact_sha256=row["installation"]["artifact_sha256"],
            venv_path=Path(row["installation"]["venv_path"]),
            python_path=Path(row["installation"]["python_path"]),
            installed_at=row["installation"]["installed_at"],
            dependencies=tuple(row["installation"].get("dependencies", [])),
            package_path=Path(row["installation"]["package_path"])
            if row["installation"].get("package_path")
            else None,
        )
        row["installation"] = installation.to_dict()
        row["manifest"] = manifest.to_dict()
        row.pop("approval", None)
        row["history"] = [item for item in history if item is not candidate] + [
            {
                "version": current.version,
                "manifest": previous_manifest_raw,
                "installation": current.to_dict(),
            }
        ]
        self.registry.replace_state(state)
        return LifecycleResult(
            plugin_id=plugin_id,
            version=installation.version,
            action="rolled-back",
            artifact_sha256=installation.artifact_sha256,
            venv_path=installation.venv_path,
        )

    def uninstall(self, plugin_id: str) -> LifecycleResult:
        state = self.registry.state_snapshot()
        row = state.get("plugins", {}).get(plugin_id)
        if not isinstance(row, dict):
            raise PluginLifecycleError(f"plugin {plugin_id!r} has no managed installation")
        installation_raw = row.get("installation")
        if not isinstance(installation_raw, dict):
            raise PluginLifecycleError(f"plugin {plugin_id!r} has an invalid installation")
        version = installation_raw.get("version", "")
        digest = installation_raw.get("artifact_sha256", "")
        state["plugins"].pop(plugin_id, None)
        state["disabled"] = sorted(set(state.get("disabled", [])) - {plugin_id})
        self.registry.replace_state(state)
        shutil.rmtree(self.root / plugin_id, ignore_errors=True)
        return LifecycleResult(
            plugin_id=plugin_id,
            version=version,
            action="uninstalled",
            artifact_sha256=digest,
            venv_path=self.root / plugin_id,
        )

    def _validate_transition(self, current: str, target: str, allow_reinstall: bool) -> None:
        try:
            current_version = Version(current)
            target_version = Version(target)
        except InvalidVersion as exc:
            raise PluginLifecycleError("installed plugin version is invalid") from exc
        if target_version == current_version and not allow_reinstall:
            raise PluginLifecycleError(f"version {target} is already installed")
        if target_version < current_version:
            raise PluginLifecycleError("downgrades require rollback or explicit reinstall")

    def _commit_installation(
        self,
        manifest: PluginManifestData,
        installation: PluginInstallation,
    ) -> None:
        plugin_id = manifest.id
        state = self.registry.state_snapshot()
        row = state.setdefault("plugins", {}).get(plugin_id)
        if row is None:
            row = {"history": []}
            state["plugins"][plugin_id] = row
        if not isinstance(row, dict):
            raise PluginLifecycleError(f"plugin state for {plugin_id!r} is invalid")
        previous_installation = row.get("installation")
        if previous_installation is not None:
            row.setdefault("history", []).append(
                {
                    "version": previous_installation.get("version", ""),
                    "manifest": row.get("manifest", {}),
                    "installation": previous_installation,
                }
            )
        row["manifest"] = manifest.to_dict()
        row["installation"] = installation.to_dict()
        row.pop("approval", None)
        self.registry.replace_state(state)


def _manifest_from_wheel(artifact: Path) -> tuple[PluginManifestData, PurePosixPath]:
    try:
        with zipfile.ZipFile(artifact) as archive:
            names = [
                name
                for name in archive.namelist()
                if Path(name).name == MANIFEST_FILENAME and not name.startswith("..")
            ]
            if len(names) != 1:
                raise PluginLifecycleError(f"wheel must contain exactly one {MANIFEST_FILENAME}")
            raw = json.loads(archive.read(names[0]).decode("utf-8"))
            source = PurePosixPath(names[0])
            if source.is_absolute() or any(part in {"", ".", ".."} for part in source.parts):
                raise PluginLifecycleError("artifact manifest has an invalid package path")
            return parse_manifest(raw), source.parent
    except (
        OSError,
        zipfile.BadZipFile,
        UnicodeDecodeError,
        ValueError,
        ManifestValidationError,
    ) as exc:
        if isinstance(exc, PluginLifecycleError):
            raise
        raise PluginLifecycleError(f"artifact manifest is unreadable: {exc}") from exc


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _installed_package_path(venv_root: Path, package_root: PurePosixPath) -> Path:
    if sys.platform == "win32":
        candidates = [venv_root / "Lib" / "site-packages"]
    else:
        candidates = sorted((venv_root / "lib").glob("python*/site-packages"))
    for site_packages in candidates:
        candidate = site_packages.joinpath(*package_root.parts)
        try:
            resolved = candidate.resolve(strict=True)
        except OSError:
            continue
        if resolved.is_dir():
            return resolved
    raise PluginLifecycleError("installed plugin package root is missing")


def _venv_python(root: Path) -> Path:
    if sys.platform == "win32":
        return root / "Scripts" / "python.exe"
    return root / "bin" / "python"


def _clean_env() -> dict[str, str]:
    keep = ("PATH", "HOME", "LANG", "LC_ALL", "TMPDIR", "SSL_CERT_FILE", "SSL_CERT_DIR")
    env = {key: os.environ[key] for key in keep if key in os.environ}
    for key in ("HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY", "http_proxy", "https_proxy"):
        if key in os.environ:
            env[key] = os.environ[key]
    env["PIP_DISABLE_PIP_VERSION_CHECK"] = "1"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    return env


def _run_command(argv: list[str], *, env: dict[str, str] | None = None) -> tuple[int, str]:
    try:
        completed = subprocess.run(  # noqa: S603 - argv is assembled here
            argv,
            env=env,
            capture_output=True,
            text=True,
            timeout=900,
            check=False,
        )
    except FileNotFoundError:
        return 127, f"{argv[0]}: not found"
    except subprocess.TimeoutExpired:
        return 124, "installation timed out after 900s"
    return completed.returncode, (completed.stdout or "") + (completed.stderr or "")


def _installation_from_history(raw: dict) -> PluginInstallation | None:
    installation_raw = raw.get("installation")
    if not isinstance(installation_raw, dict):
        return None
    dependencies = installation_raw.get("dependencies", [])
    if not isinstance(dependencies, list):
        dependencies = []
    required = (
        "version",
        "artifact_path",
        "artifact_sha256",
        "venv_path",
        "python_path",
        "installed_at",
    )
    if not all(isinstance(installation_raw.get(name), str) for name in required):
        return None
    package_path_raw = installation_raw.get("package_path")
    if package_path_raw is not None and (
        not isinstance(package_path_raw, str) or not package_path_raw
    ):
        return None
    return PluginInstallation(
        version=installation_raw["version"],
        artifact_path=Path(installation_raw["artifact_path"]),
        artifact_sha256=installation_raw["artifact_sha256"],
        venv_path=Path(installation_raw["venv_path"]),
        python_path=Path(installation_raw["python_path"]),
        installed_at=installation_raw["installed_at"],
        dependencies=tuple(item for item in dependencies if isinstance(item, str)),
        package_path=Path(package_path_raw) if package_path_raw else None,
    )


def _log(plugin_root: Path, chunks: list[str]) -> str:
    text = "\n\n".join(chunks)
    try:
        plugin_root.mkdir(parents=True, exist_ok=True)
        path = plugin_root / "install.log"
        with tempfile.NamedTemporaryFile(
            "w",
            encoding="utf-8",
            dir=plugin_root,
            delete=False,
        ) as handle:
            handle.write(text)
            temp = Path(handle.name)
        temp.replace(path)
    except OSError:
        pass
    return text[-20_000:]


def _timestamp() -> str:
    return datetime.now(UTC).isoformat()


__all__ = [
    "LifecycleResult",
    "PluginLifecycleError",
    "PluginLifecycleManager",
]
