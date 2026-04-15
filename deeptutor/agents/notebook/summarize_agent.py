"""Notebook summarization agent."""

from __future__ import annotations

from typing import AsyncGenerator

from deeptutor.services.llm import clean_thinking_tags, get_llm_config, get_token_limit_kwargs
from deeptutor.services.llm import stream as llm_stream


def _clip_text(value: str, limit: int) -> str:
    text = str(value or "").strip()
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "\n...[truncated]"


class NotebookSummarizeAgent:
    """Generate concise summaries for notebook records."""

    def __init__(self, language: str = "en") -> None:
        self.language = "zh" if str(language or "en").lower().startswith("zh") else "en"
        self.llm_config = get_llm_config()
        self.model = getattr(self.llm_config, "model", None)
        self.api_key = getattr(self.llm_config, "api_key", None)
        self.base_url = getattr(self.llm_config, "base_url", None)
        self.api_version = getattr(self.llm_config, "api_version", None)
        self.binding = getattr(self.llm_config, "binding", None) or "openai"
        self.extra_headers = getattr(self.llm_config, "extra_headers", None) or {}

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
        if self.language == "zh":
            return (
                "你是 DeepTutor 的 notebook summary agent。"
                "请把一条待保存内容提炼成简洁、可检索、面向未来复用的摘要。"
                "摘要必须突出主题、关键结论、适用场景和保存价值。"
                "只输出摘要正文，不要加标题、前缀或项目符号。"
            )
        return (
            "You are DeepTutor's notebook summary agent. "
            "Compress a saved record into a concise, retrieval-friendly summary for future reuse. "
            "Focus on topic, key conclusions, use cases, and why this record matters. "
            "Output only the summary text with no heading or bullets."
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
        clipped_metadata = _clip_text(str(metadata or {}), 1000)
        record_hint = self._record_hint(record_type)
        if self.language == "zh":
            return (
                f"记录类型：{record_type}\n"
                f"类型提示：{record_hint}\n"
                f"标题：{title or '(untitled)'}\n"
                f"用户输入：\n{clipped_query}\n\n"
                f"保存内容：\n{clipped_output}\n\n"
                f"元数据：{clipped_metadata or '(none)'}\n\n"
                "请输出 80-180 字的中文摘要。要求："
                "1. 优先概括知识主题与关键信息；"
                "2. 如果内容是草稿或中间过程，要说明当前完成度；"
                "3. 如果内容适合后续复用，要点明可复用角度。"
            )
        return (
            f"Record type: {record_type}\n"
            f"Type hint: {record_hint}\n"
            f"Title: {title or '(untitled)'}\n"
            f"User input:\n{clipped_query}\n\n"
            f"Saved content:\n{clipped_output}\n\n"
            f"Metadata: {clipped_metadata or '(none)'}\n\n"
            "Write an 80-180 word summary. Focus on the topic, key information, current completion state, "
            "and what makes this record useful for future reuse."
        )

    def _record_hint(self, record_type: str) -> str:
        hints = {
            "chat": {
                "zh": "一段完整聊天历史，重点提炼问题、结论与后续行动。",
                "en": "A full chat transcript; focus on the question, conclusion, and next actions.",
            },
            "co_writer": {
                "zh": "一份写作草稿，重点提炼主题、结构、当前完成度与可继续扩展方向。",
                "en": "A writing draft; focus on theme, structure, current completeness, and expansion paths.",
            },
            "guided_learning": {
                "zh": "一段引导式学习记录，重点提炼学习主题、知识点结构与阶段性产出。",
                "en": "A guided learning record; focus on topic, knowledge structure, and partial/final output.",
            },
        }
        localized = hints.get(record_type, {})
        return localized.get(self.language, "Summarize the most reusable information in this record.")
