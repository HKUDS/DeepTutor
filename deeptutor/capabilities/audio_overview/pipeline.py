"""Grounded two-voice audio overview generation pipeline."""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
import re
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from deeptutor.capabilities.audio_overview.request_config import AudioOverviewRequestConfig
from deeptutor.utils.json_parser import parse_json_response


class AudioOverviewError(ValueError):
    """A user-readable failure in one of the deterministic pipeline gates."""


class ScriptSegment(BaseModel):
    model_config = ConfigDict(extra="ignore")

    speaker: str
    text: str = Field(min_length=1, max_length=4_000)
    source_ids: list[str] = Field(default_factory=list)


class AudioOverviewScript(BaseModel):
    model_config = ConfigDict(extra="ignore")

    title: str = Field(min_length=1, max_length=200)
    segments: list[ScriptSegment] = Field(min_length=2, max_length=80)

    @model_validator(mode="after")
    def _validate_alternating_roles(self) -> AudioOverviewScript:
        for index, segment in enumerate(self.segments):
            expected = "host" if index % 2 == 0 else "expert"
            if segment.speaker != expected:
                raise ValueError(
                    f"segment {index + 1} must be spoken by {expected}, "
                    f"not {segment.speaker or 'unknown'}"
                )
            segment.source_ids = list(dict.fromkeys(segment.source_ids))
        return self


@dataclass(frozen=True, slots=True)
class SourceCitation:
    source_id: str
    title: str
    locator: str
    snippet: str

    def reference_dict(self) -> dict[str, str]:
        return {
            "source_id": self.source_id,
            "title": self.title,
            "locator": self.locator,
        }


@dataclass(frozen=True, slots=True)
class RetrievedContext:
    answer: str
    citations: list[SourceCitation]

    @property
    def citation_ids(self) -> set[str]:
        return {citation.source_id for citation in self.citations}


@dataclass(frozen=True, slots=True)
class AudioOverviewArtifacts:
    title: str
    script: AudioOverviewScript
    transcript: str
    audio_path: Path
    transcript_path: Path
    citations: list[dict[str, str]]
    workspace_items: list[dict[str, Any]]


RagSearchFunc = Callable[..., Awaitable[dict[str, Any]]]
CompleteFunc = Callable[[str, str], Awaitable[str]]
SpeechFunc = Callable[..., Awaitable[tuple[bytes, str]]]

_MAX_QUERY_CHARS = 1_000
_MAX_SNIPPET_CHARS = 2_000
_MAX_CONTEXT_CHARS = 16_000
_SOURCE_FIELDS = ("sources", "citations", "search_results", "documents")
_TITLE_FIELDS = ("title", "source", "filename", "file_name", "document", "document_name", "path")
_LOCATOR_FIELDS = ("locator", "page", "page_number", "section", "url", "source_url")
_SNIPPET_FIELDS = ("snippet", "content", "text", "preview", "excerpt")


def parse_script(raw_response: str, citation_ids: set[str]) -> AudioOverviewScript:
    """Parse and strictly validate the LLM script without repairing citations."""

    payload = parse_json_response(raw_response, fallback=None)
    if not isinstance(payload, dict):
        raise AudioOverviewError("The audio overview model did not return a JSON object.")
    try:
        script = AudioOverviewScript.model_validate(payload)
    except ValidationError as exc:
        details = "; ".join(
            f"{'.'.join(str(part) for part in error['loc'])}: {error['msg']}"
            for error in exc.errors()
        )
        raise AudioOverviewError(f"Invalid audio overview script: {details}") from exc

    for index, segment in enumerate(script.segments, start=1):
        unknown = sorted(set(segment.source_ids) - citation_ids)
        if unknown:
            raise AudioOverviewError(f"Invalid citation in segment {index}: {', '.join(unknown)}.")
    return script


def _first_text(row: Mapping[str, Any], fields: tuple[str, ...]) -> str:
    for field in fields:
        value = row.get(field)
        if value is None:
            continue
        text = str(value).strip()
        if text:
            return text
    return ""


def _citation_title(row: Mapping[str, Any], fallback: str) -> str:
    title = _first_text(row, _TITLE_FIELDS)
    if title and ("/" in title or "\\" in title) and not title.startswith("http"):
        title = Path(title).name
    return title[:200] or fallback


def _source_rows(result: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    for field in _SOURCE_FIELDS:
        value = result.get(field)
        if not isinstance(value, list):
            continue
        rows = [row for row in value if isinstance(row, Mapping)]
        if rows:
            return rows
    return []


def normalize_rag_result(result: Mapping[str, Any]) -> RetrievedContext:
    if result.get("error_type") or result.get("needs_reindex"):
        reason = str(
            result.get("answer") or result.get("content") or "the knowledge base is not searchable"
        )
        raise AudioOverviewError(f"RAG retrieval failed: {reason[:500]}")

    citations: list[SourceCitation] = []
    for index, row in enumerate(_source_rows(result), start=1):
        source_id = f"S{index}"
        snippet = _first_text(row, _SNIPPET_FIELDS)[:_MAX_SNIPPET_CHARS]
        citations.append(
            SourceCitation(
                source_id=source_id,
                title=_citation_title(row, source_id),
                locator=_first_text(row, _LOCATOR_FIELDS)[:200],
                snippet=snippet,
            )
        )

    answer = str(result.get("answer") or result.get("content") or "").strip()
    if not answer and not citations:
        raise AudioOverviewError("The knowledge base returned no usable content.")
    return RetrievedContext(answer=answer[:_MAX_CONTEXT_CHARS], citations=citations)


def _safe_stem(value: str, fallback: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip("-.")
    return (cleaned[:100] or fallback).lower()


def _transcript(script: AudioOverviewScript, citations: list[SourceCitation], language: str) -> str:
    labels = (
        {"host": "Host", "expert": "Expert"}
        if not language.startswith("zh")
        else {
            "host": "主持人",
            "expert": "专家",
        }
    )
    lines = [f"# {script.title}", ""]
    if citations:
        lines.extend(["## Sources", ""])
        lines.extend(
            f"- [{citation.source_id}] {citation.title}"
            + (f" — {citation.locator}" if citation.locator else "")
            for citation in citations
        )
        lines.append("")
    lines.append("## Transcript")
    lines.append("")
    for segment in script.segments:
        marker = " ".join(f"[{source_id}]" for source_id in segment.source_ids)
        suffix = f" {marker}" if marker else ""
        lines.append(f"### {labels[segment.speaker]}")
        lines.append("")
        lines.append(f"{segment.text}{suffix}")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


class AudioOverviewPipeline:
    """Generate and publish one bounded, KB-grounded overview artifact set."""

    def __init__(
        self,
        *,
        language: str = "en",
        system_prompt: str,
        instruction_prompt: str,
        rag_search_func: RagSearchFunc | None = None,
        complete_func: CompleteFunc | None = None,
        speech_func: SpeechFunc | None = None,
        workspace_output_dir: str | Path | None = None,
        workspace_logical_dir: str = "",
        workspace_id: str = "",
    ) -> None:
        self.language = language
        self.system_prompt = system_prompt
        self.instruction_prompt = instruction_prompt
        self._rag_search_func = rag_search_func
        self._complete_func = complete_func
        self._speech_func = speech_func
        self.workspace_output_dir = (
            Path(workspace_output_dir).resolve() if workspace_output_dir else None
        )
        self.workspace_logical_dir = workspace_logical_dir.strip("/")
        self.workspace_id = workspace_id

    async def retrieve(
        self, *, topic: str, kb_name: str, request_config: AudioOverviewRequestConfig
    ) -> RetrievedContext:
        query = " ".join(part.strip() for part in (topic, "audio overview") if part)
        query = query[:_MAX_QUERY_CHARS]
        rag_search = self._rag_search_func
        if rag_search is None:
            from deeptutor.tools.rag_tool import rag_search as rag_search_impl

            rag_search = rag_search_impl
        result = await rag_search(
            query,
            kb_name,
            top_k=request_config.max_context_chunks,
        )
        return normalize_rag_result(result)

    async def generate_script(
        self,
        *,
        topic: str,
        context: RetrievedContext,
        request_config: AudioOverviewRequestConfig,
    ) -> AudioOverviewScript:
        complete = self._complete_func
        if complete is None:
            from deeptutor.services.llm import factory as llm_factory
            from deeptutor.services.llm.config import get_llm_config

            llm_config = get_llm_config()

            async def complete(prompt: str, system_prompt: str) -> str:
                return await llm_factory.complete_with_config(
                    llm_config,
                    prompt,
                    system_prompt=system_prompt,
                )

        citation_block = (
            "\n".join(
                f"- [{citation.source_id}] {citation.title}"
                + (f" ({citation.locator})" if citation.locator else "")
                + f"\n  {citation.snippet}"
                for citation in context.citations
            )
            or "- No source metadata was returned; rely only on the retrieved answer."
        )
        language_label = "Simplified Chinese" if self.language.startswith("zh") else "English"
        prompt = (
            f"{self.instruction_prompt}\n\n"
            f"Language: {language_label}\n"
            f"Topic: {topic}\n"
            f"Target duration: about {request_config.target_minutes} minutes\n"
            "Valid citation IDs:\n"
            f"{citation_block}\n\n"
            f"Retrieved context:\n{context.answer or '(no synthesized answer)'}"
        )
        raw = await complete(prompt, self.system_prompt)
        return parse_script(raw, context.citation_ids)

    async def publish(
        self,
        *,
        turn_id: str,
        script: AudioOverviewScript,
        context: RetrievedContext,
        request_config: AudioOverviewRequestConfig,
    ) -> AudioOverviewArtifacts:
        if self.workspace_output_dir is None:
            raise AudioOverviewError("No writable runtime workspace is available.")

        speech = self._speech_func
        if speech is None:
            from deeptutor.services.voice import synthesize_speech as synthesize_speech_impl

            speech = synthesize_speech_impl

        audio_parts: list[bytes] = []
        for segment in script.segments:
            voice = (
                request_config.host_voice
                if segment.speaker == "host"
                else request_config.expert_voice
            )
            audio, _content_type = await speech(
                segment.text,
                voice=voice,
                response_format="mp3",
            )
            audio_parts.append(audio)

        stem = _safe_stem(f"{turn_id}-audio-overview", "audio-overview")
        audio_path = self.workspace_output_dir / f"{stem}.mp3"
        transcript_path = self.workspace_output_dir / f"{stem}.md"
        transcript = _transcript(script, context.citations, self.language)

        try:
            self.workspace_output_dir.mkdir(parents=True, exist_ok=True)
            audio_path.write_bytes(b"".join(audio_parts))
            transcript_path.write_text(transcript, encoding="utf-8")
        except OSError as exc:
            raise AudioOverviewError(f"Could not write audio overview artifacts: {exc}") from exc

        workspace_items = self._publish_workspace_items(
            audio_path,
            transcript_path,
            title=script.title,
        )
        return AudioOverviewArtifacts(
            title=script.title,
            script=script,
            transcript=transcript,
            audio_path=audio_path,
            transcript_path=transcript_path,
            citations=[citation.reference_dict() for citation in context.citations],
            workspace_items=workspace_items,
        )

    def _publish_workspace_items(
        self,
        audio_path: Path,
        transcript_path: Path,
        *,
        title: str,
    ) -> list[dict[str, Any]]:
        if not self.workspace_id or not self.workspace_logical_dir:
            return []
        from deeptutor.services.workspace import get_content_workspace_service

        service = get_content_workspace_service()
        binding = service.binding_by_id(self.workspace_id)
        logical = self.workspace_logical_dir
        rows = [
            {
                "path": f"{logical}/{audio_path.name}",
                "title": title,
                "caption": "Audio overview",
            },
            {
                "path": f"{logical}/{transcript_path.name}",
                "title": title,
                "caption": "Audio overview transcript",
            },
        ]
        items = service.publish(binding, rows)
        return [item.to_dict() for item in items]


__all__ = [
    "AudioOverviewArtifacts",
    "AudioOverviewError",
    "AudioOverviewPipeline",
    "AudioOverviewScript",
    "RetrievedContext",
    "SourceCitation",
    "normalize_rag_result",
    "parse_script",
]
