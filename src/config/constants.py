#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Constants for DeepTutor
"""

from pathlib import Path

# Project root directory - central location for all path calculations
PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent

# Valid tools for investigate agent
VALID_INVESTIGATE_TOOLS = ["rag_naive", "rag_hybrid", "web_search", "query_item", "none"]

# Valid tools for solve agent
VALID_SOLVE_TOOLS = [
    "web_search",
    "code_execution",
    "rag_naive",
    "rag_hybrid",
    "query_item",
    "none",
    "finish",
]

# Standard log level tags (used in unified logging format)
LOG_LEVEL_TAGS = [
    "DEBUG",
    "INFO",
    "SUCCESS",
    "WARNING",
    "ERROR",
    "CRITICAL",
    "PROGRESS",
    "COMPLETE",
]
