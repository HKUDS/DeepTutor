"""Conservative Markdown-to-text projection for authoritative selections."""

from __future__ import annotations

import re

from markdown_it import MarkdownIt
from markdown_it.rules_inline import StateInline
from markdown_it.token import Token

_MATH = re.compile(r"\$\$[\s\S]+?\$\$|\$(?!\$)[^$\n]+?\$")


def _math_literal(state: StateInline, silent: bool) -> bool:
    match = _MATH.match(state.src, state.pos)
    if match is None:
        return False
    if not silent:
        token = state.push("text", "", 0)
        token.content = match.group()
    state.pos = match.end()
    return True


def rendered_markdown_text(source: str) -> str:
    """Project structural markup only; preserve code, math and literal symbols.

    The selection is already browser text. Parsing it again could erase a
    fabricated number, operator or identifier and incorrectly ground it.
    """
    parser = MarkdownIt("commonmark", {"html": False}).enable("table")
    parser.inline.ruler.before("backticks", "selection_math", _math_literal)

    def text(tokens: list[Token]) -> str:
        parts: list[str] = []
        for token in tokens:
            if token.children is not None:
                parts.append(text(token.children))
            elif token.type in {"text", "code_inline", "code_block", "fence"}:
                parts.append(token.content)
            elif token.block or token.type in {"softbreak", "hardbreak"}:
                parts.append(" ")
        return "".join(parts)

    return " ".join(text(parser.parse(source)).split())
