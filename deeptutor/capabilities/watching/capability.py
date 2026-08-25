"""Loop capability that grounds chat turns in the current video segment."""

from __future__ import annotations

import logging
from typing import Any

from deeptutor.capabilities.protocol import PromptBlock
from deeptutor.core.context import UnifiedContext

logger = logging.getLogger(__name__)

MATERIAL_ID_KEY = "timed_media_id"
VIEWPORT_KEY = "timed_media_viewport"
MODE_KEY = "immersive_watching_mode"


def resolve_material_id(context: UnifiedContext) -> str:
    return str((context.metadata or {}).get(MATERIAL_ID_KEY) or "").strip().lower()


def resolve_viewport(context: UnifiedContext) -> dict[str, Any]:
    value = (context.metadata or {}).get(VIEWPORT_KEY)
    return value if isinstance(value, dict) else {}


class WatchingCapability:
    name = "immersive_watching"
    owned_tools: tuple[str, ...] = ()

    def is_active(self, context: UnifiedContext) -> bool:
        return bool(resolve_material_id(context) or (context.metadata or {}).get(MODE_KEY))

    def system_block(self, context: UnifiedContext, *, language: str, prompts: dict[str, Any]) -> PromptBlock | None:
        del prompts
        material_id = resolve_material_id(context)
        if not material_id:
            if not (context.metadata or {}).get(MODE_KEY):
                return None
            return PromptBlock(
                name="immersive_watching",
                content="The user selected Immersive Watching but has not opened a YouTube learning material. Ask them to paste a YouTube URL.",
            )
        try:
            from deeptutor.video_learning import TimedMediaNotFound, get_timed_media_store

            material = get_timed_media_store().get(material_id)
        except TimedMediaNotFound:
            return PromptBlock(name="immersive_watching", content="The selected video learning material is unavailable. Ask the user to resolve the YouTube URL again.")
        source = material.get("source", {})
        metadata = material.get("metadata", {})
        viewport = resolve_viewport(context)
        current = float(viewport.get("time_seconds") or source.get("entry_time_seconds") or 0)
        segment = next((row for row in material.get("segments", []) if isinstance(row, dict) and float(row.get("start") or 0) <= current <= float(row.get("end") or 0)), None)
        text = str(segment.get("text") or "") if segment else ""
        language_hint = "Answer in the user's language." if str(language).lower().startswith("zh") else "Answer in the user's language."
        content = (
            "You are tutoring alongside a video in DeepTutor Immersive Watching. "
            "Ground explanations in the timed transcript and never invent a visual detail not present in the supplied context. "
            "When referring to the video, cite timestamps as [MM:SS] or [H:MM:SS]. "
            f"{language_hint}\n"
            f"Video: {metadata.get('title') or source.get('video_id')} by {metadata.get('author') or 'unknown'}\n"
            f"Current playback position: {current:.1f}s ({_timestamp(current)})\n"
        )
        if text:
            content += f"Current transcript segment ({segment.get('start', 0):.1f}-{segment.get('end', 0):.1f}s): {text}\n"
        if material.get("transcript", {}).get("cues"):
            nearby = [row for row in material["transcript"]["cues"] if abs(float(row.get("start") or 0) - current) <= 60]
            if nearby:
                content += "Nearby transcript:\n" + "\n".join(f"[{_timestamp(row.get('start', 0))}] {row.get('text', '')}" for row in nearby[:24])
        marks = (material.get("learning") or {}).get("marks") if isinstance(material.get("learning"), dict) else None
        if isinstance(marks, list):
            nearby_marks = [
                row for row in marks
                if isinstance(row, dict) and abs(float(row.get("start_seconds") or 0) - current) <= 90
            ]
            if nearby_marks:
                content += "\nLearner marks (private to DeepTutor, not Invidious):\n"
                content += "\n".join(
                    f"- {row.get('kind')} [{_timestamp(row.get('start_seconds', 0))}-{_timestamp(row.get('end_seconds', 0))}] {row.get('quote') or row.get('note') or ''}"
                    for row in nearby_marks[:12]
                )
        return PromptBlock(name="immersive_watching", content=content)

    def augment_kwargs(self, tool_name: str, kwargs: dict[str, Any], context: UnifiedContext) -> dict[str, Any]:
        return kwargs

    def pre_loop_seed(self, context: UnifiedContext) -> str:
        viewport = resolve_viewport(context)
        time_seconds = float(viewport.get("time_seconds") or 0)
        return f"The user is currently watching the video at {_timestamp(time_seconds)}." if time_seconds else ""


def _timestamp(seconds: Any) -> str:
    total = max(0, int(float(seconds or 0)))
    hours, remainder = divmod(total, 3600)
    minutes, seconds = divmod(remainder, 60)
    return f"{hours}:{minutes:02d}:{seconds:02d}" if hours else f"{minutes:02d}:{seconds:02d}"


__all__ = ["MATERIAL_ID_KEY", "MODE_KEY", "VIEWPORT_KEY", "WatchingCapability"]
