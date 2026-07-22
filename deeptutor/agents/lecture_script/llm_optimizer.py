"""LLM-based colloquial narration optimizer.

Converts technical math explanations into conversational teaching scripts
suitable for video narration with TTS.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from .models import LectureScript, LectureSegment, ScriptTiming
from .visual_elements import VisualElements, extract_visual_elements

logger = logging.getLogger(__name__)


# System prompt for lecture optimization
COLLOQUIAL_OPTIMIZER_PROMPT = """You are a professional math education video script writer. Your task is to convert technical math solution steps into conversational, engaging teaching scripts suitable for video narration.

## Conversion Requirements

1. **Conversational Tone**: Write like a friendly teacher talking to a student one-on-one. Use phrases like:
   - "Let's look at..."
   - "You'll notice that..."
   - "Here's the key insight..."
   - "Now, what happens if..."

2. **Smooth Transitions**: Add natural transitions between steps:
   - "Next, let's move to..."
   - "Having understood this, we can now..."
   - "This leads us to our next step..."

3. **Emphasis on Key Points**: Highlight important concepts:
   - "Pay attention to..."
   - "The crucial point here is..."
   - "This is important because..."

4. **Pacing Control**: Keep sentences at moderate length for TTS (avoid very long clauses). Break complex ideas into shorter sentences.

5. **Visual Cues**: Mark where visuals should appear with [VISUAL: description]

## Input Format

You will receive:
- Problem: The original math problem
- Solution Strategy: Overall approach to solving the problem
- Steps: Technical step descriptions

## Output Format

For each step, provide a JSON object with:
- narration: Colloquial English narration script (for TTS)
- visual_desc: Description of what should be shown visually
- key_points: List of 2-3 key mathematical points to emphasize
- duration_hint: Estimated duration in seconds (3-15 range)

Output format:
{
  "segments": [
    {
      "step_index": 1,
      "narration": "English narration text...",
      "visual_desc": "Visual description...",
      "key_points": ["point 1", "point 2"],
      "duration_hint": 8
    },
    ...
  ],
  "intro": {
    "narration": "Introduction narration...",
    "visual_desc": "Intro visual...",
    "duration_hint": 10
  },
  "conclusion": {
    "narration": "Conclusion narration...",
    "visual_desc": "Conclusion visual...",
    "duration_hint": 8
  }
}

## Important Rules

1. Output ONLY valid JSON, no markdown formatting or explanations
2. Narration must be in English (for TTS compatibility)
3. Keep each segment's narration under 200 words
4. Use simple, clear language suitable for educational content
5. Include specific math terms where needed (formulas, theorem names)
6. Match the pacing to the complexity: simple steps = 3-5s, complex derivations = 10-15s
"""


def format_steps_for_llm(segments: list[LectureSegment]) -> str:
    """Format segments for the LLM prompt."""
    parts = []
    for seg in segments:
        parts.append(f"""
Step {seg.step_index}: {seg.title}
Technical Content: {seg.script[:300]}
Visual Elements: {seg.visual_description}
""")
    return "\n".join(parts)


class LectureScriptOptimizer:
    """Optimize lecture scripts using LLM for colloquial narration."""

    def __init__(self, llm_client=None):
        """Initialize with optional LLM client.

        Args:
            llm_client: LLM client for optimization. If None, will try to get default.
        """
        self._llm = llm_client

    def _get_llm(self):
        """Get LLM client (lazy initialization)."""
        if self._llm is None:
            try:
                from deeptutor.services.llm import get_llm_client
                self._llm = get_llm_client()
            except Exception as e:
                logger.error(f"Failed to initialize LLM client: {e}")
                raise
        return self._llm

    async def optimize_script(
        self,
        base_script: LectureScript,
        problem_data: dict[str, Any],
    ) -> LectureScript:
        """Optimize a lecture script with LLM colloquial narration.

        Args:
            base_script: The base script from template generation
            problem_data: Problem data from MathNet

        Returns:
            Optimized LectureScript with colloquial narration
        """
        try:
            llm = self._get_llm()

            # Build the prompt
            prompt = self._build_optimization_prompt(base_script, problem_data)

            # Call LLM
            response = await llm.complete(
                prompt,
                system_prompt=COLLOQUIAL_OPTIMIZER_PROMPT,
                temperature=0.7,
            )

            # Parse response
            content = response.text if hasattr(response, "text") else str(response)
            optimized_data = self._parse_llm_response(content)

            # Merge with base script
            return self._merge_optimized_content(base_script, optimized_data, problem_data)

        except Exception as e:
            logger.exception("LLM optimization failed, returning base script")
            # Return base script with visual elements added
            return self._enrich_base_script(base_script, problem_data)

    def _build_optimization_prompt(
        self,
        base_script: LectureScript,
        problem_data: dict[str, Any],
    ) -> str:
        """Build the optimization prompt."""
        problem_markdown = problem_data.get("problem_markdown", "")
        strategy = problem_data.get("solution_strategy_zh", "")

        return f"""Convert this math problem solution into a conversational teaching script.

PROBLEM:
{problem_markdown[:500]}

SOLUTION STRATEGY:
{strategy[:300] if strategy else "Solve step by step"}

STEPS TO CONVERT:
{format_steps_for_llm(base_script.segments)}

Generate the optimized script in the required JSON format."""

    def _parse_llm_response(self, content: str) -> dict[str, Any]:
        """Parse the LLM response into structured data.

        Args:
            content: Raw LLM response

        Returns:
            Parsed dictionary with segments, intro, conclusion
        """
        # Try to extract JSON from markdown code blocks
        if "```json" in content:
            content = content.split("```json")[1].split("```")[0].strip()
        elif "```" in content:
            content = content.split("```")[1].split("```")[0].strip()

        try:
            return json.loads(content)
        except json.JSONDecodeError as e:
            logger.warning(f"Failed to parse LLM response as JSON: {e}")
            # Return empty structure as fallback
            return {"segments": [], "intro": None, "conclusion": None}

    def _merge_optimized_content(
        self,
        base_script: LectureScript,
        optimized_data: dict[str, Any],
        problem_data: dict[str, Any],
    ) -> LectureScript:
        """Merge LLM-optimized content with base script.

        Args:
            base_script: Original base script
            optimized_data: LLM optimization output
            problem_data: Problem data

        Returns:
            Merged LectureScript
        """
        # Create new segments with optimized content
        new_segments = []

        for base_seg in base_script.segments:
            # Find matching optimized segment
            opt_seg = None
            for s in optimized_data.get("segments", []):
                if s.get("step_index") == base_seg.step_index:
                    opt_seg = s
                    break

            if opt_seg:
                # Use optimized content
                duration_hint = opt_seg.get("duration_hint", 5)
                new_seg = LectureSegment(
                    step_index=base_seg.step_index,
                    title=base_seg.title,
                    script=opt_seg.get("narration", base_seg.script),
                    visual_description=opt_seg.get("visual_desc", base_seg.visual_description),
                    timing=ScriptTiming(estimated_duration_seconds=duration_hint),
                    key_points=opt_seg.get("key_points", base_seg.key_points),
                    start_time_ms=0,
                    end_time_ms=0,
                )
            else:
                # Fall back to base segment
                new_seg = base_seg

            # Extract visual elements from problem data
            step_data = self._find_step_data(problem_data, base_seg.step_index)
            if step_data:
                visual_elements = extract_visual_elements(step_data)
                # Add visual elements to visual_description
                if visual_elements.geometry:
                    geom_desc = ", ".join([f"{g.type} {g.label}" for g in visual_elements.geometry])
                    new_seg.visual_description += f" | Geometry: {geom_desc}"

            new_segments.append(new_seg)

        # Handle intro
        intro_data = optimized_data.get("intro")
        if intro_data:
            intro = LectureSegment(
                step_index=0,
                title="Introduction",
                script=intro_data.get("narration", base_script.intro.script),
                visual_description=intro_data.get("visual_desc", base_script.intro.visual_description),
                timing=ScriptTiming(
                    estimated_duration_seconds=intro_data.get("duration_hint", 8)
                ),
                key_points=["Understanding the problem"],
            )
        else:
            intro = base_script.intro

        # Handle conclusion
        conclusion_data = optimized_data.get("conclusion")
        if conclusion_data:
            conclusion = LectureSegment(
                step_index=len(new_segments) + 1,
                title="Conclusion",
                script=conclusion_data.get("narration", base_script.conclusion.script),
                visual_description=conclusion_data.get("visual_desc", base_script.conclusion.visual_description),
                timing=ScriptTiming(
                    estimated_duration_seconds=conclusion_data.get("duration_hint", 6)
                ),
                key_points=["Summary"],
            )
        else:
            conclusion = base_script.conclusion

        return LectureScript(
            problem_id=base_script.problem_id,
            intro=intro,
            segments=new_segments,
            conclusion=conclusion,
        )

    def _enrich_base_script(
        self,
        base_script: LectureScript,
        problem_data: dict[str, Any],
    ) -> LectureScript:
        """Enrich base script with visual elements (fallback when LLM fails).

        Args:
            base_script: Original base script
            problem_data: Problem data

        Returns:
            Enriched LectureScript
        """
        for seg in base_script.segments:
            step_data = self._find_step_data(problem_data, seg.step_index)
            if step_data:
                visual_elements = extract_visual_elements(step_data)
                if visual_elements.geometry:
                    geom_desc = ", ".join([f"{g.type} {g.label}" for g in visual_elements.geometry])
                    seg.visual_description += f" | Geometry: {geom_desc}"

        return base_script

    def _find_step_data(
        self,
        problem_data: dict[str, Any],
        step_index: int,
    ) -> dict[str, Any] | None:
        """Find step data by index."""
        steps = problem_data.get("steps", [])
        for step in steps:
            if step.get("step_index") == step_index:
                return step
        return None


# Convenience function for direct use
async def optimize_script_with_llm(
    base_script: LectureScript,
    problem_data: dict[str, Any],
) -> LectureScript:
    """Convenience function to optimize a script with LLM.

    Args:
        base_script: Base script from template generation
        problem_data: Problem data from MathNet

    Returns:
        Optimized LectureScript
    """
    optimizer = LectureScriptOptimizer()
    return await optimizer.optimize_script(base_script, problem_data)
