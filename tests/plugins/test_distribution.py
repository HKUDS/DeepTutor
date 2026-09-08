"""Reviewed catalog artifact download and install handoff tests."""

from __future__ import annotations

import hashlib
from pathlib import Path
from types import SimpleNamespace

import httpx
import pytest

from deeptutor.plugins.distribution import (
    CatalogArtifactDownloader,
    CatalogInstallManager,
    PluginDistributionError,
)


def _artifact(payload: bytes) -> SimpleNamespace:
    return SimpleNamespace(
        url="https://artifacts.example.com/example-1.0.0.whl",
        size_bytes=len(payload),
        sha256=hashlib.sha256(payload).hexdigest(),
    )


def _client(response: httpx.Response) -> httpx.Client:
    return httpx.Client(
        transport=httpx.MockTransport(lambda request: response),
        follow_redirects=False,
    )


def test_downloader_verifies_reviewed_size_and_digest(tmp_path: Path) -> None:
    payload = b"valid-wheel-bytes"
    downloader = CatalogArtifactDownloader(
        client_factory=lambda timeout: _client(
            httpx.Response(
                200,
                content=payload,
                headers={"content-length": str(len(payload))},
            )
        )
    )

    result = downloader.download(_artifact(payload), destination_dir=tmp_path)

    assert result.path.read_bytes() == payload
    assert result.path.suffix == ".whl"
    assert result.sha256 == hashlib.sha256(payload).hexdigest()
    assert result.size_bytes == len(payload)


def test_downloader_rejects_redirect_and_declared_size_mismatch(
    tmp_path: Path,
) -> None:
    redirect = CatalogArtifactDownloader(
        client_factory=lambda timeout: _client(
            httpx.Response(302, headers={"location": "https://other.example.com/artifact.whl"})
        )
    )
    size_mismatch = CatalogArtifactDownloader(
        client_factory=lambda timeout: _client(
            httpx.Response(200, content=b"12345", headers={"content-length": "5"})
        )
    )
    artifact = _artifact(b"1234")

    with pytest.raises(PluginDistributionError, match="redirects are not allowed"):
        redirect.download(artifact, destination_dir=tmp_path)
    with pytest.raises(
        PluginDistributionError, match="Content-Length does not match reviewed size"
    ):
        size_mismatch.download(artifact, destination_dir=tmp_path)
    assert list(tmp_path.iterdir()) == []


def test_downloader_rejects_body_size_or_digest_mismatch_and_cleans(
    tmp_path: Path,
) -> None:
    artifact = _artifact(b"1234")
    oversized_response = httpx.Response(200, content=b"12345")
    oversized_response.headers["content-length"] = "4"
    oversized = CatalogArtifactDownloader(
        client_factory=lambda timeout: _client(oversized_response)
    )
    corrupt = CatalogArtifactDownloader(
        client_factory=lambda timeout: _client(httpx.Response(200, content=b"5678"))
    )

    with pytest.raises(PluginDistributionError, match="exceeds reviewed size"):
        oversized.download(artifact, destination_dir=tmp_path)
    with pytest.raises(PluginDistributionError, match="SHA-256"):
        corrupt.download(artifact, destination_dir=tmp_path)
    assert list(tmp_path.iterdir()) == []


def test_catalog_install_uses_lifecycle_after_verified_download(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    artifact = _artifact(b"wheel")
    calls: list[tuple[Path, str]] = []

    class FakeLifecycle:
        def install(self, path, *, expected_sha256, allow_reinstall=False):
            calls.append((path, expected_sha256))
            assert path.is_file()
            return SimpleNamespace(
                plugin_id="org.author.example",
                version="1.0.0",
                action="installed",
                artifact_sha256=expected_sha256,
                venv_path=tmp_path / "venv",
            )

    def fake_resolve(plugin_id, version, *, allow_deprecated, **kwargs):
        assert (plugin_id, version, allow_deprecated) == (
            "org.author.example",
            "1.0.0",
            True,
        )
        return SimpleNamespace(artifact=artifact)

    monkeypatch.setattr("deeptutor.plugins.distribution.resolve_catalog_entry", fake_resolve)

    result = CatalogInstallManager(
        downloader_factory=lambda: CatalogArtifactDownloader(
            client_factory=lambda timeout: _client(httpx.Response(200, content=b"wheel"))
        ),
        lifecycle_factory=FakeLifecycle,
    ).install(
        "org.author.example",
        version="1.0.0",
        allow_deprecated=True,
    )

    assert result.artifact_url == artifact.url
    assert len(calls) == 1
    assert calls[0][1] == artifact.sha256


def test_failed_catalog_download_never_reaches_lifecycle() -> None:
    class FailedDownloader:
        def download(self, artifact, *, destination_dir, timeout_seconds):
            raise PluginDistributionError("catalog artifact download failed")

    class UnexpectedLifecycle:
        def install(self, *args, **kwargs):
            raise AssertionError("download failure must not reach lifecycle")

    with pytest.raises(PluginDistributionError):
        CatalogInstallManager(
            downloader_factory=FailedDownloader,
            lifecycle_factory=UnexpectedLifecycle,
        ).install("org.author.example")
