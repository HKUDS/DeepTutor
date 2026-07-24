from pathlib import Path
import unittest

from typer.testing import CliRunner

from deeptutor_cli import provider_cmd
from deeptutor_cli.main import app

ROOT = Path(__file__).resolve().parents[2]
PROVIDER_CMD = (ROOT / "deeptutor_cli" / "provider_cmd.py").read_text(encoding="utf-8")
CLI_README = (ROOT / "deeptutor_cli" / "README.md").read_text(encoding="utf-8")
ROOT_README = (ROOT / "README.md").read_text(encoding="utf-8")


class ProviderCliDocsContractTest(unittest.TestCase):
    def test_provider_contract_describes_copilot_as_validation_not_oauth_login(self) -> None:
        self.assertIn(
            'help="Provider: openai-codex (OAuth login) | github-copilot (validate existing Copilot auth)"',
            PROVIDER_CMD,
        )
        self.assertIn('"""Authenticate or validate provider access."""', PROVIDER_CMD)
        self.assertIn("GitHub Copilot auth validation succeeded.", PROVIDER_CMD)
        self.assertIn("GitHub Copilot auth validation failed:", PROVIDER_CMD)
        self.assertNotIn("OAuth provider: openai-codex | github-copilot", PROVIDER_CMD)
        self.assertNotIn("GitHub Copilot OAuth authentication succeeded.", PROVIDER_CMD)

    def test_readmes_match_the_cli_contract(self) -> None:
        self.assertIn(
            "Provider auth (`openai-codex` OAuth login; `github-copilot` validates an existing Copilot auth session)",
            ROOT_README,
        )
        self.assertIn(
            "deeptutor provider login github-copilot    # 校验现有 GitHub Copilot 认证是否可用",
            CLI_README,
        )
        self.assertNotIn("OAuth login (`openai-codex`, `github-copilot`)", ROOT_README)


class _FakeCliCodexService:
    def __init__(self) -> None:
        self.cancelled = False

    async def start_login(self) -> dict[str, object]:
        return {
            "operation_id": "operation-1",
            "authorize_url": "https://auth.openai.com/oauth/authorize?state=opaque",
            "expires_in": 300,
        }

    def public_status(self) -> dict[str, object]:
        return {
            "connection": "connected",
            "operation_state": "completed",
            "active_model": "gpt-5.6-sol",
            "error_code": None,
        }

    async def cancel_login(self) -> dict[str, object]:
        self.cancelled = True
        return self.public_status()


def test_openai_codex_cli_does_not_import_codex_cli_credentials() -> None:
    assert "oauth_cli_kit" not in PROVIDER_CMD
    assert "get_codex_oauth_service" in PROVIDER_CMD
    assert "~/.codex" not in PROVIDER_CMD
    assert "Path.home" not in PROVIDER_CMD


def test_cli_opens_authorize_url_and_waits_for_completion(monkeypatch) -> None:
    service = _FakeCliCodexService()
    urls: list[str] = []
    monkeypatch.setattr(
        provider_cmd,
        "get_codex_oauth_service",
        lambda: service,
        raising=False,
    )
    monkeypatch.setattr(
        provider_cmd.webbrowser,
        "open",
        lambda url: urls.append(url) or True,
        raising=False,
    )

    result = CliRunner().invoke(
        app,
        ["provider", "login", "openai-codex"],
    )

    assert urls == ["https://auth.openai.com/oauth/authorize?state=opaque"]
    assert result.exit_code == 0
    assert "DeepTutor 私有凭据" in result.stdout
    assert "gpt-5.6-sol" in result.stdout


if __name__ == "__main__":
    unittest.main()
