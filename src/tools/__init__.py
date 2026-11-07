#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Tools Package - Unified tool collection

Includes:
- rag_tool: RAG retrieval tool
- web_search: Web search tool
- code_executor: Code execution tool
- multi_kb_rag_tool: Multi-knowledge-base RAG tool
- question: Question generation tools (pdf_parser, question_extractor, exam_mimic)
"""

# Patch lightrag.utils BEFORE any imports that use lightrag
import importlib.util
import sys

try:
    # Directly load lightrag.utils module without triggering lightrag/__init__.py
    _spec = importlib.util.find_spec("lightrag.utils")
    if _spec and _spec.origin:
        _utils = importlib.util.module_from_spec(_spec)
        sys.modules["lightrag.utils"] = _utils
        _spec.loader.exec_module(_utils)

        # Apply patches
        for _k, _v in {
            "verbose_debug": lambda *args, **kwargs: None,
            "VERBOSE_DEBUG": False,
            "get_env_value": lambda key, default=None: default,
            "safe_unicode_decode": lambda t: (
                t.decode("utf-8", errors="ignore") if isinstance(t, bytes) else t
            ),
        }.items():
            if not hasattr(_utils, _k):
                setattr(_utils, _k, _v)

        if not hasattr(_utils, "wrap_embedding_func_with_attrs"):

            def _wrap(**attrs):
                def dec(f):
                    for k, v in attrs.items():
                        setattr(f, k, v)
                    return f

                return dec

            _utils.wrap_embedding_func_with_attrs = _wrap
except Exception as e:
    import traceback

    print(f"Warning: Failed to patch lightrag.utils: {e}")
    traceback.print_exc()

from .code_executor import run_code, run_code_sync
from .rag_tool import rag_search
from .reason import reason
from .web_search import web_search

__all__ = [
    "rag_search",
    "reason",
    "run_code",
    "run_code_sync",
    "web_search",
]

# Question generation tools (lazy import to avoid circular dependencies)
# Access via: from src.tools.question import parse_pdf_with_mineru, etc.
