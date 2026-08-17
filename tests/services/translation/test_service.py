import json
from pathlib import Path

import pytest

from deeptutor.immersive_reading.bilingual.service import BilingualPairingService
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
    position_path = (
        fake_path.get_immersive_reading_pairing_root(pairing_id) / "reading_position.json"
    )
    position_path.write_text(
        json.dumps({"chapter_index": 1, "group_index": 0, "scroll_percent": 0}),
        encoding="utf-8",
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
