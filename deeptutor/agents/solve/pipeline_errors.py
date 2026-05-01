"""Pipeline-level exception raised when the user question needs clarification."""

from __future__ import annotations


class QuestionNeedsClarification(Exception):
    """Raised before planning when the question is too incomplete to solve."""

    def __init__(
        self,
        message: str,
        question_issues: list[str] | None = None,
    ) -> None:
        super().__init__(message)
        self.question_issues = question_issues or []