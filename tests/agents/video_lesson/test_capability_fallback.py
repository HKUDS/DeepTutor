"""候选回退必须恢复同一次生成的源码、语音和播放器。"""

from pathlib import Path
from types import SimpleNamespace

import pytest

from deeptutor.agents.video_lesson import capability, lesson_writer, narration, runtime
from deeptutor.agents.video_lesson.lesson_writer import LessonDraft
from deeptutor.agents.video_lesson.narration import Clip
from deeptutor.core.context import UnifiedContext
from deeptutor.runtime.stream_bus import StreamBus


@pytest.mark.asyncio
async def test_parse_failures_restore_previous_compiled_candidate(monkeypatch, tmp_path: Path):
    from deeptutor.services import path_service
    from deeptutor.services.llm import config as llm_config
    from deeptutor.services.model_selection import task_agent

    good = LessonDraft("原始标题", "原始摘要", "原始源码", "原始回复")
    broken = LessonDraft("错误标题", "错误摘要", "", "无代码")

    class Writer:
        def __init__(self, **kwargs):
            pass

        def set_trace_callback(self, callback):
            pass

        def start(self, **kwargs):
            pass

        def add_feedback(self, **kwargs):
            pass

        async def write(self, *, attempt):
            return good if attempt == 1 else broken

    async def prepare_runtime():
        return tmp_path

    async def fake_narrate(lines, language, cache):
        return {"s1": Clip("声音", 30, [(0, "声音")], b"fixture-audio")}

    async def fake_build(lesson, bundle):
        bundle.write_text("fixture bundle", encoding="utf-8")
        return runtime.BuildResult(True, "done", [], [{"frame": 59}])

    captured = {}

    async def capture(stream, payload, **kwargs):
        captured.update(payload)

    monkeypatch.setattr(lesson_writer, "LessonWriterAgent", Writer)
    monkeypatch.setattr(runtime, "ensure_runtime", prepare_runtime)
    monkeypatch.setattr(runtime, "build_lesson", fake_build)
    monkeypatch.setattr(narration, "narrate", fake_narrate)
    monkeypatch.setattr(
        llm_config,
        "get_llm_config",
        lambda: SimpleNamespace(api_key="", base_url="", api_version="", model="fixture"),
    )
    monkeypatch.setattr(task_agent, "task_model_agent", lambda factory: None)
    monkeypatch.setattr(
        path_service,
        "get_path_service",
        lambda: SimpleNamespace(get_agent_dir=lambda name: tmp_path, user_data_dir=tmp_path),
    )
    monkeypatch.setattr(capability, "emit_capability_result", capture)
    monkeypatch.setattr(
        capability.VideoLessonCapability, "_layout_issues", lambda *args: ["collision"]
    )

    await capability.VideoLessonCapability().run(
        UnifiedContext(session_id="turn", user_message="问题", language="zh"), StreamBus()
    )

    assert captured["title"] == "原始标题"
    assert captured["code"]["content"] == "原始源码"
    assert captured["render"]["narrated"] is True
    assert (tmp_path / "turn" / "source" / "Lesson.tsx").read_text() == "原始源码"
    assert "fixture bundle" in (tmp_path / "turn" / "artifacts" / "lesson.html").read_text()
