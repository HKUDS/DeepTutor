from __future__ import annotations

import httpx

from deeptutor.update import (
    HttpReleaseProvider,
    Installation,
    InstallMode,
)


def test_pypi_release_lookup_ignores_prereleases_and_yanked_files() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url == "https://pypi.org/pypi/deeptutor/json"
        return httpx.Response(
            200,
            json={
                "releases": {
                    "1.5.5": [{"yanked": False}],
                    "1.6.0rc1": [{"yanked": False}],
                    "1.6.0": [{"yanked": True}],
                }
            },
        )

    provider = HttpReleaseProvider(client=httpx.Client(transport=httpx.MockTransport(handler)))

    release = provider.latest(
        Installation(
            mode=InstallMode.PYPI,
            current_version="1.5.4",
            package_name="deeptutor",
        )
    )

    assert release.version == "1.5.5"
    assert release.release_url.endswith("/releases/tag/v1.5.5")


def test_source_release_lookup_uses_the_latest_stable_github_release() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url == ("https://api.github.com/repos/HKUDS/DeepTutor/releases/latest")
        return httpx.Response(
            200,
            json={
                "tag_name": "v1.6.0",
                "html_url": ("https://github.com/HKUDS/DeepTutor/releases/tag/v1.6.0"),
                "draft": False,
                "prerelease": False,
            },
        )

    provider = HttpReleaseProvider(client=httpx.Client(transport=httpx.MockTransport(handler)))

    release = provider.latest(
        Installation(
            mode=InstallMode.SOURCE_WEB,
            current_version="1.5.4",
            package_name="deeptutor",
        )
    )

    assert release.version == "1.6.0"
    assert release.release_url.endswith("/releases/tag/v1.6.0")
