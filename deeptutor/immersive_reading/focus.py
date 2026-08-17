"""Focus-check workflow for immersive reading."""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING

from deeptutor.immersive_reading.focus_material import build_focus_material
from deeptutor.immersive_reading.focus_parser import parse_focus_check_output
from deeptutor.immersive_reading.focus_prompts import (
    FOCUS_CHECK_MAX_TOKENS,
    FOCUS_CHECK_PASS_THRESHOLD,
    FOCUS_CHECK_PROMPT_VERSION,
    build_focus_prompt,
    build_focus_prompts,
    build_focus_system_prompt,
    detect_content_type,
    requires_focus_check,
)
from deeptutor.immersive_reading.models import (
    FocusAttempt,
    FocusAttemptRecord,
    FocusCheckResult,
)
from deeptutor.services.llm import get_llm_config

if TYPE_CHECKING:
    from deeptutor.immersive_reading.models import ReadingProgress


logger = logging.getLogger(__name__)


class FocusMixin:
    async def _complete_focus(self, **kwargs: object) -> str:
        """Retain the service module's LLM patch point for callers and tests."""
        from deeptutor.immersive_reading import service as service_module

        return await service_module.complete(**kwargs)

    async def _focus_material(self, content: str, *, language: str) -> str:
        return await build_focus_material(self._complete_focus, content, language=language)

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

        system = build_focus_system_prompt(language)
        prompt = build_focus_prompt(
            doc.title,
            section.title,
            material,
            summary=cleaned_summary,
            reflection=cleaned_reflection,
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
        try:
            score, passed, feedback, strengths, missing_points = parse_focus_check_output(
                raw, passed_threshold=FOCUS_CHECK_PASS_THRESHOLD
            )
        except RuntimeError as exc:
            record.status = "error"
            record.error = str(exc)
            record.updated_at = time.time()
            self._save_progress(progress)
            logger.warning(
                "Focus-Check model returned invalid output document=%s section=%s elapsed=%.2fs",
                document_id,
                section_id,
                elapsed,
            )
            raise

        attempt = progress.focus_attempts.get(section.id) or FocusAttempt(section_id=section.id)
        attempt.attempt_count += 1
        attempt.passed = passed
        attempt.score = score
        attempt.feedback = feedback
        attempt.updated_at = time.time()
        progress.focus_attempts[section.id] = attempt
        record.status = "graded"
        record.passed = passed
        record.score = score
        record.feedback = feedback
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
            feedback=feedback,
            strengths=strengths,
            missing_points=missing_points,
            prompts=focus_prompts,
            progress=progress,
        )


__all__ = [
    "FocusMixin",
    "FOCUS_CHECK_MAX_TOKENS",
    "FOCUS_CHECK_PASS_THRESHOLD",
    "FOCUS_CHECK_PROMPT_VERSION",
    "build_focus_prompts",
    "build_focus_prompt",
    "build_focus_system_prompt",
    "build_focus_material",
    "detect_content_type",
    "requires_focus_check",
]
