"""Notebook summarization agent."""

from __future__ import annotations

from typing import AsyncGenerator

from deeptutor.services.config import parse_language
from deeptutor.services.llm import clean_thinking_tags, get_llm_config, get_token_limit_kwargs
from deeptutor.services.llm import stream as llm_stream
from deeptutor.services.prompt.language import append_language_directive
from deeptutor.services.prompt.manager import get_prompt_manager


def _clip_text(value: str, limit: int) -> str:
    text = str(value or "").strip()
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "\n...[truncated]"


class NotebookSummarizeAgent:
    """Generate concise summaries for notebook records."""

    def __init__(self, language: str = "en") -> None:
        self.language = parse_language(language)
        self.llm_config = get_llm_config()
        self.model = getattr(self.llm_config, "model", None)
        self.api_key = getattr(self.llm_config, "api_key", None)
        self.base_url = getattr(self.llm_config, "base_url", None)
        self.api_version = getattr(self.llm_config, "api_version", None)
        self.binding = getattr(self.llm_config, "binding", None) or "openai"
        self.extra_headers = getattr(self.llm_config, "extra_headers", None) or {}
        # Prompts live under deeptutor/agents/notebook/prompts/{en,zh}/summarize_agent.yaml
        # so the notebook summarizer follows the same bilingual convention as
        # the rest of the agents and never hard-codes prompt strings here.
        self._prompts = get_prompt_manager().load_prompts(
            "notebook", "summarize_agent", self.language
        )

    async def summarize(
        self,
        *,
        title: str,
        record_type: str,
        user_query: str,
        output: str,
        metadata: dict | None = None,
    ) -> str:
        chunks: list[str] = []
        async for chunk in self.stream_summary(
            title=title,
            record_type=record_type,
            user_query=user_query,
            output=output,
            metadata=metadata,
        ):
            if chunk:
                chunks.append(chunk)
        return clean_thinking_tags("".join(chunks), self.binding, self.model).strip()

    async def stream_summary(
        self,
        *,
        title: str,
        record_type: str,
        user_query: str,
        output: str,
        metadata: dict | None = None,
    ) -> AsyncGenerator[str, None]:
        prompt = self._build_user_prompt(
            title=title,
            record_type=record_type,
            user_query=user_query,
            output=output,
            metadata=metadata or {},
        )
        kwargs = {"temperature": 0.2}
        if self.model:
            kwargs.update(get_token_limit_kwargs(self.model, 300))

        if self.extra_headers:
            kwargs["extra_headers"] = self.extra_headers

        async for chunk in llm_stream(
            prompt=prompt,
            system_prompt=self._system_prompt(),
            model=self.model,
            api_key=self.api_key,
            base_url=self.base_url,
            api_version=self.api_version,
            binding=self.binding,
            **kwargs,
        ):
            if chunk:
                yield chunk

    def _system_prompt(self) -> str:
        return append_language_directive(
            str(self._prompts.get("system", "")).strip(),
            self.language,
        )

    def _build_user_prompt(
        self,
        *,
        title: str,
        record_type: str,
        user_query: str,
        output: str,
        metadata: dict,
    ) -> str:
        clipped_query = _clip_text(user_query, 1200) or "(empty)"
        clipped_output = _clip_text(output, 6000) or "(empty)"
        clipped_metadata = _clip_text(str(metadata or {}), 1000) or "(none)"
        template = str(self._prompts.get("user_template", "")).strip()
        return template.format(
            record_type=record_type,
            record_hint=self._record_hint(record_type),
            title=title or "(untitled)",
            user_query=clipped_query,
            output=clipped_output,
            metadata=clipped_metadata,
        )

    def _record_hint(self, record_type: str) -> str:
        hints = self._prompts.get("record_hints") or {}
        if not isinstance(hints, dict):
            hints = {}
        if record_type in hints:
            return str(hints[record_type])
        return str(hints.get("default", ""))
