"""Unit tests for the quiz-judge WebSocket router.

``deeptutor/api/routers/quiz_judge.py`` previously had little line coverage:
judge prompt assembly, image mime handling, and the WS
judging loop (including disconnect cleanup) were essentially untested.

The LLM is mocked at ``quiz_judge.llm_stream`` — no real provider call is
ever made. The socket is exercised two ways:

* through Starlette's ``TestClient`` for the protocol frames a real client
  sees (started / text / done / error), and
* through a fake WebSocket for deterministic ordering of the disconnect
  and cleanup paths (``TestClient`` cannot control exactly when the send
  side breaks mid-stream).
"""

from __future__ import annotations

import asyncio
import base64
from types import SimpleNamespace
from unittest.mock import MagicMock

from fastapi import FastAPI, WebSocketDisconnect
from fastapi.testclient import TestClient
import pytest

from deeptutor.api.routers import auth, quiz_judge
from deeptutor.api.routers.quiz_judge import (
    _JUDGE_SYSTEM_PROMPTS,
    SUPPORTED_JUDGE_LANGUAGES,
    _build_judge_user_prompt,
    _build_multimodal_user_content,
    _guess_image_mime,
)

_WS_TOKEN = object()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _judge_payload(**overrides) -> dict:
    payload = {
        "question": "What is 2+2?",
        "question_type": "short_answer",
        "options": None,
        "correct_answer": "4",
        "explanation": "2+2 equals 4.",
        "user_answer": "4",
        "language": "en",
    }
    payload.update(overrides)
    return payload


class _ScriptedStream:
    """Drop-in replacement for ``quiz_judge.llm_stream``.

    Records every call and replays scripted chunks. ``endless=True`` keeps
    yielding (with a consumed counter) so a disconnect test can prove the
    handler stopped pulling from the stream. ``exc`` is raised after the
    chunks are exhausted.
    """

    def __init__(self, chunks=(), *, exc: Exception | None = None, endless: bool = False):
        self.chunks = list(chunks)
        self.exc = exc
        self.endless = endless
        self.calls: list[dict] = []
        self.consumed = 0

    async def __call__(self, *, prompt: str, system_prompt: str, **kwargs):
        self.calls.append({"prompt": prompt, "system_prompt": system_prompt, **kwargs})
        if self.endless:
            while True:
                self.consumed += 1
                yield "chunk"
        for chunk in self.chunks:
            self.consumed += 1
            yield chunk
        if self.exc is not None:
            raise self.exc


class _FakeJudgeSocket:
    """Minimal WebSocket stand-in with scriptable failure points."""

    def __init__(self, payload: dict | None, *, ok_sends: int = 10, close_raises: bool = False):
        self._payload = payload
        self._ok_sends = ok_sends
        self._close_raises = close_raises
        self.sent: list[dict] = []
        self.accepted = False
        self.closed = False

    async def accept(self) -> None:
        self.accepted = True

    async def receive_json(self) -> dict:
        if self._payload is None:
            raise WebSocketDisconnect(code=1000)
        return self._payload

    async def send_json(self, payload: dict) -> None:
        if len(self.sent) >= self._ok_sends:
            raise WebSocketDisconnect(code=1001)
        self.sent.append(payload)

    async def close(self) -> None:
        if self._close_raises:
            raise RuntimeError("socket already closed")
        self.closed = True


class _InvalidJsonSocket(_FakeJudgeSocket):
    """receive_json fails the way a malformed text frame does."""

    async def receive_json(self) -> dict:
        raise ValueError("Expecting value")


def _raising_reset(monkeypatch) -> MagicMock:
    from deeptutor.multi_user import context

    spy = MagicMock(side_effect=RuntimeError("reset boom"))
    monkeypatch.setattr(context, "reset_current_user", spy)
    return spy


@pytest.fixture
def reset_spy(monkeypatch) -> MagicMock:
    """Spy on the user-context cleanup the handler must run on exit."""
    from deeptutor.multi_user import context

    spy = MagicMock()
    monkeypatch.setattr(context, "reset_current_user", spy)
    return spy


@pytest.fixture
def ws_token(monkeypatch):
    """Bypass WS auth with a non-None token so cleanup paths activate."""

    async def allow(_websocket):
        return _WS_TOKEN

    monkeypatch.setattr(auth, "ws_require_auth", allow)
    return _WS_TOKEN


@pytest.fixture
def fake_attachment_store(monkeypatch) -> MagicMock:
    from deeptutor.services import storage

    store = MagicMock()
    store.resolve_path = MagicMock(return_value=None)
    monkeypatch.setattr(storage, "get_attachment_store", lambda: store)
    return store


@pytest.fixture
def llm_vision(monkeypatch):
    """Pin the LLM binding/model and vision capability deterministically."""
    from deeptutor.services.llm import capabilities
    from deeptutor.services.llm import config as llm_config_mod

    def _install(supports: bool) -> None:
        monkeypatch.setattr(
            llm_config_mod,
            "get_llm_config",
            lambda: SimpleNamespace(binding="openai", model="gpt-4o-mini"),
        )
        monkeypatch.setattr(capabilities, "supports_vision", lambda binding, model=None: supports)

    return _install


def _judge_client(monkeypatch, stream: _ScriptedStream) -> TestClient:
    monkeypatch.setattr(quiz_judge, "llm_stream", stream)
    app = FastAPI()
    app.include_router(quiz_judge.router, prefix="/ws")
    return TestClient(app)


# ---------------------------------------------------------------------------
# Prompt assembly (pure functions)
# ---------------------------------------------------------------------------


class TestGuessImageMime:
    @pytest.mark.parametrize(
        "filename,expected",
        [
            (None, "image/png"),
            ("", "image/png"),
            ("photo.png", "image/png"),
            ("photo.PNG", "image/png"),
            ("photo.jpg", "image/jpeg"),
            ("photo.JPEG", "image/jpeg"),
            ("anim.gif", "image/gif"),
            ("pic.webp", "image/webp"),
            ("noext", "image/png"),
            ("weird.tiff", "image/png"),
            ("a.b.jpg", "image/jpeg"),
        ],
    )
    def test_common_filenames(self, filename, expected):
        assert _guess_image_mime(filename) == expected


class TestBuildJudgeUserPrompt:
    def test_zh_prompt_carries_question_options_answer_explanation_and_image_note(self):
        prompt = _build_judge_user_prompt(
            language="zh",
            question="地球绕太阳一圈需要多久？",
            question_type="single_choice",
            options={"A": "一天", "B": "一年", "C": "一个月"},
            correct_answer="B",
            explanation="地球公转周期约365天。",
            user_answer="B",
            has_image=True,
            image_count=1,
        )
        assert "题目类型：single_choice" in prompt
        assert "题干：\n地球绕太阳一圈需要多久？" in prompt
        assert "选项：" in prompt
        assert "  A. 一天" in prompt
        assert "  B. 一年" in prompt
        assert "参考答案：\nB" in prompt
        assert "参考解析：\n地球公转周期约365天。" in prompt
        assert "学习者作答：\nB" in prompt
        assert "一张图片" in prompt
        assert prompt.endswith("请针对该学习者的具体作答给出 AI 评判。")

    def test_zh_prompt_reports_multi_image_count(self):
        prompt = _build_judge_user_prompt(
            language="zh",
            question="证明勾股定理",
            question_type="proof",
            options=None,
            correct_answer="见参考",
            explanation="多种证法均可",
            user_answer="如图所示",
            has_image=True,
            image_count=3,
        )
        assert "另附了 3 张图片" in prompt

    def test_zh_prompt_without_optional_fields_omits_them(self):
        prompt = _build_judge_user_prompt(
            language="zh",
            question="1+1=?",
            question_type="",
            options=None,
            correct_answer="",
            explanation="",
            user_answer="2",
            has_image=False,
            image_count=0,
        )
        assert "题目类型：unknown" in prompt
        assert "选项" not in prompt
        assert "参考答案" not in prompt
        assert "参考解析" not in prompt
        assert "图片" not in prompt

    def test_image_only_answer_gets_zh_placeholder(self):
        prompt = _build_judge_user_prompt(
            language="zh",
            question="画出示意图",
            question_type="drawing",
            options=None,
            correct_answer="任意合理示意",
            explanation="",
            user_answer="   ",
            has_image=True,
            image_count=1,
        )
        assert "（仅提交了图片，无文字作答）" in prompt

    def test_en_prompt_carries_question_answer_and_unknown_type(self):
        prompt = _build_judge_user_prompt(
            language="en",
            question="What is 2+2?",
            question_type="",
            options=None,
            correct_answer="4",
            explanation="2+2 equals 4.",
            user_answer="4",
            has_image=False,
            image_count=0,
        )
        assert "Question type: unknown" in prompt
        assert "Question:\nWhat is 2+2?" in prompt
        assert "Reference answer:\n4" in prompt
        assert "Reference explanation:\n2+2 equals 4." in prompt
        assert "Learner's answer:\n4" in prompt
        assert "attached" not in prompt

    def test_en_prompt_renders_options_and_multi_image_note(self):
        prompt = _build_judge_user_prompt(
            language="en",
            question="Pick the primes",
            question_type="multi_choice",
            options={"A": "2", "B": "4", "C": "5"},
            correct_answer="A and C",
            explanation="2 and 5 are prime.",
            user_answer="A",
            has_image=True,
            image_count=2,
        )
        assert "Options:" in prompt
        assert "  A. 2" in prompt
        assert "  B. 4" in prompt
        assert "The learner attached 2 images" in prompt

    def test_image_only_answer_gets_en_placeholder(self):
        prompt = _build_judge_user_prompt(
            language="en",
            question="Sketch the graph",
            question_type="drawing",
            options=None,
            correct_answer="any correct sketch",
            explanation="",
            user_answer="",
            has_image=True,
            image_count=1,
        )
        assert "(only an image was submitted, no typed answer)" in prompt
        assert "attached an image as part of the answer" in prompt

    def test_unrenderable_options_are_dropped_not_fatal(self):
        class _BadOptions(dict):
            def items(self):
                raise TypeError("unrenderable")

        prompt = _build_judge_user_prompt(
            language="en",
            question="Q",
            question_type="t",
            options=_BadOptions(A="a"),
            correct_answer="a",
            explanation="",
            user_answer="a",
            has_image=False,
            image_count=0,
        )
        assert "Options:" not in prompt
        assert "Question:\nQ" in prompt


# ---------------------------------------------------------------------------
# Multimodal content builder
# ---------------------------------------------------------------------------


class TestBuildMultimodalUserContent:
    def test_text_part_comes_first_and_base64_becomes_data_url(self, fake_attachment_store):
        content = asyncio.run(
            _build_multimodal_user_content(
                text="judge this",
                image_records=[
                    {"base64": "QUJD", "url": "", "filename": "a.jpg", "mime_type": "image/jpeg"},
                ],
            )
        )
        assert content[0] == {"type": "text", "text": "judge this"}
        assert content[1] == {
            "type": "image_url",
            "image_url": {"url": "data:image/jpeg;base64,QUJD"},
        }

    def test_url_only_record_is_passed_through(self, fake_attachment_store):
        content = asyncio.run(
            _build_multimodal_user_content(
                text="t",
                image_records=[
                    {"base64": "", "url": "https://cdn.example.com/x.png", "filename": "x.png"},
                ],
            )
        )
        # mime missing → guessed from filename; url cannot be resolved → passed through
        assert content[1] == {
            "type": "image_url",
            "image_url": {"url": "https://cdn.example.com/x.png"},
        }

    def test_local_attachment_url_is_resolved_to_base64(self, fake_attachment_store, tmp_path):
        blob = tmp_path / "photo.jpg"
        blob.write_bytes(b"\xff\xd8jpeg-bytes")
        fake_attachment_store.resolve_path.return_value = blob

        content = asyncio.run(
            _build_multimodal_user_content(
                text="t",
                image_records=[
                    {
                        "base64": "",
                        "url": "/api/attachments/s%201/att%202/photo.jpg",
                        "filename": "photo.jpg",
                    },
                ],
            )
        )
        fake_attachment_store.resolve_path.assert_called_once_with(
            session_id="s 1", attachment_id="att 2", filename="photo.jpg"
        )
        expected_b64 = base64.b64encode(b"\xff\xd8jpeg-bytes").decode("ascii")
        assert content[1]["image_url"]["url"] == f"data:image/jpeg;base64,{expected_b64}"

    def test_unresolvable_attachment_url_falls_back_to_url(self, fake_attachment_store):
        content = asyncio.run(
            _build_multimodal_user_content(
                text="t",
                image_records=[
                    {
                        "base64": "",
                        "url": "/api/attachments/s/a/missing.png",
                        "filename": "missing.png",
                    },
                ],
            )
        )
        assert content[1] == {
            "type": "image_url",
            "image_url": {"url": "/api/attachments/s/a/missing.png"},
        }

    def test_resolution_failure_is_swallowed_and_url_kept(self, fake_attachment_store):
        fake_attachment_store.resolve_path.side_effect = OSError("disk on fire")
        content = asyncio.run(
            _build_multimodal_user_content(
                text="t",
                image_records=[
                    {"base64": "", "url": "/api/attachments/s/a/x.png", "filename": "x.png"},
                ],
            )
        )
        assert content[1] == {
            "type": "image_url",
            "image_url": {"url": "/api/attachments/s/a/x.png"},
        }

    def test_record_without_payload_is_skipped(self, fake_attachment_store):
        content = asyncio.run(
            _build_multimodal_user_content(
                text="t",
                image_records=[{"base64": "", "url": "", "filename": "empty.png"}],
            )
        )
        assert content == [{"type": "text", "text": "t"}]


# ---------------------------------------------------------------------------
# WebSocket protocol (TestClient)
# ---------------------------------------------------------------------------


class TestJudgeVerdicts:
    """The three judgment outcomes a learner can receive, end to end."""

    @pytest.mark.parametrize(
        "scenario,answer,verdict_chunks",
        [
            (
                "correct",
                "4",
                ["✅ Correct — 4 is right.", " 2+2 equals 4, well done."],
            ),
            (
                "wrong",
                "5",
                ["❌ Incorrect — 5 is not 2+2.", " The sum is 4."],
            ),
            (
                "multi_answer",
                "A",
                ["⚠️ Partially correct — A is prime but C also is.", " Both A and C were valid."],
            ),
        ],
    )
    def test_verdict_chunks_are_streamed_then_done(
        self, ws_token, reset_spy, monkeypatch, scenario, answer, verdict_chunks
    ):
        stream = _ScriptedStream(verdict_chunks)
        client = _judge_client(monkeypatch, stream)
        payload = _judge_payload(user_answer=answer)
        if scenario == "multi_answer":
            payload.update(
                question="Pick the primes",
                question_type="multi_choice",
                options={"A": "2", "B": "4", "C": "5"},
                correct_answer="A and C",
                explanation="2 and 5 are prime.",
            )

        with client.websocket_connect("/ws/questions/judge") as ws:
            ws.send_json(payload)
            assert ws.receive_json() == {"type": "started"}
            assert ws.receive_json() == {"type": "text", "content": verdict_chunks[0]}
            assert ws.receive_json() == {"type": "text", "content": verdict_chunks[1]}
            assert ws.receive_json() == {"type": "done"}

        assert len(stream.calls) == 1
        call = stream.calls[0]
        assert call["system_prompt"] == _JUDGE_SYSTEM_PROMPTS["en"]
        assert call["prompt"].startswith("Question type:")
        assert "Learner's answer:\n" + answer in call["prompt"]
        if scenario == "multi_answer":
            assert "Options:" in call["prompt"]
            assert "Reference answer:\nA and C" in call["prompt"]
        reset_spy.assert_called_once_with(ws_token)

    def test_empty_llm_chunks_are_not_relayed(self, ws_token, reset_spy, monkeypatch):
        stream = _ScriptedStream(["", "real text", ""])
        client = _judge_client(monkeypatch, stream)
        with client.websocket_connect("/ws/questions/judge") as ws:
            ws.send_json(_judge_payload())
            assert ws.receive_json() == {"type": "started"}
            assert ws.receive_json() == {"type": "text", "content": "real text"}
            assert ws.receive_json() == {"type": "done"}


class TestJudgeRequestValidation:
    def test_missing_question_is_rejected_without_llm_call(self, ws_token, reset_spy, monkeypatch):
        stream = _ScriptedStream(["never called"])
        client = _judge_client(monkeypatch, stream)
        with client.websocket_connect("/ws/questions/judge") as ws:
            ws.send_json(_judge_payload(question="   "))
            frame = ws.receive_json()
        assert frame == {"type": "error", "content": "Question is required"}
        assert stream.calls == []
        reset_spy.assert_called_once_with(ws_token)

    def test_invalid_json_request_is_reported(self, ws_token, reset_spy, monkeypatch):
        stream = _ScriptedStream(["never called"])
        client = _judge_client(monkeypatch, stream)
        with client.websocket_connect("/ws/questions/judge") as ws:
            ws.send_text("{not json")
            frame = ws.receive_json()
        assert frame["type"] == "error"
        assert frame["content"].startswith("Invalid request:")
        assert stream.calls == []
        reset_spy.assert_called_once_with(ws_token)

    def test_answerless_submission_is_rejected(self, ws_token, reset_spy, monkeypatch):
        stream = _ScriptedStream(["never called"])
        client = _judge_client(monkeypatch, stream)
        with client.websocket_connect("/ws/questions/judge") as ws:
            ws.send_json(_judge_payload(user_answer="   "))
            frame = ws.receive_json()
        assert frame == {
            "type": "error",
            "content": "No answer to judge — submit a typed answer or attach an image.",
        }
        assert stream.calls == []
        reset_spy.assert_called_once_with(ws_token)


class TestJudgeLanguage:
    def test_supported_language_is_used_directly(self, ws_token, reset_spy, monkeypatch):
        def _unexpected(*_args, **_kwargs):
            raise AssertionError(
                "get_response_language must not be consulted for supported languages"
            )

        monkeypatch.setattr(quiz_judge, "get_response_language", _unexpected)
        stream = _ScriptedStream(["добре"])
        client = _judge_client(monkeypatch, stream)
        with client.websocket_connect("/ws/questions/judge") as ws:
            ws.send_json(_judge_payload(language="uk"))
            assert ws.receive_json() == {"type": "started"}
            assert ws.receive_json() == {"type": "text", "content": "добре"}
            assert ws.receive_json() == {"type": "done"}
        assert stream.calls[0]["system_prompt"] == _JUDGE_SYSTEM_PROMPTS["uk"]

    def test_unsupported_language_falls_back_to_interface_language(
        self, ws_token, reset_spy, monkeypatch
    ):
        monkeypatch.setattr(quiz_judge, "get_response_language", lambda *, default: "de")
        stream = _ScriptedStream(["gut"])
        client = _judge_client(monkeypatch, stream)
        with client.websocket_connect("/ws/questions/judge") as ws:
            ws.send_json(_judge_payload(language="klingon"))
            assert ws.receive_json() == {"type": "started"}
            assert ws.receive_json() == {"type": "text", "content": "gut"}
            assert ws.receive_json() == {"type": "done"}
        assert stream.calls[0]["system_prompt"] == _JUDGE_SYSTEM_PROMPTS["de"]

    def test_unsupported_interface_language_falls_back_to_english(
        self, ws_token, reset_spy, monkeypatch
    ):
        monkeypatch.setattr(quiz_judge, "get_response_language", lambda *, default: "klingon")
        stream = _ScriptedStream(["ok"])
        client = _judge_client(monkeypatch, stream)
        with client.websocket_connect("/ws/questions/judge") as ws:
            ws.send_json(_judge_payload(language=""))
            assert ws.receive_json() == {"type": "started"}
            assert ws.receive_json() == {"type": "text", "content": "ok"}
            assert ws.receive_json() == {"type": "done"}
        assert stream.calls[0]["system_prompt"] == _JUDGE_SYSTEM_PROMPTS["en"]

    def test_supported_languages_mirror_available_prompts(self):
        assert SUPPORTED_JUDGE_LANGUAGES == frozenset(_JUDGE_SYSTEM_PROMPTS)
        assert {"zh", "en", "de", "uk"} <= SUPPORTED_JUDGE_LANGUAGES


class TestJudgeImages:
    def test_vision_model_receives_multimodal_messages_with_image_mimes(
        self, ws_token, reset_spy, monkeypatch, fake_attachment_store, llm_vision
    ):
        llm_vision(supports=True)
        stream = _ScriptedStream(["looking at your sketch"])
        client = _judge_client(monkeypatch, stream)
        payload = _judge_payload(
            user_answer="",
            user_answer_images=[
                {"base64": "data:image/jpeg;base64,QUJD", "filename": "work.jpg"},
                {
                    "url": "https://cdn.example.com/sketch.webp",
                    "filename": "sketch.webp",
                    "mime_type": "image/webp",
                },
                "not-a-dict",  # junk entries are skipped
                {"filename": "no-payload.png"},  # neither base64 nor url → skipped
            ],
        )

        with client.websocket_connect("/ws/questions/judge") as ws:
            ws.send_json(payload)
            assert ws.receive_json() == {"type": "started"}
            assert ws.receive_json() == {"type": "text", "content": "looking at your sketch"}
            assert ws.receive_json() == {"type": "done"}

        call = stream.calls[0]
        messages = call["messages"]
        assert messages[0] == {"role": "system", "content": _JUDGE_SYSTEM_PROMPTS["en"]}
        user_content = messages[1]["content"]
        assert user_content[0]["type"] == "text"
        assert "(only an image was submitted, no typed answer)" in user_content[0]["text"]
        # data: prefix stripped, mime preserved from the record / guessed from filename
        assert user_content[1] == {
            "type": "image_url",
            "image_url": {"url": "data:image/jpeg;base64,QUJD"},
        }
        assert user_content[2] == {
            "type": "image_url",
            "image_url": {"url": "https://cdn.example.com/sketch.webp"},
        }
        assert len(user_content) == 3
        assert "The learner attached 2 images" in call["prompt"]
        reset_spy.assert_called_once_with(ws_token)

    def test_non_vision_model_judges_the_typed_answer_text_only(
        self, ws_token, reset_spy, monkeypatch, fake_attachment_store, llm_vision
    ):
        llm_vision(supports=False)
        stream = _ScriptedStream(["text-only feedback"])
        client = _judge_client(monkeypatch, stream)
        payload = _judge_payload(
            user_answer="my written reasoning",
            user_answer_images=[
                {"base64": "QUJD", "filename": "work.jpg", "mime_type": "image/jpeg"}
            ],
        )

        with client.websocket_connect("/ws/questions/judge") as ws:
            ws.send_json(payload)
            assert ws.receive_json() == {"type": "started"}
            assert ws.receive_json() == {"type": "text", "content": "text-only feedback"}
            assert ws.receive_json() == {"type": "done"}

        call = stream.calls[0]
        assert "messages" not in call
        assert "my written reasoning" in call["prompt"]
        assert "attached an image" in call["prompt"]
        reset_spy.assert_called_once_with(ws_token)

    def test_legacy_single_image_form_is_normalized(
        self, ws_token, reset_spy, monkeypatch, fake_attachment_store, llm_vision
    ):
        llm_vision(supports=True)
        stream = _ScriptedStream(["ok"])
        client = _judge_client(monkeypatch, stream)
        payload = _judge_payload(
            user_answer_image="data:image/png;base64,QUJD", image_filename="scan.png"
        )

        with client.websocket_connect("/ws/questions/judge") as ws:
            ws.send_json(payload)
            assert ws.receive_json() == {"type": "started"}
            assert ws.receive_json() == {"type": "text", "content": "ok"}
            assert ws.receive_json() == {"type": "done"}

        user_content = stream.calls[0]["messages"][1]["content"]
        assert user_content[1] == {
            "type": "image_url",
            "image_url": {"url": "data:image/png;base64,QUJD"},
        }
        assert "attached an image" in stream.calls[0]["prompt"]

    def test_malformed_data_url_entries_are_dropped(
        self, ws_token, reset_spy, monkeypatch, fake_attachment_store, llm_vision
    ):
        llm_vision(supports=True)
        stream = _ScriptedStream(["ok"])
        client = _judge_client(monkeypatch, stream)
        # "data:" with no comma — the payload split fails, the entry is dropped
        payload = _judge_payload(
            user_answer="typed answer",
            user_answer_images=[{"base64": "data:image/png;base64-no-comma", "filename": "x.png"}],
        )

        with client.websocket_connect("/ws/questions/judge") as ws:
            ws.send_json(payload)
            assert ws.receive_json() == {"type": "started"}
            assert ws.receive_json() == {"type": "text", "content": "ok"}
            assert ws.receive_json() == {"type": "done"}

        assert "messages" not in stream.calls[0]
        assert "attached an image" not in stream.calls[0]["prompt"]

    def test_legacy_data_url_without_payload_part_is_dropped(
        self, ws_token, reset_spy, monkeypatch
    ):
        stream = _ScriptedStream(["fine"])
        client = _judge_client(monkeypatch, stream)
        payload = _judge_payload(
            user_answer="written answer",
            user_answer_image="data:image/png;base64,",  # empty payload after the comma
        )
        with client.websocket_connect("/ws/questions/judge") as ws:
            ws.send_json(payload)
            assert ws.receive_json() == {"type": "started"}
            assert ws.receive_json() == {"type": "text", "content": "fine"}
            assert ws.receive_json() == {"type": "done"}
        # "data:...," splits to an empty payload — falsy, treated as no image
        assert "messages" not in stream.calls[0]
        assert "attached an image" not in stream.calls[0]["prompt"]

    def test_legacy_malformed_data_url_is_dropped(self, ws_token, reset_spy, monkeypatch):
        stream = _ScriptedStream(["fine"])
        client = _judge_client(monkeypatch, stream)
        payload = _judge_payload(
            user_answer="written answer",
            user_answer_image="data:image/png;base64-no-comma",  # split fails → dropped
        )
        with client.websocket_connect("/ws/questions/judge") as ws:
            ws.send_json(payload)
            assert ws.receive_json() == {"type": "started"}
            assert ws.receive_json() == {"type": "text", "content": "fine"}
            assert ws.receive_json() == {"type": "done"}
        assert "messages" not in stream.calls[0]
        assert "attached an image" not in stream.calls[0]["prompt"]


# ---------------------------------------------------------------------------
# Failure & cleanup paths (fake WebSocket — deterministic ordering)
# ---------------------------------------------------------------------------


class TestJudgeDisconnectAndCleanup:
    def test_client_disconnect_mid_stream_stops_pulling_and_cleans_up(
        self, ws_token, reset_spy, monkeypatch
    ):
        stream = _ScriptedStream(endless=True)
        monkeypatch.setattr(quiz_judge, "llm_stream", stream)
        socket = _FakeJudgeSocket(_judge_payload(), ok_sends=3)

        asyncio.run(quiz_judge.websocket_quiz_judge(socket))

        # started + 2 text frames delivered; the 3rd chunk's send fails → break
        assert [frame["type"] for frame in socket.sent] == ["started", "text", "text"]
        assert stream.consumed == 3
        assert socket.accepted is True
        assert socket.closed is True
        reset_spy.assert_called_once_with(ws_token)

    def test_stream_timeout_is_reported_as_error_and_socket_closed(
        self, ws_token, reset_spy, monkeypatch
    ):
        stream = _ScriptedStream(["partial"], exc=TimeoutError())
        monkeypatch.setattr(quiz_judge, "llm_stream", stream)
        socket = _FakeJudgeSocket(_judge_payload())

        asyncio.run(quiz_judge.websocket_quiz_judge(socket))

        assert socket.sent[-1] == {
            "type": "error",
            "content": "AI judge timed out. Please try again.",
        }
        assert socket.sent[0] == {"type": "started"}
        assert socket.closed is True
        reset_spy.assert_called_once_with(ws_token)

    def test_stream_failure_is_reported_as_error_frame(self, ws_token, reset_spy, monkeypatch):
        stream = _ScriptedStream([], exc=RuntimeError("judge backend exploded"))
        monkeypatch.setattr(quiz_judge, "llm_stream", stream)
        socket = _FakeJudgeSocket(_judge_payload())

        asyncio.run(quiz_judge.websocket_quiz_judge(socket))

        assert socket.sent[0] == {"type": "started"}
        assert socket.sent[-1] == {"type": "error", "content": "judge backend exploded"}
        assert socket.closed is True
        reset_spy.assert_called_once_with(ws_token)

    def test_stream_disconnect_error_ends_the_judge_quietly(self, ws_token, reset_spy, monkeypatch):
        stream = _ScriptedStream(["partial"], exc=WebSocketDisconnect(code=1001))
        monkeypatch.setattr(quiz_judge, "llm_stream", stream)
        socket = _FakeJudgeSocket(_judge_payload())

        asyncio.run(quiz_judge.websocket_quiz_judge(socket))

        # the mid-stream disconnect is not an error for the learner — just ends
        assert socket.sent == [
            {"type": "started"},
            {"type": "text", "content": "partial"},
        ]
        assert socket.closed is True
        reset_spy.assert_called_once_with(ws_token)

    def test_cleanup_failures_during_happy_path_are_swallowed(self, ws_token, monkeypatch):
        raising_reset = _raising_reset(monkeypatch)
        stream = _ScriptedStream(["fine"])
        monkeypatch.setattr(quiz_judge, "llm_stream", stream)
        socket = _FakeJudgeSocket(_judge_payload(), close_raises=True)

        asyncio.run(quiz_judge.websocket_quiz_judge(socket))

        assert socket.sent[-1] == {"type": "done"}
        raising_reset.assert_called_once_with(ws_token)

    def test_missing_question_cleanup_failures_are_swallowed(self, ws_token, monkeypatch):
        raising_reset = _raising_reset(monkeypatch)
        stream = _ScriptedStream(["never called"])
        monkeypatch.setattr(quiz_judge, "llm_stream", stream)
        socket = _FakeJudgeSocket(_judge_payload(question="  "), close_raises=True)

        asyncio.run(quiz_judge.websocket_quiz_judge(socket))

        assert socket.sent == [{"type": "error", "content": "Question is required"}]
        raising_reset.assert_called_once_with(ws_token)

    def test_invalid_json_cleanup_failures_are_swallowed(self, ws_token, monkeypatch):
        raising_reset = _raising_reset(monkeypatch)
        stream = _ScriptedStream(["never called"])
        monkeypatch.setattr(quiz_judge, "llm_stream", stream)
        socket = _InvalidJsonSocket(None, close_raises=True)

        asyncio.run(quiz_judge.websocket_quiz_judge(socket))

        assert len(socket.sent) == 1
        assert socket.sent[0]["type"] == "error"
        assert socket.sent[0]["content"].startswith("Invalid request:")
        raising_reset.assert_called_once_with(ws_token)

    def test_answerless_cleanup_failures_are_swallowed(self, ws_token, monkeypatch):
        raising_reset = _raising_reset(monkeypatch)
        stream = _ScriptedStream(["never called"])
        monkeypatch.setattr(quiz_judge, "llm_stream", stream)
        socket = _FakeJudgeSocket(_judge_payload(user_answer="   "), close_raises=True)

        asyncio.run(quiz_judge.websocket_quiz_judge(socket))

        assert socket.sent[0]["type"] == "error"
        assert socket.sent[0]["content"].startswith("No answer to judge")
        raising_reset.assert_called_once_with(ws_token)

    def test_failed_ws_auth_returns_without_accepting(self, monkeypatch, reset_spy):
        async def deny(_websocket):
            return auth.ws_auth_failed

        monkeypatch.setattr(auth, "ws_require_auth", deny)
        socket = _FakeJudgeSocket(_judge_payload())

        asyncio.run(quiz_judge.websocket_quiz_judge(socket))

        assert socket.accepted is False
        assert socket.sent == []
        assert socket.closed is False
        reset_spy.assert_not_called()

    def test_disconnect_before_request_returns_without_llm_call(
        self, ws_token, monkeypatch, reset_spy
    ):
        stream = _ScriptedStream(["never called"])
        monkeypatch.setattr(quiz_judge, "llm_stream", stream)
        socket = _FakeJudgeSocket(None)  # receive_json raises WebSocketDisconnect

        asyncio.run(quiz_judge.websocket_quiz_judge(socket))

        assert socket.sent == []
        assert stream.calls == []
