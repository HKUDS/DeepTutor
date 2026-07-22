"""Layout manager for consistent screen organization.

Based on Manim Skill best practices:
- LEFT PANEL: Graphics/diagrams (x ∈ [-6, -1])
- RIGHT PANEL: Text/formulas (x ∈ [1, 6])
- Step label: Top center
- Subtitle area: Reserved at bottom (y ∈ [-4, -2.5])
"""

from __future__ import annotations

import re

from dataclasses import dataclass
from typing import Any


@dataclass
class LayoutConfig:
    """Configuration for screen layout.

    All coordinates are in Manim's default coordinate system:
    - Origin (0, 0, 0) at center of screen
    - X: LEFT (-) to RIGHT (+)
    - Y: DOWN (-) to UP (+)
    """

    # Screen dimensions
    frame_width: float = 14.0
    frame_height: float = 8.0

    # Panel centers (following left-right layout)
    left_panel_x: float = -3.5
    right_panel_x: float = 3.5
    panel_y: float = 0.3  # Slightly above center

    # Step label position
    label_y: float = 3.2
    label_buff: float = 0.3

    # Safe content area (avoid subtitle overlap)
    safe_y_min: float = -1.0
    safe_y_max: float = 2.5

    # Subtitle reserved area
    subtitle_y_min: float = -4.0
    subtitle_y_max: float = -2.5

    # Panel dimensions
    panel_width: float = 5.0  # Max width per panel
    panel_height: float = 3.0  # Max height per panel

    # Spacing
    default_buff: float = 0.5


class LayoutManager:
    """Manages positioning of objects in the left-right panel layout."""

    def __init__(self, config: LayoutConfig | None = None):
        """Initialize with layout configuration.

        Args:
            config: Layout configuration. Uses default if None.
        """
        self.config = config or LayoutConfig()

    def get_left_panel_center(self) -> str:
        """Get the center position for left panel (graphics)."""
        return f"LEFT * {abs(self.config.left_panel_x)} + UP * {self.config.panel_y}"

    def get_right_panel_center(self) -> str:
        """Get the center position for right panel (text/formulas)."""
        return f"RIGHT * {self.config.right_panel_x} + UP * {self.config.panel_y}"

    def get_label_position(self) -> str:
        """Get the position for step label (top of screen)."""
        return f"UP * {self.config.label_y}"

    def place_in_left_panel(
        self,
        mobject_name: str,
        scale_to_fit: bool = True,
    ) -> list[str]:
        """Generate code to place a mobject in the left panel.

        Args:
            mobject_name: Name of the mobject variable
            scale_to_fit: Whether to add scaling to fit panel

        Returns:
            List of code lines
        """
        code = [
            f"        # Place {mobject_name} in left panel (graphics)",
            f"        {mobject_name}.move_to({self.get_left_panel_center()})",
        ]

        if scale_to_fit:
            code.extend([
                f"        if {mobject_name}.get_width() > {self.config.panel_width}:",
                f"            {mobject_name}.scale_to_fit_width({self.config.panel_width})",
                f"        if {mobject_name}.get_height() > {self.config.panel_height}:",
                f"            {mobject_name}.scale_to_fit_height({self.config.panel_height})",
            ])

        return code

    def place_in_right_panel(
        self,
        mobject_name: str,
        scale_to_fit: bool = True,
    ) -> list[str]:
        """Generate code to place a mobject in the right panel.

        Args:
            mobject_name: Name of the mobject variable
            scale_to_fit: Whether to add scaling to fit panel

        Returns:
            List of code lines
        """
        code = [
            f"        # Place {mobject_name} in right panel (formulas)",
            f"        {mobject_name}.move_to({self.get_right_panel_center()})",
        ]

        if scale_to_fit:
            code.extend([
                f"        if {mobject_name}.get_width() > {self.config.panel_width}:",
                f"            {mobject_name}.scale_to_fit_width({self.config.panel_width})",
                f"        if {mobject_name}.get_height() > {self.config.panel_height}:",
                f"            {mobject_name}.scale_to_fit_height({self.config.panel_height})",
            ])

        return code

    def place_label(self, mobject_name: str = "step_label") -> list[str]:
        """Generate code to place step label at top.

        Args:
            mobject_name: Name of the label mobject variable

        Returns:
            List of code lines
        """
        return [
            f"        # Place step label at top",
            f"        {mobject_name}.to_edge(UP, buff={self.config.label_buff})",
        ]

    def generate_scene_header(self) -> list[str]:
        """Generate the standard scene header with camera setup.

        Returns:
            List of code lines for scene header
        """
        return [
            "from manim import *",
            "import numpy as np",
            "",
            "class MathVisualization(Scene):",
            "    def construct(self):",
            f"        # Camera setup for consistent coordinate system",
            f"        self.camera.frame_width = {self.config.frame_width}",
            f"        self.camera.frame_height = {self.config.frame_height}",
            "",
        ]

    def generate_segment_header(
        self,
        segment_type: str,
        title: str,
        step_index: int = 0,
    ) -> list[str]:
        """Generate header for a segment.

        Args:
            segment_type: Type of segment (intro, step, conclusion)
            title: Segment title
            step_index: Step number (for steps)

        Returns:
            List of code lines
        """
        escaped_title = title.replace('"', '\\"')

        code = [
            f"        # ===== {segment_type.upper()}: {escaped_title[:40]} =====",
        ]

        # Add step label
        if step_index > 0:
            # Avoid redundant "Step N: Step N" when title is already "Step N"
            if re.match(r'^Step\s+\d+', escaped_title):
                label_text = f"Step {step_index}"
            else:
                label_text = f"Step {step_index}: {escaped_title}"
            code.extend([
                f"        step_label = Text(\"{label_text}\", font_size=24, color=YELLOW)",
            ])
        else:
            code.extend([
                f"        step_label = Text(\"{escaped_title}\", font_size=24, color=YELLOW)",
            ])

        code.extend(self.place_label())
        code.append("        self.play(FadeIn(step_label), run_time=0.3)")
        code.append("")

        return code

    def generate_wait_and_cleanup(
        self,
        duration: float,
        mobject_names: list[str] | None = None,
    ) -> list[str]:
        """Generate code for wait and cleanup.

        Args:
            duration: Wait duration in seconds
            mobject_names: List of mobject names to fade out

        Returns:
            List of code lines
        """
        # Calculate wait time (leave time for animations)
        wait_time = max(1.0, duration - 1.0)

        code = [
            f"        # Wait for narration",
            f"        self.wait({wait_time:.1f})",
        ]

        # Generate cleanup
        if mobject_names:
            fade_outs = ", ".join([f"FadeOut({name})" for name in mobject_names])
            code.append(f"        self.play({fade_outs}, run_time=0.5)")
        else:
            code.append("        self.play(FadeOut(step_label), run_time=0.3)")

        code.append("")

        return code

    def generate_left_right_layout(
        self,
        left_content: str = "diagram",
        right_content: str = "formulas",
        show_animation: bool = True,
    ) -> list[str]:
        """Generate code for left-right panel layout.

        Args:
            left_content: Variable name for left panel content
            right_content: Variable name for right panel content
            show_animation: Whether to include animation code

        Returns:
            List of code lines
        """
        code = [
            f"        # LEFT PANEL: Graphics/Diagrams",
        ]
        code.extend(self.place_in_left_panel(left_content))

        if show_animation:
            code.append(f"        self.play(Create({left_content}), run_time=1.0)")

        code.extend([
            "",
            f"        # RIGHT PANEL: Formulas/Text",
        ])
        code.extend(self.place_in_right_panel(right_content))

        if show_animation:
            code.append(f"        self.play(FadeIn({right_content}), run_time=0.5)")

        return code

    def get_safe_position(self, x: float, y: float) -> tuple[float, float]:
        """Ensure a position is within the safe content area.

        Args:
            x: X coordinate
            y: Y coordinate

        Returns:
            Adjusted (x, y) within safe area
        """
        # Clamp y to safe range
        safe_y = max(self.config.safe_y_min, min(self.config.safe_y_max, y))
        return (x, safe_y)

    def is_in_safe_area(self, y: float) -> bool:
        """Check if a y-coordinate is in the safe content area.

        Args:
            y: Y coordinate

        Returns:
            True if in safe area
        """
        return self.config.safe_y_min <= y <= self.config.safe_y_max


# Predefined layouts for common scenarios

INTRO_LAYOUT = {
    "step_label": "to_edge(UP, buff=0.3)",
    "problem_title": "move_to(UP * 2)",
    "problem_content": "move_to(RIGHT * 3.5 + UP * 0.3)",
}

STEP_LAYOUT = {
    "step_label": "to_edge(UP, buff=0.3)",
    "diagram": "move_to(LEFT * 3.5 + UP * 0.3)",
    "formulas": "move_to(RIGHT * 3.5 + UP * 0.3)",
}

CONCLUSION_LAYOUT = {
    "step_label": "to_edge(UP, buff=0.3)",
    "summary": "move_to(UP * 1)",
    "answer": "move_to(RIGHT * 3.5 + UP * 0.3)",
}
