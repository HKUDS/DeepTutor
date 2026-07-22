"""Public entry points for the tool layer."""

from __future__ import annotations

import importlib

_LAZY_EXPORTS = {
    "brainstorm": (".brainstorm", "brainstorm"),
    "rag_search": (".rag_tool", "rag_search"),
    "reason": (".reason", "reason"),
    "web_search": (".web_search", "web_search"),
    "PaperSearchTool": (".paper_search_tool", "PaperSearchTool"),
    "TexChunker": (".tex_chunker", "TexChunker"),
    "TexDownloader": (".tex_downloader", "TexDownloader"),
    "read_tex_file": (".tex_downloader", "read_tex_file"),
    "BrainstormTool": (".builtin", "BrainstormTool"),
    "CodeExecutionTool": (".builtin", "CodeExecutionTool"),
    "GeoGebraAnalysisTool": (".builtin", "GeoGebraAnalysisTool"),
    "PaperSearchToolWrapper": (".builtin", "PaperSearchToolWrapper"),
    "RAGTool": (".builtin", "RAGTool"),
    "ReasonTool": (".builtin", "ReasonTool"),
    "WebSearchTool": (".builtin", "WebSearchTool"),
    "ToolPromptComposer": (".prompting", "ToolPromptComposer"),
    "load_prompt_hints": (".prompting", "load_prompt_hints"),
}

__all__ = sorted(_LAZY_EXPORTS)


def __getattr__(name: str):
    if name not in _LAZY_EXPORTS:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

    module_name, attr_name = _LAZY_EXPORTS[name]
    module = importlib.import_module(module_name, __name__)
    value = getattr(module, attr_name)
    globals()[name] = value
    return value


# Question generation tools (lazy import to avoid circular dependencies)
# Access via: from deeptutor.tools.question import parse_pdf_with_mineru, etc.
