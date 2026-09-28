"""GeoGebra command validator and fixer.

This module validates GeoGebra commands and attempts to fix common mistakes
that LLMs might make when generating GeoGebra scripts.
"""

from dataclasses import dataclass, field
import re


@dataclass
class ValidationResult:
    """Result of validating a GeoGebra command."""

    original: str
    fixed: str
    is_valid: bool
    warnings: list[str] = field(default_factory=list)
    errors: list[str] = field(default_factory=list)


# Commands that should use square brackets (GeoGebra standard syntax)
COMMANDS_WITH_BRACKETS = {
    # Points
    "Point",
    "Midpoint",
    "Intersect",
    "Center",
    "Focus",
    "Vertex",
    # Lines
    "Line",
    "Segment",
    "Ray",
    "Perpendicular",
    "PerpendicularBisector",
    "AngleBisector",
    "Tangent",
    "Asymptote",
    "Directrix",
    # Vectors
    "Vector",
    "UnitVector",
    "PerpendicularVector",
    # Circles and Conics
    "Circle",
    "Ellipse",
    "Hyperbola",
    "Parabola",
    "Conic",
    # Polygons
    "Polygon",
    # Angles
    "Angle",
    # Transformations
    "Translate",
    "Rotate",
    "Reflect",
    "Dilate",
    # Functions
    "Derivative",
    "Integral",
    "If",
    "Function",
    # Styling
    "SetColor",
    "SetLineThickness",
    "SetPointSize",
    "SetFilling",
    "SetLabelVisible",
    "SetLabelMode",
    "SetCaption",
    "SetVisible",
    "SetLineStyle",
    # View
    "SetCoordSystem",
    "ShowAxes",
    "ShowGrid",
    "ZoomIn",
    "ZoomOut",
    # Text
    "Text",
    # Other
    "Locus",
    "Sequence",
    "Element",
    "Length",
    "Distance",
}

# Common mistakes patterns and their fixes
COMMON_MISTAKES = [
    # Point({x, y}) -> (x, y)
    (r"Point\s*\(\s*\{\s*([^}]+)\s*\}\s*\)", r"(\1)"),
    # log(10, x) -> lg(x)
    (r"\blog\s*\(\s*10\s*,\s*([^)]+)\s*\)", r"lg(\1)"),
    # Remove # comments (GeoGebra doesn't support them)
    (r"^\s*#.*$", ""),
]

# Patterns for detecting parentheses that should be brackets
PAREN_TO_BRACKET_PATTERN = re.compile(
    r"\b(" + "|".join(COMMANDS_WITH_BRACKETS) + r")\s*\(([^()]*(?:\([^()]*\)[^()]*)*)\)",
    re.IGNORECASE,
)


def fix_brackets(command: str) -> tuple[str, list[str]]:
    """Fix commands that use parentheses instead of square brackets.

    Args:
        command: A single GeoGebra command

    Returns:
        Tuple of (fixed command, list of warnings)
    """
    warnings = []
    fixed = command

    def replace_with_brackets(match):
        cmd_name = match.group(1)
        args = match.group(2)
        warnings.append(f"Changed {cmd_name}(...) to {cmd_name}[...]")
        return f"{cmd_name}[{args}]"

    fixed = PAREN_TO_BRACKET_PATTERN.sub(replace_with_brackets, fixed)

    return fixed, warnings


def fix_common_mistakes(command: str) -> tuple[str, list[str]]:
    """Fix common LLM mistakes in GeoGebra commands.

    Args:
        command: A single GeoGebra command

    Returns:
        Tuple of (fixed command, list of warnings)
    """
    warnings = []
    fixed = command

    for pattern, replacement in COMMON_MISTAKES:
        if re.search(pattern, fixed, re.MULTILINE):
            old = fixed
            fixed = re.sub(pattern, replacement, fixed, flags=re.MULTILINE)
            if old != fixed:
                warnings.append(f"Fixed pattern: {pattern}")

    return fixed, warnings


def validate_equation_format(command: str) -> tuple[str, list[str]]:
    """Validate and fix equation formats.

    Args:
        command: A single GeoGebra command

    Returns:
        Tuple of (fixed command, list of warnings)
    """
    warnings = []

    # Check for fractional coefficients in conic equations
    if re.search(r"[xy]\s*\^\s*2\s*/\s*\d+", command):
        warnings.append(
            "Equation contains fractional coefficients. "
            "Consider using integer form (e.g., '9x^2 + 4y^2 = 36' instead of 'x^2/4 + y^2/9 = 1')"
        )

    return command, warnings


def _split_command_args(arg_string: str) -> list[str]:
    """Split a comma-separated argument string, respecting nested brackets.

    String literals (``"..."``) and parenthesised expressions may contain
    commas that are not argument separators.
    """
    args: list[str] = []
    depth = 0
    in_string = False
    current: list[str] = []
    for char in arg_string:
        if char == '"' and (not current or current[-1] != "\\"):
            in_string = not in_string
        if in_string:
            current.append(char)
            continue
        if char in "([":
            depth += 1
        elif char in ")]":
            depth -= 1
        elif char == "," and depth == 0:
            args.append("".join(current).strip())
            current = []
            continue
        current.append(char)
    tail = "".join(current).strip()
    if tail:
        args.append(tail)
    return args


def _is_boolean_argument(arg: str) -> bool:
    return arg.lower() in {"true", "false"}


def _is_point_argument(arg: str) -> bool:
    """Return whether an argument is a syntactic two-coordinate point."""
    stripped = arg.strip()
    if not (stripped.startswith("(") and stripped.endswith(")")):
        return False
    coordinates = _split_command_args(stripped[1:-1])
    return len(coordinates) == 2 and all(coordinates)


def _is_scalar_argument(arg: str) -> bool:
    """Recognize conservative scalar expressions used for coordinate repair."""
    stripped = arg.strip()
    if not stripped or _is_boolean_argument(stripped) or _is_point_argument(stripped):
        return False
    if stripped.startswith('"'):
        return False
    # Plain uppercase names follow GeoGebra's point convention. Do not turn
    # Text["label", P, Q] into a point when P and Q may both be point objects.
    if re.fullmatch(r"[A-Z][A-Za-z0-9_]*", stripped):
        return False
    return True


def _is_explicit_scalar_expression(arg: str) -> bool:
    """Only repair coordinates when the third argument cannot be a Boolean name."""
    stripped = arg.strip()
    return _is_scalar_argument(stripped) and not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", stripped)


def validate_text_command(command: str) -> tuple[str, list[str], list[str]]:
    """Validate a ``Text`` command for arity and LaTeX balance.

    GeoGebra also accepts a one-argument form, a two-argument substitution
    Boolean, and a six-argument form with horizontal/vertical alignment. The common invented
    form ``Text[<string>, <x>, <y>]`` is repaired into a two-argument point
    when both trailing values are scalar expressions.

    Also checks that ``$`` LaTeX delimiters are balanced inside string
    arguments; an unbalanced ``$`` silently renders raw markup.

    Returns:
        Tuple of (fixed command, warnings, and error descriptions).
    """
    fixed = command
    warnings: list[str] = []
    errors: list[str] = []
    match = re.search(r"\bText\s*\[(.*)\]\s*$", command, re.DOTALL)
    if match is None:
        return fixed, warnings, errors

    args = _split_command_args(match.group(1))

    for arg in args:
        if arg.startswith('"'):
            if not arg.endswith('"'):
                errors.append(f"Text[] argument {arg} has an unterminated string.")
                continue
            if arg.count("$") % 2 != 0:
                errors.append(f"Text[] argument {arg} has unbalanced $ LaTeX delimiters.")

    if len(args) == 3 and not errors:
        second, third = args[1], args[2]
        if _is_scalar_argument(second) and _is_explicit_scalar_expression(third):
            args[1] = f"({second},{third})"
            del args[2]
            fixed = command[: match.start(1)] + ",".join(args) + command[match.end(1) :]
            warnings.append("Combined scalar x and y arguments into a Text[] point argument")
        elif _is_point_argument(second) and _is_explicit_scalar_expression(third):
            errors.append(
                "Invalid 3-argument Text[] signature. Use "
                "Text[<object>, <point>, <bool>] with a boolean third argument, "
                "or combine scalar coordinates into Text[<object>, (<x>, <y>)]."
            )

    if len(args) == 5 or len(args) > 6:
        errors.append(
            "Text[] supports one to four arguments, or six with horizontal and vertical alignment."
        )

    return fixed, warnings, errors


def validate_command(command: str) -> ValidationResult:
    """Validate and fix a single GeoGebra command.

    Args:
        command: A single GeoGebra command

    Returns:
        ValidationResult with the fixed command and any warnings/errors
    """
    result = ValidationResult(original=command, fixed=command, is_valid=True)

    # Skip empty lines
    if not command.strip():
        return result

    # Skip comment lines
    if command.strip().startswith("#"):
        result.fixed = ""
        result.warnings.append("Removed comment line (GeoGebra doesn't support # comments)")
        return result

    # Fix common mistakes
    fixed, warnings = fix_common_mistakes(command)
    result.fixed = fixed
    result.warnings.extend(warnings)

    # Fix brackets
    fixed, warnings = fix_brackets(result.fixed)
    result.fixed = fixed
    result.warnings.extend(warnings)

    # Check equation format
    _, warnings = validate_equation_format(result.fixed)
    result.warnings.extend(warnings)

    # Check Text command arity and LaTeX balance
    fixed, warnings, errors = validate_text_command(result.fixed)
    result.fixed = fixed
    result.warnings.extend(warnings)
    result.errors.extend(errors)

    if result.errors:
        result.is_valid = False

    # Check if anything was fixed
    if result.original != result.fixed:
        result.is_valid = False

    return result


def validate_ggbscript(script: str) -> tuple[str, list[str], list[str]]:
    """Validate and fix a complete GGBScript.

    Args:
        script: The full GeoGebra script content

    Returns:
        Tuple of (fixed script, list of all warnings, list of all errors)
    """
    lines = script.split("\n")
    fixed_lines = []
    all_warnings = []
    all_errors = []

    for i, line in enumerate(lines, 1):
        stripped = line.strip()

        # Skip empty lines
        if not stripped:
            fixed_lines.append(line)
            continue

        result = validate_command(stripped)

        if result.warnings:
            for warning in result.warnings:
                all_warnings.append(f"Line {i}: {warning}")

        if result.errors:
            for error in result.errors:
                all_errors.append(f"Line {i}: {error}")

        # Add the fixed line (preserve original indentation)
        if result.fixed:
            indent = len(line) - len(line.lstrip())
            fixed_lines.append(" " * indent + result.fixed)
        # If fixed is empty (e.g., removed comment), skip the line

    return "\n".join(fixed_lines), all_warnings, all_errors


def get_command_help(command_name: str) -> str | None:
    """Get help text for a GeoGebra command.

    Args:
        command_name: The name of the command

    Returns:
        Help text or None if command not found
    """
    help_texts = {
        "Circle": "Circle[center, radius] or Circle[center, point] or Circle[A, B, C]",
        "Ellipse": "Ellipse[F1, F2, a] (foci and semi-major axis) or Ellipse[F1, F2, P] (foci and point)",
        "Hyperbola": "Hyperbola[F1, F2, a] or Hyperbola[F1, F2, P]",
        "Parabola": "Parabola[focus, directrix_line]",
        "Line": "Line[A, B] (through two points) or Line[point, parallel_line]",
        "Segment": "Segment[A, B] or Segment[A, length]",
        "Ray": "Ray[A, B] (from A through B)",
        "Perpendicular": "Perpendicular[point, line] (perpendicular line through point)",
        "Midpoint": "Midpoint[A, B] or Midpoint[segment]",
        "Intersect": "Intersect[obj1, obj2] (all intersections) or Intersect[obj1, obj2, n] (nth intersection)",
        "Polygon": "Polygon[A, B, C, ...] or Polygon[A, B, n] (regular n-gon)",
        "SetColor": 'SetColor[obj, r, g, b] (RGB 0-255) or SetColor[obj, "Red"]',
        "SetCoordSystem": "SetCoordSystem[xMin, xMax, yMin, yMax]",
        "If": "If[condition, then_value, else_value]",
        "Derivative": "Derivative[f] or Derivative[f, n] (nth derivative)",
        "Integral": "Integral[f] (indefinite) or Integral[f, a, b] (definite)",
    }

    return help_texts.get(command_name)
