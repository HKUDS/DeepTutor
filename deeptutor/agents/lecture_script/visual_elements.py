"""Visual element extraction from math problem steps.

Extracts geometry objects, formulas, and annotations from step text
to support Tier 2 rule-based diagram generation.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any


@dataclass
class GeometryObject:
    """A geometric object extracted from step text.

    Attributes:
        type: Object type ("triangle", "circle", "line", "point", etc.)
        label: Name/label (e.g., "ABC" for triangle ABC)
        properties: Dict of properties (e.g., {"right_angle": "C"})
        relationships: List of relationships (e.g., "AD是BC边上的高")
    """

    type: str
    label: str
    properties: dict[str, Any] = field(default_factory=dict)
    relationships: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "type": self.type,
            "label": self.label,
            "properties": self.properties,
            "relationships": self.relationships,
        }


@dataclass
class VisualElements:
    """All visual elements extracted from a step.

    Attributes:
        formulas: List of LaTeX formulas for MathTex
        geometry: List of geometric objects
        annotations: List of annotations (points, labels)
        key_symbols: List of key mathematical symbols
    """

    formulas: list[str] = field(default_factory=list)
    geometry: list[GeometryObject] = field(default_factory=list)
    annotations: list[str] = field(default_factory=list)
    key_symbols: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "formulas": self.formulas,
            "geometry": [g.to_dict() for g in self.geometry],
            "annotations": self.annotations,
            "key_symbols": self.key_symbols,
        }


# Regex patterns for geometry extraction
# \$? allows matching LaTeX-wrapped labels like "三角形 $ABC$"
GEOMETRY_PATTERNS = {
    "triangle": r"(?:三角形|triangle)\s*\$?([A-Z]{3})\$?",
    "right_triangle": r"(?:直角三角形|right triangle)\s*\$?([A-Z]{3})\$?",
    "quadrilateral": r"(?:四边形|quadrilateral)\s*\$?([A-Z]{4})\$?",
    "circle": r"(?:圆|circle)\s*\$?([A-Z])\$?",
    "altitude": r"(?:高线|altitude)\s*\$?([A-Z]{2})\$?",
    "median": r"(?:中线|median)\s*\$?([A-Z]{2})\$?",
    "diameter": r"(?:直径|diameter)\s*\$?([A-Z]{2})\$?",
    "radius": r"(?:半径|radius)\s*\$?([A-Z]{2}|[A-Z])\$?",
    "chord": r"(?:弦|chord)\s*\$?([A-Z]{2})\$?",
    "angle": r"(?:角|angle)\s*\$?([A-Z]{3}|[A-Z])\$?",
    "point_on_circle": r"(?:点|point)\s*\$?([A-Z])\$?\s*(?:在圆|on circle)",
    "parallel_lines": r"([A-Z]{2})\s*//\s*([A-Z]{2})",
    "perpendicular": r"([A-Z]{2})\s*⊥\s*([A-Z]{2})",
}

# Additional English-only and mixed patterns
ENGLISH_GEOMETRY_PATTERNS = {
    "triangle": r"\b(triangle|△)\s*([A-Z]{3})\b",
    "right_triangle": r"\bright triangle\b.*?([A-Z]{3})",
    "quadrilateral": r"\bquadrilateral\s+([A-Z]{4})\b",
    "cyclic_quadrilateral": r"\bcyclic\s+quadrilateral\s+([A-Z]{4})\b",
    "altitude": r"\baltitude\s+([A-Z]{2})\b",
    "right_angle": r"(?:∠\s*)?([A-Z]{3})\s*(?:∠\s*)?=\s*90",
    "diameter": r"\bdiameter\s+([A-Z]{2})\b",
    "circle": r"\bcircle\b",
    "line": r"\b(line|segment)\s+([A-Z]{2})\b",
    "perpendicular": r"([A-Z]{2})\s*⟂\s*([A-Z]{2})",
}

# Right angle patterns
RIGHT_ANGLE_PATTERNS = [
    r"直角在\s*([A-Z])",
    r"([A-Z])\s*为直角",
    r"∠([A-Z]{3})\s*=\s*90°",
    r"∠([A-Z]{3})\s*为直角",
]

# Formula extraction patterns
FORMULA_PATTERNS = {
    "latex_inline": r"\$(.+?)\$",
    "latex_display": r"\$\$(.+?)\$\$",
    "equation": r"([^，。！？\s]{3,50}=[^，。！？\s]{3,50})",
    "inequality": r"([^，。！？\s]{2,30}[<>≤≥][^，。！？\s]{2,30})",
    "polynomial": r"([a-zA-Z]\^?\d*(?:\s*[\+\-]\s*[a-zA-Z]\^?\d*)+)",
    "paren_expr": r"\([^()]{2,30}\)\^?\d*",
}


def extract_geometry_objects(text: str) -> list[GeometryObject]:
    """Extract geometric objects from Chinese math text.

    Args:
        text: The step text to analyze

    Returns:
        List of GeometryObject instances
    """
    objects = []
    processed_labels = set()  # Avoid duplicates

    # Extract triangles
    for match in re.finditer(GEOMETRY_PATTERNS["triangle"], text):
        label = match.group(1)
        if label not in processed_labels:
            # Check if it's a right triangle
            properties = {}
            for pattern in RIGHT_ANGLE_PATTERNS:
                ra_match = re.search(pattern, text)
                if ra_match:
                    raw = ra_match.group(1)
                    # If it's a 3-letter angle (e.g., "ADB"), extract middle letter as vertex
                    vertex = raw[1] if len(raw) == 3 else raw
                    # Only set if the vertex is part of this triangle
                    if vertex in label:
                        properties["right_angle"] = vertex
                    break

            objects.append(GeometryObject(
                type="triangle",
                label=label,
                properties=properties,
            ))
            processed_labels.add(label)

    # Extract circles
    for match in re.finditer(GEOMETRY_PATTERNS["circle"], text):
        label = match.group(1)
        key = f"circle_{label}"
        if key not in processed_labels:
            objects.append(GeometryObject(
                type="circle",
                label=label,
            ))
            processed_labels.add(key)

    # Extract lines (altitudes, medians, diameters)
    for line_type, pattern in [
        ("altitude", GEOMETRY_PATTERNS["altitude"]),
        ("median", GEOMETRY_PATTERNS["median"]),
        ("diameter", GEOMETRY_PATTERNS["diameter"]),
    ]:
        for match in re.finditer(pattern, text):
            label = match.group(1)
            key = f"{line_type}_{label}"
            if key not in processed_labels:
                objects.append(GeometryObject(
                    type="line",
                    label=label,
                    properties={"line_type": line_type},
                ))
                processed_labels.add(key)

    # Extract angles
    for match in re.finditer(GEOMETRY_PATTERNS["angle"], text):
        label = match.group(1)
        if len(label) == 3 and label not in processed_labels:
            objects.append(GeometryObject(
                type="angle",
                label=label,
            ))
            processed_labels.add(label)

    return objects


def extract_formulas(text: str) -> list[str]:
    """Extract mathematical formulas for MathTex rendering.

    Args:
        text: The step text to analyze

    Returns:
        List of LaTeX-compatible formula strings
    """
    formulas = []
    seen = set()

    # Extract LaTeX expressions (already in $...$)
    for pattern_name in ["latex_inline", "latex_display"]:
        for match in re.finditer(FORMULA_PATTERNS[pattern_name], text):
            expr = match.group(1).strip()
            if expr and expr not in seen:
                formulas.append(expr)
                seen.add(expr)

    # Extract equations (x = ...)
    for match in re.finditer(FORMULA_PATTERNS["equation"], text):
        expr = match.group(1).strip()
        expr = expr.replace(" ", "")
        expr = _clean_formula(expr)
        if len(expr) >= 3 and expr not in seen:
            if any(c in expr for c in "=+-*/^_"):
                formulas.append(expr)
                seen.add(expr)

    # Extract polynomial expressions
    for match in re.finditer(FORMULA_PATTERNS["polynomial"], text):
        expr = match.group(1).strip()
        expr = expr.replace(" ", "")
        expr = _clean_formula(expr)
        if len(expr) >= 3 and expr not in seen:
            formulas.append(expr)
            seen.add(expr)

    # Extract parenthesized expressions
    for match in re.finditer(FORMULA_PATTERNS["paren_expr"], text):
        expr = match.group(0).strip()
        expr = _clean_formula(expr)
        if any(c in expr for c in "+-*/^=") and expr not in seen:
            formulas.append(expr)
            seen.add(expr)

    return formulas[:5]



def _clean_formula(expr: str) -> str:
    """Remove trailing non-LaTeX punctuation from regex-extracted formulas.

    Non-$...$ extraction patterns (equation, polynomial, paren_expr) can
    capture trailing punctuation from surrounding text, e.g. ``).`` in
    ``(T_{-1}=0).``. This strips those artifacts without mangling valid
    LaTeX (which never ends with ASCII punctuation).
    """
    return expr.rstrip('.,;:!?！？，。；、')


def extract_key_symbols(text: str) -> list[str]:
    """Extract key mathematical symbols for highlighting.

    Args:
        text: The step text to analyze

    Returns:
        List of key symbols/variables
    """
    symbols = []
    seen = set()

    # Single letters (variables)
    for match in re.finditer(r"\b([a-zA-Z])\b", text):
        sym = match.group(1)
        if sym not in seen and sym not in ["A", "B", "C", "D", "E", "F"]:
            symbols.append(sym)
            seen.add(sym)

    # Greek letters (written as \alpha, \beta, etc. in LaTeX)
    greek_pattern = r"(\\(?:alpha|beta|gamma|delta|epsilon|theta|lambda|mu|pi|sigma|phi|omega))"
    for match in re.finditer(greek_pattern, text):
        sym = match.group(1)
        if sym not in seen:
            symbols.append(sym)
            seen.add(sym)

    return symbols[:8]  # Limit to 8 symbols


def extract_visual_elements(step_data: dict[str, Any]) -> VisualElements:
    """Extract all visual elements from a step.

    Args:
        step_data: The step data from MathNet (with step_text_zh, etc.)

    Returns:
        VisualElements containing formulas, geometry, annotations
    """
    # Combine all text fields for analysis (both Chinese and English)
    text_parts = [
        step_data.get("step_text_zh", ""),
        step_data.get("step_text_en", ""),
        step_data.get("explanation_zh", ""),
        step_data.get("explanation_en", ""),
        step_data.get("step_goal_zh", ""),
    ]
    full_text = " ".join(text_parts)

    if not full_text:
        return VisualElements()

    # Extract different element types
    geometry = extract_geometry_objects(full_text)
    formulas = extract_formulas(full_text)
    symbols = extract_key_symbols(full_text)

    # Extract annotations (point labels from geometry)
    annotations = []
    for geom in geometry:
        if geom.label:
            if len(geom.label) > 1:
                # Multi-character label (e.g., "ABC" -> "A", "B", "C")
                annotations.extend(list(geom.label))
            else:
                annotations.append(geom.label)

    return VisualElements(
        formulas=formulas,
        geometry=geometry,
        annotations=list(set(annotations)),  # Deduplicate
        key_symbols=symbols,
    )
