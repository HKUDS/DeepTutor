from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
import re

_FENCE_RE = re.compile(r"(```[\s\S]*?```|~~~[\s\S]*?~~~)")
_INLINE_CODE_RE = re.compile(r"`[^`\n]+`")
_BRACKET_BLOCK_RE = re.compile(r"\\\[([\s\S]*?)\\\]")
_PAREN_INLINE_RE = re.compile(r"\\\(([\s\S]*?)\\\)")
_SINGLE_DOLLAR_RE = re.compile(r"(?<!\\)(?<!\$)\$(?!\$|\s)([^$\n]+?)(?<!\s)(?<!\\)\$(?!\$)")
_DOUBLE_DOLLAR_RE = re.compile(r"(?<!\$)\$\$([\s\S]*?)\$\$(?!\$)")
_LATEX_ENV_RE = re.compile(
    r"\\begin\{(equation\*?|displaymath|align\*?|gather\*?|multline\*?)\}"
    r"([\s\S]*?)"
    r"\\end\{\1\}",
)

_MATH_SIGNAL_RE = re.compile(
    r"(\\[A-Za-z]+|[=<>^_{}]|[+\-*/]\s*[A-Za-z0-9]|[A-Za-z0-9]\s*[+\-*/]|"
    r"[≤≥≈≠→←×÷±∈∉∪∩∞∑∫√])"
)
_CODE_LIKE_CALL_RE = re.compile(r"^[A-Za-z_][\w.]*\([A-Za-z0-9_.,\s:'\"-]*\)$")


@dataclass(frozen=True)
class MarkdownValidationResult:
    warnings: list[str]

    @property
    def ok(self) -> bool:
        return not self.warnings


def normalize_structure_note_markdown(markdown_text: str) -> str:
    """Normalize Structure Note Markdown for the current online/PDF renderers.

    The Structure Note render path uses remark-math/KaTeX online and a PDF
    fallback renderer. Both paths expect inline math as ``$...$`` and display
    math as ``$$...$$``. This pass converts unsupported wrappers, repairs common
    mixed wrappers, and keeps code-like calls as inline code.
    """

    if not markdown_text:
        return ""

    parts = _split_fenced_code(markdown_text)
    normalized = [
        part if is_fence else _normalize_non_fenced_markdown(part) for is_fence, part in parts
    ]
    return re.sub(r"\n{3,}", "\n\n", "".join(normalized)).strip() + "\n"


def validate_renderer_compatible_markdown(markdown_text: str) -> MarkdownValidationResult:
    warnings: list[str] = []
    for is_fence, part in _split_fenced_code(markdown_text):
        if is_fence:
            continue
        protected, _restore = _protect_inline_code(part)
        if re.search(r"\\[\(\)\[\]]", protected):
            warnings.append("Unsupported LaTeX wrapper remains after normalization.")
        if _has_inline_double_dollar(protected):
            warnings.append("Inline double-dollar math remains after normalization.")
        warnings.extend(_dangling_math_delimiter_warnings(protected))
        for kind, expression in _iter_math_expressions(protected):
            warnings.extend(_validate_math_expression(expression, kind))
    return MarkdownValidationResult(warnings=warnings)


def _split_fenced_code(markdown_text: str) -> list[tuple[bool, str]]:
    parts: list[tuple[bool, str]] = []
    last = 0
    for match in _FENCE_RE.finditer(markdown_text):
        if match.start() > last:
            parts.append((False, markdown_text[last : match.start()]))
        parts.append((True, match.group(0)))
        last = match.end()
    if last < len(markdown_text):
        parts.append((False, markdown_text[last:]))
    return parts or [(False, markdown_text)]


def _protect_inline_code(text: str) -> tuple[str, Callable[[str], str]]:
    protected: list[str] = []

    def stash(match: re.Match[str]) -> str:
        protected.append(match.group(0))
        return f"\u0000CODE{len(protected) - 1}\u0000"

    def restore(value: str) -> str:
        for index, original in enumerate(protected):
            value = value.replace(f"\u0000CODE{index}\u0000", original)
        return value

    return _INLINE_CODE_RE.sub(stash, text), restore


def _normalize_non_fenced_markdown(text: str) -> str:
    protected, restore = _protect_inline_code(text)
    normalized = _LATEX_ENV_RE.sub(lambda match: _display_math(_latex_env_body(match)), protected)
    normalized = _BRACKET_BLOCK_RE.sub(lambda match: _display_math(match.group(1)), normalized)
    normalized = _PAREN_INLINE_RE.sub(
        lambda match: _inline_math_replacement(match.group(1)), normalized
    )
    normalized = _DOUBLE_DOLLAR_RE.sub(lambda match: _display_math(match.group(1)), normalized)
    normalized = _SINGLE_DOLLAR_RE.sub(
        lambda match: _single_dollar_replacement(match.group(1)), normalized
    )
    return restore(normalized)


def _latex_env_body(match: re.Match[str]) -> str:
    env_name = match.group(1).rstrip("*")
    body = match.group(2).strip()
    if env_name in {"align", "gather", "multline"}:
        return f"\\begin{{aligned}}\n{body}\n\\end{{aligned}}"
    return body


def _single_dollar_replacement(expression: str) -> str:
    expression = _clean_math_expression(expression)
    if _is_code_like_expression(expression):
        return f"`{expression}`"
    if _looks_like_math_expression(expression):
        return _inline_math(expression)
    return f"${expression}$"


def _inline_math_replacement(expression: str) -> str:
    expression = _clean_math_expression(expression)
    if _is_code_like_expression(expression):
        return f"`{expression}`"
    return _inline_math(expression)


def _inline_math(expression: str) -> str:
    body = _clean_math_expression(expression)
    return f"${body}$" if body else ""


def _display_math(expression: str) -> str:
    body = _clean_math_expression(expression)
    return f"\n\n$$\n{body}\n$$\n\n" if body else ""


def _clean_math_expression(expression: str) -> str:
    body = expression.strip()
    changed = True
    while changed:
        changed = False
        for opener, closer in (("\\(", "\\)"), ("\\[", "\\]"), ("$$", "$$"), ("$", "$")):
            if (
                body.startswith(opener)
                and body.endswith(closer)
                and len(body) > len(opener) + len(closer)
            ):
                body = body[len(opener) : len(body) - len(closer)].strip()
                changed = True
    body = re.sub(r"\n{3,}", "\n\n", body)
    return body


def _is_code_like_expression(expression: str) -> bool:
    if "\\" in expression or "\n" in expression:
        return False
    if any(symbol in expression for symbol in ("=", "^", "_", "<", ">", "+", "*", "/", "|")):
        return False
    return bool(_CODE_LIKE_CALL_RE.fullmatch(expression.strip()))


def _looks_like_math_expression(expression: str) -> bool:
    expr = expression.strip()
    if not expr:
        return False
    if _MATH_SIGNAL_RE.search(expr):
        return True
    return bool(re.fullmatch(r"[A-Za-z](?:_[A-Za-z0-9]+)?|[A-Za-z]\d*", expr))


def _has_inline_double_dollar(text: str) -> bool:
    for match in _DOUBLE_DOLLAR_RE.finditer(text):
        before = text[: match.start()].rsplit("\n", 1)[-1].strip()
        after = text[match.end() :].split("\n", 1)[0].strip()
        if before or after:
            return True
    return False


def _iter_math_expressions(text: str) -> list[tuple[str, str]]:
    expressions: list[tuple[str, str]] = []
    display_spans: list[tuple[int, int]] = []
    for match in _DOUBLE_DOLLAR_RE.finditer(text):
        expressions.append(("display", match.group(1).strip()))
        display_spans.append((match.start(), match.end()))

    def is_inside_display(match: re.Match[str]) -> bool:
        return any(start <= match.start() and match.end() <= end for start, end in display_spans)

    for match in _SINGLE_DOLLAR_RE.finditer(text):
        if not is_inside_display(match):
            expressions.append(("inline", match.group(1).strip()))
    return expressions


def _validate_math_expression(expression: str, kind: str) -> list[str]:
    warnings: list[str] = []
    body = expression.strip()
    if not body:
        warnings.append(f"Empty {kind} math expression.")
        return warnings
    if "\\(" in body or "\\)" in body or "\\[" in body or "\\]" in body:
        warnings.append(f"Unsupported LaTeX wrapper remains inside {kind} math.")
    if "$" in body:
        warnings.append(f"Nested dollar delimiter remains inside {kind} math.")
    if not _balanced_braces(body, "{", "}"):
        warnings.append(f"Unbalanced braces in {kind} math: {body[:80]}")
    if not _balanced_braces(body, "(", ")"):
        warnings.append(f"Unbalanced parentheses in {kind} math: {body[:80]}")
    if not _balanced_braces(body, "[", "]"):
        warnings.append(f"Unbalanced brackets in {kind} math: {body[:80]}")
    return warnings


def _balanced_braces(value: str, opener: str, closer: str) -> bool:
    depth = 0
    escaped = False
    for char in value:
        if escaped:
            escaped = False
            continue
        if char == "\\":
            escaped = True
            continue
        if char == opener:
            depth += 1
        elif char == closer:
            depth -= 1
            if depth < 0:
                return False
    return depth == 0


def _dangling_math_delimiter_warnings(text: str) -> list[str]:
    warnings: list[str] = []
    without_display = _DOUBLE_DOLLAR_RE.sub("", text)
    for line in without_display.splitlines():
        scan = re.sub(r"\\\$", "", line)
        scan = re.sub(r"\$\d+(?:[.,]\d+)?", "", scan)
        single_dollars = [match.start() for match in re.finditer(r"(?<!\\)\$(?!\$)", scan)]
        if len(single_dollars) % 2 == 1 and _MATH_SIGNAL_RE.search(scan):
            warnings.append(f"Possible damaged inline math delimiter near: {line.strip()[:100]}")
    return warnings
