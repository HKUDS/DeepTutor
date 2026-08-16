from __future__ import annotations

import asyncio


def test_delete_session_cleans_only_current_user_artifacts(as_user, monkeypatch) -> None:
    from deeptutor.api.routers import sessions as sessions_router
    from deeptutor.learning.models import LearningProgress
    from deeptutor.learning.storage import LearningStore
    from deeptutor.services.storage.attachment_store import (
        get_attachment_store,
        reset_attachment_store,
    )

    session_id = "shared-session-id"
    attachment_id = "upload-1"

    class _SessionStore:
        async def delete_session(self, candidate: str) -> bool:
            return candidate == session_id

    monkeypatch.setattr(sessions_router, "get_session_store", lambda: _SessionStore())
    reset_attachment_store()

    async def _seed(uid: str) -> None:
        with as_user(uid):
            LearningStore().save(LearningProgress(book_id=session_id))
            await get_attachment_store().put(
                session_id=session_id,
                attachment_id=attachment_id,
                filename="notes.txt",
                data=uid.encode(),
            )

    async def _artifacts_exist(uid: str) -> tuple[bool, bool]:
        with as_user(uid):
            learning_exists = LearningStore().exists(session_id)
            attachment_exists = (
                get_attachment_store().resolve_path(
                    session_id=session_id,
                    attachment_id=attachment_id,
                    filename="notes.txt",
                )
                is not None
            )
            return learning_exists, attachment_exists

    async def _exercise() -> None:
        await _seed("u_alice")
        await _seed("u_bob")

        with as_user("u_alice"):
            response = await sessions_router.delete_session(session_id)

        assert response == {"deleted": True, "session_id": session_id}
        assert await _artifacts_exist("u_alice") == (False, False)
        assert await _artifacts_exist("u_bob") == (True, True)

    asyncio.run(_exercise())
