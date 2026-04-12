"""CLI commands for provider auth (OAuth-first providers)."""

from __future__ import annotations

import typer

from .common import maybe_run


def register(app: typer.Typer) -> None:
    @app.command("login")
    def provider_login(
        provider: str = typer.Argument(
            ...,
            help="OAuth 提供商：openai-codex | github-copilot",
        ),
    ) -> None:
        """Authenticate an OAuth-backed provider."""
        key = provider.strip().lower().replace("-", "_")
        if key == "openai_codex":
            _login_openai_codex()
            return
        if key == "github_copilot":
            maybe_run(_login_github_copilot())
            return
        raise typer.BadParameter(
            f"未知提供商 `{provider}`。支持：openai-codex、github-copilot"
        )


def _login_openai_codex() -> None:
    try:
        from oauth_cli_kit import get_token, login_oauth_interactive
    except ImportError:
        typer.echo(
            "未安装 oauth_cli_kit。请安装 CLI 依赖："
            "pip install -r requirements/cli.txt"
        )
        raise typer.Exit(code=1)

    token = None
    try:
        token = get_token()
    except Exception:
        token = None
    if not (token and getattr(token, "access", None)):
        token = login_oauth_interactive(
            print_fn=typer.echo,
            prompt_fn=typer.prompt,
        )
    if not (token and getattr(token, "access", None)):
        typer.echo("OpenAI Codex OAuth 认证失败。")
        raise typer.Exit(code=1)
    typer.echo("OpenAI Codex OAuth 认证成功。")


async def _login_github_copilot() -> None:
    try:
        from litellm import acompletion
    except ImportError:
        typer.echo("未安装 litellm。请安装 CLI 依赖：pip install -r requirements/cli.txt")
        raise typer.Exit(code=1)
    try:
        await acompletion(
            model="github_copilot/gpt-4o",
            messages=[{"role": "user", "content": "ping"}],
            max_tokens=1,
        )
    except Exception as exc:
        typer.echo(f"GitHub Copilot OAuth 认证失败：{exc}")
        raise typer.Exit(code=1) from exc
    typer.echo("GitHub Copilot OAuth 认证成功。")
