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
            help=(
                "Provider: openai-codex (OAuth login) | github-copilot "
                "(validate existing Copilot auth) | codebuddy (validate CodeBuddy SDK auth)"
            ),
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
        if key in {"codebuddy", "codebuddy_code", "workbuddy"}:
            maybe_run(_login_codebuddy())
            return
        raise typer.BadParameter(
            f"Unknown provider `{provider}`. Supported: openai-codex, github-copilot, codebuddy"
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


async def _login_codebuddy() -> None:
    """Validate CodeBuddy auth, starting an SDK login when needed."""
    from deeptutor.services.codebuddy_credentials import load_credentials, probe_account

    credentials = load_credentials()
    if credentials is not None:
        label = await probe_account(credentials)
        if label:
            typer.echo(f"CodeBuddy auth validation succeeded for {label}.")
            return

    try:
        from codebuddy_agent_sdk import authenticate, query
    except ImportError:
        typer.echo(
            "CodeBuddy is not signed in. Sign in with the CodeBuddy IDE plugin, run "
            "`codebuddy` and enter `/login`, or set CODEBUDDY_API_KEY. For in-app login "
            "install the SDK: `python -m pip install codebuddy-agent-sdk`."
        )
        raise typer.Exit(code=1)

    try:
        saw_message = False
        async for _message in query(prompt="Reply with only OK."):
            saw_message = True
        if not saw_message:
            raise RuntimeError("CodeBuddy SDK returned no messages.")
    except Exception as exc:
        if "Authentication required" not in str(exc):
            typer.echo(f"CodeBuddy auth validation failed: {exc}")
            raise typer.Exit(code=1) from exc
        typer.echo("CodeBuddy is not logged in. Starting CodeBuddy login flow ...")
        try:
            auth = await authenticate(timeout=300.0)
            if getattr(auth, "auth_url", ""):
                typer.echo(f"Open this URL to sign in: {auth.auth_url}")
                try:
                    webbrowser.open(auth.auth_url)
                except Exception:
                    pass
            result = await auth
        except Exception as login_exc:
            typer.echo(f"CodeBuddy login failed: {login_exc}")
            typer.echo("You can also run `codebuddy`, enter `/login`, or set CODEBUDDY_API_KEY.")
            raise typer.Exit(code=1) from login_exc
        userinfo = getattr(result, "userinfo", None)
        label = (
            getattr(userinfo, "user_nickname", None)
            or getattr(userinfo, "user_name", None)
            or getattr(userinfo, "user_id", None)
            or "current account"
        )
        typer.echo(f"CodeBuddy auth validation succeeded for {label}.")
        return
    typer.echo("CodeBuddy auth validation succeeded.")
