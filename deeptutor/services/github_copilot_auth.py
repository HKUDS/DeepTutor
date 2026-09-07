"""GitHub device login and Copilot token exchange."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from contextlib import suppress
from dataclasses import dataclass
import os
import time
from typing import Any
import webbrowser

import httpx

DEFAULT_GITHUB_DEVICE_CODE_URL = "https://github.com/login/device/code"
DEFAULT_GITHUB_ACCESS_TOKEN_URL = "https://github.com/login/oauth/access_token"
DEFAULT_GITHUB_USER_URL = "https://api.github.com/user"
DEFAULT_COPILOT_TOKEN_URL = "https://api.github.com/copilot_internal/v2/token"
DEFAULT_COPILOT_BASE_URL = "https://api.githubcopilot.com"
GITHUB_COPILOT_CLIENT_ID = "Iv1.b507a08c87ecfe98"
GITHUB_COPILOT_SCOPE = "read:user"
TOKEN_FILENAME = "github-copilot.json"
TOKEN_APP_NAME = "nanobot"
USER_AGENT = "DeepTutor/1"
EDITOR_VERSION = "vscode/1.99.0"
EDITOR_PLUGIN_VERSION = "copilot-chat/0.26.0"
_LONG_LIVED_TOKEN_SECONDS = 315_360_000


@dataclass(frozen=True)
class CopilotAccess:
    token: str
    expires_at: float
    api_base: str


def _resolve(env_var: str, default: str) -> str:
    value = os.environ.get(env_var)
    return value.strip() if value and value.strip() else default


def get_github_copilot_storage() -> Any:
    try:
        from oauth_cli_kit.storage import FileTokenStorage
    except ImportError as exc:
        raise RuntimeError(
            "oauth-cli-kit is required for GitHub Copilot login. "
            "Install the DeepTutor CLI dependencies first."
        ) from exc
    # Keep compatibility with tokens created by nanobot, where this integration
    # originated, so users do not have to sign in twice.
    return FileTokenStorage(
        token_filename=TOKEN_FILENAME,
        app_name=TOKEN_APP_NAME,
        import_codex_cli=False,
    )


def load_github_token() -> Any | None:
    token = get_github_copilot_storage().load()
    if not token or not getattr(token, "access", None):
        return None
    return token


def _github_headers(token: str) -> dict[str, str]:
    return {
        "Authorization": f"token {token}",
        "Accept": "application/json",
        "User-Agent": USER_AGENT,
        "Editor-Version": EDITOR_VERSION,
        "Editor-Plugin-Version": EDITOR_PLUGIN_VERSION,
    }


async def login_github_copilot(
    print_fn: Callable[[str], None] | None = None,
) -> Any:
    """Run GitHub's device flow and persist the resulting OAuth token."""
    try:
        from oauth_cli_kit.models import OAuthToken
    except ImportError as exc:
        raise RuntimeError(
            "oauth-cli-kit is required for GitHub Copilot login. "
            "Install the DeepTutor CLI dependencies first."
        ) from exc

    printer = print_fn or print
    timeout = httpx.Timeout(20.0, connect=20.0)
    client_id = _resolve("DEEPTUTOR_GITHUB_COPILOT_CLIENT_ID", GITHUB_COPILOT_CLIENT_ID)
    device_code_url = _resolve("DEEPTUTOR_GITHUB_DEVICE_CODE_URL", DEFAULT_GITHUB_DEVICE_CODE_URL)
    access_token_url = _resolve(
        "DEEPTUTOR_GITHUB_ACCESS_TOKEN_URL", DEFAULT_GITHUB_ACCESS_TOKEN_URL
    )
    user_url = _resolve("DEEPTUTOR_GITHUB_USER_URL", DEFAULT_GITHUB_USER_URL)

    async with httpx.AsyncClient(
        timeout=timeout,
        follow_redirects=True,
        trust_env=True,
    ) as client:
        response = await client.post(
            device_code_url,
            headers={"Accept": "application/json", "User-Agent": USER_AGENT},
            data={"client_id": client_id, "scope": GITHUB_COPILOT_SCOPE},
        )
        response.raise_for_status()
        payload = response.json()

        device_code = str(payload["device_code"])
        user_code = str(payload["user_code"])
        verification_url = str(
            payload.get("verification_uri") or payload.get("verification_uri_complete") or ""
        )
        verification_complete = str(payload.get("verification_uri_complete") or verification_url)
        interval = max(1, int(payload.get("interval") or 5))
        expires_in = int(payload.get("expires_in") or 900)

        printer(f"Open: {verification_url}")
        printer(f"Code: {user_code}")
        if verification_complete:
            with suppress(Exception):
                webbrowser.open(verification_complete)

        deadline = time.monotonic() + expires_in
        current_interval = interval
        access_token = ""
        token_expires_in = _LONG_LIVED_TOKEN_SECONDS
        while time.monotonic() < deadline:
            await asyncio.sleep(current_interval)
            poll = await client.post(
                access_token_url,
                headers={"Accept": "application/json", "User-Agent": USER_AGENT},
                data={
                    "client_id": client_id,
                    "device_code": device_code,
                    "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
                },
            )
            poll.raise_for_status()
            poll_payload = poll.json()
            access_token = str(poll_payload.get("access_token") or "")
            if access_token:
                token_expires_in = int(poll_payload.get("expires_in") or _LONG_LIVED_TOKEN_SECONDS)
                break

            error = poll_payload.get("error")
            if error == "authorization_pending":
                continue
            if error == "slow_down":
                current_interval += 5
                continue
            if error == "expired_token":
                raise RuntimeError("GitHub device code expired. Please run login again.")
            if error == "access_denied":
                raise RuntimeError("GitHub device login was denied.")
            if error:
                raise RuntimeError(str(poll_payload.get("error_description") or error))
        else:
            raise RuntimeError("GitHub device login timed out.")

        user = await client.get(
            user_url,
            headers={
                "Authorization": f"Bearer {access_token}",
                "Accept": "application/vnd.github+json",
                "User-Agent": USER_AGENT,
            },
        )
        user.raise_for_status()
        user_payload = user.json()
        account_id = user_payload.get("login") or user_payload.get("id")

    token = OAuthToken(
        access=access_token,
        refresh="",
        expires=int((time.time() + token_expires_in) * 1000),
        account_id=str(account_id) if account_id else None,
    )
    get_github_copilot_storage().save(token)
    return token


async def exchange_copilot_token(github_token: str | None = None) -> CopilotAccess:
    """Exchange a GitHub OAuth token for a short-lived Copilot API token."""
    if not github_token:
        stored = load_github_token()
        github_token = str(getattr(stored, "access", "") or "")
    if not github_token:
        raise RuntimeError(
            "GitHub Copilot is not logged in. Run: deeptutor provider login github-copilot"
        )

    async with httpx.AsyncClient(
        timeout=httpx.Timeout(20.0, connect=20.0),
        follow_redirects=True,
        trust_env=True,
    ) as client:
        response = await client.get(
            _resolve("DEEPTUTOR_COPILOT_TOKEN_URL", DEFAULT_COPILOT_TOKEN_URL),
            headers=_github_headers(github_token),
        )
        response.raise_for_status()
        payload = response.json()

    token = str(payload.get("token") or "")
    if not token:
        raise RuntimeError("GitHub Copilot token exchange returned no token.")
    expires_at = payload.get("expires_at")
    if not isinstance(expires_at, (int, float)):
        expires_at = time.time() + int(payload.get("refresh_in") or 1500)
    endpoints = payload.get("endpoints")
    api_base = (
        str(endpoints.get("api"))
        if isinstance(endpoints, dict) and endpoints.get("api")
        else _resolve("DEEPTUTOR_COPILOT_BASE_URL", DEFAULT_COPILOT_BASE_URL)
    )
    return CopilotAccess(token=token, expires_at=float(expires_at), api_base=api_base)


async def list_github_copilot_models() -> list[str]:
    access = await exchange_copilot_token()
    async with httpx.AsyncClient(
        timeout=httpx.Timeout(20.0, connect=20.0),
        follow_redirects=True,
        trust_env=True,
    ) as client:
        response = await client.get(
            f"{access.api_base.rstrip('/')}/models",
            headers={
                "Authorization": f"Bearer {access.token}",
                "Accept": "application/json",
                "User-Agent": USER_AGENT,
                "Editor-Version": EDITOR_VERSION,
                "Editor-Plugin-Version": EDITOR_PLUGIN_VERSION,
            },
        )
        response.raise_for_status()
        payload = response.json()

    rows = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(rows, list):
        return []
    models: list[str] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        model_id = row.get("id")
        policy = row.get("policy")
        if (
            not isinstance(model_id, str)
            or not model_id
            or row.get("model_picker_enabled") is False
            or (isinstance(policy, dict) and policy.get("state") == "disabled")
        ):
            continue
        models.append(f"github-copilot/{model_id}")
    return list(dict.fromkeys(models))


__all__ = [
    "CopilotAccess",
    "exchange_copilot_token",
    "get_github_copilot_storage",
    "list_github_copilot_models",
    "load_github_token",
    "login_github_copilot",
]
