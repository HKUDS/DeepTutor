from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest

from deeptutor.services import app_update
from deeptutor.services.app_update import UpdateJobStore, VersionCheckError, VersionCheckService


def _client_factory(payload: dict, *, status_code: int = 200):
    def handler(_request: httpx.Request) -> httpx.Response:
        return httpx.Response(status_code, json=payload)

    return lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler))


def _release(**overrides: object) -> dict:
    payload = {
        "tag_name": "v1.7.0",
        "name": "DeepTutor 1.7",
        "published_at": "2026-08-30T00:00:00Z",
        "html_url": "https://github.com/HKUDS/DeepTutor/releases/tag/v1.7.0",
        "body": "A stable release.",
        "draft": False,
        "prerelease": False,
    }
    payload.update(overrides)
    return payload


@pytest.mark.asyncio
async def test_version_check_caches_success_for_the_ttl() -> None:
    calls = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return httpx.Response(200, json=_release())

    service = VersionCheckService(
        client_factory=lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler)),
        clock=lambda: 100,
    )

    first = await service.check()
    second = await service.check()

    assert calls == 1
    assert first.cached is False
    assert second.cached is True
    assert second.release.version == "1.7.0"
    assert second.update_available is True


@pytest.mark.asyncio
async def test_version_check_falls_back_to_latest_redirect_when_api_is_rate_limited() -> None:
    requests: list[tuple[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append((request.method, str(request.url)))
        if request.url.host == "api.github.com":
            return httpx.Response(403, json={"message": "API rate limit exceeded"})
        return httpx.Response(
            302,
            headers={"location": "https://github.com/HKUDS/DeepTutor/releases/tag/v1.6.1"},
        )

    service = VersionCheckService(
        client_factory=lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )

    result = await service.check()

    assert requests == [
        ("GET", app_update.GITHUB_LATEST_RELEASE_URL),
        ("HEAD", app_update.GITHUB_LATEST_RELEASE_WEB_URL),
    ]
    assert result.release.version == "1.6.1"
    assert result.release.url == "https://github.com/HKUDS/DeepTutor/releases/tag/v1.6.1"
    assert result.update_available is False


@pytest.mark.asyncio
async def test_version_check_rejects_untrusted_latest_redirect() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "api.github.com":
            return httpx.Response(403, json={"message": "API rate limit exceeded"})
        return httpx.Response(302, headers={"location": "https://example.com/tag/v9.9.9"})

    service = VersionCheckService(
        client_factory=lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler)),
    )

    with pytest.raises(VersionCheckError, match="invalid URL"):
        await service.check()


@pytest.mark.asyncio
async def test_version_check_rejects_prereleases_and_untrusted_urls() -> None:
    prerelease = VersionCheckService(
        client_factory=_client_factory(_release(prerelease=True)),
    )
    bad_url = VersionCheckService(
        client_factory=_client_factory(_release(html_url="https://example.com/v1.7.0")),
    )

    with pytest.raises(VersionCheckError):
        await prerelease.check()
    with pytest.raises(VersionCheckError):
        await bad_url.check()


@pytest.mark.asyncio
async def test_release_marks_migration_notes() -> None:
    service = VersionCheckService(
        client_factory=_client_factory(_release(body="Breaking changes: run migration first.")),
    )

    result = await service.check()

    assert result.release.migration_warning is True


@pytest.mark.asyncio
async def test_release_excerpt_is_clean_plain_text() -> None:
    service = VersionCheckService(
        client_factory=_client_factory(
            _release(
                body=(
                    "# DeepTutor release notes\n\n"
                    "**Release Date:** 2026.08.30\n\n"
                    "Use the [new updater](https://example.com) with **one confirmation**."
                )
            )
        ),
    )

    result = await service.check()

    assert result.release.excerpt == "Use the new updater with one confirmation."


def test_detect_installation_keeps_source_and_docker_host_managed(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    monkeypatch.setattr(app_update, "_running_in_container", lambda: True)
    assert app_update.detect_installation().mode == "docker"

    monkeypatch.setattr(app_update, "_running_in_container", lambda: False)
    monkeypatch.setattr(app_update, "_running_from_source_checkout", lambda: False)
    monkeypatch.setattr(
        app_update,
        "_distribution_direct_url",
        lambda: {"dir_info": {"editable": True}},
    )
    assert app_update.detect_installation().mode == "source"

    monkeypatch.setattr(app_update, "_distribution_direct_url", lambda: {})
    monkeypatch.setattr(app_update.sys, "prefix", str(tmp_path / "venv"))
    monkeypatch.setattr(app_update.sys, "base_prefix", str(tmp_path / "base"))
    installation = app_update.detect_installation()
    assert installation.mode == "pypi"
    assert installation.automatic_update is True


def test_detect_installation_prefers_source_checkout_when_metadata_is_shadowed(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    checkout_root = tmp_path / "DeepTutor"
    module_path = checkout_root / "deeptutor" / "services" / "app_update.py"
    module_path.parent.mkdir(parents=True)
    module_path.touch()
    (checkout_root / ".git").mkdir()
    (checkout_root / "pyproject.toml").write_text(
        '[project]\nname = "deeptutor"\n',
        encoding="utf-8",
    )

    monkeypatch.setattr(app_update, "__file__", str(module_path))
    monkeypatch.setattr(app_update, "_running_in_container", lambda: False)
    monkeypatch.setattr(app_update, "_distribution_direct_url", lambda: {})
    monkeypatch.setattr(app_update.sys, "prefix", str(tmp_path / "venv"))
    monkeypatch.setattr(app_update.sys, "base_prefix", str(tmp_path / "base"))

    installation = app_update.detect_installation()

    assert installation.mode == "source"
    assert installation.automatic_update is False
    assert installation.command == "git pull && pip install -e ."


def test_update_job_store_persists_trusted_lifecycle(tmp_path: Path) -> None:
    store = UpdateJobStore(tmp_path / "update")
    job = store.create(current_version="1.6.1", target_version="1.7.0")
    home = tmp_path / "home"

    handoff = store.prepare_handoff(
        job.id,
        home=home,
        restart_argv=["start", "--home", str(home.resolve())],
    )
    running = store.mark_running(job.id)
    restarting = store.mark_restarting(job.id)
    succeeded = store.mark_succeeded(job.id)

    assert handoff.status == "handoff"
    assert running.started_at
    assert restarting.restart_count == 1
    assert succeeded.status == "succeeded"
    assert not store.active_path.exists()


def test_update_job_rejects_tampered_restart_arguments(tmp_path: Path) -> None:
    store = UpdateJobStore(tmp_path / "update")
    job = store.create(current_version="1.6.1", target_version="1.7.0")
    home = tmp_path / "home"

    with pytest.raises(ValueError, match="Invalid restart arguments"):
        store.prepare_handoff(
            job.id,
            home=home,
            restart_argv=["start", "--home", str(home.resolve()), "--port", "9999"],
        )


def test_launcher_available_uses_the_read_only_process_probe(monkeypatch) -> None:
    probed: list[int] = []
    monkeypatch.setenv(app_update.LAUNCHER_PID_ENV, "4242")
    monkeypatch.setattr(
        app_update,
        "is_process_alive",
        lambda pid: probed.append(pid) or True,
    )

    assert app_update.launcher_available() is True
    assert probed == [4242]
