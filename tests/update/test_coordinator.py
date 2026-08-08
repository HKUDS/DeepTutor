from __future__ import annotations

import httpx

from deeptutor.update import (
    DistributionEvidence,
    Installation,
    InstallMode,
    ReleaseInfo,
    RuntimeEvidence,
    UpdateCoordinator,
    UpdateStatus,
    detect_installation,
)


class _StaticReleases:
    def latest(self, installation: Installation) -> ReleaseInfo:
        return ReleaseInfo(
            version="1.6.0",
            release_url="https://github.com/HKUDS/DeepTutor/releases/tag/v1.6.0",
        )


def test_check_reports_a_stable_pypi_update() -> None:
    installation = Installation(
        mode=InstallMode.PYPI,
        current_version="1.5.4",
        package_name="deeptutor",
    )
    coordinator = UpdateCoordinator(
        installation_provider=lambda: installation,
        release_provider=_StaticReleases(),
    )

    result = coordinator.check()

    assert result.status is UpdateStatus.AVAILABLE
    assert result.current_version == "1.5.4"
    assert result.latest_version == "1.6.0"
    assert result.install_mode is InstallMode.PYPI
    assert result.can_auto_update is True
    assert result.release_url.endswith("/v1.6.0")


def test_check_reports_equal_stable_versions_as_up_to_date() -> None:
    installation = Installation(
        mode=InstallMode.PYPI,
        current_version="1.6.0",
        package_name="deeptutor",
    )
    coordinator = UpdateCoordinator(
        installation_provider=lambda: installation,
        release_provider=_StaticReleases(),
    )

    result = coordinator.check()

    assert result.status is UpdateStatus.UP_TO_DATE
    assert result.latest_version == "1.6.0"


def test_detect_installation_classifies_a_wheel_as_pypi(tmp_path) -> None:
    evidence = RuntimeEvidence(
        current_version="1.5.4",
        package_root=tmp_path / "site-packages",
        containerized=False,
        deeptutor=DistributionEvidence(name="deeptutor", version="1.5.4"),
        deeptutor_cli=None,
    )

    installation = detect_installation(evidence)

    assert installation == Installation(
        mode=InstallMode.PYPI,
        current_version="1.5.4",
        package_name="deeptutor",
        detail="installed distribution",
    )


def test_detect_installation_classifies_an_editable_full_checkout(tmp_path) -> None:
    checkout = tmp_path / "DeepTutor"
    evidence = RuntimeEvidence(
        current_version="1.5.4",
        package_root=checkout,
        containerized=False,
        deeptutor=DistributionEvidence(
            name="deeptutor",
            version="1.5.4",
            editable_root=checkout,
        ),
        deeptutor_cli=None,
    )

    installation = detect_installation(evidence)

    assert installation == Installation(
        mode=InstallMode.SOURCE_WEB,
        current_version="1.5.4",
        package_name="deeptutor",
        source_root=checkout,
        detail="editable full installation",
    )


def test_detect_installation_classifies_an_editable_cli_checkout(tmp_path) -> None:
    checkout = tmp_path / "DeepTutor"
    cli_project = checkout / "packaging" / "deeptutor-cli"
    evidence = RuntimeEvidence(
        current_version="1.5.4",
        package_root=checkout,
        containerized=False,
        deeptutor=None,
        deeptutor_cli=DistributionEvidence(
            name="deeptutor-cli",
            version="1.5.4",
            editable_root=cli_project,
        ),
    )

    installation = detect_installation(evidence)

    assert installation == Installation(
        mode=InstallMode.SOURCE_CLI,
        current_version="1.5.4",
        package_name="deeptutor-cli",
        source_root=checkout,
        detail="editable CLI-only installation",
    )


def test_container_detection_wins_and_never_allows_automatic_updates(tmp_path) -> None:
    evidence = RuntimeEvidence(
        current_version="1.5.4",
        package_root=tmp_path,
        containerized=True,
        deeptutor=DistributionEvidence(name="deeptutor", version="1.5.4"),
        deeptutor_cli=None,
    )
    coordinator = UpdateCoordinator(
        installation_provider=lambda: detect_installation(evidence),
        release_provider=_StaticReleases(),
    )

    result = coordinator.check()

    assert result.install_mode is InstallMode.DOCKER
    assert result.status is UpdateStatus.AVAILABLE
    assert result.can_auto_update is False


def test_detect_installation_refuses_conflicting_distributions(tmp_path) -> None:
    evidence = RuntimeEvidence(
        current_version="1.5.4",
        package_root=tmp_path,
        containerized=False,
        deeptutor=DistributionEvidence(name="deeptutor", version="1.5.4"),
        deeptutor_cli=DistributionEvidence(
            name="deeptutor-cli",
            version="1.5.4",
            editable_root=tmp_path,
        ),
    )

    installation = detect_installation(evidence)

    assert installation.mode is InstallMode.UNSUPPORTED
    assert installation.can_auto_update is False
    assert installation.detail == "conflicting DeepTutor distributions"


def test_check_reports_release_lookup_failures_without_crashing() -> None:
    class OfflineReleases:
        def latest(self, installation: Installation) -> ReleaseInfo:
            raise httpx.ConnectError("offline")

    coordinator = UpdateCoordinator(
        installation_provider=lambda: Installation(
            mode=InstallMode.PYPI,
            current_version="1.5.4",
            package_name="deeptutor",
        ),
        release_provider=OfflineReleases(),
    )

    result = coordinator.check()

    assert result.status is UpdateStatus.FAILED
    assert result.latest_version is None
    assert result.release_url is None
    assert result.detail == "Unable to check for updates."
