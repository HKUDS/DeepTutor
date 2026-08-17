import asyncio
import json
from pathlib import Path

import pytest

from deeptutor.immersive_reading.bilingual.service import BilingualPairingService
from deeptutor.services.translation.glossary import (
    build_translation_guardrail,
    review_glossary_candidates,
    terms_for_text,
)
from deeptutor.services.translation.protection import (
    TranslationProtectionError,
    protect_translation_text,
    restore_translation_text,
    translate_with_protection,
)
from deeptutor.services.translation.service import TranslationTaskService
from tests.immersive_reading.bilingual._fixtures import make_minimal_epub


@pytest.fixture
def setup(tmp_path: Path, monkeypatch):
    en_epub = tmp_path / "en.epub"
    zh_epub = tmp_path / "zh.epub"
    chapters_en = [
        ("Story Chapter 1", ["The quiet harbour slept.", "A lantern flickered."]),
        ("API Deployment", ["The service returned a response.", "The client retried the request."]),
    ]
    chapters_zh = [
        ("第一章", ["安静的港口睡着了。", "灯笼闪烁。"]),
        ("接口部署", ["服务返回了响应。", "客户端重试了请求。"]),
    ]
    make_minimal_epub(en_epub, "Test Book", chapters_en)
    make_minimal_epub(zh_epub, "测试书", chapters_zh)
    for document_id, epub in (("en", en_epub), ("zh", zh_epub)):
        document_dir = tmp_path / f"document_{document_id}"
        document_dir.mkdir()
        (document_dir / "original.epub").write_bytes(epub.read_bytes())

    class FakePathService:
        workspace_root = tmp_path / "workspace"

        def get_immersive_reading_bilingual_dir(self):
            root = tmp_path / "bilingual"
            root.mkdir(parents=True, exist_ok=True)
            return root

        def get_immersive_reading_pairing_root(self, pairing_id):
            return tmp_path / "bilingual" / f"pairing_{pairing_id}"

        def ensure_immersive_reading_pairing_root(self, pairing_id):
            root = self.get_immersive_reading_pairing_root(pairing_id)
            root.mkdir(parents=True, exist_ok=True)
            return root

        def get_immersive_reading_document_root(self, document_id):
            return tmp_path / f"document_{document_id}"

        def get_knowledge_bases_root(self):
            root = tmp_path / "knowledge_bases"
            root.mkdir(parents=True, exist_ok=True)
            return root

    fake_path = FakePathService()
    monkeypatch.setattr(
        "deeptutor.immersive_reading.bilingual.service.get_path_service", lambda: fake_path
    )
    monkeypatch.setattr(
        "deeptutor.services.translation.service.get_path_service", lambda: fake_path
    )
    pairing_service = BilingualPairingService()
    pairing = pairing_service.pair_documents("en", "zh")
    pairing_id = pairing["pairing_id"]
    pairing_service.align(pairing_id)
    pairing_service.update_reading_position(
        pairing_id,
        {"chapter_index": 1, "group_index": 0, "scroll_percent": 0},
    )
    section_path = (
        fake_path.get_immersive_reading_pairing_root(pairing_id) / "sections" / "ch002.json"
    )
    section = json.loads(section_path.read_text())
    section["groups"][0]["zh"] = []
    section_path.write_text(json.dumps(section, ensure_ascii=False), encoding="utf-8")

    kb_raw = fake_path.get_knowledge_bases_root() / "research" / "raw"
    kb_raw.mkdir(parents=True)
    (kb_raw / "article.md").write_text("A short English article.", encoding="utf-8")

    task_service = TranslationTaskService(tmp_path / "translation_tasks.json")
    return fake_path, pairing_service, task_service, pairing_id


@pytest.mark.asyncio
async def test_bilingual_plan_priority_and_run_updates_section(monkeypatch, setup):
    fake_path, pairing_service, service, pairing_id = setup
    board = service.plan("bilingual", pairing_id)

    assert board["summary"]["filtered_total"] == 2
    task = next(item for item in board["tasks"] if item["reason"] == "missing_translation")
    assert task["priority"] == "high"
    assert task["reason"] == "missing_translation"
    assert board["chapters"][1]["translated_units"] == 1

    async def fake_translate(text, language):
        return f"翻译：{text}"

    class FakeImmersiveService:
        translate = staticmethod(fake_translate)

    monkeypatch.setattr(
        "deeptutor.immersive_reading.get_immersive_reading_service", lambda: FakeImmersiveService()
    )
    result = await service.run(source_type="bilingual", source_id=pairing_id)

    assert result["summary"]["filtered_completed"] == 2
    assert result["chapters"][1]["completed"] is True
    source = next(item for item in result["sources"] if item["source_id"] == pairing_id)
    assert source["translated_units"] == source["total_units"]
    assert source["all_translated"] is True
    section = pairing_service.get_bilingual_section(pairing_id, "ch002")
    assert section["groups"][0]["zh"] == [f"翻译：{section['groups'][0]['en'][0]}"]


@pytest.mark.asyncio
async def test_kb_plan_run_and_document_completion(monkeypatch, setup):
    _fake_path, _pairing_service, service, _pairing_id = setup
    board = service.plan("kb_document", "research")

    assert board["summary"]["filtered_total"] == 1
    assert board["documents"][0]["completed"] is False

    class FakeImmersiveService:
        @staticmethod
        async def translate(text, language):
            assert text == "A short English article."
            return "一篇简短英文文章。"

    monkeypatch.setattr(
        "deeptutor.immersive_reading.get_immersive_reading_service", lambda: FakeImmersiveService()
    )
    result = await service.run(source_type="kb_document", source_id="research", limit=1)

    assert result["summary"]["filtered_completed"] == 1
    assert result["documents"][0]["completed"] is True
    source = next(item for item in result["sources"] if item["source_type"] == "kb_document")
    assert source["translated_units"] == source["total_units"]
    assert source["all_translated"] is True


def test_plan_rejects_path_traversal_source_ids(setup):
    _fake_path, _pairing_service, service, pairing_id = setup

    with pytest.raises(ValueError, match="Invalid bilingual pairing id"):
        service.plan("bilingual", f"../../{pairing_id}")
    with pytest.raises(ValueError, match="reserved characters"):
        service.plan("kb_document", "../research")


def test_plan_allows_unicode_knowledge_base_name(setup):
    fake_path, _pairing_service, service, _pairing_id = setup
    kb_raw = fake_path.get_knowledge_bases_root() / "高等数学 KB" / "raw"
    kb_raw.mkdir(parents=True)
    (kb_raw / "article.md").write_text("A short English article.", encoding="utf-8")

    board = service.plan("kb_document", "高等数学 KB")

    assert board["summary"]["filtered_total"] == 1


def test_glossary_candidates_are_extracted_and_injected_into_tasks(setup):
    fake_path, _pairing_service, service, _pairing_id = setup
    document = fake_path.get_knowledge_bases_root() / "research" / "raw" / "guide.md"
    document.write_text(
        "\n".join(
            [
                "DeepSolver coordinates the retry pipeline.",
                "Call `fetch_user()` before DeepSolver retries.",
                "The invariant is $$E = mc^2$$ and `$fetch_user()` is code.",
                "DeepSolver never translates the formula.",
            ]
        ),
        encoding="utf-8",
    )

    board = service.plan("kb_document", "research")
    glossary = board["glossary"]
    terms = {entry["term"]: entry for entry in glossary}
    assert terms["DeepSolver"]["kind"] == "proper_noun"
    assert terms["fetch_user()"]["kind"] == "api_identifier"
    assert terms["fetch_user()"]["protected"] is True
    assert "$fetch_user()" not in terms

    task = next(item for item in board["tasks"] if item["title"] == "guide.md")
    assert {entry["term"] for entry in task["glossary"]} >= {"DeepSolver", "fetch_user()"}
    guardrail = build_translation_guardrail("Chinese", task["glossary"])
    glossary_json = guardrail.split("Glossary JSON (source, translation, protected; obey each entry):\n", 1)[1]
    payload = json.loads(glossary_json)
    assert {"source": "DeepSolver", "translation": "DeepSolver", "protected": False} in payload
    assert {
        "source": "fetch_user()",
        "translation": "fetch_user()",
        "protected": True,
    } in payload
    assert "Preserve inline math" in guardrail
    assert "Preserve fenced code blocks" in guardrail


@pytest.mark.parametrize("failure", ["unavailable", "invalid_json", "timeout"])
@pytest.mark.asyncio
async def test_glossary_review_falls_back_on_model_failures(
    monkeypatch, failure
):
    if failure == "unavailable":

        async def model_failure(*args, **kwargs):
            raise RuntimeError("model unavailable")

        monkeypatch.setattr("deeptutor.services.llm.complete", model_failure)
    elif failure == "invalid_json":

        async def invalid_json(*args, **kwargs):
            return "not-json"

        monkeypatch.setattr("deeptutor.services.llm.complete", invalid_json)
    else:

        async def timeout(*_coro, **_kwargs):
            raise asyncio.TimeoutError()

        monkeypatch.setattr(
            "deeptutor.services.translation.glossary.asyncio.wait_for", timeout
        )

    reviewed = await review_glossary_candidates(
        [{"term": "DeepSolver", "translation": "DeepSolver"}], "Chinese"
    )
    assert reviewed[0]["term"] == "DeepSolver"
    assert reviewed[0]["decision"] == "candidate"


@pytest.mark.asyncio
async def test_glossary_review_merges_model_aliases(monkeypatch):
    async def complete(*args, **kwargs):
        return json.dumps(
            {
                "entries": [
                    {
                        "term": "DeepSolver",
                        "translation": "深度求解器",
                        "kind": "proper_noun",
                        "protected": False,
                        "aliases": ["Deep Solver"],
                    }
                ]
            },
            ensure_ascii=False,
        )

    monkeypatch.setattr("deeptutor.services.llm.complete", complete)
    reviewed = await review_glossary_candidates(
        [{"term": "DeepSolver", "translation": "DeepSolver"}], "Chinese"
    )
    terms = {entry["term"]: entry for entry in reviewed}
    assert terms["DeepSolver"]["translation"] == "深度求解器"
    assert terms["Deep Solver"]["translation"] == "深度求解器"
    assert all(entry["decision"] == "candidate" for entry in reviewed)


def test_rejected_glossary_candidate_is_a_tombstone(setup):
    _fake_path, _pairing_service, service, _pairing_id = setup
    service.update_glossary(
        "kb_document",
        "research",
        [
            {
                "term": "DeepSolver",
                "translation": "DeepSolver",
                "kind": "proper_noun",
                "frequency": 2,
                "protected": True,
                "approved": False,
                "decision": "rejected",
            }
        ],
    )
    persisted = service.get_glossary("kb_document", "research")
    assert persisted[0]["decision"] == "rejected"
    assert persisted[0]["approved"] is False
    merged = service._refresh_glossary(
        service._load(),
        "kb_document",
        "research",
        ["DeepSolver appears again. DeepSolver appears again."],
    )
    entry = next(item for item in merged if item["term"] == "DeepSolver")
    assert entry["decision"] == "rejected"
    assert terms_for_text(merged, "DeepSolver appears again.") == []


def test_translation_protection_restores_fragments_and_retries_once():
    source = "Use `fetch_user()` and $$E=mc^2$$ at https://example.com/a."
    masked, fragments = protect_translation_text(
        source,
        [{"term": "fetch_user()", "translation": "fetch_user()", "protected": True}],
    )
    assert "fetch_user()" not in masked
    assert len(fragments) == 3
    assert restore_translation_text(masked, fragments) == source
    assert restore_translation_text(f"使用 {masked}", fragments) == f"使用 {source}"

    calls = []

    def translate(text, language):
        calls.append(text)
        if len(calls) == 1:
            return "丢失占位符"
        return text

    assert translate_with_protection(source, "Chinese", [], translate) == source
    assert len(calls) == 2

    with pytest.raises(TranslationProtectionError):
        restore_translation_text("broken", fragments)


def test_translation_protection_covers_all_required_fragment_types():
    source = (
        "Intro\n\n```python\nfetch_user()\n```\n\n"
        "Use `client.id` and $E=mc^2$ at https://example.com/a?a=1. "
        "<strong>Important</strong>: DeepSolver."
    )
    masked, fragments = protect_translation_text(
        source,
        [{"term": "DeepSolver", "translation": "DeepSolver", "protected": True}],
    )
    assert masked.count("[[DT-KEEP-") == 7
    assert restore_translation_text(masked, fragments) == source
    with pytest.raises(TranslationProtectionError):
        restore_translation_text(masked.replace("[[DT-KEEP-0]]", "[[DT-KEEP-1]]", 1), fragments)


@pytest.mark.asyncio
async def test_edited_glossary_is_reapplied_to_queued_tasks(monkeypatch, setup):
    _fake_path, _pairing_service, service, _pairing_id = setup
    document = _fake_path.get_knowledge_bases_root() / "research" / "raw" / "names.md"
    document.write_text(
        "DeepSolver starts. DeepSolver retries. DeepSolver finishes.",
        encoding="utf-8",
    )
    service.plan("kb_document", "research")
    service.update_glossary(
        "kb_document",
        "research",
        [
            {
                "term": "DeepSolver",
                "translation": "深度求解器",
                "kind": "proper_noun",
                "frequency": 3,
                "protected": False,
                "approved": True,
            }
        ],
    )
    captured = []

    class FakeImmersiveService:
        @staticmethod
        async def translate(text, language, glossary=None):
            captured.append(glossary or [])
            return "译文"

    monkeypatch.setattr(
        "deeptutor.immersive_reading.get_immersive_reading_service", lambda: FakeImmersiveService()
    )

    await service.run(source_type="kb_document", source_id="research", limit=2)

    guide_glossaries = [
        entries for entries in captured if any(item["term"] == "DeepSolver" for item in entries)
    ]
    assert guide_glossaries
    assert guide_glossaries[0][0]["translation"] == "深度求解器"


@pytest.mark.asyncio
async def test_bilingual_run_emits_one_group_translated_event_per_group(monkeypatch, setup):
    _fake_path, _pairing_service, service, pairing_id = setup
    service.plan("bilingual", pairing_id)

    class FakeImmersiveService:
        @staticmethod
        async def translate(text, language):
            return f"译文：{text}"

    monkeypatch.setattr(
        "deeptutor.immersive_reading.get_immersive_reading_service", lambda: FakeImmersiveService()
    )
    stream = service.subscribe(source_type="bilingual", source_id=pairing_id)
    snapshot = await stream.asend(None)
    assert snapshot["type"] == "snapshot"

    events = []
    consumer = asyncio.ensure_future(
        _collect_stream_events(stream, events, expected_groups=2)
    )
    await service.run(source_type="bilingual", source_id=pairing_id)
    await asyncio.wait_for(consumer, timeout=2)
    translated = [event for event in events if event["type"] == "group_translated"]
    assert len(translated) == 2
    assert all(event["task"]["translation"].startswith("译文：") for event in translated)
    assert {event["task"]["group_index"] for event in translated} == {0, 1}


@pytest.mark.asyncio
async def test_run_is_bounded_and_stream_closes_after_run_completed(monkeypatch, setup):
    fake_path, _pairing_service, service, _pairing_id = setup
    raw = fake_path.get_knowledge_bases_root() / "research" / "raw"
    for index in range(10):
        (raw / f"group-{index}.md").write_text(f"English group {index}.", encoding="utf-8")
    (raw / "article.md").unlink()
    service.plan("kb_document", "research")

    class FakeImmersiveService:
        @staticmethod
        async def translate(text, language, glossary=None):
            return f"译文 {text}"

    monkeypatch.setattr(
        "deeptutor.immersive_reading.get_immersive_reading_service",
        lambda: FakeImmersiveService(),
    )
    run = service.start_run(source_type="kb_document", source_id="research", limit=8)
    stream = service.subscribe(run_id=run["run_id"])
    events = []
    consumer = asyncio.ensure_future(_collect_run_events(stream, events))
    await service.run(run_id=run["run_id"])
    await asyncio.wait_for(consumer, timeout=2)

    assert len([event for event in events if event["type"] == "group_translated"]) == 8
    assert events[-1]["type"] == "run_completed"
    assert events[-1]["completed"] == 8
    board = service._board(source_type="kb_document", source_id="research")
    assert board["summary"]["filtered_queued"] == 2


@pytest.mark.asyncio
async def test_running_translation_run_can_be_cancelled(setup, monkeypatch):
    _fake_path, _pairing_service, service, pairing_id = setup
    service.plan("bilingual", pairing_id)
    started = asyncio.Event()
    stop = asyncio.Event()

    class FakeImmersiveService:
        @staticmethod
        async def translate(text, language):
            started.set()
            await stop.wait()
            return f"译文：{text}"

    monkeypatch.setattr(
        "deeptutor.immersive_reading.get_immersive_reading_service",
        lambda: FakeImmersiveService(),
    )

    run = service.start_run(source_type="bilingual", source_id=pairing_id, limit=2)
    run_task = asyncio.create_task(service.run(run_id=run["run_id"]))
    await started.wait()
    cancel_board = service.cancel_run(run["run_id"])
    stop.set()
    await asyncio.wait_for(run_task, timeout=2.0)

    canceled = service.get_run(run["run_id"])
    assert canceled["status"] == "cancelled"
    assert cancel_board["summary"]["filtered_failed"] >= 1
    assert any(
        task["status"] == "failed"
        for task in cancel_board["tasks"]
        if task["run_id"] == run["run_id"]
    )


@pytest.mark.asyncio
async def test_glossary_edit_during_model_call_is_not_overwritten(monkeypatch, setup):
    fake_path, _pairing_service, service, _pairing_id = setup
    raw = fake_path.get_knowledge_bases_root() / "research" / "raw"
    for index in range(2):
        (raw / f"term-{index}.md").write_text(f"DeepSolver record {index}.", encoding="utf-8")
    service.plan("kb_document", "research")

    class FakeImmersiveService:
        @staticmethod
        async def translate(text, language, glossary=None):
            service.update_glossary(
                "kb_document",
                "research",
                [
                    {
                        "term": "NewTerm",
                        "translation": "新术语",
                        "kind": "custom",
                        "frequency": 1,
                        "protected": False,
                        "approved": True,
                        "decision": "approved",
                    }
                ],
            )
            return "译文"

    monkeypatch.setattr(
        "deeptutor.immersive_reading.get_immersive_reading_service",
        lambda: FakeImmersiveService(),
    )
    await service.run(source_type="kb_document", source_id="research", limit=2)
    glossary = service.get_glossary("kb_document", "research")
    assert any(entry["term"] == "NewTerm" and entry["translation"] == "新术语" for entry in glossary)


@pytest.mark.asyncio
async def test_second_source_run_waits_for_queue_and_finishes(monkeypatch, setup):
    fake_path, _pairing_service, service, _pairing_id = setup
    for source in ("one", "two"):
        raw = fake_path.get_knowledge_bases_root() / source / "raw"
        raw.mkdir(parents=True)
        (raw / "document.md").write_text(f"Document from {source}.", encoding="utf-8")
        service.plan("kb_document", source)

    class FakeImmersiveService:
        @staticmethod
        async def translate(text, language):
            await asyncio.sleep(0.02)
            return "译文"

    monkeypatch.setattr(
        "deeptutor.immersive_reading.get_immersive_reading_service",
        lambda: FakeImmersiveService(),
    )
    first = service.start_run(source_type="kb_document", source_id="one")
    second = service.start_run(source_type="kb_document", source_id="two")
    results = await asyncio.gather(
        service.run(run_id=first["run_id"]),
        service.run(run_id=second["run_id"]),
    )
    assert all(result["summary"]["filtered_completed"] == 1 for result in results)
    assert service.get_run(first["run_id"])["status"] == "completed"
    assert service.get_run(second["run_id"])["status"] == "completed"


async def _collect_stream_events(stream, events, *, expected_groups):
    async for event in stream:
        events.append(event)
        if sum(item["type"] == "group_translated" for item in events) >= expected_groups:
            return


async def _collect_run_events(stream, events):
    async for event in stream:
        events.append(event)


def test_apply_translation_rejects_escaped_sink_paths(setup):
    _fake_path, _pairing_service, service, pairing_id = setup
    service.plan("bilingual", pairing_id)
    bilingual_task = {
        "source_type": "bilingual",
        "source_id": pairing_id,
        "chapter_id": "../../outside",
        "group_index": 0,
    }
    kb_task = {
        "source_type": "kb_document",
        "source_id": "research",
        "document_path": "../outside/article.md",
    }

    with pytest.raises(ValueError, match="Invalid chapter path"):
        service._apply_translation(bilingual_task, "translation")
    with pytest.raises(ValueError, match="Invalid document path"):
        service._apply_translation(kb_task, "translation")


@pytest.mark.asyncio
async def test_write_failure_marks_task_failed_and_preserves_source(monkeypatch, setup):
    from deeptutor.services.translation import service as service_module

    fake_path, pairing_service, service, pairing_id = setup
    board = service.plan("bilingual", pairing_id)
    task = board["tasks"][0]
    task_id = task["id"]
    section_path = (
        fake_path.get_immersive_reading_pairing_root(pairing_id)
        / "sections"
        / f"{task['chapter_id']}.json"
    )
    section = json.loads(section_path.read_text(encoding="utf-8"))
    section["groups"][0]["zh"] = []
    section_path.write_text(json.dumps(section, ensure_ascii=False), encoding="utf-8")

    class FakeImmersiveService:
        @staticmethod
        async def translate(text, language):
            return "translation"

    original_writer = service_module._write_json

    def fail_section_write(path, payload):
        if Path(path).resolve().parent.name == "sections":
            raise OSError("simulated disk failure")
        original_writer(path, payload)

    monkeypatch.setattr(service_module, "_write_json", fail_section_write)
    monkeypatch.setattr(
        "deeptutor.immersive_reading.get_immersive_reading_service", lambda: FakeImmersiveService()
    )
    result = await service.run(source_type="bilingual", source_id=pairing_id)

    task = next(item for item in result["tasks"] if item["id"] == task_id)
    assert task["status"] == "failed"
    assert "simulated disk failure" in task["error"]
    preserved = pairing_service.get_bilingual_section(pairing_id, task["chapter_id"])
    assert preserved["groups"][0]["zh"] == []


@pytest.mark.asyncio
async def test_protection_failure_marks_task_failed_without_writing(
    monkeypatch, setup
):
    from types import SimpleNamespace

    import deeptutor.immersive_reading.service as reading_module
    from deeptutor.immersive_reading.service import ImmersiveReadingService

    fake_path, _pairing_service, service, pairing_id = setup
    section_path = (
        fake_path.get_immersive_reading_pairing_root(pairing_id)
        / "sections"
        / "ch002.json"
    )
    section = json.loads(section_path.read_text(encoding="utf-8"))
    section["groups"][0]["en"] = ["Restore `fetch_user()` exactly."]
    section["groups"][0]["zh"] = []
    section_path.write_text(json.dumps(section, ensure_ascii=False), encoding="utf-8")
    board = service.plan("bilingual", pairing_id)

    monkeypatch.setattr(
        reading_module,
        "get_llm_config",
        lambda: SimpleNamespace(
            model="hy-mt2",
            binding="ollama",
            provider_name="ollama",
            base_url="http://127.0.0.1:11434",
        ),
    )
    calls = 0

    async def broken_placeholders(*_args, **_kwargs):
        nonlocal calls
        calls += 1
        return "丢失 [[DT-KEEP-0]] [[DT-KEEP-0]]"

    reader = ImmersiveReadingService()
    async def _reachable(): return ["hy-mt2"]
    monkeypatch.setattr(reader, "_ensure_ollama_reachable", _reachable)
    monkeypatch.setattr(reader, "_ollama_native_chat", broken_placeholders)
    monkeypatch.setattr(
        "deeptutor.immersive_reading.get_immersive_reading_service", lambda: reader
    )

    result = await service.run(source_type="bilingual", source_id=pairing_id, limit=1)
    failed_task = next(task for task in result["tasks"] if task["source_type"] == "bilingual")
    assert failed_task["status"] == "failed"
    assert "Protected code" in failed_task["error"]
    assert calls == 2
    preserved = _pairing_service.get_bilingual_section(pairing_id, "ch002")
    assert preserved["groups"][0]["zh"] == []


def test_initialization_requeues_interrupted_running_tasks(setup):
    _fake_path, _pairing_service, service, _pairing_id = setup
    state = {"version": 1, "tasks": [], "sources": {}, "is_running": False, "last_run_at": 0}
    state["is_running"] = True
    state["tasks"] = [
        {
            "id": "interrupted",
            "status": "running",
            "started_at": 123,
            "updated_at": 123,
        }
    ]
    service._save(state)

    recovered = TranslationTaskService(service._state_path)
    state = json.loads(recovered._state_path.read_text(encoding="utf-8"))

    assert state["is_running"] is False
    assert state["tasks"][0]["status"] == "queued"
    assert state["tasks"][0]["started_at"] is None
    assert state["version"] == 2
    assert state["runs"] == {}


def test_hymt_model_detection_and_prompt_formatting():
    from deeptutor.services.translation.glossary import (
        is_hymt_model,
        build_hymt_translation_prompt,
    )
    from deeptutor.immersive_reading.service import ImmersiveReadingService

    assert is_hymt_model("hy-mt2") is True
    assert is_hymt_model("Hy-MT2-1.8B") is True
    assert is_hymt_model("hf.co/tencent/Hy-MT2-1.8B-GGUF:Q4_K_M") is True
    assert is_hymt_model("hunyuan-mt-7b") is True
    assert is_hymt_model("qwen3.5:4b") is False

    # Hy-MT2 prompt formatting for Chinese
    zh_prompt = build_hymt_translation_prompt(
        "Deep learning is powerful.",
        "Chinese",
        glossary=[{"term": "Deep learning", "translation": "深度学习", "approved": True}]
    )
    assert "参考下面的翻译：" in zh_prompt
    assert "Deep learning 翻译成 深度学习" in zh_prompt
    assert "将以下文本翻译为 中文，注意只需要输出翻译后的结果，不要额外解释：" in zh_prompt
    assert "Deep learning is powerful." in zh_prompt

    # Hy-MT2 prompt formatting for English
    en_prompt = build_hymt_translation_prompt(
        "今天天气真好。",
        "English",
        glossary=[{"term": "今天", "translation": "today", "approved": True}]
    )
    assert "Reference the following translations:" in en_prompt
    assert "今天 translates to today" in en_prompt
    assert "Translate the following text into English" in en_prompt

    # Translation model resolution prefers Hy-MT2 when available
    installed = ["qwen3.5:4b", "hy-mt2:1.8b", "llama3:8b"]
    assert ImmersiveReadingService._resolve_ollama_model("qwen3.5:4b", installed, for_translation=True) == "qwen3.5:4b"
    assert ImmersiveReadingService._resolve_ollama_model("hy-mt2", installed, for_translation=True) == "hy-mt2:1.8b"
    assert ImmersiveReadingService._resolve_ollama_model("qwen3.5:4b", installed, for_translation=False) == "qwen3.5:4b"
