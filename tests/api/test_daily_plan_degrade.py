"""The daily-plan endpoint degrades instead of 500ing.

The "today" card is a convenience read over the session and mastery stores.
When a store fails to open (fresh deployment, partial migration, locked
sqlite) the plan must come back empty — the card renders its starter state —
rather than as a 500 that every learner's Learning Space turns into
"今日学习暂时无法加载".
"""

from __future__ import annotations

import asyncio


def test_daily_plan_returns_empty_plan_when_a_store_fails(monkeypatch) -> None:
    from deeptutor.api.routers import daily_plan

    def explode():
        raise RuntimeError("sqlite unavailable")

    monkeypatch.setattr(daily_plan, "get_session_store", explode)

    plan = asyncio.run(daily_plan.get_daily_plan(None))
    assert plan == {"continue_learning": None, "recommendations": []}


def test_daily_plan_returns_empty_plan_when_the_mastery_store_fails(monkeypatch) -> None:
    from deeptutor.api.routers import daily_plan

    class BrokenStore:
        def list_topic_snapshots(self, status=None):
            raise RuntimeError("mastery store unavailable")

    monkeypatch.setattr(
        daily_plan,
        "get_session_store",
        lambda: type("S", (), {"list_sessions": staticmethod(lambda limit, offset: [])})(),
    )
    monkeypatch.setattr(daily_plan, "LearningStore", BrokenStore)

    plan = asyncio.run(daily_plan.get_daily_plan(None))
    assert plan == {"continue_learning": None, "recommendations": []}
