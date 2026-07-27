"""CLI commands for provider auth and access validation."""

from __future__ import annotations

import asyncio
import webbrowser

import typer

from deeptutor.services.codex_auth import CodexAuthError, get_codex_oauth_service

from .common import maybe_run


def register(app: typer.Typer) -> None:
    @app.command("login")
    def provider_login(
        provider: str = typer.Argument(
            ...,
            help="Provider: openai-codex (OAuth login) | github-copilot (validate existing Copilot auth)",
        ),
    ) -> None:
        """Authenticate or validate provider access."""
        key = provider.strip().lower().replace("-", "_")
        if key == "openai_codex":
            maybe_run(_login_openai_codex())
            return
        if key == "github_copilot":
            maybe_run(_login_github_copilot())
            return
        raise typer.BadParameter(
            f"Unknown provider `{provider}`. Supported: openai-codex, github-copilot"
        )


async def _login_openai_codex() -> None:
    service = get_codex_oauth_service()
    try:
        started = await service.start_login()
        authorize_url = str(started["authorize_url"])
        typer.echo(f"Callback: {started['redirect_uri']}")
        typer.echo(f"Authorization URL: {authorize_url}")
        typer.echo(f"Remote server tunnel command: {started['ssh_forward_command']}")
        typer.echo(
            "Opening the OpenAI Codex sign-in in your browser; "
            "credentials are written only to DeepTutor's private directory."
        )
        if not webbrowser.open(authorize_url):
            typer.echo(f"The browser did not open automatically. Visit: {authorize_url}")

        while True:
            status = service.public_status()
            operation_state = status.get("operation_state")
            if operation_state == "completed":
                typer.echo(
                    f"OpenAI Codex sign-in succeeded. Models available: "
                    f"{status.get('model_count', 0)}."
                )
                active_model = status.get("active_model")
                if active_model:
                    typer.echo(f"Codex is the active model: {active_model}")
                else:
                    typer.echo("Select a Codex model in Settings to start using it.")
                return
            if operation_state in {"failed", "expired", "cancelled"}:
                error_code = status.get("error_code") or operation_state
                typer.echo(f"OpenAI Codex sign-in did not complete: {error_code}")
                raise typer.Exit(code=1)
            await asyncio.sleep(0.5)
    except asyncio.CancelledError:
        await service.cancel_login()
        typer.echo("Cancelled the OpenAI Codex sign-in.")
        raise typer.Exit(code=130) from None
    except CodexAuthError as exc:
        typer.echo(f"OpenAI Codex sign-in failed: {exc.public_message}")
        raise typer.Exit(code=1)


async def _login_github_copilot() -> None:
    """Validate an existing GitHub Copilot auth session via a lightweight request."""
    try:
        from openai import AsyncOpenAI
    except ImportError:
        typer.echo(
            "openai is not installed. Install CLI deps from a local checkout: "
            "python -m pip install -e ./packaging/deeptutor-cli"
        )
        raise typer.Exit(code=1)
    try:
        client = AsyncOpenAI(
            api_key="copilot",
            base_url="https://api.githubcopilot.com",
            max_retries=0,
        )
        await client.chat.completions.create(
            model="gpt-4o",
            messages=[{"role": "user", "content": "ping"}],
            max_tokens=1,
        )
    except Exception as exc:
        typer.echo(f"GitHub Copilot auth validation failed: {exc}")
        raise typer.Exit(code=1) from exc
    typer.echo("GitHub Copilot auth validation succeeded.")
