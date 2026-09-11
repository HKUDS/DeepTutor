"""KB Audio Overview capability."""

from __future__ import annotations

from typing import Any
import uuid

from deeptutor.agents._shared.capability_result import emit_capability_result
from deeptutor.capabilities.audio_overview.pipeline import (
    AudioOverviewError,
    AudioOverviewPipeline,
)
from deeptutor.capabilities.audio_overview.request_config import AudioOverviewRequestConfig
from deeptutor.core.capability_protocol import CapabilityManifest, StreamBusProtocol, TurnCapability
from deeptutor.core.context import UnifiedContext
from deeptutor.i18n import StatusI18n
from deeptutor.runtime.agentic.usage import UsageTracker
from deeptutor.runtime.request_contracts import get_capability_request_schema


class AudioOverviewCapability(TurnCapability):
    manifest = CapabilityManifest(
        name="audio_overview",
        description="Create a grounded two-voice audio overview and transcript from a knowledge base.",
        stages=["retrieving", "script_writing", "voice_generation", "publishing"],
        tools_used=["rag"],
        cli_aliases=["audio-overview", "overview"],
        request_schema=get_capability_request_schema("audio_overview"),
        config_defaults={
            "topic": "",
            "target_minutes": 5,
            "host_voice": "alloy",
            "expert_voice": "nova",
            "max_context_chunks": 6,
        },
    )

    async def run(self, context: UnifiedContext, stream: StreamBusProtocol) -> None:
        i18n = StatusI18n(self.name, context.language, module="capabilities")
        kb_name = str(context.knowledge_bases[0]) if context.knowledge_bases else ""
        if not kb_name:
            raise AudioOverviewError(
                i18n.t("missing_kb", "Attach a knowledge base to create an audio overview.")
            )

        request_config = AudioOverviewRequestConfig.model_validate(context.config_overrides or {})
        if request_config.topic and request_config.topic != context.user_message:
            topic = request_config.topic
        else:
            topic = context.user_message or "Knowledge base overview"

        workspace = context.runtime.workspace
        if workspace is None or not workspace.output_dir:
            raise AudioOverviewError(
                i18n.t("missing_workspace", "No writable runtime workspace is available.")
            )

        from deeptutor.services.prompt import get_prompt_manager

        prompts = get_prompt_manager().load_prompts(
            "capabilities",
            self.name,
            language=context.language,
        )
        usage = UsageTracker()
        pipeline = AudioOverviewPipeline(
            language=context.language,
            system_prompt=str(prompts.get("system") or ""),
            instruction_prompt=str(prompts.get("instructions") or ""),
            workspace_output_dir=workspace.output_dir,
            workspace_logical_dir=workspace.logical_output_dir,
            workspace_id=workspace.workspace_id,
        )

        turn_id = str(context.metadata.get("turn_id", "") or context.session_id or uuid.uuid4().hex)
        async with stream.stage("retrieving", source=self.name):
            retrieved = await pipeline.retrieve(
                topic=topic,
                kb_name=kb_name,
                request_config=request_config,
            )
            if retrieved.citations:
                await stream.sources(
                    [
                        {"type": "rag", "kb_name": kb_name, **citation.reference_dict()}
                        for citation in retrieved.citations
                    ],
                    source=self.name,
                    stage="retrieving",
                )

        async with stream.stage("script_writing", source=self.name):
            script = await pipeline.generate_script(
                topic=topic,
                context=retrieved,
                request_config=request_config,
            )

        artifacts: Any
        async with stream.stage("voice_generation", source=self.name):
            artifacts = await pipeline.publish(
                turn_id=turn_id,
                script=script,
                context=retrieved,
                request_config=request_config,
            )

        async with stream.stage("publishing", source=self.name):
            if artifacts.workspace_items:
                await stream.sources(
                    [{"type": "workspace_item", **item} for item in artifacts.workspace_items],
                    source=self.name,
                    stage="publishing",
                )

        await emit_capability_result(
            stream,
            {
                "response": artifacts.transcript,
                "title": artifacts.title,
                "kb_name": kb_name,
                "selected_kbs": list(context.knowledge_bases),
                "citations": artifacts.citations,
                "segments": [segment.model_dump() for segment in artifacts.script.segments],
                "audio_path": artifacts.audio_path.name,
                "transcript_path": artifacts.transcript_path.name,
                "workspace_items": artifacts.workspace_items,
            },
            source=self.name,
            usage=usage,
        )


__all__ = ["AudioOverviewCapability"]
