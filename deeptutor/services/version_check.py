"""GitHub release checks for the Settings version panel."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
import importlib.metadata
import json
import logging
import os
from pathlib import Path
import re
import subprocess  # nosec B404 - fixed argv, never user input
import sys
import threading
import time
from typing import Any, Callable

import httpx

from deeptutor.__version__ import __version__
from deeptutor.services.config.runtime_settings import get_runtime_settings_service
from deeptutor.services.file_io import atomic_write_json

logger = logging.getLogger(__name__)

GITHUB_LATEST_RELEASE_URL = "https://api.github.com/repos/HKUDS/DeepTutor/releases/latest"
VERSION_CHECK_TTL_SECONDS = 24 * 60 * 60
VERSION_UPDATE_MAX_STORED_LINES = 200
_VERSION_PATTERN = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)")


class VersionCheckError(RuntimeError):
    """Raised when the latest release cannot be safely resolved."""


@dataclass(frozen=True)
class VersionCheckResult:
    current_version: str
    latest_release: dict[str, Any] | None
    checked_at: str
    cached: bool


@dataclass(frozen=True)
class VersionInstallation:
    mode: str
    update_supported: bool
    command: str
    reason: str


@dataclass(frozen=True)
class VersionUpdateState:
    state: str
    message: str
    previous_version: str
    installed_version: str
    target_version: str
    restart_required: bool
    lines: tuple[str, ...]


class VersionUpdateError(RuntimeError):
    """Raised when an explicit update cannot be started."""


class VersionCheckService:
    """Resolve GitHub's latest release with a process-local 24-hour cache.

    The service never launches install commands or mutates deployment state.
    A failed request is not cached, so the next explicit check can retry.
    """

    def __init__(
        self,
        *,
        api_url: str = GITHUB_LATEST_RELEASE_URL,
        timeout: float = 8.0,
        ttl_seconds: float = VERSION_CHECK_TTL_SECONDS,
        clock: Callable[[], float] = time.time,
        client_factory: Callable[[], httpx.AsyncClient] | None = None,
    ) -> None:
        self._api_url = api_url
        self._timeout = timeout
        self._ttl_seconds = ttl_seconds
        self._clock = clock
        self._client_factory = client_factory
        self._cache: VersionCheckResult | None = None
        self._cached_at: float | None = None
        self._lock = asyncio.Lock()

    def cached_result(self) -> VersionCheckResult:
        """Return the current version and any unexpired cached release."""
        result = self._cache
        if result is not None and self._is_cache_valid():
            return VersionCheckResult(
                current_version=__version__,
                latest_release=result.latest_release,
                checked_at=result.checked_at,
                cached=True,
            )
        return VersionCheckResult(
            current_version=__version__,
            latest_release=None,
            checked_at="",
            cached=False,
        )

    async def check(self, *, force: bool = False) -> VersionCheckResult:
        async with self._lock:
            if not force and self._cache is not None and self._is_cache_valid():
                return VersionCheckResult(
                    current_version=__version__,
                    latest_release=self._cache.latest_release,
                    checked_at=self._cache.checked_at,
                    cached=True,
                )

            release = await self._fetch_latest_release()
            checked_at = datetime.now(timezone.utc).isoformat()
            result = VersionCheckResult(
                current_version=__version__,
                latest_release=release,
                checked_at=checked_at,
                cached=False,
            )
            self._cache = result
            self._cached_at = self._clock()
            return result

    def _is_cache_valid(self) -> bool:
        if self._cache is None or self._cached_at is None:
            return False
        return self._clock() - self._cached_at < self._ttl_seconds

    async def _fetch_latest_release(self) -> dict[str, Any]:
        factory = self._client_factory or (
            lambda: httpx.AsyncClient(
                timeout=httpx.Timeout(self._timeout, connect=5.0),
                follow_redirects=True,
            )
        )
        try:
            async with factory() as client:
                response = await client.get(
                    self._api_url,
                    headers={
                        "Accept": "application/vnd.github+json",
                        "X-GitHub-Api-Version": "2022-11-28",
                        "User-Agent": "DeepTutor-Version-Check",
                    },
                )
                response.raise_for_status()
                payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            logger.warning("Version check failed: %s", type(exc).__name__)
            raise VersionCheckError("Unable to check for updates") from None

        return _release_payload(payload)


def _release_payload(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise VersionCheckError("Unable to check for updates")

    tag_name = payload.get("tag_name")
    html_url = payload.get("html_url")
    if not isinstance(tag_name, str) or not tag_name.strip():
        raise VersionCheckError("Unable to check for updates")
    if not isinstance(html_url, str) or not html_url.startswith(("http://", "https://")):
        raise VersionCheckError("Unable to check for updates")

    body = payload.get("body")
    release_body = _optional_text(body).lower()
    migration_bearing = bool(
        re.search(
            r"breaking chang|migration(?: needed| required)|database migration|run migration|migrate your",
            release_body,
        )
    )
    return {
        "tag_name": tag_name.strip(),
        "name": _optional_text(payload.get("name")),
        "published_at": _optional_text(payload.get("published_at")),
        "html_url": html_url.strip(),
        "excerpt": _excerpt(body),
        "update_available": _is_newer(tag_name, __version__),
        "migration_bearing": migration_bearing,
    }


def _optional_text(value: Any) -> str:
    return value.strip() if isinstance(value, str) else ""


def _excerpt(value: Any, limit: int = 480) -> str:
    text = _optional_text(value).replace("\r\n", "\n").replace("\r", "\n")
    if len(text) <= limit:
        return text
    cut = text[:limit]
    boundary = cut.rfind("\n")
    if boundary >= limit // 2:
        cut = cut[:boundary]
    return f"{cut.rstrip()}..."


def _is_newer(candidate: str, current: str) -> bool:
    candidate_match = _VERSION_PATTERN.match(candidate.strip())
    current_match = _VERSION_PATTERN.match(current.strip())
    if candidate_match is None or current_match is None:
        return False
    return tuple(map(int, candidate_match.groups())) > tuple(map(int, current_match.groups()))


def _normalised_release_version(value: str) -> str | None:
    match = _VERSION_PATTERN.match(value.strip())
    return ".".join(match.groups()) if match else None


def _running_in_container() -> bool:
    return (
        Path("/.dockerenv").exists()
        or Path("/run/.containerenv").exists()
        or bool(os.environ.get("KUBERNETES_SERVICE_HOST"))
    )


def _detect_installation() -> VersionInstallation:
    if _running_in_container():
        return VersionInstallation(
            mode="docker",
            update_supported=False,
            command="docker pull ghcr.io/hkuds/deeptutor:latest, then recreate the container",
            reason="Containers are replaced from their image instead of upgraded in place.",
        )

    direct_url: dict[str, Any] = {}
    try:
        raw_direct_url = importlib.metadata.distribution("deeptutor").read_text("direct_url.json")
        if raw_direct_url:
            loaded = json.loads(raw_direct_url)
            direct_url = loaded if isinstance(loaded, dict) else {}
    except (importlib.metadata.PackageNotFoundError, OSError, ValueError):
        direct_url = {}

    if bool((direct_url.get("dir_info") or {}).get("editable")):
        return VersionInstallation(
            mode="source",
            update_supported=False,
            command="git pull, pip install -e ., npm ci --legacy-peer-deps",
            reason="Source checkouts follow their own Git and dependency workflow.",
        )

    in_venv = Path(sys.prefix).resolve() != Path(sys.base_prefix).resolve()
    if not direct_url and in_venv:
        return VersionInstallation(
            mode="pypi",
            update_supported=True,
            command="pip install -U deeptutor",
            reason="",
        )

    return VersionInstallation(
        mode="unknown",
        update_supported=False,
        command="pip install -U deeptutor",
        reason=(
            "Automatic updates need a regular PyPI install inside the active virtual environment."
            if not direct_url
            else "This DeepTutor distribution was installed from a local artifact."
        ),
    )


class VersionUpdateService:
    """Run one explicit, fixed-argv pip upgrade at a time.

    Docker and editable source installations stay manual: replacing an image or
    updating a checkout is deployment state that pip cannot safely own.
    """

    def __init__(
        self,
        *,
        installation: VersionInstallation | None = None,
        process_factory: Callable[..., subprocess.Popen] | None = None,
        history_path: Path | None = None,
        installed_version: Callable[[], str] | None = None,
    ) -> None:
        resolved_history_path = (
            history_path
            if history_path is not None
            else get_runtime_settings_service().path_for("version_updates")
        )
        self._installation = installation or _detect_installation()
        self._process_factory = process_factory or self._start_process
        self._history_path = resolved_history_path
        self._installed_version = installed_version or (
            lambda: importlib.metadata.version("deeptutor")
        )
        self._lock = threading.Lock()
        self._state = "idle"
        self._message = ""
        self._previous_version = __version__
        self._installed_result = __version__
        self._target_version = ""
        self._lines: list[str] = []
        self._process: subprocess.Popen | None = None
        self._cancel_requested = False

    def installation(self) -> VersionInstallation:
        return self._installation

    def history(self) -> dict[str, Any] | None:
        if self._history_path is None:
            return None
        try:
            payload = json.loads(self._history_path.read_text(encoding="utf-8"))
            return payload if isinstance(payload, dict) else None
        except (OSError, ValueError):
            return None

    def status(self) -> VersionUpdateState:
        with self._lock:
            return self._status_unlocked()

    def start_update(self, *, target_version: str) -> VersionUpdateState:
        target = _normalised_release_version(target_version)
        if target is None:
            raise VersionUpdateError("The latest release has an invalid version")
        if not self._installation.update_supported:
            raise VersionUpdateError(self._installation.reason)
        if not _is_newer(target, __version__):
            raise VersionUpdateError("No newer DeepTutor release is available")

        argv = [
            sys.executable,
            "-m",
            "pip",
            "install",
            "--no-input",
            "--disable-pip-version-check",
            "--upgrade",
            f"deeptutor=={target}",
        ]
        with self._lock:
            if self._state == "running":
                raise VersionUpdateError("An update is already running")
            try:
                process = self._process_factory(
                    argv,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.STDOUT,
                    text=True,
                    shell=False,
                    env={
                        **os.environ,
                        "PIP_DISABLE_PIP_VERSION_CHECK": "1",
                    },
                )
            except Exception as exc:  # noqa: BLE001 - surfaced to the admin
                self._state = "failed"
                self._message = f"Failed to launch pip: {exc}"
                self._lines = [self._message]
                self._target_version = target
                return self._status_unlocked()
            self._state = "running"
            self._message = ""
            self._previous_version = __version__
            self._installed_result = __version__
            self._target_version = target
            self._lines = [f"$ {' '.join(argv)}"]
            self._process = process
            self._cancel_requested = False

        threading.Thread(
            target=self._watch,
            args=(process, target),
            daemon=True,
            name="DeepTutor-version-update",
        ).start()
        return self.status()

    def cancel(self) -> VersionUpdateState:
        with self._lock:
            process = self._process
            if self._state != "running" or process is None:
                return self.status()
            self._message = "Cancelling..."
            self._cancel_requested = True
        try:
            process.terminate()
        except Exception as exc:  # noqa: BLE001 - surfaced to the admin
            with self._lock:
                self._message = f"Failed to cancel: {exc}"
        return self.status()

    def _start_process(self, *args: Any, **kwargs: Any) -> subprocess.Popen:
        return subprocess.Popen(  # nosec B603 - fixed argv, shell=False
            *args,
            **kwargs,
        )

    def _watch(self, process: subprocess.Popen, target: str) -> None:
        try:
            assert process.stdout is not None
            for raw_line in process.stdout:
                line = raw_line.strip()
                if line:
                    self._append(line[:500])
        except Exception:
            logger.exception("Version update output pump failed")
        returncode = process.wait()
        with self._lock:
            self._process = None
            if self._cancel_requested:
                self._state = "cancelled"
                self._message = "Update cancelled."
            elif returncode == 0:
                try:
                    self._installed_result = self._installed_version()
                except Exception:  # noqa: BLE001 - metadata is best effort
                    self._installed_result = target
                self._write_history(target)
                self._state = "done"
                self._message = "Update installed. Restart DeepTutor to use it."
            else:
                self._state = "failed"
                self._message = f"pip exited with code {returncode}."
            self._lines.append(self._message)

    def _append(self, line: str) -> None:
        with self._lock:
            if len(self._lines) <= VERSION_UPDATE_MAX_STORED_LINES:
                self._lines.append(line)

    def _status_unlocked(self) -> VersionUpdateState:
        return VersionUpdateState(
            state=self._state,
            message=self._message,
            previous_version=self._previous_version,
            installed_version=self._installed_result,
            target_version=self._target_version,
            restart_required=self._state == "done",
            lines=tuple(self._lines[-200:]),
        )

    def _write_history(self, target: str) -> None:
        if self._history_path is None:
            return
        try:
            atomic_write_json(
                self._history_path,
                {
                    "previous_version": self._previous_version,
                    "installed_version": self._installed_result,
                    "target_version": target,
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                },
            )
        except OSError:
            logger.exception("Could not record the previous DeepTutor version")


_version_check_service = VersionCheckService()
_version_update_service = VersionUpdateService()


def get_version_check_service() -> VersionCheckService:
    return _version_check_service


def reset_version_check_service_for_tests() -> None:
    global _version_check_service
    _version_check_service = VersionCheckService()


def get_version_update_service() -> VersionUpdateService:
    return _version_update_service


def reset_version_update_service_for_tests(
    service: VersionUpdateService | None = None,
) -> None:
    global _version_update_service
    _version_update_service = service or VersionUpdateService()
