"""Formula renderer for MathTex expressions with highlighting.

Based on Manim Skill best practices:
- Use substrings_to_isolate for precise coloring
- VGroup for organizing multiple formulas
- arrange(DOWN) for vertical stacking
"""

from __future__ import annotations

import re
from typing import Any


class FormulaRenderer:
    """Renderer for mathematical formulas using Manim's MathTex."""

    # Default styling
    DEFAULT_FONT_SIZE = 28
    DEFAULT_SCALE = 0.9
    HIGHLIGHT_COLORS = ["YELLOW", "GREEN", "RED", "BLUE", "ORANGE", "PURPLE"]

    def __init__(self):
        """Initialize the formula renderer."""
        pass

    def render_formula(
        self,
        formula: str,
        font_size: int = DEFAULT_FONT_SIZE,
        scale: float = DEFAULT_SCALE,
        color: str | None = None,
    ) -> list[str]:
        """Render a single formula with MathTex.

        Args:
            formula: LaTeX formula string (without $ delimiters)
            font_size: Font size for the formula
            scale: Scale factor
            color: Optional color name

        Returns:
            List of code lines
        """
        # Sanitize: remove any non-LaTeX characters (Chinese, etc.)
        formula = sanitize_for_math_tex(formula)
        if not formula:
            return []

        # Escape special characters for Python string
        escaped_formula = formula.replace("\\", "\\\\").replace('"', '\\"')

        code = [
            f"        # Formula: {escaped_formula[:50]}{'...' if len(escaped_formula) > 50 else ''}",
        ]

        if color:
            code.extend([
                f"        formula = MathTex(r\"{escaped_formula}\", font_size={font_size})",
                f"        formula.set_color({color})",
            ])
        else:
            code.append(f"        formula = MathTex(r\"{escaped_formula}\", font_size={font_size})")

        if scale != 1.0:
            code.append(f"        formula.scale({scale})")

        return code

    def render_with_highlight(
        self,
        formula: str,
        highlight_parts: list[str],
        font_size: int = DEFAULT_FONT_SIZE,
        scale: float = DEFAULT_SCALE,
    ) -> list[str]:
        """Render formula with specific parts highlighted.

        Uses substrings_to_isolate for precise coloring control.

        Args:
            formula: LaTeX formula string
            highlight_parts: List of substrings to highlight
            font_size: Font size
            scale: Scale factor

        Returns:
            List of code lines
        """
        # Sanitize: remove any non-LaTeX characters
        formula = sanitize_for_math_tex(formula)
        if not formula:
            return []

        # Escape special characters
        escaped_formula = formula.replace("\\", "\\\\").replace('"', '\\"')

        # Escape parts for substrings_to_isolate
        escaped_parts = [p.replace("\\", "\\\\").replace('"', '\\"') for p in highlight_parts]

        code = [
            f"        # Formula with highlights: {escaped_formula[:40]}...",
            f"        formula = MathTex(",
            f"            r\"{escaped_formula}\",",
            f"            font_size={font_size},",
        ]

        if escaped_parts:
            parts_str = ", ".join([f'r"{p}"' for p in escaped_parts[:5]])  # Limit to 5 parts
            code.append(f"            substrings_to_isolate=[{parts_str}],")

        code.append("        )")

        if scale != 1.0:
            code.append(f"        formula.scale({scale})")

        # Add color for each highlighted part
        for i, part in enumerate(escaped_parts[:5]):
            color = self.HIGHLIGHT_COLORS[i % len(self.HIGHLIGHT_COLORS)]
            code.append(f"        formula.set_color_by_tex(r\"{part}\", {color})")

        return code

    def create_formula_group(
        self,
        formulas: list[str],
        arrange_direction: str = "DOWN",
        buff: float = 0.4,
        font_size: int = DEFAULT_FONT_SIZE,
        scale: float = DEFAULT_SCALE,
    ) -> list[str]:
        """Create a VGroup of multiple formulas arranged vertically.

        Args:
            formulas: List of LaTeX formula strings
            arrange_direction: Direction for arrangement (DOWN, UP, RIGHT, LEFT)
            buff: Buffer between formulas
            font_size: Font size
            scale: Scale factor

        Returns:
            List of code lines
        """
        if not formulas:
            return ["        # No formulas to render", "        formulas_group = VGroup()"]

        code = [
            "        # Formula group",
            "        formulas_group = VGroup(*[",
        ]

        for f in formulas[:4]:  # Limit to 4 formulas
            escaped_f = f.replace(chr(92), chr(92)+chr(92)).replace('"', '\\"')
            code.append(f"            MathTex(r\"{escaped_f}\", font_size={font_size}).scale({scale}),")

        code.append("        ])")

        code.append(f"        formulas_group.arrange({arrange_direction}, buff={buff})")

        return code

    def create_step_formula(
        self,
        formula: str,
        step_key_symbols: list[str] | None = None,
        all_step_symbols: list[str] | None = None,
    ) -> list[str]:
        """Create formula code for a specific step with contextual highlighting.

        Args:
            formula: The formula to render
            step_key_symbols: Symbols to highlight in this step
            all_step_symbols: All symbols from all steps (for context)

        Returns:
            List of code lines
        """
        if not step_key_symbols:
            return self.render_formula(formula)

        # Determine which parts to highlight
        parts_to_highlight = []
        for symbol in step_key_symbols[:3]:
            if symbol in formula:
                parts_to_highlight.append(symbol)

        if parts_to_highlight:
            return self.render_with_highlight(formula, parts_to_highlight)
        else:
            return self.render_formula(formula)


def create_formula_group(
    formulas: list[str],
    arrange_direction: str = "DOWN",
    buff: float = 0.4,
) -> list[str]:
    """Convenience function to create a group of formulas.

    Args:
        formulas: List of LaTeX formulas
        arrange_direction: Direction for arrangement
        buff: Buffer between formulas

    Returns:
        List of code lines
    """
    renderer = FormulaRenderer()
    return renderer.create_formula_group(formulas, arrange_direction, buff)


def sanitize_for_math_tex(text: str) -> str:
    """Remove characters that crash pdflatex in MathTex mode.

    Strips CJK characters and other Unicode that LaTeX can't handle
    in math mode. Keeps ASCII letters, digits, and common math symbols.
    """
    if not text:
        return ""

    # Only keep characters safe for LaTeX math mode
    result = []
    for ch in text:
        # ASCII printable range (32-126) is always safe
        # Also keep tab, newline, carriage return
        if 32 <= ord(ch) <= 126 or ch in "\t\n\r":
            result.append(ch)
        # Allow common math Unicode symbols that LaTeX handles
        elif ch in "αβγδεθλμνωπϕφστψκρςηζπ≤≥≠≈±×÷·√∞∩∪∈∉⊂⊃⊆⊇∂∇∆∏∑∫∅→↔∧∨¬∀∃":
            result.append(ch)
        # Skip everything else (CJK, emoji, etc.)
    return "".join(result)


def escape_for_latex(text: str) -> str:
    """Escape special LaTeX characters in text.

    Args:
        text: Raw text to escape

    Returns:
        Escaped text safe for LaTeX
    """
    # List of characters that need escaping in LaTeX
    special_chars = {
        "\\": "\\textbackslash{}",
        "&": "\\&",
        "%": "\\%",
        "$": "\\$",
        "#": "\\#",
        "_": "\\_",
        "{": "\\{",
        "}": "\\}",
        "~": "\\textasciitilde{}",
        "^": "\\textasciicircum{}",
    }

    result = text
    for char, replacement in special_chars.items():
        result = result.replace(char, replacement)

    return result
