"""A conversation's explicit reply language survives later account defaults."""

from __future__ import annotations

from fastapi import HTTPException
from pydantic import ValidationError
import pytest

from deeptutor.api.routers import sessions as sessions_router
from deeptutor.core.turn_request import TurnRequest
from deeptutor.services.session.sqlite_store import SQLiteSessionStore
from deeptutor.services.session.turn_runtime import TurnRuntimeManager


@pytest.mark.asyncio
async def test_explicit_reply_language_stays_with_one_conversation(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    store = SQLiteSessionStore(tmp_path / "reply-language.db")
    runtime = TurnRuntimeManager(store)
    languages: list[tuple[str, bool]] = []

    async def capture_turn(execution) -> None:
        languages.append(
            (execution.payload["language"], execution.payload["_reply_language_fixed"])
        )
        await store.transition_turn(execution.turn_id, "completed")

    monkeypatch.setattr(runtime, "_run_turn", capture_turn)
    monkeypatch.setattr(sessions_router, "get_session_store", lambda: store)

    async def send(session_id: str | None, account_language: str, **extra) -> str:
        session, turn = await runtime.start_turn(
            {
                "session_id": session_id,
                "content": "Explain this concept",
                "language": account_language,
                **extra,
            }
        )
        await runtime._executions[turn["id"]].task
        return session["id"]

    # A Chinese question can be taught in French. A later English account
    # setting must not reset the conversation; a different session still uses
    # its own account default.
    session_id = await send(None, "zh", reply_language_override="fr")
    await send(session_id, "en")
    assert languages == [("fr", True), ("fr", True)]
    assert (await store.get_session(session_id))["preferences"]["reply_language_override"] == "fr"

    other_id = await send(None, "ja")
    assert other_id != session_id
    assert languages[-1] == ("ja", False)

    # Clearing the selector resumes the current account default, even if the
    # session's last effective language was French.
    await sessions_router.update_session_reply_language(
        session_id, sessions_router.SessionReplyLanguageRequest(language=None)
    )
    await send(session_id, "zh")
    assert languages[-1] == ("zh", False)
    assert (await store.get_session(session_id))["preferences"]["reply_language_override"] is None


@pytest.mark.parametrize(
    "code", ["en", "zh", "zh-tw", "ja", "ko", "es", "fr", "de", "ru", "pt", "it", "ar", "pl", "uk"]
)
def test_selector_accepts_every_supported_response_language(code: str) -> None:
    assert TurnRequest(content="hi", reply_language_override=code).reply_language_override == code
    assert sessions_router.SessionReplyLanguageRequest(language=code).language == code


@pytest.mark.parametrize("value", ["", "xx", "French", "zh-CN", "__default__"])
def test_invalid_selector_value_fails_instead_of_silently_falling_back(value: str) -> None:
    with pytest.raises(ValidationError):
        TurnRequest(content="hi", reply_language_override=value)
    with pytest.raises(ValidationError):
        sessions_router.SessionReplyLanguageRequest(language=value)


def test_omitted_selector_is_distinct_from_explicit_default() -> None:
    assert "reply_language_override" not in TurnRequest(content="hi").to_payload()
    assert (
        TurnRequest(content="hi", reply_language_override=None).to_payload()[
            "reply_language_override"
        ]
        is None
    )


@pytest.mark.asyncio
async def test_selector_does_not_create_a_missing_session(
    monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    store = SQLiteSessionStore(tmp_path / "reply-language-missing.db")
    monkeypatch.setattr(sessions_router, "get_session_store", lambda: store)
    with pytest.raises(HTTPException) as error:
        await sessions_router.update_session_reply_language(
            "missing", sessions_router.SessionReplyLanguageRequest(language="fr")
        )
    assert error.value.status_code == 404
    assert await store.get_session("missing") is None
