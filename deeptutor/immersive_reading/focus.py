"""Focus-Check workflow for immersive reading."""

from __future__ import annotations

import asyncio
import logging
import time
from typing import TYPE_CHECKING, Literal

from deeptutor.immersive_reading.models import (
    FocusAttempt,
    FocusAttemptRecord,
    FocusCheckResult,
    ReadingSection,
)
from deeptutor.services.llm import get_llm_config
from deeptutor.services.llm.context_window import resolve_effective_context_window
from deeptutor.utils.json_parser import parse_json_response

if TYPE_CHECKING:
    from deeptutor.immersive_reading.models import ReadingProgress


FOCUS_CHECK_MAX_TOKENS = 4000
FOCUS_CHECK_PROMPT_VERSION = "focus-check-v4-structured"
FOCUS_CHECK_PASS_THRESHOLD = 65

logger = logging.getLogger(__name__)


def requires_focus_check(section: ReadingSection) -> bool:
    return section.checkpoint_kind != "none"


def detect_content_type(text: str) -> Literal["code_heavy", "conceptual"]:
    """Heuristic: code blocks or tables indicate API/tutorial, prose indicates conceptual."""
    if not text:
        return "conceptual"
    code_fences = text.count("```")
    tables = text.count("|---")
    lines = text.splitlines()
    non_blank = max(1, sum(1 for line in lines if line.strip()))
    code_ratio = (code_fences / 2) / non_blank
    table_ratio = tables / non_blank
    return "code_heavy" if code_ratio > 0.03 or table_ratio > 0.02 else "conceptual"


def build_focus_prompts(content_type: str, *, language: str) -> list[str]:
    zh = language.startswith("zh")
    if content_type == "code_heavy":
        return [
            "这节解决什么问题或实现什么功能？"
            if zh
            else "What problem does this section solve or what feature does it implement?",
            "列出 1-2 个关键 API、命令或配置项"
            if zh
            else "List 1-2 key APIs, commands, or config options",
            "你会怎么在实际中使用？" if zh else "How would you use this in practice?",
        ]
    return [
        "用自己的话概括核心概念" if zh else "Summarize the core concept in your own words",
        "这个概念和什么相关或依赖什么？"
        if zh
        else "What does this concept relate to or depend on?",
        "它解决了什么问题？" if zh else "What problem does it solve?",
    ]


class FocusMixin:
    async def _complete_focus(self, **kwargs: object) -> str:
        """Retain the service module's LLM patch point for callers and tests."""
        from deeptutor.immersive_reading import service as service_module

        return await service_module.complete(**kwargs)

    async def _focus_material(self, content: str, *, language: str) -> str:
        cfg = get_llm_config()
        window = resolve_effective_context_window(
            context_window=getattr(cfg, "context_window", None),
            model=cfg.model,
            max_tokens=getattr(cfg, "max_tokens", None),
        )
        safe_chars = max(18_000, (window - 8_000) * 3)
        if len(content) <= safe_chars:
            return content
        # Reuse the service's established source-preserving section splitter.
        # The lazy import also preserves the public service module as the
        # compatibility boundary for downstream extensions.
        from deeptutor.immersive_reading.service import _split_near

        chunks = _split_near(content, target=safe_chars)
        system = (
            "Create a source-faithful checkpoint digest of this PART of a chapter. Preserve all major events, "
            "claims, characters, causality, turning points, and emotionally significant moments. Do not judge the learner."
        )
        semaphore = asyncio.Semaphore(4)

        async def summarise(index: int, chunk: str) -> str:
            async with semaphore:
                return await self._complete_focus(
                    prompt=(
                        f"Language for digest: {language}\n\n"
                        f"Chapter part {index + 1}/{len(chunks)}:\n{chunk}"
                    ),
                    system_prompt=system,
                    temperature=0.1,
                    max_tokens=2200,
                    reasoning_effort="minimal",
                    max_retries=0,
                    timeout=30,
                )

        summaries = await asyncio.gather(
            *(summarise(index, chunk) for index, chunk in enumerate(chunks))
        )
        return "\n\n".join(
            f"[Part {index + 1}]\n{summary}" for index, summary in enumerate(summaries)
        )

    async def focus_check(
        self,
        document_id: str,
        section_id: str,
        summary: str,
        reflection: str,
        language: str,
    ) -> FocusCheckResult:
        doc = self.load_document(document_id)
        if doc is None:
            raise ValueError("Reading document not found")
        section = next((item for item in doc.sections if item.id == section_id), None)
        if section is None:
            raise ValueError("Reading section not found")
        progress: ReadingProgress = self.load_progress(document_id)
        if not requires_focus_check(section):
            return FocusCheckResult(
                passed=True,
                score=100,
                feedback="No Focus-Check is required for reference matter.",
                progress=progress,
            )
        if len(summary.strip()) < 20:
            raise ValueError("Please describe the main content of this section")

        cleaned_summary = summary.strip()
        cleaned_reflection = reflection.strip()
        history = progress.focus_history.setdefault(section.id, [])
        try:
            raw_content = self._section_path(document_id, section_id).read_text(encoding="utf-8")
        except Exception:
            raw_content = ""
        content_type = detect_content_type(raw_content)
        focus_prompts = build_focus_prompts(content_type, language=language)
        record = FocusAttemptRecord(
            section_id=section.id,
            attempt_number=max((item.attempt_number for item in history), default=0) + 1,
            immersive_run=progress.immersive_run,
            summary=cleaned_summary,
            reflection=cleaned_reflection,
            pass_threshold=FOCUS_CHECK_PASS_THRESHOLD,
            language=language,
            prompt_version=f"{FOCUS_CHECK_PROMPT_VERSION}-{content_type}",
        )
        history.append(record)
        # Persist the answer before grading so provider failures never lose it.
        self._save_progress(progress)

        try:
            cfg = get_llm_config()
            record.model = str(getattr(cfg, "model", "") or "")
            record.binding = str(getattr(cfg, "binding", "") or "")
            material = await self._focus_material(raw_content, language=language)
        except Exception as exc:
            record.status = "error"
            record.error = str(exc)
            record.updated_at = time.time()
            self._save_progress(progress)
            raise
        zh = language.startswith("zh")
        system = (
            "你是严谨但公平的精读检查员。判断读者是否真正读懂刚才的内容，而不是要求逐字复述。"
            "叙事作品看主要情节、关键因果和有原文依据的感受；技术或参考资料看核心概念、用途、结构或实际收获。"
            "技术资料不要求情绪反应，也不要求覆盖目录中的每个条目。允许措辞不同、选择性阅读和合理的个人解读。"
            "读者回答了若干结构化问题；逐条评估，并在 missing_points 中标注哪个问题答得不足。"
            "只输出 JSON："
            f'{{"passed":bool,"score":0-100,"feedback":str,"strengths":[str],"missing_points":[str]}}。分数达到{FOCUS_CHECK_PASS_THRESHOLD}通常应通过。'
            if zh
            else "You are a rigorous but fair close-reading checker. Decide whether the reader genuinely understood "
            "the material without requiring verbatim recall. For narrative works, assess the main events, causality, "
            "and a text-grounded response. For technical or reference material, assess core concepts, purpose, structure, "
            "or practical takeaways; do not require an emotional reaction or exhaustive coverage of every TOC item. "
            "The reader answered structured questions; evaluate each one and note in missing_points which question was "
            "insufficiently addressed. Allow selective reading, different wording, and "
            f'reasonable interpretation. Return JSON only: {{"passed":bool,"score":0-100,"feedback":str,'
            f'"strengths":[str],"missing_points":[str]}}. A score of {FOCUS_CHECK_PASS_THRESHOLD} normally passes.'
        )
        prompt = (
            f"Book: {doc.title}\nSection: {section.title}\n\nSource material:\n{material}\n\n"
            f"Reader's account of the main content:\n{cleaned_summary}\n\n"
            f"Reader's additional notes (optional, may be empty):\n{cleaned_reflection}"
        )
        started_at = time.monotonic()
        try:
            raw = await self._complete_focus(
                prompt=prompt,
                system_prompt=system,
                temperature=0.1,
                max_tokens=FOCUS_CHECK_MAX_TOKENS,
                reasoning_effort="minimal",
                max_retries=0,
                timeout=30,
            )
        except Exception as exc:
            record.status = "error"
            record.error = str(exc)
            record.updated_at = time.time()
            self._save_progress(progress)
            raise
        elapsed = time.monotonic() - started_at
        record.latency_seconds = round(elapsed, 3)
        if not raw or not raw.strip():
            logger.warning(
                "Focus-Check model returned an empty response document=%s section=%s elapsed=%.2fs",
                document_id,
                section_id,
                elapsed,
            )
            message = "The model returned an empty Focus-Check response. Please try again."
            record.status = "error"
            record.error = message
            record.updated_at = time.time()
            self._save_progress(progress)
            raise RuntimeError(message)
        try:
            parsed = parse_json_response(raw)
        except Exception as exc:
            logger.warning(
                "Focus-Check model returned invalid JSON document=%s section=%s elapsed=%.2fs",
                document_id,
                section_id,
                elapsed,
            )
            message = "The model returned an invalid Focus-Check response. Please try again."
            record.status = "error"
            record.error = message
            record.updated_at = time.time()
            self._save_progress(progress)
            raise RuntimeError(message) from exc
        if not isinstance(parsed, dict) or not isinstance(parsed.get("passed"), bool) or "score" not in parsed:
            logger.warning(
                "Focus-Check model response lacked required fields document=%s section=%s elapsed=%.2fs",
                document_id,
                section_id,
                elapsed,
            )
            message = "The model returned an invalid Focus-Check response. Please try again."
            record.status = "error"
            record.error = message
            record.updated_at = time.time()
            self._save_progress(progress)
            raise RuntimeError(message)
        try:
            score = max(0, min(100, int(parsed["score"])))
        except (TypeError, ValueError) as exc:
            message = "The model returned an invalid Focus-Check score. Please try again."
            record.status = "error"
            record.error = message
            record.updated_at = time.time()
            self._save_progress(progress)
            raise RuntimeError(message) from exc
        passed = bool(parsed.get("passed")) and score >= FOCUS_CHECK_PASS_THRESHOLD
        raw_strengths = parsed.get("strengths")
        raw_missing_points = parsed.get("missing_points")
        strengths = [str(item) for item in raw_strengths if str(item).strip()] if isinstance(raw_strengths, list) else []
        missing_points = [str(item) for item in raw_missing_points if str(item).strip()] if isinstance(raw_missing_points, list) else []
        attempt = progress.focus_attempts.get(section.id) or FocusAttempt(section_id=section.id)
        attempt.attempt_count += 1
        attempt.passed = passed
        attempt.score = score
        attempt.feedback = str(parsed.get("feedback") or ("通过" if passed else "请重新阅读后再试。"))
        attempt.updated_at = time.time()
        progress.focus_attempts[section.id] = attempt
        record.status = "graded"
        record.passed = passed
        record.score = score
        record.feedback = attempt.feedback
        record.strengths = strengths
        record.missing_points = missing_points
        record.updated_at = attempt.updated_at
        if passed and section.id not in progress.passed_section_ids:
            progress.passed_section_ids.append(section.id)
            if section.id in progress.skipped_section_ids:
                progress.skipped_section_ids.remove(section.id)
            progress.scroll_percent = 100.0
        self._save_progress(progress)
        logger.info(
            "Focus-Check completed document=%s section=%s elapsed=%.2fs score=%s passed=%s",
            document_id,
            section_id,
            elapsed,
            score,
            passed,
        )
        return FocusCheckResult(
            passed=passed,
            score=score,
            feedback=attempt.feedback,
            strengths=strengths,
            missing_points=missing_points,
            prompts=focus_prompts,
            progress=progress,
        )
