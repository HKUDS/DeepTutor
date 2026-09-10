from pathlib import Path
from types import SimpleNamespace
import unittest

import pytest
from typer.testing import CliRunner

from deeptutor_cli import provider_cmd
from deeptutor_cli.main import app

ROOT = Path(__file__).resolve().parents[2]
PROVIDER_CMD = (ROOT / "deeptutor_cli" / "provider_cmd.py").read_text(encoding="utf-8")
CLI_README = (ROOT / "deeptutor_cli" / "README.md").read_text(encoding="utf-8")
ROOT_README = (ROOT / "README.md").read_text(encoding="utf-8")


class ProviderCliDocsContractTest(unittest.TestCase):
    def test_provider_contract_describes_copilot_device_login(self) -> None:
        self.assertIn(
            '"Provider: openai-codex (OAuth login) | github-copilot "',
            PROVIDER_CMD,
        )
        self.assertIn("| codebuddy (validate CodeBuddy SDK auth)", PROVIDER_CMD)
        self.assertIn('"""Authenticate or validate provider access."""', PROVIDER_CMD)
        self.assertIn("(GitHub device login)", PROVIDER_CMD)
        self.assertIn("GitHub Copilot login succeeded for", PROVIDER_CMD)
        self.assertIn("GitHub Copilot login failed:", PROVIDER_CMD)
        self.assertIn("CodeBuddy auth validation succeeded.", PROVIDER_CMD)
        self.assertIn("CodeBuddy auth validation failed:", PROVIDER_CMD)
        self.assertIn("Starting CodeBuddy login flow", PROVIDER_CMD)
        self.assertNotIn("OAuth provider: openai-codex | github-copilot", PROVIDER_CMD)

    def test_readmes_match_the_cli_contract(self) -> None:
        self.assertIn(
            "Provider auth (`openai-codex` OAuth login; `github-copilot` GitHub device login; `codebuddy` validates CodeBuddy SDK auth and starts login when needed)",
            ROOT_README,
        )
        self.assertIn(
            "deeptutor provider login github-copilot    # 通过 GitHub 设备授权登录 Copilot",
            CLI_README,
        )
        self.assertIn(
            "deeptutor provider login codebuddy         # 校验 CodeBuddy SDK 登录；未登录时打开登录入口",
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
            "callback_port": 1457,
            "callback_forward_port": 3782,
            "redirect_uri": "http://localhost:1457/auth/callback",
            "ssh_forward_command": ("ssh -N -L 1457:127.0.0.1:3782 <ssh-user>@<server-host>"),
            "expires_in": 300,
        }

    def public_status(self) -> dict[str, object]:
        return {
            "connection": "connected",
            "operation_state": "completed",
            "active_model": "gpt-5.6-sol",
            "model_count": 7,
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
    events: list[tuple[str, str]] = []
    original_echo = provider_cmd.typer.echo

    def record_echo(message: object, *args: object, **kwargs: object) -> None:
        events.append(("echo", str(message)))
        original_echo(message, *args, **kwargs)

    monkeypatch.setattr(
        provider_cmd,
        "get_codex_oauth_service",
        lambda: service,
        raising=False,
    )
    monkeypatch.setattr(provider_cmd.typer, "echo", record_echo)
    monkeypatch.setattr(
        provider_cmd.webbrowser,
        "open",
        lambda url: events.append(("open", url)) or urls.append(url) or True,
        raising=False,
    )

    result = CliRunner().invoke(
        app,
        ["provider", "login", "openai-codex"],
    )

    assert urls == ["https://auth.openai.com/oauth/authorize?state=opaque"]
    assert result.exit_code == 0
    assert "http://localhost:1457/auth/callback" in result.stdout
    assert "https://auth.openai.com/oauth/authorize?state=opaque" in result.stdout
    assert "ssh -N -L 1457:127.0.0.1:3782 <ssh-user>@<server-host>" in result.stdout
    assert "ssh -N -L 1457:127.0.0.1:1457" not in result.stdout
    open_index = events.index(("open", "https://auth.openai.com/oauth/authorize?state=opaque"))
    output_before_open = "\n".join(message for kind, message in events[:open_index])
    assert "http://localhost:1457/auth/callback" in output_before_open
    assert "https://auth.openai.com/oauth/authorize?state=opaque" in output_before_open
    assert "ssh -N -L 1457:127.0.0.1:3782 <ssh-user>@<server-host>" in output_before_open
    assert "ssh -N -L 1457:127.0.0.1:1457" not in output_before_open
    # The CLI speaks English like every other command in this app.
    assert "private directory" in result.stdout
    assert "gpt-5.6-sol" in result.stdout


@pytest.mark.parametrize("outcome", ["success", "error", "exception", "no-models"])
def test_github_copilot_cli_runs_device_login_and_validates_access(monkeypatch, outcome) -> None:
    from deeptutor.services import github_copilot_auth
    from deeptutor.services.llm.provider_core import github_copilot_provider

    events: list[str] = []

    async def login(*, print_fn):
        print_fn("Code: ABCD-1234")
        events.append("login")
        return SimpleNamespace(account_id="octocat")

    async def models():
        return [] if outcome == "no-models" else ["github-copilot/claude-sonnet"]

    class FakeProvider:
        def __init__(self, *, default_model: str) -> None:
            events.append(default_model)

        async def chat(self, **_kwargs):
            events.append("chat")
            if outcome == "exception":
                raise RuntimeError("model disabled")
            return SimpleNamespace(
                content="model disabled" if outcome == "error" else "OK",
                finish_reason="error" if outcome == "error" else "stop",
            )

        async def aclose(self) -> None:
            events.append("close")

    monkeypatch.setattr(github_copilot_auth, "login_github_copilot", login)
    monkeypatch.setattr(github_copilot_auth, "list_github_copilot_models", models)
    monkeypatch.setattr(github_copilot_provider, "GitHubCopilotProvider", FakeProvider)

    result = CliRunner().invoke(app, ["provider", "login", "github-copilot"])

    assert result.exit_code == (0 if outcome == "success" else 1)
    assert "Code: ABCD-1234" in result.stdout
    if outcome == "success":
        assert "GitHub Copilot login succeeded for octocat." in result.stdout
        assert "Validated model access: github-copilot/claude-sonnet" in result.stdout
    else:
        assert "login succeeded" not in result.stdout
        assert "GitHub Copilot login failed:" in result.stdout
    assert events == (
        ["login"]
        if outcome == "no-models"
        else ["login", "github-copilot/claude-sonnet", "chat", "close"]
    )


if __name__ == "__main__":
    unittest.main()
