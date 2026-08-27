from __future__ import annotations

import io
import json
from pathlib import Path
import sys
import threading
import time
from typing import Any

import httpx
import pytest

from deeptutor.__version__ import __version__
from deeptutor.services.version_check import (
    VersionCheckError,
    VersionCheckService,
    VersionInstallation,
    VersionUpdateError,
    VersionUpdateService,
)


def _service(
    handler,
    *,
    ttl_seconds: float = 24 * 60 * 60,
    clock_values: list[float] | None = None,
) -> tuple[VersionCheckService, list[httpx.Request]]:
    requests: list[httpx.Request] = []
    times = iter(clock_values or [1.0, 1.0, 1.0, 1.0])

    def transport(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return handler(request)

    return (
        VersionCheckService(
            ttl_seconds=ttl_seconds,
            clock=lambda: next(times),
            client_factory=lambda: httpx.AsyncClient(transport=httpx.MockTransport(transport)),
        ),
        requests,
    )


def _release_response() -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "tag_name": "v999.0.0",
            "name": "DeepTutor v999.0.0",
            "published_at": "2026-01-01T00:00:00Z",
            "html_url": "https://github.com/HKUDS/DeepTutor/releases/tag/v999.0.0",
            "body": "Fixes streaming output.\nAdds settings version checks.\n" + ("x" * 600),
        },
    )


@pytest.mark.asyncio
async def test_version_check_parses_release_and_excerpts_body() -> None:
    service, requests = _service(lambda request: _release_response())

    result = await service.check()
    latest = result.latest_release

    assert result.current_version == __version__
    assert latest is not None
    assert latest["tag_name"] == "v999.0.0"
    assert latest["html_url"].startswith("https://github.com/HKUDS/DeepTutor/")
    assert latest["update_available"] is True
    assert latest["migration_bearing"] is False
    assert latest["excerpt"].startswith("Fixes streaming output.")
    assert len(latest["excerpt"]) < 600
    assert latest["excerpt"].endswith("...")
    assert len(requests) == 1


@pytest.mark.asyncio
async def test_version_check_uses_cache_until_ttl_expires_and_force_bypasses() -> None:
    service, requests = _service(
        lambda request: _release_response(),
        clock_values=[10.0, 20.0, 100.0, 100.0],
    )

    first = await service.check()
    second = await service.check()
    assert first.cached is False
    assert second.cached is True
    assert second.checked_at == first.checked_at
    assert len(requests) == 1

    third = await service.check(force=True)
    assert third.cached is False
    assert len(requests) == 2

    fourth = await service.check()
    assert fourth.cached is True
    assert len(requests) == 2


@pytest.mark.asyncio
async def test_version_check_does_not_cache_failures() -> None:
    responses = [
        lambda request: httpx.Response(503, json={"message": "rate limited"}),
        lambda request: _release_response(),
    ]
    service, requests = _service(lambda request: responses.pop(0)(request))

    with pytest.raises(VersionCheckError, match="Unable to check for updates"):
        await service.check()
    assert service.cached_result().latest_release is None

    result = await service.check()
    assert result.latest_release is not None
    assert len(requests) == 2


@pytest.mark.asyncio
async def test_version_check_rejects_invalid_release_payload() -> None:
    service, _ = _service(lambda request: httpx.Response(200, text=json.dumps(["bad"])))

    with pytest.raises(VersionCheckError, match="Unable to check for updates"):
        await service.check()


@pytest.mark.asyncio
async def test_version_check_refetches_after_ttl_expires() -> None:
    service, requests = _service(
        lambda request: _release_response(),
        ttl_seconds=10,
        clock_values=[1.0, 12.0, 12.0],
    )

    first = await service.check()
    second = await service.check()

    assert first.cached is False
    assert second.cached is False
    assert len(requests) == 2


@pytest.mark.asyncio
async def test_version_check_rejects_non_http_release_url() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"tag_name": "v2.0.0", "html_url": "javascript:x"})

    service, _ = _service(handler)

    with pytest.raises(VersionCheckError, match="Unable to check for updates"):
        await service.check()


@pytest.mark.asyncio
async def test_version_check_flags_migration_bearing_release() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "tag_name": "v999.0.0",
                "html_url": "https://github.com/HKUDS/DeepTutor/releases/tag/v999.0.0",
                "body": "Run migration before upgrading.",
            },
        )

    service, _ = _service(handler)

    result = await service.check()

    assert result.latest_release is not None
    assert result.latest_release["migration_bearing"] is True


class _FakeProcess:
    def __init__(self, output: str = "Installing collected packages\n") -> None:
        self.stdout = io.StringIO(output)
        self.argv: list[str] | None = None
        self.env: dict[str, str] | None = None

    def wait(self) -> int:
        return 0


class _VerboseFakeProcess(_FakeProcess):
    def __init__(self) -> None:
        super().__init__(output="\n".join(f"output {index}" for index in range(250)))


def _next_version() -> str:
    major = int(__version__.split(".")[0])
    return f"{major + 1}.0.0"


def _update_service(
    tmp_path: Path,
    *,
    process_factory=None,
) -> tuple[VersionUpdateService, list[list[str]], list[dict[str, str]]]:
    argv_seen: list[list[str]] = []
    env_seen: list[dict[str, str]] = []
    factory = process_factory
    if factory is None:

        def factory(*args, **kwargs):  # noqa: ANN002, ANN003
            argv_seen.append(args[0])
            env_seen.append(kwargs["env"])
            return _FakeProcess()

    service = VersionUpdateService(
        installation=VersionInstallation(
            mode="pypi",
            update_supported=True,
            command="pip install -U deeptutor",
            reason="",
        ),
        process_factory=factory,
        history_path=tmp_path / "version_updates.json",
        installed_version=lambda: _next_version(),
    )
    return service, argv_seen, env_seen


def _wait_until_done(service: VersionUpdateService) -> None:
    for _ in range(100):
        if service.status().state != "running":
            return
        time.sleep(0.01)
    raise AssertionError("version update did not finish")


def test_version_update_uses_fixed_pip_argv_and_records_previous_version(
    tmp_path: Path,
) -> None:
    service, argv_seen, env_seen = _update_service(tmp_path)
    target = _next_version()

    started = service.start_update(target_version=f"v{target}")
    _wait_until_done(service)
    finished = service.status()

    assert started.target_version == target
    assert argv_seen == [
        [
            sys.executable,
            "-m",
            "pip",
            "install",
            "--no-input",
            "--disable-pip-version-check",
            "--upgrade",
            f"deeptutor=={target}",
        ]
    ]
    assert env_seen[0]["PIP_DISABLE_PIP_VERSION_CHECK"] == "1"
    assert finished.state == "done"
    assert finished.restart_required is True
    assert finished.previous_version == __version__
    assert finished.installed_version == target
    assert finished.lines[0].startswith("$ ")
    assert service.history() == {
        "previous_version": __version__,
        "installed_version": target,
        "target_version": target,
        "updated_at": service.history()["updated_at"],
    }


def test_version_update_refuses_unsupported_installations() -> None:
    service = VersionUpdateService(
        installation=VersionInstallation(
            mode="docker",
            update_supported=False,
            command="docker pull ghcr.io/hkuds/deeptutor:latest",
            reason="Replace the container.",
        ),
        installed_version=lambda: __version__,
    )

    with pytest.raises(VersionUpdateError, match="Replace the container"):
        service.start_update(target_version=_next_version())


def test_version_update_refuses_older_or_invalid_target() -> None:
    service = VersionUpdateService(
        installation=VersionInstallation(
            mode="pypi",
            update_supported=True,
            command="pip install -U deeptutor",
            reason="",
        ),
        installed_version=lambda: __version__,
    )

    with pytest.raises(VersionUpdateError, match="invalid version"):
        service.start_update(target_version="development")
    with pytest.raises(VersionUpdateError, match="No newer"):
        service.start_update(target_version="0.0.1")


def test_version_update_launch_failure_returns_failed_state(tmp_path: Path) -> None:
    launch = threading.Event()

    def factory(*args, **kwargs):  # noqa: ANN002, ANN003
        launch.set()
        raise OSError("pip unavailable")

    service, _, _ = _update_service(tmp_path, process_factory=factory)

    result = service.start_update(target_version=_next_version())

    assert launch.is_set()
    assert result.state == "failed"
    assert "pip unavailable" in result.message


def test_version_update_output_is_bounded(tmp_path: Path) -> None:
    service, _, _ = _update_service(
        tmp_path,
        process_factory=lambda *args, **kwargs: _VerboseFakeProcess(),
    )

    service.start_update(target_version=_next_version())
    _wait_until_done(service)

    assert len(service.status().lines) <= 201
