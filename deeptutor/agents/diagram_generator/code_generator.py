"""Static diagram code generator for Tier 2 fallback.

Generates complete, runnable Manim code with:
- Precise geometric objects (triangles, circles, lines)
- MathTex formulas with proper rendering
- Left-right panel layout
- Coordinated animations with proper timing
"""

from __future__ import annotations

import logging
import textwrap
from typing import Any

from deeptutor.agents.lecture_script.models import LectureSegment, LectureScript
from deeptutor.agents.lecture_script.visual_elements import VisualElements

from .geometry_factory import GeometryFactory
from .formula_renderer import FormulaRenderer, sanitize_for_math_tex
from .layout_manager import LayoutManager, LayoutConfig

logger = logging.getLogger(__name__)


class StaticDiagramGenerator:
    """Tier 2 static diagram generator - rule-based, no LLM.

    This generator creates Manim code using precise rules:
    1. Extract visual elements from step data
    2. Generate geometry using exact coordinates
    3. Render formulas with MathTex
    4. Apply left-right layout
    5. Add coordinated animations
    """

    # Content animation run_time per segment type (seconds).
    # These determine how long content FadeIn takes AFTER step_label appears.
    # _inject_manim_subtitles() uses these to reduce EARLY subtitle wait so
    # that subtitles stay visible during content animation.
    # If you change run_time values below, update these to match.
    ANIM_DUR_INTRO = 0.8       # FadeIn(intro_content) run_time=0.8
    ANIM_DUR_STEP = 1.5        # FadeIn(left, 1.0) + FadeIn(right, 0.5)
    ANIM_DUR_CONCLUSION = 1.0  # FadeIn(summary, 0.5) + FadeIn(answer, 0.5)

    def __init__(self):
        """Initialize the generator."""
        self.geometry_factory = GeometryFactory()
        self.formula_renderer = FormulaRenderer()
        self.layout_manager = LayoutManager(LayoutConfig())

    def generate_for_segment(
        self,
        segment: LectureSegment,
        visual_elements: VisualElements | None = None,
    ) -> list[str]:
        """Generate Manim code for a single segment.

        Args:
            segment: The lecture segment
            visual_elements: Pre-extracted visual elements

        Returns:
            List of code lines
        """
        code = []

        # Header
        code.extend(
            self.layout_manager.generate_segment_header(
                segment_type="step" if segment.step_index > 0 else "intro",
                title=segment.title,
                step_index=segment.step_index,
            )
        )

        # EARLY subtitle slot — subtitles play DURING content FadeIn
        code.append("        self.wait(0.01)  # SUBS_EARLY")

        # Determine content based on segment type
        if segment.step_index == 0:
            # Intro segment (full-width centered layout)
            code.extend(self._generate_intro_content(segment, visual_elements))
            cleanup_mobjects = ["step_label", "intro_content"]
        elif segment.title.lower() == "conclusion":  # Conclusion
            code.extend(self._generate_conclusion_content(segment, visual_elements))
            cleanup_mobjects = ["step_label", "summary", "answer"]
        else:
            # Step segment — always uses left-right split layout
            code.extend(self._generate_step_content(segment, visual_elements))
            cleanup_mobjects = ["step_label", "left_content", "right_content"]

        # LATE subtitle slot — after content fully visible
        seg_duration = segment.timing.estimated_duration_seconds if segment.timing else 5.0
        code.append(f"        self.wait({max(0.5, seg_duration - 1.0):.1f})  # SUBS_LATE")

        # PAUSE for conclusion only — keeps answer visible before fade out
        is_conclusion = segment.step_index > 0 and segment.title.lower() == "conclusion"
        if is_conclusion:
            code.append("        self.wait(3.0)  # PAUSE — buffer so video doesn't end abruptly")

        # Cleanup (FadeOut all content)
        if cleanup_mobjects:
            fade_outs = ", ".join([f"FadeOut({name})" for name in cleanup_mobjects])
            code.append(f"        self.play({fade_outs}, run_time=0.5)")
        else:
            code.append("        self.play(FadeOut(step_label), run_time=0.3)")
        code.append("")

        return code

    def _generate_intro_content(
        self,
        segment: LectureSegment,
        visual_elements: VisualElements | None,
    ) -> list[str]:
        """Generate content for intro segment — FULL-WIDTH centered layout (deterministic template)."""
        code = []

        problem_text = getattr(segment, 'problem_text', None)

        # Problem text content — full-width centered (no separate heading, step_label is enough)
        code.append("        intro_content = VGroup()")
        if problem_text:
            lines = textwrap.wrap(problem_text, width=50)
            if len(lines) > 10:
                lines = lines[:8] + ["..."] + lines[-2:]
            for i, line in enumerate(lines):
                escaped = line.replace('"', '\\"')
                code.extend([
                    f"        prob_line_{i} = Text(\"{escaped}\", font_size=18, font=\"sans-serif\")",
                    f"        intro_content.add(prob_line_{i})",
                ])
        else:
            code.extend([
                '        prob_line_0 = Text("Problem Statement", font_size=22, color=GRAY, font="sans-serif")',
                '        intro_content.add(prob_line_0)',
            ])

        code.extend([
            "        intro_content.arrange(DOWN, buff=0.15, aligned_edge=LEFT)",
            "        intro_content.move_to(UP * 0.3)",
            "        if intro_content.width > 12:",
            "            intro_content.scale(12.0 / intro_content.width)",
            "        self.play(FadeIn(intro_content), run_time=0.8)",
            "",
        ])

        return code

    def _generate_step_content(
        self,
        segment: LectureSegment,
        visual_elements: VisualElements | None,
    ) -> list[str]:
        """Generate content for step segment — deterministic LEFT/RIGHT formula template.

        LEFT panel: formulas extracted from step text (MathTex if possible, Text fallback)
        RIGHT panel: step title + key result formula (or step goal text)
        """
        import re
        code = []

        step_text_raw = getattr(segment, 'step_text_raw', '')
        step_title = getattr(segment, 'step_title', '') or segment.title or ''
        step_goal = getattr(segment, 'step_goal', '')

        # Extract $...$ LaTeX formulas from raw step text
        formulas = re.findall(r'\$\$?(.*?)\$\$?', step_text_raw)
        formulas = [f.strip() for f in formulas if f.strip()]

        # Fall back to visual_elements.formulas if available
        if not formulas and visual_elements and visual_elements.formulas:
            formulas = visual_elements.formulas[:4]

        # Classify: last formula = result (RIGHT), rest = process (LEFT)
        if len(formulas) >= 2:
            result_formula = formulas[-1]
            process_formulas = formulas[:-1]
        elif len(formulas) == 1:
            result_formula = formulas[0]
            process_formulas = []
        else:
            result_formula = None
            process_formulas = []

        display_text = getattr(segment, 'step_text', '') or ''

        # ===== LEFT PANEL: Math Formulas (process/transformation) =====
        code.append("        # ===== LEFT PANEL: Math Formulas =====")
        code.append("        left_content = VGroup()")

        if process_formulas:
            for i, f in enumerate(process_formulas[:3]):
                safe = f.replace('"', '\\"')
                code.append(f"        pf_{i} = MathTex(r\"{safe}\", font_size=24)")
                code.append(f"        pf_{i}.scale(0.85)")
                code.append(f"        left_content.add(pf_{i})")
        elif result_formula:
            # Single formula goes to LEFT as well (RIGHT gets title + formula too)
            safe = result_formula.replace('"', '\\"')
            code.append(f"        sf = MathTex(r\"{safe}\", font_size=24)")
            code.append("        sf.scale(0.85)")
            code.append("        left_content.add(sf)")
        else:
            # No formulas — show step description on left panel
            snippet = (display_text[:150] or segment.script[:150] or step_title).replace('"', '\\"')
            code.append(f"        step_desc = Text(\"{snippet}\", font_size=20, font=\"sans-serif\")")
            code.append("        if step_desc.width > 6.0:")
            code.append("            step_desc.scale(6.0 / step_desc.width)")
            code.append("        left_content.add(step_desc)")

        code.append("")

        # ===== RIGHT PANEL: Step Title + Result =====
        code.append("        # ===== RIGHT PANEL: Step Result =====")
        code.append("        right_content = VGroup()")

        # Step title
        escaped_title = step_title.replace('"', '\\"')[:60]
        code.append(f"        st_title = Text(\"{escaped_title}\", font_size=22, color=YELLOW, font=\"sans-serif\")")
        code.append("        right_content.add(st_title)")

        # Key result formula or goal text
        if result_formula:
            safe = result_formula.replace('"', '\\"')
            code.append(f"        st_result = MathTex(r\"{safe}\", font_size=28)")
            code.append("        st_result.set_color(YELLOW)")
            code.append("        st_result.scale(0.9)")
            code.append("        right_content.add(st_result)")
        elif step_goal:
            escaped_goal = step_goal.replace('"', '\\"')[:100]
            code.append(f"        st_goal = Text(\"{escaped_goal}\", font_size=20, color=YELLOW, font=\"sans-serif\")")
            code.append("        if st_goal.width > 6.0:")
            code.append("            st_goal.scale(6.0 / st_goal.width)")
            code.append("        right_content.add(st_goal)")

        # Shared layout positioning
        code.extend([
            "        left_content.arrange(DOWN, buff=0.25)",
            "        if left_content.width > 6.0:",
            "            left_content.scale(6.0 / left_content.width)",
            "        left_content.move_to(LEFT * 3.5 + UP * 0.3)",
            "        self.play(FadeIn(left_content), run_time=1.0)",
            "",
            "        right_content.arrange(DOWN, buff=0.3)",
            "        if right_content.width > 6.0:",
            "            right_content.scale(6.0 / right_content.width)",
            "        right_content.move_to(RIGHT * 3.5 + UP * 0.3)",
            "        self.play(FadeIn(right_content), run_time=0.5)",
            "",
        ])

        return code

    def _generate_conclusion_content(
        self,
        segment: LectureSegment,
        visual_elements: VisualElements | None,
    ) -> list[str]:
        """Generate content for conclusion segment — centered layout (deterministic template)."""
        code = []

        code.extend([
            "        # ===== CONCLUSION: Final result =====",
            "        summary = Text(\"Solution Complete\", font_size=32, color=GREEN, font=\"sans-serif\")",
            "        summary.move_to(UP * 1.5)",
            "        self.play(FadeIn(summary), run_time=0.5)",
            "",
            "        # Final answer",
            "        answer = Text(\"Answer\", font_size=28, color=YELLOW, font=\"sans-serif\")",
            "        answer.move_to(ORIGIN)",
            "        self.play(FadeIn(answer), run_time=0.5)",
            "",
        ])

        return code

    def _generate_formulas_code(
        self,
        formulas: list[str],
        panel: str = "right",
        add_to_group: str | None = None,
    ) -> list[str]:
        """Generate code for formula rendering.

        Args:
            formulas: List of LaTeX formulas
            panel: Which panel (left or right)
            add_to_group: If specified, add formulas to this VGroup

        Returns:
            List of code lines
        """
        if not formulas:
            return []

        code = []

        for i, formula in enumerate(formulas):
            # Sanitize: remove non-LaTeX chars (Chinese, etc.) that crash pdflatex
            formula = sanitize_for_math_tex(formula)
            if not formula:
                continue
            var_name = f"formula_{i}"
            escaped = formula.replace('"', '\\"')

            code.extend([
                f"        {var_name} = MathTex(r\"{escaped}\", font_size=26)",
                f"        {var_name}.scale(0.9)",
            ])

            if add_to_group:
                code.append(f"        {add_to_group}.add({var_name})")

        return code

    def generate_complete_scene(
        self,
        lecture_script: LectureScript,
    ) -> str:
        """Generate complete Manim code for entire lecture.

        Args:
            lecture_script: Complete lecture script with all segments

        Returns:
            Complete runnable Python code
        """
        code_lines = self.layout_manager.generate_scene_header()

        # Generate code for each segment
        all_segments = [lecture_script.intro] + lecture_script.segments + [lecture_script.conclusion]

        for segment in all_segments:
            # Extract visual elements for this segment
            visual_elements = None
            if hasattr(segment, 'visual_elements'):
                visual_elements = segment.visual_elements

            segment_code = self.generate_for_segment(segment, visual_elements)
            code_lines.extend(segment_code)

        # Close the construct method
        code_lines.append("        # End of presentation")

        return "\n".join(code_lines)

    def generate_for_segments(
        self,
        segments: list[LectureSegment],
    ) -> str:
        """Generate Manim code for a list of segments (simplified API).

        Args:
            segments: List of lecture segments

        Returns:
            Complete runnable Python code
        """
        code_lines = self.layout_manager.generate_scene_header()

        for segment in segments:
            # Get visual_elements from segment if attached
            visual_elements = getattr(segment, 'visual_elements', None)
            segment_code = self.generate_for_segment(segment, visual_elements)
            code_lines.extend(segment_code)

        code_lines.append("        # End of presentation")

        return "\n".join(code_lines)


def generate_tier2_manim(
    segments: list[LectureSegment],
    problem_id: str = "",
) -> str:
    """Convenience function to generate Tier 2 Manim code.

    Args:
        segments: List of lecture segments
        problem_id: Optional problem ID for reference

    Returns:
        Complete Manim code
    """
    generator = StaticDiagramGenerator()

    if problem_id:
        logger.info(f"Generating Tier 2 code for problem {problem_id}")

    return generator.generate_for_segments(segments)


def _split_subtitle_sentences(text: str) -> list[str]:
    """Split text into sentences for Manim subtitle display.

    Splits on sentence boundaries (.!?) while keeping periods within
    numbers (e.g., "n = 1.5") intact. Returns at least one sentence.
    """
    import re

    # Split on !? boundaries
    raw = re.split(r'(?<=[!?])\s+', text)

    # Further split on period + capital letter (sentence boundary)
    refined = []
    for part in raw:
        sub = re.split(r'(?<=\.)\s+(?=[A-Z])', part)
        refined.extend(sub)

    result = [s.strip() for s in refined if s.strip()]
    return result if result else [text]
