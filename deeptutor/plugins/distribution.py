"""Download and install reviewed catalog artifact pins."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import os
from pathlib import Path
import tempfile
from typing import Callable, Protocol

import httpx

from deeptutor.plugins.catalog import (
    CatalogArtifact,
    CatalogResolutionError,
    resolve_catalog_entry,
)
from deeptutor.plugins.lifecycle import LifecycleResult, PluginLifecycleManager

DEFAULT_DOWNLOAD_TIMEOUT_SECONDS = 60.0


class PluginDistributionError(ValueError):
    """Raised when a reviewed artifact cannot be downloaded safely."""


@dataclass(frozen=True, slots=True)
class CatalogDownloadResult:
    path: Path
    url: str
    size_bytes: int
    sha256: str


@dataclass(frozen=True, slots=True)
class CatalogInstallResult:
    lifecycle: LifecycleResult
    artifact_url: str


class _DownloadClient(Protocol):
    def __enter__(self) -> _DownloadClient: ...

    def __exit__(self, *args: object) -> None: ...

    def stream(self, method: str, url: str) -> httpx.Response: ...


class CatalogArtifactDownloader:
    """Stream a catalog-pinned wheel into a temporary local file."""

    def __init__(
        self,
        *,
        client_factory: Callable[[float], _DownloadClient] | None = None,
    ) -> None:
        self._client_factory = client_factory or _default_client

    def download(
        self,
        artifact: CatalogArtifact,
        *,
        destination_dir: Path,
        timeout_seconds: float = DEFAULT_DOWNLOAD_TIMEOUT_SECONDS,
    ) -> CatalogDownloadResult:
        if timeout_seconds <= 0:
            raise PluginDistributionError("artifact download timeout must be positive")
        if not artifact.url:
            raise PluginDistributionError("catalog artifact has no download URL")
        destination_dir.mkdir(parents=True, exist_ok=True)
        descriptor, name = tempfile.mkstemp(
            prefix="deeptutor-plugin-", suffix=".whl", dir=destination_dir
        )
        os.close(descriptor)
        destination = Path(name)
        digest = hashlib.sha256()
        size = 0
        try:
            with self._client_factory(timeout_seconds) as client:
                with client.stream("GET", artifact.url) as response:
                    if 300 <= response.status_code < 400:
                        raise PluginDistributionError("catalog artifact redirects are not allowed")
                    if response.status_code != 200:
                        raise PluginDistributionError(
                            f"catalog artifact download exited {response.status_code}"
                        )
                    content_length = response.headers.get("content-length")
                    if content_length is not None:
                        try:
                            declared_size = int(content_length)
                        except ValueError as exc:
                            raise PluginDistributionError(
                                "catalog artifact has an invalid Content-Length"
                            ) from exc
                        if declared_size != artifact.size_bytes:
                            raise PluginDistributionError(
                                "catalog artifact Content-Length does not match reviewed size"
                            )
                    with destination.open("wb") as handle:
                        for chunk in response.iter_bytes():
                            size += len(chunk)
                            if size > artifact.size_bytes:
                                raise PluginDistributionError(
                                    "catalog artifact exceeds reviewed size"
                                )
                            digest.update(chunk)
                            handle.write(chunk)
            if size != artifact.size_bytes:
                raise PluginDistributionError("catalog artifact is smaller than reviewed size")
            if digest.hexdigest() != artifact.sha256:
                raise PluginDistributionError(
                    "catalog artifact SHA-256 does not match reviewed pin"
                )
        except (
            OSError,
            httpx.HTTPError,
            PluginDistributionError,
        ) as exc:
            destination.unlink(missing_ok=True)
            if isinstance(exc, PluginDistributionError):
                raise
            raise PluginDistributionError(f"catalog artifact download failed: {exc}") from exc
        return CatalogDownloadResult(
            path=destination,
            url=artifact.url,
            size_bytes=size,
            sha256=digest.hexdigest(),
        )


class CatalogInstallManager:
    """Resolve a reviewed row, download its exact wheel, then run local lifecycle."""

    def __init__(
        self,
        *,
        downloader_factory: Callable[[], CatalogArtifactDownloader] | None = None,
        lifecycle_factory: Callable[[], PluginLifecycleManager] | None = None,
    ) -> None:
        self._downloader_factory = downloader_factory or CatalogArtifactDownloader
        self._lifecycle_factory = lifecycle_factory or PluginLifecycleManager

    def install(
        self,
        plugin_id: str,
        *,
        version: str = "latest",
        allow_deprecated: bool = False,
        timeout_seconds: float = DEFAULT_DOWNLOAD_TIMEOUT_SECONDS,
        allow_reinstall: bool = False,
    ) -> CatalogInstallResult:
        try:
            entry = resolve_catalog_entry(
                plugin_id,
                version,
                allow_deprecated=allow_deprecated,
            )
        except CatalogResolutionError as exc:
            raise PluginDistributionError(str(exc)) from exc
        if not entry.artifact.url:
            raise PluginDistributionError(
                f"catalog entry for {plugin_id!r} {entry.version} has no download URL"
            )

        with tempfile.TemporaryDirectory(prefix="deeptutor-plugin-download-") as temporary:
            downloaded = self._downloader_factory().download(
                entry.artifact,
                destination_dir=Path(temporary),
                timeout_seconds=timeout_seconds,
            )
            lifecycle = self._lifecycle_factory().install(
                downloaded.path,
                expected_sha256=entry.artifact.sha256,
                allow_reinstall=allow_reinstall,
            )
        return CatalogInstallResult(
            lifecycle=lifecycle,
            artifact_url=entry.artifact.url,
        )


def _default_client(timeout_seconds: float) -> _DownloadClient:
    return httpx.Client(
        timeout=timeout_seconds,
        follow_redirects=False,
        headers={"User-Agent": "DeepTutor-plugin-catalog/2"},
    )
