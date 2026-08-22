"""Cache behavior for child reading comprehension quizzes."""

import hashlib
import json
from types import SimpleNamespace

import pytest

from deeptutor.immersive_reading.models import KidsQuizQuestion, KidsQuizResult
import deeptutor.immersive_reading.service as service_module
from deeptutor.immersive_reading.service import ImmersiveReadingService

CONTENT = "Mit sat in the sun. Mag saw Mit. Mit ran and got wet."


def comprehension_question(number: int) -> KidsQuizQuestion:
    return KidsQuizQuestion(
        id=f"q{number}",
        kind="comprehension",
        question=f"What happens in part {number}?",
        choices=["The characters play.", "A car flies.", "It snows.", "They sleep."],
        answer_index=0,
        explanation="The story says the characters play.",
    )


def llm_payload() -> str:
    return json.dumps(
        {
            "questions": [
                {
                    "id": "llm-1",
                    "kind": "comprehension",
                    "question": "Who is outside?",
                    "choices": ["Mit", "A truck", "A frog", "A duck"],
                    "answer_index": 0,
                    "explanation": "Mit sat in the sun.",
                },
                {
                    "id": "llm-2",
                    "kind": "comprehension",
                    "question": "What happened to Mit?",
                    "choices": ["She got wet.", "She slept.", "She ate.", "She flew."],
                    "answer_index": 0,
                    "explanation": "Mit ran and got wet.",
                },
                {
                    "id": "llm-3",
                    "kind": "comprehension",
                    "question": "How does Mit feel?",
                    "choices": ["Wet", "Sleepy", "Hungry", "Tall"],
                    "answer_index": 0,
                    "explanation": "Mit got wet in the story.",
                },
            ]
        }
    )


def make_service(tmp_path, monkeypatch):
    service = ImmersiveReadingService()
    quiz_path = tmp_path / "kids-quiz" / "section-1.json"
    monkeypatch.setattr(
        service,
        "_kids_quiz_path",
        lambda _document_id, _section_id: quiz_path,
    )
    monkeypatch.setattr(
        service,
        "_section_path",
        lambda _document_id, _section_id: tmp_path / "section-1.txt",
    )
    (tmp_path / "section-1.txt").write_text(CONTENT, encoding="utf-8")
    monkeypatch.setattr(
        service,
        "load_document",
        lambda _document_id: SimpleNamespace(
            title="Story",
            sections=[SimpleNamespace(id="section-1", title="Story")],
        ),
    )
    calls = {"complete": 0}

    async def fake_complete(**_kwargs):
        calls["complete"] += 1
        return llm_payload()

    monkeypatch.setattr(
        service_module, "get_llm_config", lambda: SimpleNamespace(model="test-model")
    )
    monkeypatch.setattr(service_module, "complete", fake_complete)
    return service, quiz_path, calls


def write_cache(path, *, age_band="6-8", sight_word=False):
    questions = [comprehension_question(i) for i in range(1, 4)]
    if sight_word:
        questions[0] = KidsQuizQuestion(
            id="old-1",
            kind="sight_word",
            question='What does "mag" mean?',
            choices=["A cat", "A truck", "A plum", "A sled"],
            answer_index=0,
            explanation="A vocabulary drill.",
        )
    result = KidsQuizResult(
        document_id="document-1",
        section_id="section-1",
        questions=questions,
        content_hash=hashlib.sha256(CONTENT.encode("utf-8")).hexdigest(),
        model="cached-model",
        prompt_version="kids-quiz-v4",
        age_band=age_band,
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(result.model_dump_json(), encoding="utf-8")
    return result


@pytest.mark.asyncio
async def test_unsupported_cache_version_is_regenerated(tmp_path, monkeypatch):
    service, quiz_path, calls = make_service(tmp_path, monkeypatch)
    cached = write_cache(quiz_path)
    cached.prompt_version = "kids-quiz-v3"
    quiz_path.write_text(cached.model_dump_json(), encoding="utf-8")

    result = await service.generate_kids_quiz("document-1", "section-1", age_band="6-8")

    assert calls["complete"] == 1
    assert result.prompt_version == service.KIDS_QUIZ_PROMPT_VERSION


@pytest.mark.asyncio
async def test_matching_comprehension_cache_is_reused(tmp_path, monkeypatch):
    service, quiz_path, calls = make_service(tmp_path, monkeypatch)
    cached = write_cache(quiz_path)

    result = await service.generate_kids_quiz("document-1", "section-1", age_band="6-8")

    assert calls["complete"] == 0
    assert result.model_dump() == cached.model_dump()


@pytest.mark.asyncio
async def test_sight_word_cache_is_regenerated(tmp_path, monkeypatch):
    service, quiz_path, calls = make_service(tmp_path, monkeypatch)
    write_cache(quiz_path, sight_word=True)

    result = await service.generate_kids_quiz("document-1", "section-1", age_band="6-8")

    assert calls["complete"] == 1
    assert all(question.kind == "comprehension" for question in result.questions)
    assert result.age_band == "6-8"
    assert all(
        question.kind != "sight_word"
        for question in KidsQuizResult.model_validate_json(
            quiz_path.read_text(encoding="utf-8")
        ).questions
    )


@pytest.mark.asyncio
async def test_age_band_change_bypasses_cache(tmp_path, monkeypatch):
    service, quiz_path, calls = make_service(tmp_path, monkeypatch)
    write_cache(quiz_path, age_band="6-8")

    result = await service.generate_kids_quiz("document-1", "section-1", age_band="9-12")

    assert calls["complete"] == 1
    assert result.age_band == "9-12"


@pytest.mark.asyncio
async def test_cache_without_age_provenance_is_regenerated(tmp_path, monkeypatch):
    service, quiz_path, calls = make_service(tmp_path, monkeypatch)
    write_cache(quiz_path)
    raw_cache = json.loads(quiz_path.read_text(encoding="utf-8"))
    del raw_cache["age_band"]
    quiz_path.write_text(json.dumps(raw_cache), encoding="utf-8")

    result = await service.generate_kids_quiz("document-1", "section-1", age_band="6-8")

    assert calls["complete"] == 1
    assert result.age_band == "6-8"


def test_sight_word_quiz_is_never_written_to_cache(tmp_path, monkeypatch):
    service = ImmersiveReadingService()
    quiz_path = tmp_path / "kids-quiz" / "section-1.json"
    monkeypatch.setattr(
        service,
        "_kids_quiz_path",
        lambda _document_id, _section_id: quiz_path,
    )
    result = write_cache(tmp_path / "ignored.json", sight_word=True)

    service._save_kids_quiz_cache("document-1", "section-1", result)

    assert not quiz_path.exists()
