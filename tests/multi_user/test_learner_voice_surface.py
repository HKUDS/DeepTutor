"""Learner access to the chat voice endpoints (#2437).

The voice router is shared infrastructure: its module contract says any
authenticated user may call it. But the endpoints are mounted with the
"learning" guard, so a learner account granted only "chat" used to get a
403 from the chat composer's Record voice / Play aloud buttons. The
surface mapping now covers the two POST endpoints (see
test_learning_surface_map.py for the exact-match allowlist).
"""

from __future__ import annotations

from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
import pytest


@pytest.fixture()
def learner_voice_client(monkeypatch, mu_isolated_root):
    """Voice router behind the real auth + learning-surface guards."""
    from deeptutor.api.routers import auth, voice
    from deeptutor.multi_user import learning_access
    from deeptutor.services.auth import TokenPayload

    monkeypatch.setattr(auth, "AUTH_ENABLED", True)
    monkeypatch.setattr(
        auth,
        "decode_token",
        lambda _token: TokenPayload(username="student", role="user", user_id="u_student"),
    )

    def use_surfaces(*surfaces: str) -> None:
        monkeypatch.setattr(
            learning_access,
            "learning_policy_for_user",
            lambda _user_id, **_kwargs: {"allowed_surfaces": list(surfaces)},
        )

    calls: list[tuple[str, object]] = []

    async def fake_tts(text: str, **_kwargs):
        calls.append(("tts", text))
        return b"audio-bytes", "audio/mpeg"

    async def fake_stt(audio: bytes, **_kwargs):
        calls.append(("stt", audio))
        return "transcribed"

    monkeypatch.setattr(voice, "synthesize_speech", fake_tts)
    monkeypatch.setattr(voice, "transcribe_audio", fake_stt)

    app = FastAPI()
    app.include_router(
        voice.router,
        prefix="/api/voice",
        dependencies=[Depends(auth.require_learning_surface)],
    )
    return TestClient(app), use_surfaces, calls


_HEADERS = {"Authorization": "Bearer student-token"}


@pytest.mark.parametrize("surfaces", [("chat",), ("chat", "reading")])
def test_chat_learner_can_read_aloud(learner_voice_client, surfaces) -> None:
    client, use_surfaces, calls = learner_voice_client
    use_surfaces(*surfaces)

    response = client.post("/api/voice/tts", json={"text": "hello"}, headers=_HEADERS)

    assert response.status_code == 200, response.text
    assert response.content == b"audio-bytes"
    assert calls == [("tts", "hello")]


@pytest.mark.parametrize("surfaces", [("chat",), ("chat", "reading")])
def test_chat_learner_can_record_voice(learner_voice_client, surfaces) -> None:
    client, use_surfaces, calls = learner_voice_client
    use_surfaces(*surfaces)

    response = client.post(
        "/api/voice/stt",
        files={"file": ("clip.webm", b"audio", "audio/webm")},
        headers=_HEADERS,
    )

    assert response.status_code == 200, response.text
    assert response.json() == {"text": "transcribed"}
    assert calls == [("stt", b"audio")]


@pytest.mark.parametrize("surfaces", [("reading",), ("books",)])
def test_non_chat_learner_stays_denied(learner_voice_client, surfaces) -> None:
    client, use_surfaces, calls = learner_voice_client
    use_surfaces(*surfaces)

    response = client.post("/api/voice/tts", json={"text": "hello"}, headers=_HEADERS)

    assert response.status_code == 403, response.text
    assert "cannot use the chat surface" in response.json()["detail"]
    assert calls == []
