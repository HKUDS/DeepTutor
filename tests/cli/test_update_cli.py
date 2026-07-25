from __future__ import annotations

import httpx
from typer.testing import CliRunner

from deeptutor.__version__ import __version__
from deeptutor_cli.main import app


def test_update_without_check_does_not_run_an_update(monkeypatch) -> None:
    def unexpected_get(self, url: str) -> httpx.Response:
        raise AssertionError("update command should not access the network")

    monkeypatch.setattr(httpx.Client, "get", unexpected_get)

    result = CliRunner().invoke(app, ["update"])

    assert result.exit_code == 2
    assert "Use --check" in result.output


def test_update_check_reports_the_latest_stable_release(monkeypatch) -> None:
    def fake_get(self, url: str) -> httpx.Response:
        request = httpx.Request("GET", url)
        return httpx.Response(
            200,
            request=request,
            json={
                "tag_name": "v1.6.0",
                "html_url": ("https://github.com/HKUDS/DeepTutor/releases/tag/v1.6.0"),
                "draft": False,
                "prerelease": False,
            },
        )

    monkeypatch.setattr(httpx.Client, "get", fake_get)

    result = CliRunner().invoke(app, ["update", "--check"])

    assert result.exit_code == 0, result.output
    assert "Installation: source_web" in result.output
    assert f"Current version: {__version__}" in result.output
    assert "Latest stable: 1.6.0" in result.output
    assert "Status: update available" in result.output
    assert "Automatic update: yes" in result.output
