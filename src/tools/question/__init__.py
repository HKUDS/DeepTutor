"""
Question Tools - Question generation system toolset

Tools for PDF parsing, question extraction, and mimic entrypoint.
"""

from .pdf_parser import parse_pdf_with_mineru
from .question_extractor import extract_questions_from_paper


async def mimic_exam_questions(*args, **kwargs):
    """
    Lazy wrapper to avoid circular imports with question coordinator.
    """
    from .exam_mimic import mimic_exam_questions as _mimic_exam_questions

    return await _mimic_exam_questions(*args, **kwargs)

__all__ = [
    "parse_pdf_with_mineru",
    "extract_questions_from_paper",
    "mimic_exam_questions",
]
