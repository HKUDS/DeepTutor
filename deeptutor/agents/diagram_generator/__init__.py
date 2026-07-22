"""Tier 2 Static Diagram Generator

Rule-based generation of static mathematical diagrams for Manim.
Provides precise geometry creation without LLM uncertainty.
"""

from .geometry_factory import GeometryFactory, create_triangle, create_circle
from .formula_renderer import FormulaRenderer, create_formula_group
from .layout_manager import LayoutManager, LayoutConfig
from .code_generator import StaticDiagramGenerator

__all__ = [
    "GeometryFactory",
    "create_triangle",
    "create_circle",
    "FormulaRenderer",
    "create_formula_group",
    "LayoutManager",
    "LayoutConfig",
    "StaticDiagramGenerator",
]
