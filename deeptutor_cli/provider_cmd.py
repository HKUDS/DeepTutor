"""CLI commands for provider auth and access validation."""

from __future__ import annotations

import asyncio
from contextlib import suppress
import webbrowser

import httpx
import typer

from deeptutor.services.codex_auth import CodexAuthError, get_codex_oauth_service
from deeptutor.services.deeptutor_account import get_deeptutor_account
from deeptutor.services.deeptutor_account.client import DeepTutorAccountError

from .common import maybe_run


def register(app: typer.Typer) -> None:
    @app.command("login")
    def provider_login(
        provider: str = typer.Argument(
            ...,
            help=(
                "Provider: openai-codex (OAuth login) | github-copilot "
                "(GitHub device login) | codebuddy (validate CodeBuddy SDK auth) | "
                "deeptutor (Studio device login)"
            ),
        ),
        no_browser: bool = typer.Option(
            False, "--no-browser", help="Print the Studio sign-in code."
        ),
        base_url: str | None = typer.Option(
            None, "--base-url", help="Override the Studio gateway."
        ),
    ) -> None:
        """Authenticate or validate provider access."""
        key = provider.strip().lower().replace("-", "_")
        if key == "deeptutor":
            maybe_run(_login_deeptutor(no_browser, base_url))
            return
        if no_browser or base_url is not None:
            raise typer.BadParameter("--no-browser and --base-url are supported for deeptutor.")
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
            f"Unknown provider `{provider}`. Supported: openai-codex, github-copilot, codebuddy, deeptutor"
        )

    @app.command("status")
    def provider_status(provider: str) -> None:
        """Show the DeepTutor Studio device connection."""
        if provider.lower().strip() != "deeptutor":
            raise typer.BadParameter("Supported provider: deeptutor")
        maybe_run(_deeptutor_status())

    @app.command("logout")
    def provider_logout(provider: str) -> None:
        """Sign out of the DeepTutor Studio device connection."""
        if provider.lower().strip() != "deeptutor":
            raise typer.BadParameter("Supported provider: deeptutor")
        maybe_run(_logout_deeptutor())


async def _login_deeptutor(no_browser: bool, base_url: str | None) -> None:
    account = get_deeptutor_account()
    try:
        sign_in = await account.start(base_url)
        typer.echo(f"Open {sign_in.verification_uri}")
        typer.echo(f"Enter the device code {sign_in.user_code}")
        if not no_browser:
            with suppress(webbrowser.Error):
                webbrowser.open(sign_in.verification_uri_complete)
        try:
            access = await account.finish(sign_in)
        finally:
            with suppress(DeepTutorAccountError):
                await account.cancel(sign_in)
        await _deeptutor_status()
        try:
            models = await account.refresh_models(access)
        except DeepTutorAccountError as exc:
            if exc.error_code == "invalid_grant":
                raise
            typer.echo(f"Could not load models. {exc.message} Refresh them in Settings.", err=True)
        else:
            count = sum(item["available"] for item in models)
            typer.echo(f"Available DeepTutor models: {count}.")
            if not count:
                status = await account.status()
                typer.echo(f"Manage paid credits at {status['public_url']}/account/credits")
    except DeepTutorAccountError as exc:
        typer.echo(exc.message, err=True)
        raise typer.Exit(code=1) from None


async def _deeptutor_status() -> None:
    try:
        status = await get_deeptutor_account().status()
    except DeepTutorAccountError as exc:
        typer.echo(exc.message, err=True)
        raise typer.Exit(code=1) from None
    if status["state"] == "connected":
        typer.echo(
            f"Signed in to DeepTutor Studio as {status['user']['email']} ({status['account']['name']})."
        )
    else:
        typer.echo("DeepTutor Studio is signed out.")


async def _logout_deeptutor() -> None:
    try:
        await get_deeptutor_account().logout()
    except DeepTutorAccountError as exc:
        typer.echo(exc.message, err=True)
        raise typer.Exit(code=1) from None
    typer.echo("Signed out of DeepTutor Studio.")


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
    """Authenticate with GitHub device flow and validate Copilot access."""
    try:
        from deeptutor.services.github_copilot_auth import (
            list_github_copilot_models,
            login_github_copilot,
        )
        from deeptutor.services.llm.provider_core.github_copilot_provider import (
            validate_github_copilot_model,
        )
    except ImportError:
        typer.echo(
            "GitHub Copilot login dependencies are not installed. Install CLI deps: "
            "python -m pip install -e ./packaging/deeptutor-cli"
        )
        raise typer.Exit(code=1)
    try:
        token = await login_github_copilot(print_fn=typer.echo)
        typer.echo(
            "GitHub sign-in saved in DeepTutor's owner-private storage. Validating Copilot..."
        )
        models = await list_github_copilot_models()
        if not models:
            raise RuntimeError("No usable GitHub Copilot models are available for this account.")
        await validate_github_copilot_model(models[0])
    except (httpx.HTTPError, OSError, RuntimeError, ValueError, KeyError) as exc:
        typer.echo(f"GitHub Copilot login failed: {exc}")
        raise typer.Exit(code=1) from exc
    account = getattr(token, "account_id", None) or "current account"
    typer.echo(f"GitHub Copilot login succeeded for {account}.")
    typer.echo(f"Validated model access: {models[0]}")


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
