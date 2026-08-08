"""Installation-aware update checks and execution."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from importlib import metadata
import json
import os
from pathlib import Path
from typing import Callable, Protocol
from urllib.parse import unquote, urlparse
from urllib.request import url2pathname

import httpx
from packaging.version import Version

from deeptutor.__version__ import __version__


class InstallMode(str, Enum):
    """Supported DeepTutor installation layouts."""

    PYPI = "pypi"
    SOURCE_WEB = "source_web"
    SOURCE_CLI = "source_cli"
    DOCKER = "docker"
    UNSUPPORTED = "unsupported"


class UpdateStatus(str, Enum):
    """Result of a completed update check."""

    AVAILABLE = "available"
    UP_TO_DATE = "up_to_date"
    FAILED = "failed"


@dataclass(frozen=True)
class DistributionEvidence:
    """Relevant metadata from one installed Python distribution."""

    name: str
    version: str
    editable_root: Path | None = None


@dataclass(frozen=True)
class RuntimeEvidence:
    """Runtime facts used to classify the current installation."""

    current_version: str
    package_root: Path
    containerized: bool
    deeptutor: DistributionEvidence | None
    deeptutor_cli: DistributionEvidence | None


@dataclass(frozen=True)
class Installation:
    """Detected installation details used to build an update plan."""

    mode: InstallMode
    current_version: str
    package_name: str
    source_root: Path | None = None
    detail: str = ""

    @property
    def can_auto_update(self) -> bool:
        """Return whether this installation supports a managed update."""

        return self.mode not in {InstallMode.DOCKER, InstallMode.UNSUPPORTED}


def detect_installation(evidence: RuntimeEvidence) -> Installation:
    """Classify a runtime from explicit filesystem and distribution evidence."""

    if evidence.containerized:
        return Installation(
            mode=InstallMode.DOCKER,
            current_version=evidence.current_version,
            package_name="deeptutor",
            detail="container runtime",
        )
    if evidence.deeptutor is not None and evidence.deeptutor_cli is not None:
        return Installation(
            mode=InstallMode.UNSUPPORTED,
            current_version=evidence.current_version,
            package_name="deeptutor",
            detail="conflicting DeepTutor distributions",
        )
    if evidence.deeptutor is not None:
        if evidence.deeptutor.editable_root is not None:
            return Installation(
                mode=InstallMode.SOURCE_WEB,
                current_version=evidence.current_version,
                package_name="deeptutor",
                source_root=evidence.deeptutor.editable_root,
                detail="editable full installation",
            )
        return Installation(
            mode=InstallMode.PYPI,
            current_version=evidence.current_version,
            package_name="deeptutor",
            detail="installed distribution",
        )
    if evidence.deeptutor_cli is not None and evidence.deeptutor_cli.editable_root is not None:
        return Installation(
            mode=InstallMode.SOURCE_CLI,
            current_version=evidence.current_version,
            package_name="deeptutor-cli",
            source_root=evidence.package_root,
            detail="editable CLI-only installation",
        )
    return Installation(
        mode=InstallMode.UNSUPPORTED,
        current_version=evidence.current_version,
        package_name="deeptutor",
        detail="installation metadata not found",
    )


def _editable_root(distribution: metadata.Distribution) -> Path | None:
    raw = distribution.read_text("direct_url.json")
    if not raw:
        return None
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if not payload.get("dir_info", {}).get("editable"):
        return None
    parsed = urlparse(str(payload.get("url", "")))
    if parsed.scheme != "file":
        return None
    path = url2pathname(unquote(parsed.path))
    if parsed.netloc:
        path = f"//{parsed.netloc}{path}"
    return Path(path).resolve()


def _distribution_evidence(
    name: str,
    *,
    fallback_root: Path | None = None,
) -> DistributionEvidence | None:
    try:
        distribution = metadata.distribution(name)
    except metadata.PackageNotFoundError:
        return None
    editable_root = _editable_root(distribution)
    if editable_root is None and fallback_root is not None:
        editable_root = fallback_root
    return DistributionEvidence(
        name=name,
        version=distribution.version,
        editable_root=editable_root,
    )


def _is_source_checkout(package_root: Path) -> bool:
    return (package_root / "pyproject.toml").is_file() and (package_root / "deeptutor").is_dir()


def _is_containerized() -> bool:
    value = os.getenv("DEEPTUTOR_CONTAINER", "").strip().lower()
    return value in {"1", "true", "yes", "on"} or any(
        marker.exists() for marker in (Path("/.dockerenv"), Path("/run/.containerenv"))
    )


def detect_current_installation() -> Installation:
    """Detect the installation backing the current Python process."""

    package_root = Path(__file__).resolve().parents[2]
    source_root = package_root if _is_source_checkout(package_root) else None
    full_distribution = _distribution_evidence(
        "deeptutor",
        fallback_root=source_root,
    )
    cli_project = package_root / "packaging" / "deeptutor-cli" if source_root is not None else None
    cli_distribution = _distribution_evidence(
        "deeptutor-cli",
        fallback_root=cli_project if cli_project and cli_project.is_dir() else None,
    )
    if full_distribution is None and source_root is not None and cli_distribution is None:
        full_distribution = DistributionEvidence(
            name="deeptutor",
            version=__version__,
            editable_root=source_root,
        )
    evidence = RuntimeEvidence(
        current_version=__version__,
        package_root=package_root,
        containerized=_is_containerized(),
        deeptutor=full_distribution,
        deeptutor_cli=cli_distribution,
    )
    return detect_installation(evidence)


@dataclass(frozen=True)
class ReleaseInfo:
    """Latest stable release metadata."""

    version: str
    release_url: str


@dataclass(frozen=True)
class UpdateCheck:
    """Serializable result returned by :class:`UpdateCoordinator`."""

    status: UpdateStatus
    current_version: str
    latest_version: str | None
    install_mode: InstallMode
    can_auto_update: bool
    release_url: str | None
    detail: str = ""


class ReleaseProvider(Protocol):
    """Boundary for querying release metadata."""

    def latest(self, installation: Installation) -> ReleaseInfo:
        """Return the latest stable release for *installation*."""


class HttpReleaseProvider:
    """Read stable DeepTutor release metadata from official endpoints."""

    PYPI_URL = "https://pypi.org/pypi/deeptutor/json"
    GITHUB_LATEST_URL = "https://api.github.com/repos/HKUDS/DeepTutor/releases/latest"
    RELEASES_URL = "https://github.com/HKUDS/DeepTutor/releases"

    def __init__(
        self,
        *,
        client: httpx.Client | None = None,
        pypi_url: str | None = None,
        github_latest_url: str | None = None,
    ) -> None:
        self._client = client or httpx.Client(
            timeout=5.0,
            follow_redirects=True,
            headers={"User-Agent": "DeepTutor update checker"},
        )
        self._pypi_url = pypi_url or self.PYPI_URL
        self._github_latest_url = github_latest_url or self.GITHUB_LATEST_URL

    def latest(self, installation: Installation) -> ReleaseInfo:
        """Return the latest stable release usable by *installation*."""

        if installation.mode is not InstallMode.PYPI:
            response = self._client.get(self._github_latest_url)
            response.raise_for_status()
            payload = response.json()
            if payload.get("draft") or payload.get("prerelease"):
                raise ValueError("GitHub did not return a stable DeepTutor release")
            raw_version = str(payload.get("tag_name", "")).removeprefix("v")
            version = Version(raw_version)
            if version.is_prerelease or version.is_devrelease:
                raise ValueError("GitHub did not return a stable DeepTutor release")
            release_url = str(payload.get("html_url") or "").strip()
            if not release_url:
                release_url = f"{self.RELEASES_URL}/tag/v{version}"
            return ReleaseInfo(version=str(version), release_url=release_url)

        response = self._client.get(self._pypi_url)
        response.raise_for_status()
        releases = response.json().get("releases", {})
        versions: list[Version] = []
        for raw_version, files in releases.items():
            try:
                version = Version(raw_version)
            except ValueError:
                continue
            if version.is_prerelease or version.is_devrelease:
                continue
            if not files or not any(not item.get("yanked", False) for item in files):
                continue
            versions.append(version)
        if not versions:
            raise ValueError("PyPI did not return a stable DeepTutor release")
        latest = str(max(versions))
        return ReleaseInfo(
            version=latest,
            release_url=f"{self.RELEASES_URL}/tag/v{latest}",
        )


class UpdateCoordinator:
    """Coordinate installation detection and stable release checks."""

    def __init__(
        self,
        *,
        installation_provider: Callable[[], Installation],
        release_provider: ReleaseProvider,
    ) -> None:
        self._installation_provider = installation_provider
        self._release_provider = release_provider

    def check(self) -> UpdateCheck:
        """Return update availability without changing the installation."""

        installation = self._installation_provider()
        try:
            release = self._release_provider.latest(installation)
        except (httpx.HTTPError, ValueError):
            return UpdateCheck(
                status=UpdateStatus.FAILED,
                current_version=installation.current_version,
                latest_version=None,
                install_mode=installation.mode,
                can_auto_update=installation.can_auto_update,
                release_url=None,
                detail="Unable to check for updates.",
            )
        status = (
            UpdateStatus.AVAILABLE
            if Version(release.version) > Version(installation.current_version)
            else UpdateStatus.UP_TO_DATE
        )
        return UpdateCheck(
            status=status,
            current_version=installation.current_version,
            latest_version=release.version,
            install_mode=installation.mode,
            can_auto_update=installation.can_auto_update,
            release_url=release.release_url,
            detail=installation.detail,
        )


def create_update_coordinator() -> UpdateCoordinator:
    """Build the production coordinator for the current process."""

    return UpdateCoordinator(
        installation_provider=detect_current_installation,
        release_provider=HttpReleaseProvider(),
    )


__all__ = (
    "DistributionEvidence",
    "HttpReleaseProvider",
    "InstallMode",
    "Installation",
    "ReleaseInfo",
    "ReleaseProvider",
    "RuntimeEvidence",
    "UpdateCheck",
    "UpdateCoordinator",
    "UpdateStatus",
    "create_update_coordinator",
    "detect_current_installation",
    "detect_installation",
)
