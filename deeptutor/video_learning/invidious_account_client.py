"""HTTP boundary for the Invidious account API."""

from __future__ import annotations

import json
from typing import Any

import httpx

from deeptutor.video_learning.service import TimedMediaError


class InvidiousTransportError(RuntimeError):
    """The Invidious instance could not be reached."""


def bearer_token(token: dict[str, Any]) -> str:
    return json.dumps(token, ensure_ascii=False, separators=(",", ":"))


async def request_preferences(*, api_base_url: str, token: dict[str, Any]) -> dict[str, Any]:
    async with httpx.AsyncClient(timeout=15.0, follow_redirects=False) as client:
        try:
            response = await client.get(
                f"{api_base_url}/api/v1/auth/preferences",
                headers={"Authorization": f"Bearer {bearer_token(token)}"},
            )
        except httpx.HTTPError as exc:
            raise TimedMediaError("Invidious account verification request failed.") from exc
    if response.status_code != 200:
        raise TimedMediaError(
            f"Invidious account verification failed with HTTP {response.status_code}."
        )
    try:
        preferences = response.json()
    except ValueError as exc:
        raise TimedMediaError("Invidious returned invalid account preferences.") from exc
    if not isinstance(preferences, dict):
        raise TimedMediaError("Invidious returned invalid account preferences.")
    return preferences


async def revoke_token(*, api_base_url: str, token: dict[str, Any]) -> None:
    try:
        async with httpx.AsyncClient(timeout=15.0, follow_redirects=False) as client:
            response = await client.post(
                f"{api_base_url}/api/v1/auth/tokens/unregister",
                headers={"Authorization": f"Bearer {bearer_token(token)}"},
                json={"session": token["session"]},
            )
    except httpx.HTTPError as exc:
        raise InvidiousTransportError from exc
    if response.status_code < 200 or response.status_code >= 300:
        raise TimedMediaError(
            f"Invidious account disconnection failed with HTTP {response.status_code}."
        )


__all__ = [
    "InvidiousTransportError",
    "bearer_token",
    "request_preferences",
    "revoke_token",
]
