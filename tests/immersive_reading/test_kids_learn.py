"""Concept-guide behavior for the Kids reading Learn flow."""

import json
import re
from types import SimpleNamespace

import pytest

from deeptutor.immersive_reading.models import KidsLearnResult
import deeptutor.immersive_reading.service as service_module
from deeptutor.immersive_reading.service import ImmersiveReadingService

VISIBLE_TEXT = (
    "很多小朋友都听说过量子力学。量子世界和我们每天看见的世界不一样。"
    "科学家用量子力学研究很小的粒子。"
)


def make_service(tmp_path, monkeypatch):
    service = ImmersiveReadingService()
    learn_path = tmp_path / "kids-learn" / "section-1" / "page.json"
    monkeypatch.setattr(
        service,
        "_kids_learn_path",
        lambda _document_id, _section_id, _content_hash: learn_path,
    )
    monkeypatch.setattr(
        service_module, "get_llm_config", lambda: SimpleNamespace(model="test-model")
    )
    monkeypatch.setattr(
        service,
        "load_document",
        lambda _document_id: SimpleNamespace(
            title="量子世界",
            sections=[SimpleNamespace(id="section-1", title="第1讲 量子世界")],
        ),
    )
    calls = {"complete": 0}
    monkeypatch.setattr(
        service_module,
        "complete",
        fake_learn_complete(calls),
    )
    return service, learn_path, calls


def fake_learn_complete(calls):
    async def complete(**_kwargs):
        calls["complete"] += 1
        return json.dumps(
            {
                "overview": "这一页介绍量子世界和量子力学。",
                "concepts": [
                    {
                        "term": "量子世界",
                        "explanation": "很小的粒子遵循的世界的规律和日常世界不同。",
                        "analogy": "像小球在看不见的迷宫里运动。",
                    }
                ],
                "reflection": {
                    "prompt": "用自己的话说说量子世界。",
                    "hint": "想想日常世界和很小世界的差别。",
                    "answer": "量子世界是很小粒子的世界。",
                },
            },
            ensure_ascii=False,
        )

    return complete


@pytest.mark.asyncio
async def test_learn_cache_is_reused_by_visible_page_hash(tmp_path, monkeypatch):
    service, learn_path, calls = make_service(tmp_path, monkeypatch)

    first = await service.generate_kids_learn(
        "document-1", "section-1", VISIBLE_TEXT, age_band="6-8", language="zh"
    )
    second = await service.generate_kids_learn(
        "document-1", "section-1", VISIBLE_TEXT, age_band="6-8", language="zh"
    )

    assert calls["complete"] == 1
    assert first.source == "generated"
    assert first == second
    assert learn_path.exists()


@pytest.mark.asyncio
async def test_learn_cache_is_isolated_by_language_and_age(tmp_path, monkeypatch):
    service, _learn_path, calls = make_service(tmp_path, monkeypatch)

    await service.generate_kids_learn(
        "document-1", "section-1", VISIBLE_TEXT, age_band="6-8", language="zh"
    )
    await service.generate_kids_learn(
        "document-1", "section-1", VISIBLE_TEXT, age_band="9-12", language="zh"
    )
    await service.generate_kids_learn(
        "document-1", "section-1", VISIBLE_TEXT, age_band="6-8", language="en"
    )

    assert calls["complete"] == 3


@pytest.mark.asyncio
async def test_learn_model_failure_uses_nonfabricated_fallback(tmp_path, monkeypatch):
    service, learn_path, calls = make_service(tmp_path, monkeypatch)

    async def failing_complete(**_kwargs):
        calls["complete"] += 1
        raise TimeoutError("model timeout")

    monkeypatch.setattr(service_module, "complete", failing_complete)
    result = await service.generate_kids_learn(
        "document-1", "section-1", VISIBLE_TEXT, age_band="6-8", language="zh"
    )

    assert result.source == "fallback"
    assert result.overview in VISIBLE_TEXT
    assert result.concepts
    assert all(not concept.analogy for concept in result.concepts)
    assert result.reflection.answer in VISIBLE_TEXT
    assert KidsLearnResult.model_validate_json(learn_path.read_text(encoding="utf-8")) == result


@pytest.mark.asyncio
async def test_learn_fallback_never_injects_book_specific_knowledge(tmp_path, monkeypatch):
    service = ImmersiveReadingService()
    visible_text = (
        "小梅在海边发现一只寄居蟹。寄居蟹背着螺旋形的壳。潮水退去以后，沙滩上留下了许多小贝壳。"
    )

    async def failing_complete(**_kwargs):
        raise TimeoutError("model timeout")

    monkeypatch.setattr(service_module, "complete", failing_complete)
    result = await service.generate_kids_learn(
        "document-1", "section-1", visible_text, age_band="6-8", language="zh"
    )

    assert result.source == "fallback"
    assert all(
        sentence in visible_text
        for sentence in re.split(r"(?<=[。！？!?；;])", result.overview)
        if sentence
    )
    assert all(
        sentence in visible_text
        for sentence in re.split(r"(?<=[。！？!?；;])", result.reflection.answer)
        if sentence
    )
    assert all(concept.explanation in visible_text for concept in result.concepts)
    assert "玻耳兹曼" not in result.model_dump_json()
    assert "拉普拉斯" not in result.model_dump_json()
