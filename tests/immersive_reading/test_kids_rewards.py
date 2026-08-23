"""Tests for the optional Kids reward-provider extension point."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

import deeptutor.api.routers.kids as kids_router_module
import deeptutor.api.routers.kids_admin as kids_admin_router_module
import deeptutor.core.entry_points as entry_point_module
from deeptutor.immersive_reading import service as immersive_reading_service
from deeptutor.immersive_reading.models import (
    KidsBookAssignment,
    KidsInteractiveBookProgress,
    KidsLearningProgress,
    KidsQuizQuestion,
    KidsQuizResult,
)
from deeptutor.immersive_reading.service import _write_json, get_kids_manager
from deeptutor.kids_rewards import (
    KidsRewardEvent,
    RewardSnapshot,
    build_kids_reward_event,
    get_kids_reward_providers,
    kids_reward_snapshot,
    record_kids_reward_event,
    reset_kids_reward_provider_cache_for_tests,
)

EVENT_FIELDS = {
    "event_id",
    "profile_id",
    "content_type",
    "content_id",
    "item_id",
    "kind",
    "score",
    "total",
    "completed",
    "occurred_at",
}


class FakeStarsProvider:
    name = "fake_stars"
    version = "1.0.0"

    def __init__(self) -> None:
        self.events: dict[str, KidsRewardEvent] = {}
        self.content_totals_by_profile: dict[str, dict[str, int]] = {}

    def record(self, event: KidsRewardEvent) -> RewardSnapshot:
        assert set(event.model_dump()) == EVENT_FIELDS
        self.events[event.event_id] = event
        return self.snapshot(event.profile_id)

    def snapshot(self, profile_id: str) -> RewardSnapshot:
        return RewardSnapshot(
            provider=self.name,
            title="My rewards",
            message="Nice work!",
            items=[{"provider_label": "Stars", "value": str(len(self.events))}],
        )

    def content_totals(self, profile_id: str) -> dict[str, int]:
        return dict(self.content_totals_by_profile.get(profile_id, {}))


class FailingProvider(FakeStarsProvider):
    name = "failing"

    def record(self, event: KidsRewardEvent) -> RewardSnapshot:
        raise RuntimeError("provider failed")

    def snapshot(self, profile_id: str) -> RewardSnapshot:
        raise RuntimeError("provider failed")


class SecondProvider(FakeStarsProvider):
    name = "aaa_second"


class FakeQuizReadingService:
    async def generate_kids_quiz(
        self,
        document_id: str,
        section_id: str,
        *,
        force_refresh: bool = False,
        age_band: str = "6-8",
        language: str = "en",
    ):
        return KidsQuizResult(
            document_id=document_id,
            section_id=section_id,
            questions=[
                KidsQuizQuestion(
                    id=f"q{index}",
                    kind="comprehension",
                    question=f"Question {index}?",
                    choices=["Correct", "Incorrect"],
                    answer_index=0,
                    explanation="The answer is in the story.",
                )
                for index in range(1, 4)
            ],
            content_hash="test-hash",
            model="test-model",
            prompt_version="test-v1",
        )

    def _save_kids_quiz_cache(self, document_id: str, section_id: str, result) -> None:
        return None

    def load_document(self, document_id: str):
        return SimpleNamespace(
            id=document_id,
            title="Reading Doc",
            sections=[
                SimpleNamespace(
                    id="section-1", title="Chapter 1", index=0, checkpoint_kind="chapter"
                )
            ]
        )

    def _summary(self, document) -> dict:
        return {"id": document.id, "title": document.title}

    def get_section(self, document_id: str, section_id: str):
        return {"content": "The little plum is on the mat."}


@pytest.fixture(autouse=True)
def isolated_reward_provider_cache(monkeypatch):
    reset_kids_reward_provider_cache_for_tests()
    monkeypatch.setattr(
        entry_point_module,
        "entry_points",
        lambda *, group: [],
    )
    yield
    reset_kids_reward_provider_cache_for_tests()


def _install_provider(monkeypatch, provider: FakeStarsProvider) -> None:
    reset_kids_reward_provider_cache_for_tests()

    def fake_entry_points(*, group: str):
        assert group == "deeptutor.kids_reward_providers"
        return [SimpleNamespace(name=provider.name, load=lambda: provider)]

    monkeypatch.setattr(entry_point_module, "entry_points", fake_entry_points)
    assert get_kids_reward_providers(refresh=True) == [provider]


def test_reward_events_are_neutral_and_idempotent(monkeypatch):
    provider = FakeStarsProvider()
    _install_provider(monkeypatch, provider)
    event = build_kids_reward_event(
        profile_id="child001",
        content_type="reading",
        content_id="doc001",
        item_id="section-1",
        kind="quiz_submitted",
        score=3,
        total=3,
        completed=True,
    )

    first = record_kids_reward_event(event)
    second = record_kids_reward_event(event)

    assert first is not None and second is not None
    assert len(provider.events) == 1
    assert first.title == "My rewards"
    assert set(provider.events[event.event_id].model_dump()) == EVENT_FIELDS
    assert kids_reward_snapshot("child001").items[0].value == "1"


def test_multiple_providers_select_the_first_stable_provider(monkeypatch):
    active = SecondProvider()
    inactive = FakeStarsProvider()
    reset_kids_reward_provider_cache_for_tests()

    def fake_entry_points(*, group: str):
        return [
            SimpleNamespace(name=active.name, load=lambda: active),
            SimpleNamespace(name=inactive.name, load=lambda: inactive),
        ]

    monkeypatch.setattr(entry_point_module, "entry_points", fake_entry_points)
    event = build_kids_reward_event(
        profile_id="child001",
        content_type="reading",
        content_id="doc001",
        item_id="section-1",
        kind="quiz_submitted",
        score=1,
        total=1,
        completed=True,
    )
    record_kids_reward_event(event)

    assert active.events
    assert not inactive.events
    assert kids_reward_snapshot("child001") is not None


def test_old_reward_progress_fields_are_ignored_and_dropped_on_save(tmp_path, monkeypatch):
    manager = get_kids_manager()
    monkeypatch.setattr(manager, "_kids_root", lambda: tmp_path / "kids")
    profile = manager.create_profile(name="Reader")
    legacy_data = KidsLearningProgress(
        profile_id=profile.id,
        document_id="doc001",
        quiz_scores={"section-1": 3},
    ).model_dump(mode="json")
    legacy_data.update(total_stars=12, quiz_stars_awarded={"section-1": 3})
    _write_json(manager._progress_path(profile.id, "doc001"), legacy_data)

    progress = manager.record_reading_quiz_result(
        profile.id, "doc001", "section-1", 3, 3
    )

    assert progress.quiz_scores["section-1"] == 3
    assert "total_stars" not in progress.model_dump(mode="json")
    assert "quiz_stars_awarded" not in progress.model_dump(mode="json")

    legacy_interactive = KidsInteractiveBookProgress(
        profile_id=profile.id,
        book_id="book001",
    ).model_dump(mode="json")
    legacy_interactive.update(total_stars=7, quiz_stars_awarded={"block-1": 3})
    _write_json(manager._interactive_progress_path(profile.id, "book001"), legacy_interactive)
    interactive = manager.record_interactive_quiz_result(
        profile.id, "book001", "block-1", 1, 1
    )
    assert interactive.quiz_scores["block-1"] == 1
    assert "total_stars" not in interactive.model_dump(mode="json")
    assert "quiz_stars_awarded" not in interactive.model_dump(mode="json")


def _reading_client(monkeypatch, tmp_path: Path, provider: FakeStarsProvider):
    manager = get_kids_manager()
    monkeypatch.setattr(manager, "_kids_root", lambda: tmp_path / "kids")
    profile = manager.create_profile(name="Reader")
    _write_json(
        manager._assignments_path(),
        [
            KidsBookAssignment(
                id="assignment001",
                profile_id=profile.id,
                document_id="readingdoc001",
                document_title="Reading Doc",
            ).model_dump(mode="json")
        ],
    )
    monkeypatch.setattr(
        kids_router_module,
        "get_immersive_reading_service",
        lambda: FakeQuizReadingService(),
    )
    app = FastAPI()
    app.include_router(kids_router_module.router, prefix="/api/v1/kids")
    client = TestClient(app)
    selected = client.post(
        "/api/v1/kids/select-profile", json={"profile_id": profile.id}
    )
    headers = {"Authorization": f"Bearer {selected.json()['token']}"}
    return client, headers, profile.id


def test_reading_quiz_emits_neutral_events_and_provider_snapshot(monkeypatch, tmp_path):
    provider = FakeStarsProvider()
    _install_provider(monkeypatch, provider)
    client, headers, profile_id = _reading_client(monkeypatch, tmp_path, provider)

    response = client.post(
        "/api/v1/kids/books/readingdoc001/quiz/submit",
        json={"section_id": "section-1", "answers": [0, 0, 0]},
        headers=headers,
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["score"] == 3
    assert payload["total"] == 3
    assert payload["reward"]["provider"] == "fake_stars"
    assert payload["reward"]["title"] == "My rewards"
    assert not any(
        key in payload
        for key in ("stars", "new_stars_awarded", "total_stars", "encouragements")
    )
    assert set(provider.events) == {
        build_kids_reward_event(
            profile_id=profile_id,
            content_type="reading",
            content_id="readingdoc001",
            item_id="section-1",
            kind="quiz_submitted",
            score=3,
            total=3,
            completed=True,
        ).event_id,
        build_kids_reward_event(
            profile_id=profile_id,
            content_type="reading",
            content_id="readingdoc001",
            item_id="section-1",
            kind="section_completed",
            score=3,
            total=3,
            completed=True,
        ).event_id,
    }
    for event in provider.events.values():
        assert event.profile_id == profile_id
        assert event.content_id == "readingdoc001"
        assert event.item_id == "section-1"
        assert set(event.model_dump()) == EVENT_FIELDS

    rewards = client.get("/api/v1/kids/rewards", headers=headers)
    assert rewards.status_code == 200
    assert rewards.json()["reward"]["provider"] == "fake_stars"


def test_library_adds_provider_totals_without_persisting_legacy_fields(monkeypatch, tmp_path):
    provider = FakeStarsProvider()
    _install_provider(monkeypatch, provider)
    client, headers, profile_id = _reading_client(monkeypatch, tmp_path, provider)
    provider.content_totals_by_profile[profile_id] = {"reading:readingdoc001": 6}
    monkeypatch.setattr(
        immersive_reading_service,
        "get_immersive_reading_service",
        lambda: FakeQuizReadingService(),
    )
    legacy_progress = KidsLearningProgress(
        profile_id=profile_id,
        document_id="readingdoc001",
    ).model_dump(mode="json")
    legacy_progress["total_stars"] = 99
    _write_json(
        get_kids_manager()._progress_path(profile_id, "readingdoc001"), legacy_progress
    )

    response = client.get("/api/v1/kids/library", headers=headers)

    assert response.status_code == 200
    progress = response.json()["library"][0]["progress"]
    assert progress["total_stars"] == 6
    stored = get_kids_manager().load_kids_progress(profile_id, "readingdoc001")
    assert "total_stars" not in stored.model_dump(mode="json")


def test_child_rewards_endpoint_requires_device_session(monkeypatch, tmp_path):
    provider = FakeStarsProvider()
    _reading_client(monkeypatch, tmp_path, provider)

    app = FastAPI()
    app.include_router(kids_router_module.router, prefix="/api/v1/kids")
    response = TestClient(app).get("/api/v1/kids/rewards")

    assert response.status_code == 401

    provider_route = TestClient(app).get(
        "/api/v1/kids/reward-providers/fake_stars"
    )
    assert provider_route.status_code == 404


def test_parent_rewards_endpoint_returns_provider_snapshot(monkeypatch, tmp_path):
    provider = FakeStarsProvider()
    _install_provider(monkeypatch, provider)
    _, _, profile_id = _reading_client(monkeypatch, tmp_path, provider)
    app = FastAPI()
    app.include_router(kids_admin_router_module.router, prefix="/api/v1/kids-admin")

    response = TestClient(app).get(f"/api/v1/kids-admin/profiles/{profile_id}/rewards")

    assert response.status_code == 200
    assert response.json()["reward"]["items"][0]["value"] == "0"

    record_kids_reward_event(
        build_kids_reward_event(
            profile_id=profile_id,
            content_type="reading",
            content_id="readingdoc001",
            item_id="section-1",
            kind="quiz_submitted",
            score=3,
            total=3,
            completed=True,
        )
    )
    response = TestClient(app).get(f"/api/v1/kids-admin/profiles/{profile_id}/rewards")
    assert response.json()["reward"]["provider"] == "fake_stars"


def test_no_provider_keeps_learning_flow_and_reward_ui_contract(monkeypatch, tmp_path):
    provider = FakeStarsProvider()
    client, headers, _ = _reading_client(monkeypatch, tmp_path, provider)

    response = client.post(
        "/api/v1/kids/books/readingdoc001/quiz/submit",
        json={"section_id": "section-1", "answers": [0, 0, 0]},
        headers=headers,
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["score"] == 3
    assert payload["reward"] is None
    assert client.get("/api/v1/kids/rewards", headers=headers).json()["reward"] is None


def test_reading_quiz_survives_provider_failure_and_omits_reward(monkeypatch, tmp_path):
    provider = FailingProvider()
    _install_provider(monkeypatch, provider)
    client, headers, profile_id = _reading_client(monkeypatch, tmp_path, provider)

    response = client.post(
        "/api/v1/kids/books/readingdoc001/quiz/submit",
        json={"section_id": "section-1", "answers": [0, 0, 0]},
        headers=headers,
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["score"] == 3
    assert payload["total"] == 3
    assert payload["reward"] is None
    assert not any(
        key in payload
        for key in ("stars", "new_stars_awarded", "total_stars", "encouragements")
    )
    rewards = client.get("/api/v1/kids/rewards", headers=headers)
    assert rewards.status_code == 200
    assert rewards.json()["reward"] is None
