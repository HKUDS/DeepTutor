"""Learner daily-plan API — what the learning space's "today" card shows.

Read-only composition over the stores that already exist: the most recent
conversation (or the mastery path / reading collection that owns it) for
"continue", and the weakest attempted knowledge points across the learner's
active mastery paths for "recommend". Nothing here writes and no new storage
is introduced — with no history the plan is simply empty and the card renders
its starter state.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status

from deeptutor.api.routers.auth import require_auth
from deeptutor.learning import policy as learning_policy
from deeptutor.learning.models import LearningProgress
from deeptutor.learning.storage import LearningStore
from deeptutor.multi_user.identity import get_user_by_id, is_learner_account
from deeptutor.services.auth import AUTH_ENABLED, TokenPayload
from deeptutor.services.session import get_session_store
from deeptutor.services.settings.interface_settings import get_response_language

logger = logging.getLogger(__name__)

router = APIRouter()

_MAX_RECOMMENDATIONS = 3

#: The plan is a pure convenience read — a store that fails to open (fresh
#: deployment, partial migration, locked sqlite) must degrade to an empty plan
#: (the card's starter state) instead of a 500 that renders as "今日学习暂时
#: 无法加载" on every learner's Learning Space.
_EMPTY_PLAN = {"continue_learning": None, "recommendations": []}


async def require_learner(
    payload: TokenPayload | None = Depends(require_auth),
) -> TokenPayload | None:
    """Learner-only surface guard for the daily plan.

    Organizational roles other than admin may carry the learner preset, so the
    check goes through :func:`is_learner_account` rather than the raw role
    (fusion-mapping-163). AUTH_ENABLED=false — a single-user local run — is
    implicitly admin, the same convention :func:`require_admin` uses.
    """
    if not AUTH_ENABLED:
        return payload
    account = get_user_by_id(payload.user_id) if payload is not None else None
    if (
        payload is None
        or account is None
        or not is_learner_account(payload.role, account[1].get("preset"))
    ):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Learner account required"
        )
    return payload


def _continue_from_session(session: dict[str, Any]) -> dict[str, str]:
    """Which surface owns this conversation, and the id that reopens it.

    Mirrors ``sessionRoute`` on the web side: the preference pair decides
    (``workspace_mode`` + the path or collection id), because the capability
    is a per-turn action and never decides which surface owns a conversation.
    """
    preferences = session.get("preferences") or {}
    mode = str(preferences.get("workspace_mode") or "")
    title = str(session.get("title") or "")
    if mode == "mastery_path":
        path_id = str(preferences.get("mastery_path_id") or "").strip()
        if path_id:
            return {"kind": "book", "title": title, "ref": path_id}
    if mode == "immersive_reading":
        workspace_id = str(preferences.get("reading_workspace_id") or "").strip()
        if workspace_id:
            return {"kind": "reading", "title": title, "ref": workspace_id}
    return {
        "kind": "space",
        "title": title,
        "ref": str(session.get("session_id") or session.get("id") or ""),
    }


async def _continue_learning() -> dict[str, str] | None:
    """The single most recently active entry: conversation, path or collection.

    The latest session and the latest path are both candidates — a learner who
    studied a path without ever chatting into it should still be offered it.
    Sessions come ordered most-recent-first (``updated_at DESC``).
    """
    sessions = await get_session_store().list_sessions(limit=1, offset=0)
    candidates: list[tuple[float, dict[str, str]]] = []
    if sessions:
        latest = sessions[0]
        timestamp = float(latest.get("updated_at") or latest.get("created_at") or 0)
        candidates.append((timestamp, _continue_from_session(latest)))

    def latest_topic() -> tuple[float, dict[str, str]] | None:
        best: tuple[float, dict[str, str]] | None = None
        for progress, _topic, _count, _interaction in LearningStore().list_topic_snapshots(
            status="active"
        ):
            timestamp = float(progress.updated_at or 0)
            if best is None or timestamp > best[0]:
                best = (
                    timestamp,
                    {
                        "kind": "book",
                        "title": learning_policy.path_display_name(progress),
                        "ref": progress.book_id,
                    },
                )
        return best

    topic = await asyncio.to_thread(latest_topic)
    if topic is not None:
        candidates.append(topic)
    if not candidates:
        return None
    candidates.sort(key=lambda item: item[0], reverse=True)
    return candidates[0][1]


def _suggestion_text(mastery: float, language: str) -> str:
    percent = round(mastery * 100)
    if language.startswith("zh"):
        return f"掌握度 {percent}%，建议重学这一节并做几道巩固题。"
    return f"Mastery is at {percent}% — revisit this point and work a few practice questions."


def _weak_recommendations(progress: LearningProgress, language: str) -> list[dict[str, Any]]:
    """The attempted-but-not-mastered objectives of one path, weakest first.

    Untouched ("new") objectives are excluded on purpose: they are unknown,
    not weak — surfacing one as a weak point would tell a learner they
    struggled with something they never met. An empty result is the normal
    state for a fresh path.
    """
    weak: list[tuple[float, str, str]] = []
    for module in progress.modules:
        for kp in module.knowledge_points:
            if learning_policy.is_mastered(progress, kp):
                continue
            if learning_policy.objective_status(progress, kp) != "learning":
                continue
            mastery = learning_policy.display_mastery(progress, kp)
            weak.append((mastery, kp.name, kp.id))
    weak.sort(key=lambda item: (item[0], item[1]))
    return [
        {
            "kp_id": kp_id,
            "title": name,
            "mastery_level": round(mastery, 3),
            "suggestion": _suggestion_text(mastery, language),
        }
        for mastery, name, kp_id in weak
    ]


@router.get("")
async def get_daily_plan(_: TokenPayload | None = Depends(require_learner)) -> dict:
    """One learner's "today" plan: continue + up to three weak-point KPs."""
    language = get_response_language()

    def collect_recommendations() -> list[dict[str, Any]]:
        recommendations: list[dict[str, Any]] = []
        for progress, _topic, _count, _interaction in LearningStore().list_topic_snapshots(
            status="active"
        ):
            recommendations.extend(_weak_recommendations(progress, language))
        recommendations.sort(key=lambda item: item["mastery_level"])
        return recommendations[:_MAX_RECOMMENDATIONS]

    try:
        continue_learning = await _continue_learning()
        recommendations = await asyncio.to_thread(collect_recommendations)
    except Exception:  # noqa: BLE001 — degrade to the empty plan, never a 500
        logger.warning("daily-plan composition failed; serving an empty plan", exc_info=True)
        return dict(_EMPTY_PLAN)

    return {
        "continue_learning": continue_learning,
        "recommendations": recommendations,
    }
