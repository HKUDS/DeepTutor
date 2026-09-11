from __future__ import annotations

import asyncio
import json
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest

from deeptutor.capabilities.audio_overview.capability import AudioOverviewCapability
from deeptutor.capabilities.audio_overview.pipeline import (
    AudioOverviewError,
    AudioOverviewPipeline,
    normalize_rag_result,
    parse_script,
)
from deeptutor.capabilities.audio_overview.request_config import AudioOverviewRequestConfig
from deeptutor.core.context import UnifiedContext
from deeptutor.core.stream import StreamEventType
from deeptutor.runtime.bootstrap.builtin_capabilities import (
    BUILTIN_CAPABILITY_CLASSES,
    BUILTIN_CAPABILITY_SPECS,
)
from deeptutor.runtime.request_contracts import CAPABILITY_CONFIG_MODELS
from deeptutor.runtime.stream_bus import StreamBus


def test_audio_overview_is_registered_with_request_contract() -> None:
    assert "audio_overview" in BUILTIN_CAPABILITY_CLASSES
    assert (
        BUILTIN_CAPABILITY_SPECS["audio_overview"].class_path
        == (BUILTIN_CAPABILITY_CLASSES["audio_overview"])
    )
    assert CAPABILITY_CONFIG_MODELS["audio_overview"] is AudioOverviewRequestConfig

    manifest = AudioOverviewCapability.manifest
    assert manifest.stages == [
        "retrieving",
        "script_writing",
        "voice_generation",
        "publishing",
    ]
    assert manifest.request_schema["properties"]["target_minutes"]["default"] == 5


@pytest.mark.asyncio
async def test_audio_overview_requires_kb_before_external_calls() -> None:
    capability = AudioOverviewCapability()
    with pytest.raises(AudioOverviewError, match="knowledge base"):
        await capability.run(UnifiedContext(user_message="Summarize"), StreamBus())


def test_parse_script_enforces_alternation_and_known_citations() -> None:
    script = parse_script(
        json.dumps(
            {
                "title": "Overview",
                "segments": [
                    {"speaker": "host", "text": "Welcome.", "source_ids": []},
                    {"speaker": "expert", "text": "The mechanism.", "source_ids": ["S1", "S1"]},
                ],
            }
        ),
        {"S1"},
    )
    assert script.segments[1].source_ids == ["S1"]

    with pytest.raises(AudioOverviewError, match="segment 2"):
        parse_script(
            json.dumps(
                {
                    "title": "Overview",
                    "segments": [
                        {"speaker": "host", "text": "Welcome."},
                        {"speaker": "host", "text": "Wrong role."},
                    ],
                }
            ),
            {"S1"},
        )

    with pytest.raises(AudioOverviewError, match="Invalid citation"):
        parse_script(
            json.dumps(
                {
                    "title": "Overview",
                    "segments": [
                        {"speaker": "host", "text": "Welcome."},
                        {"speaker": "expert", "text": "Claim.", "source_ids": ["S9"]},
                    ],
                }
            ),
            {"S1"},
        )


def test_normalize_rag_result_maps_bounded_citations() -> None:
    context = normalize_rag_result(
        {
            "answer": "Grounded answer",
            "sources": [
                {
                    "title": "/tmp/library/Systems Design.pdf",
                    "page": 4,
                    "text": "Queues absorb bursts." * 300,
                }
            ],
        }
    )

    assert context.citation_ids == {"S1"}
    citation = context.citations[0]
    assert citation.title == "Systems Design.pdf"
    assert citation.locator == "4"
    assert len(citation.snippet) == 2_000


@pytest.mark.asyncio
async def test_pipeline_generates_two_voices_and_publishes_workspace_items(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    rag_calls: list[tuple[str, str, int]] = []

    async def fake_rag(query: str, kb_name: str, *, top_k: int) -> dict[str, Any]:
        rag_calls.append((query, kb_name, top_k))
        return {
            "answer": "Retries use bounded backoff.",
            "sources": [{"title": "Reliability.pdf", "page": 2, "text": "Retry with backoff."}],
        }

    async def fake_complete(prompt: str, system_prompt: str) -> str:
        assert "Reliability.pdf" in prompt
        assert system_prompt
        return json.dumps(
            {
                "title": "Reliability Overview",
                "segments": [
                    {"speaker": "host", "text": "Let's begin.", "source_ids": []},
                    {
                        "speaker": "expert",
                        "text": "Backoff controls retries.",
                        "source_ids": ["S1"],
                    },
                ],
            }
        )

    speech_calls: list[dict[str, Any]] = []

    async def fake_speech(text: str, **kwargs: Any) -> tuple[bytes, str]:
        speech_calls.append({"text": text, **kwargs})
        return (f"audio:{text}".encode(), "audio/mpeg")

    published: list[list[dict[str, Any]]] = []

    class FakeWorkspaceService:
        def binding_by_id(self, workspace_id: str) -> SimpleNamespace:
            assert workspace_id == "ws_test"
            return SimpleNamespace(workspace_id=workspace_id)

        def publish(self, binding: SimpleNamespace, rows: list[dict[str, Any]]) -> list[Any]:
            published.append(rows)
            return [
                SimpleNamespace(
                    to_dict=lambda row=row, index=index: {
                        "workspace_id": binding.workspace_id,
                        "workspace_item_id": f"wsi_{index}",
                        "relative_path": row["path"],
                        "filename": Path(row["path"]).name,
                        "mime_type": "audio/mpeg" if index == 0 else "text/markdown",
                        "url": f"/files/workspace-items/{index}",
                        "title": row["title"],
                        "caption": row["caption"],
                        "generated": True,
                    }
                )
                for index, row in enumerate(rows)
            ]

    import deeptutor.services.workspace as workspace_module

    monkeypatch.setattr(
        workspace_module,
        "get_content_workspace_service",
        lambda: FakeWorkspaceService(),
    )

    output_dir = tmp_path / "outputs" / "audio_overview" / "session" / "turn"
    pipeline = AudioOverviewPipeline(
        language="en",
        system_prompt="Return JSON.",
        instruction_prompt="Create the overview.",
        rag_search_func=fake_rag,
        complete_func=fake_complete,
        speech_func=fake_speech,
        workspace_output_dir=output_dir,
        workspace_logical_dir="outputs/audio_overview/session/turn",
        workspace_id="ws_test",
    )
    context = await pipeline.retrieve(
        topic="reliability",
        kb_name="engineering",
        request_config=AudioOverviewRequestConfig(),
    )
    script = await pipeline.generate_script(
        topic="reliability",
        context=context,
        request_config=AudioOverviewRequestConfig(),
    )
    artifacts = await pipeline.publish(
        turn_id="turn-42",
        script=script,
        context=context,
        request_config=AudioOverviewRequestConfig(host_voice="alloy", expert_voice="nova"),
    )

    assert rag_calls == [("reliability audio overview", "engineering", 6)]
    assert [call["voice"] for call in speech_calls] == ["alloy", "nova"]
    assert artifacts.audio_path.read_bytes() == b"audio:Let's begin.audio:Backoff controls retries."
    assert "[S1] Reliability.pdf" in artifacts.transcript_path.read_text(encoding="utf-8")
    assert [row["path"] for row in published[0]] == [
        "outputs/audio_overview/session/turn/turn-42-audio-overview.mp3",
        "outputs/audio_overview/session/turn/turn-42-audio-overview.md",
    ]
    assert [item["workspace_item_id"] for item in artifacts.workspace_items] == [
        "wsi_0",
        "wsi_1",
    ]


@pytest.mark.asyncio
async def test_capability_publishes_two_workspace_attachments() -> None:
    async def fake_retrieve(self, **kwargs: Any) -> Any:
        return normalize_rag_result(
            {
                "answer": "Context",
                "sources": [{"title": "Source.pdf", "page": 1, "text": "Evidence"}],
            }
        )

    async def fake_generate(self, **kwargs: Any) -> Any:
        return parse_script(
            json.dumps(
                {
                    "title": "Overview",
                    "segments": [
                        {"speaker": "host", "text": "Hello."},
                        {"speaker": "expert", "text": "Detail.", "source_ids": ["S1"]},
                    ],
                }
            ),
            {"S1"},
        )

    async def fake_publish(self, **kwargs: Any) -> Any:
        from deeptutor.capabilities.audio_overview.pipeline import AudioOverviewArtifacts

        return AudioOverviewArtifacts(
            title="Overview",
            script=kwargs["script"],
            transcript="# Overview\n",
            audio_path=Path("/tmp/unused.mp3"),
            transcript_path=Path("/tmp/unused.md"),
            citations=[{"source_id": "S1", "title": "Source.pdf", "locator": "1"}],
            workspace_items=[
                {"workspace_item_id": "audio", "filename": "overview.mp3"},
                {"workspace_item_id": "transcript", "filename": "overview.md"},
            ],
        )

    from unittest.mock import patch

    with (
        patch.object(AudioOverviewPipeline, "retrieve", fake_retrieve),
        patch.object(AudioOverviewPipeline, "generate_script", fake_generate),
        patch.object(AudioOverviewPipeline, "publish", fake_publish),
    ):
        bus = StreamBus()
        events: list[Any] = []

        async def consume() -> None:
            async for event in bus.subscribe():
                events.append(event)

        consumer = asyncio.create_task(consume())
        await asyncio.sleep(0)
        context = UnifiedContext(
            user_message="overview",
            knowledge_bases=["kb"],
            runtime=SimpleNamespace(
                workspace=SimpleNamespace(
                    output_dir="/tmp",
                    logical_output_dir="outputs/audio_overview/s/t",
                    workspace_id="ws",
                )
            ),
        )
        await AudioOverviewCapability().run(context, bus)
        await bus.close()
        await consumer

    source_events = [event for event in events if event.type == StreamEventType.SOURCES]
    assert len(source_events) == 2
    workspace_items = source_events[-1].metadata["sources"]
    assert [item["workspace_item_id"] for item in workspace_items] == [
        "audio",
        "transcript",
    ]
    assert all(item["type"] == "workspace_item" for item in workspace_items)
