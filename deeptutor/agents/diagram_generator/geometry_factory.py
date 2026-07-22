"""Geometry factory for creating precise Manim geometric objects.

Based on Manim Skill best practices:
- Use Polygon with explicit vertices for triangles
- Use precise coordinate calculations
- VGroup for organizing related objects
"""

from __future__ import annotations

import numpy as np
from typing import Any

from deeptutor.agents.lecture_script.visual_elements import GeometryObject


class GeometryFactory:
    """Factory for creating Manim geometric objects with precise coordinates."""

    # Standard coordinate system (ManimCE)
    DEFAULT_TRIANGLE_SIZE = 2.0
    DEFAULT_CIRCLE_RADIUS = 1.5

    def __init__(self):
        """Initialize the geometry factory."""
        self._code_lines: list[str] = []
        self._imports_added: set[str] = set()
        # Shared coordinate registry: point label → (x, y, z)
        # Pre-computed once across segments for geometry consistency
        self._coordinate_registry: dict[str, tuple[float, float, float]] = {}

    def register_coordinate(self, label: str, pos: tuple[float, float, float]) -> None:
        """Register a point coordinate."""
        self._coordinate_registry[label] = pos

    def get_coordinate(self, label: str) -> tuple[float, float, float] | None:
        """Get a registered point coordinate."""
        return self._coordinate_registry.get(label)

    def precompute_orthic_positions(
        self,
        triangles: list[GeometryObject],
        lines: list[GeometryObject],
        center: tuple[float, float] = (0, 0),
        size: float = 3.5,
    ) -> None:
        """Pre-compute ALL point positions for the orthic triangle configuration.

        Computes A, B, C from the first triangle, then calculates foot
        positions D (from A to BC), E (from B to AC), F (from C to AB).
        All positions stored in registry so each triangle uses consistent coords.
        """
        if "A" in self._coordinate_registry:
            return

        for geom in triangles:
            if geom.type == "triangle" and len(geom.label) == 3:
                label = geom.label
                vertices = self._calculate_triangle_vertices(
                    label, center, size, geom.properties
                )
                for i, char in enumerate(label):
                    self.register_coordinate(char, vertices[i])

                a_pos = vertices[label.index(label[0])]
                b_pos = vertices[label.index(label[1])]
                c_pos = vertices[label.index(label[2])]

                d_pos = self._foot_of_perpendicular(a_pos, b_pos, c_pos)
                self.register_coordinate("D", d_pos)
                e_pos = self._foot_of_perpendicular(b_pos, a_pos, c_pos)
                self.register_coordinate("E", e_pos)
                f_pos = self._foot_of_perpendicular(c_pos, a_pos, b_pos)
                self.register_coordinate("F", f_pos)

                for line_geom in lines:
                    if line_geom.properties.get("line_type") == "altitude" and len(line_geom.label) == 2:
                        foot_v = line_geom.label[1]
                        start_v = line_geom.label[0]
                        if start_v == label[0] and foot_v not in self._coordinate_registry:
                            self.register_coordinate(foot_v, d_pos)
                        elif start_v == label[1] and foot_v not in self._coordinate_registry:
                            self.register_coordinate(foot_v, e_pos)
                        elif start_v == label[2] and foot_v not in self._coordinate_registry:
                            self.register_coordinate(foot_v, f_pos)
                break

    @staticmethod
    def _foot_of_perpendicular(
        p: tuple[float, float, float],
        q1: tuple[float, float, float],
        q2: tuple[float, float, float],
    ) -> tuple[float, float, float]:
        """Foot of perpendicular from point P to line Q1-Q2."""
        px, py, _ = p
        q1x, q1y, _ = q1
        q2x, q2y, _ = q2
        dx, dy = q2x - q1x, q2y - q1y
        denom = dx * dx + dy * dy
        if denom < 1e-10:
            return p
        t = ((px - q1x) * dx + (py - q1y) * dy) / denom
        return (q1x + t * dx, q1y + t * dy, 0)

    def create_triangle(
        self,
        geom: GeometryObject,
        center: tuple[float, float] = (0, 0),
        size: float = DEFAULT_TRIANGLE_SIZE,
    ) -> list[str]:
        """Create triangle code with precise vertex positioning.

        Args:
            geom: Geometry object with type="triangle" and label like "ABC"
            center: Center position (x, y)
            size: Overall size of the triangle

        Returns:
            List of code lines for Manim
        """
        label = geom.label if geom.label else "ABC"
        vertices = self._calculate_triangle_vertices(
            label=label,
            center=center,
            size=size,
            properties=geom.properties,
        )

        code = [
            "        # Triangle with vertex labels",
            f"        triangle_{label} = Polygon(",
            f"            {self._fmt_point(vertices[0])},",
            f"            {self._fmt_point(vertices[1])},",
            f"            {self._fmt_point(vertices[2])},",
            "            color=BLUE,",
            "            fill_opacity=0.15,",
            "            stroke_width=3,",
            "        )",
            f"        diagram.add(triangle_{label})",
            "",
            f"        # Labels for vertices {label}",
        ]

        # Add vertex labels positioned relative to vertices
        label_positions = self._get_vertex_label_positions(label, vertices)
        for i, (vertex_label, pos, direction) in enumerate(label_positions):
            code.extend([
                f"        label_{vertex_label} = MathTex(\"{vertex_label}\")",
                f"        label_{vertex_label}.next_to({self._fmt_point(pos)}, {direction}, buff=0.15)",
                f"        diagram.add(label_{vertex_label})",
            ])

        # Add right angle mark if specified
        if geom.properties.get("right_angle"):
            right_angle_vertex = geom.properties["right_angle"]
            code.extend(self._create_right_angle_mark(label, right_angle_vertex, vertices))

        return code

    def _calculate_triangle_vertices(
        self,
        label: str,
        center: tuple[float, float],
        size: float,
        properties: dict[str, Any],
    ) -> list[tuple[float, float, float]]:
        """Calculate precise triangle vertices.

        For a right triangle with right angle at C (last vertex):
        - Place C at bottom right
        - B at bottom left
        - A at top right

        For general triangle:
        - Equilateral triangle centered at origin
        """
        cx, cy = center

        # Check registry first — use pre-computed positions if available
        reg_vertices = []
        for char in label:
            pos = self._coordinate_registry.get(char)
            if pos is not None:
                reg_vertices.append(pos)
        if len(reg_vertices) == 3:
            return reg_vertices

        # Check if right triangle
        right_angle_vertex = properties.get("right_angle")

        if right_angle_vertex and len(label) == 3:
            # Right triangle: right angle at specified vertex
            # Layout: right angle at bottom right, legs along axes
            ra_idx = label.index(right_angle_vertex)

            # Vertices in order: [A, B, C] where C is right angle
            # Reorder so right_angle_vertex is at index 2
            ordered_label = list(label)
            if ra_idx != 2:
                ordered_label[2], ordered_label[ra_idx] = ordered_label[ra_idx], ordered_label[2]

            # C (right angle) at bottom right
            v_c = (cx + size * 0.5, cy - size * 0.4, 0)
            # B at bottom left (horizontal leg)
            v_b = (cx - size * 0.5, cy - size * 0.4, 0)
            # A at top right (vertical leg)
            v_a = (cx + size * 0.5, cy + size * 0.6, 0)

            # Map back to original label order
            vertices = [None, None, None]
            for i, char in enumerate(label):
                idx = ordered_label.index(char)
                vertices[i] = [v_a, v_b, v_c][idx]

            return vertices

        # General/equilateral triangle
        # A at top, B at bottom left, C at bottom right
        height = size * np.sqrt(3) / 2
        v_a = (cx, cy + height * 0.5, 0)
        v_b = (cx - size * 0.5, cy - height * 0.3, 0)
        v_c = (cx + size * 0.5, cy - height * 0.3, 0)

        return [v_a, v_b, v_c]

    def _get_vertex_label_positions(
        self,
        label: str,
        vertices: list[tuple[float, float, float]],
    ) -> list[tuple[str, tuple[float, float, float], str]]:
        """Get label positions and directions for each vertex.

        Returns:
            List of (label_char, position, direction) tuples
        """
        positions = []
        directions = ["UP", "DL", "DR"]  # Top vertex up, others down-left/down-right

        for i, char in enumerate(label):
            if i < len(vertices):
                vx, vy, _ = vertices[i]
                # Offset slightly from vertex
                offset = 0.3
                if i == 0:  # Top vertex
                    pos = (vx, vy + offset, 0)
                    direction = "UP"
                elif i == 1:  # Bottom left
                    pos = (vx - offset * 0.5, vy - offset, 0)
                    direction = "DL"
                else:  # Bottom right
                    pos = (vx + offset * 0.5, vy - offset, 0)
                    direction = "DR"
                positions.append((char, pos, direction))

        return positions

    def _create_right_angle_mark(
        self,
        triangle_label: str,
        right_angle_vertex: str,
        vertices: list[tuple[float, float, float]],
    ) -> list[str]:
        """Create right angle mark (small square) at the specified vertex.

        Args:
            triangle_label: Label of the triangle (e.g., "ABC")
            right_angle_vertex: Which vertex has the right angle (e.g., "C")
            vertices: List of vertex coordinates

        Returns:
            Code lines for the right angle mark
        """
        # Find the vertex index
        if right_angle_vertex not in triangle_label:
            return []

        idx = triangle_label.index(right_angle_vertex)
        if idx >= len(vertices):
            return []

        vx, vy, _ = vertices[idx]

        # Create a small square for right angle mark
        # Position it inside the angle
        square_size = 0.25

        # Determine offset direction based on vertex position
        if idx == 2:  # Bottom right vertex (typical right angle position)
            offset_x, offset_y = -square_size / 2, square_size / 2
        elif idx == 0:  # Top vertex
            offset_x, offset_y = square_size / 2, -square_size / 2
        else:  # Bottom left
            offset_x, offset_y = square_size / 2, square_size / 2

        code = [
            f"        # Right angle mark at {right_angle_vertex}",
            f"        right_angle_sq = Square(side_length={square_size}, fill_opacity=0, stroke_width=2, color=YELLOW)",
            f"        right_angle_sq.move_to({self._fmt_point((vx + offset_x, vy + offset_y, 0))})",
            f"        diagram.add(right_angle_sq)",
        ]

        return code

    def create_circle(
        self,
        geom: GeometryObject,
        center: tuple[float, float] = (0, 0),
        radius: float = DEFAULT_CIRCLE_RADIUS,
    ) -> list[str]:
        """Create circle with center point and optional label.

        Args:
            geom: Geometry object with type="circle"
            center: Center position (x, y)
            radius: Circle radius

        Returns:
            List of code lines for Manim
        """
        label = geom.label if geom.label else "O"
        cx, cy = center

        code = [
            f"        # Circle {label}",
            f"        circle_{label} = Circle(radius={radius}, color=GREEN, stroke_width=2)",
            f"        circle_{label}.move_to({self._fmt_point((cx, cy, 0))})",
            f"        diagram.add(circle_{label})",
            "",
            f"        # Center point {label}",
            f"        center_dot = Dot(point={self._fmt_point((cx, cy, 0))}, radius=0.08, color=YELLOW)",
            f"        diagram.add(center_dot)",
        ]

        # Add center label
        code.extend([
            f"        center_label = MathTex(\"{label}\")",
            f"        center_label.next_to({self._fmt_point((cx, cy, 0))}, DOWN, buff=0.2)",
            "        diagram.add(center_label)",
        ])

        return code

    def create_line(
        self,
        geom: GeometryObject,
        start_point: tuple[float, float] = (-1, 0),
        end_point: tuple[float, float] = (1, 0),
        dashed: bool = False,
    ) -> list[str]:
        """Create a line segment (for altitudes, medians, etc.).

        Args:
            geom: Geometry object with type="line"
            start_point: Start position (x, y)
            end_point: End position (x, y)
            dashed: Whether to use dashed line

        Returns:
            List of code lines for Manim
        """
        label = geom.label if geom.label else "L"
        line_type = geom.properties.get("line_type", "line")

        # Color based on line type
        color_map = {
            "altitude": "YELLOW",
            "median": "GREEN",
            "diameter": "BLUE",
            "line": "WHITE",
        }
        color = color_map.get(line_type, "WHITE")

        if dashed:
            code = [
                f"        # {line_type.capitalize()} line {label}",
                f"        line_{label} = DashedLine(",
                f"            start={self._fmt_point((start_point[0], start_point[1], 0))},",
                f"            end={self._fmt_point((end_point[0], end_point[1], 0))},",
                "            dash_length=0.15,",
                f"            color={color},",
                "            stroke_width=2,",
                "        )",
                f"        diagram.add(line_{label})",
            ]
        else:
            code = [
                f"        # {line_type.capitalize()} line {label}",
                f"        line_{label} = Line(",
                f"            start={self._fmt_point((start_point[0], start_point[1], 0))},",
                f"            end={self._fmt_point((end_point[0], end_point[1], 0))},",
                f"            color={color},",
                "            stroke_width=2,",
                "        )",
                f"        diagram.add(line_{label})",
            ]

        return code

    def create_angle(
        self,
        geom: GeometryObject,
        vertex: tuple[float, float] = (0, 0),
        radius: float = 0.5,
    ) -> list[str]:
        """Create an angle arc mark.

        Args:
            geom: Geometry object with type="angle"
            vertex: Vertex position (x, y)
            radius: Arc radius

        Returns:
            List of code lines for Manim
        """
        label = geom.label if geom.label else "A"

        code = [
            f"        # Angle {label}",
            f"        angle_arc = Arc(radius={radius}, angle=PI/3, start_angle=PI/6, color=YELLOW)",
            f"        angle_arc.move_to({self._fmt_point((vertex[0], vertex[1], 0))})",
            f"        diagram.add(angle_arc)",
        ]

        return code

    def create_altitude_line(
        self,
        altitude_label: str,
        triangle_label: str,
        triangle_vertices: list[tuple[float, float, float]],
    ) -> list[str]:
        """Generate code for altitude line in a triangle.

        Calculates the foot of the perpendicular from the altitude's start
        vertex to the opposite side of the triangle.

        Args:
            altitude_label: Label like "AD" where A is vertex, D is foot
            triangle_label: Triangle label like "ABC"
            triangle_vertices: List of 3 vertex coordinates matching triangle_label

        Returns:
            Code lines for the altitude DashedLine
        """
        if len(altitude_label) < 2:
            return []

        start_v = altitude_label[0]

        if start_v not in triangle_label:
            return []

        # Other two vertices = opposite side
        other = [v for v in triangle_label if v != start_v]
        if len(other) != 2:
            return []

        p_start = triangle_vertices[triangle_label.index(start_v)]
        p_side0 = triangle_vertices[triangle_label.index(other[0])]
        p_side1 = triangle_vertices[triangle_label.index(other[1])]

        # Calculate foot of perpendicular from start_v to line side0-side1
        ax, ay, _ = p_start
        vx, vy, _ = p_side0
        wx, wy, _ = p_side1

        # Project A onto line VW: foot = V + t*(W-V), t = ((A-V)·(W-V))/|W-V|²
        dx, dy = wx - vx, wy - vy
        denom = dx * dx + dy * dy
        if denom < 1e-10:
            return []

        t = ((ax - vx) * dx + (ay - vy) * dy) / denom
        foot_x = vx + t * dx
        foot_y = vy + t * dy

        code = [
            f"        # Altitude from {start_v} to side {other[0]}{other[1]}",
            f"        altitude_{altitude_label} = DashedLine(",
            f"            start={self._fmt_point(p_start)},",
            f"            end={self._fmt_point((foot_x, foot_y, 0))},",
            "            color=YELLOW,",
            "            stroke_width=2,",
            "            dash_length=0.1,",
            "        )",
            f"        diagram.add(altitude_{altitude_label})",
            "",
        ]

        return code

    def _fmt_point(self, point: tuple[float, float, float]) -> str:
        """Format a 3D point for Manim code."""
        x, y, z = point
        # Use compact format for common values
        if z == 0:
            return f"np.array([{x:.2f}, {y:.2f}, 0])"
        return f"np.array([{x:.2f}, {y:.2f}, {z:.2f}])"


# Convenience functions for direct use

def create_triangle(
    label: str = "ABC",
    right_angle: str | None = None,
    center: tuple[float, float] = (0, 0),
    size: float = 2.0,
) -> list[str]:
    """Convenience function to create triangle code.

    Args:
        label: Triangle vertex labels (e.g., "ABC")
        right_angle: Which vertex has right angle (e.g., "C")
        center: Center position
        size: Triangle size

    Returns:
        List of code lines
    """
    factory = GeometryFactory()
    geom = GeometryObject(
        type="triangle",
        label=label,
        properties={"right_angle": right_angle} if right_angle else {},
    )
    return factory.create_triangle(geom, center, size)


def create_circle(
    label: str = "O",
    center: tuple[float, float] = (0, 0),
    radius: float = 1.5,
) -> list[str]:
    """Convenience function to create circle code.

    Args:
        label: Circle center label
        center: Center position
        radius: Circle radius

    Returns:
        List of code lines
    """
    factory = GeometryFactory()
    geom = GeometryObject(type="circle", label=label)
    return factory.create_circle(geom, center, radius)
