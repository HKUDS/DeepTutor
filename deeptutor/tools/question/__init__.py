"""
Question Tools - Question generation system toolset

Tools for PDF parsing, question extraction, and mimic entrypoint.
"""

# MinerU parsing now lives in the shared parse layer
# (deeptutor/services/parsing/engines/mineru); re-exported here for the question
# toolset's backward-compatible public API.
from deeptutor.services.parsing.engines.mineru.backend import parse_pdf_to_workdir
from deeptutor.services.parsing.engines.mineru.config import (
    MinerUConfig,
    MinerUError,
    resolve_mineru_config,
)
from deeptutor.services.parsing.engines.mineru.local import parse_pdf_with_mineru

from .question_extractor import extract_questions_from_paper


async def mimic_exam_questions(*args, **kwargs):
    """
    Lazy wrapper to avoid circular imports with question coordinator.
    """
    from .exam_mimic import mimic_exam_questions as _mimic_exam_questions

    return await _mimic_exam_questions(*args, **kwargs)


__all__ = [
    "MinerUConfig",
    "MinerUError",
    "parse_pdf_to_workdir",
    "parse_pdf_with_mineru",
    "resolve_mineru_config",
    "extract_questions_from_paper",
    "mimic_exam_questions",
]
