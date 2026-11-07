#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Data models for the refactored question pipeline.
"""

from dataclasses import dataclass, field
from typing import Any


@dataclass
class QuestionTemplate:
    """
    Standardized intermediate template shared by all input paths.
    """

    question_id: str
    concentration: str
    question_type: str
    difficulty: str
    source: str = "custom"
    reference_question: str | None = None
    reference_answer: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class QAPair:
    """
    Final generated Q-A payload.
    """

    question_id: str
    question: str
    correct_answer: str
    explanation: str
    question_type: str
    options: dict[str, str] | None = None
    concentration: str = ""
    difficulty: str = ""
    validation: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)
