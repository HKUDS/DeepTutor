"""CLI tests for skill hub commands."""

from __future__ import annotations

import io

from rich.console import Console
from typer.testing import CliRunner

from deeptutor.services.skill.hub import HubSkillRef
from deeptutor_cli.main import app

runner = CliRunner()


class FakeProvider:
    def search(self, query: str, *, limit: int = 10) -> list[HubSkillRef]:
        assert query == "stock analysis"
        return [
            HubSkillRef(
                hub="clawhub",
                slug="stock-analysis",
                owner_handle="acme",
                display_name="Stock Analysis",
                summary="Analyze stock filings",
                version="1.2.0",
            )
        ]


def test_skill_search_shows_publisher_scoped_install_refs(monkeypatch) -> None:
    import deeptutor.services.skill.hub as hub
    import deeptutor_cli.skill as skill_cli

    output = io.StringIO()
    monkeypatch.setattr(hub, "get_hub_provider", lambda _hub: FakeProvider())
    monkeypatch.setattr(
        skill_cli,
        "console",
        Console(file=output, width=120, force_terminal=False),
    )

    result = runner.invoke(app, ["skill", "search", "stock analysis"])

    assert result.exit_code == 0, result.output
    rendered = output.getvalue()
    assert "Publisher" in rendered
    assert "acme" in rendered
    assert "clawhub:acme/stock-analysis" in rendered
