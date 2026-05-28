"""Lecture Script Generator implementation.

Converts MathNet problem steps into lecture scripts for video generation.
"""

from __future__ import annotations

import re
from typing import Any

from .models import LectureScript, LectureSegment, ScriptTiming


class LectureScriptGenerator:
    """Generate lecture scripts from MathNet problem data.

    Usage:
        generator = LectureScriptGenerator()
        script = generator.generate_from_mathnet(
            problem_id="0kg6",
            problem_markdown="...",
            architecture={...},
            steps=[...]
        )
    """

    # Speaking rate estimates (characters per second)
    CHINESE_CHARS_PER_SECOND = 4.0
    ENGLISH_CHARS_PER_SECOND = 10.0

    def __init__(self):
        """Initialize the generator."""
        pass

    def _estimate_duration(self, text: str) -> float:
        """Estimate narration duration for text.

        Args:
            text: The text to be spoken

        Returns:
            Estimated duration in seconds
        """
        # Count Chinese and English characters
        chinese_chars = len(re.findall(r'[一-鿿]', text))
        english_chars = len(re.findall(r'[a-zA-Z]', text))

        chinese_duration = chinese_chars / self.CHINESE_CHARS_PER_SECOND
        english_duration = english_chars / self.ENGLISH_CHARS_PER_SECOND

        # Add base pause time
        base_duration = 1.0

        return max(base_duration, chinese_duration + english_duration)

    def _generate_intro_script(
        self,
        problem_id: str,
        problem_markdown: str,
        architecture: dict[str, Any] | None,
    ) -> LectureSegment:
        """Generate the introduction segment.

        Introduces the problem and sets up the context.
        """
        # Use problem summary if available
        if architecture and architecture.get("problem_summary_zh"):
            summary = architecture["problem_summary_zh"]
            script = f"今天我们来解这道有趣的数学题。{summary}"
        else:
            # Fallback: use truncated problem text
            problem_preview = problem_markdown[:100] + "..." if len(problem_markdown) > 100 else problem_markdown
            script = f"今天我们来解这道数学题。{problem_preview}"

        # Add difficulty info if available
        if architecture and architecture.get("suggested_tier"):
            tier = architecture["suggested_tier"]
            tier_names = {
                "L1": "基础入门",
                "L2": "初级竞赛",
                "L3": "中级竞赛",
                "L4": "高级竞赛",
            }
            tier_name = tier_names.get(tier, tier)
            script += f"这是一道{tier_name}难度的题目。"

        script += "让我们开始吧。"

        duration = self._estimate_duration(script)

        return LectureSegment(
            step_index=0,
            title="题目介绍",
            script=script,
            visual_description="显示题目原文，高亮关键条件",
            timing=ScriptTiming(estimated_duration_seconds=duration),
            key_points=["理解题意", "识别已知条件"],
        )

    def _generate_step_segment(
        self,
        step_index: int,
        step_data: dict[str, Any],
    ) -> LectureSegment:
        """Generate a segment for a single solution step.

        Args:
            step_index: The step number (1-based)
            step_data: The step data from MathNet

        Returns:
            LectureSegment for this step
        """
        # Extract step content
        title = step_data.get("step_title_zh", f"第{step_index}步")
        text = step_data.get("step_text_zh", "")
        explanation = step_data.get("explanation_zh", "")
        role = step_data.get("role_in_solution_zh", "")

        # Build script
        parts = []

        # Add transition if not first step
        if step_index > 1:
            transitions = [
                "接下来，",
                "我们继续看下一步。",
                "那么接下来怎么做呢？",
                "现在，",
            ]
            parts.append(transitions[step_index % len(transitions)])

        # Add step title
        parts.append(f"{title}。")

        # Add main content
        if text:
            parts.append(text)

        # Add explanation if available and different from text
        if explanation and explanation != text:
            parts.append(f"这里的关键是：{explanation}")

        # Add role description if available
        if role:
            parts.append(f"这一步的作用是：{role}")

        script = "".join(parts)

        # Generate visual description
        visual = self._infer_visual_from_step(title, text)

        # Extract key points from knowledge points
        key_points = []
        for kp in step_data.get("knowledge_points", []):
            kp_name = kp.get("name_zh", "")
            if kp_name:
                key_points.append(kp_name)

        duration = self._estimate_duration(script)

        return LectureSegment(
            step_index=step_index,
            title=title,
            script=script,
            visual_description=visual,
            timing=ScriptTiming(estimated_duration_seconds=duration),
            key_points=key_points[:3],  # Limit to top 3
        )

    def _infer_visual_from_step(self, title: str, text: str) -> str:
        """Infer what visual should be shown for a step.

        This is a simple heuristic-based approach.
        """
        title_lower = title.lower()
        text_lower = text.lower()

        # Check for specific visual patterns
        if any(kw in title_lower or kw in text_lower for kw in ["图", "画", "构造", "作图"]):
            return "几何图形，动画展示作图过程"

        if any(kw in title_lower or kw in text_lower for kw in ["方程", "代数", "计算", "代入"]):
            return "代数表达式，逐步计算过程"

        if any(kw in title_lower or kw in text_lower for kw in ["数列", "序列", "归纳"]):
            return "数列项，递推关系图示"

        if any(kw in title_lower or kw in text_lower for kw in ["证明", "推导", "因为", "所以"]):
            return "逻辑推导链条，因果箭头"

        if any(kw in title_lower or kw in text_lower for kw in ["函数", "图像", "曲线"]):
            return "函数图像，坐标系"

        # Default
        return "数学表达式和关键步骤高亮"

    def _generate_conclusion_script(
        self,
        problem_id: str,
        steps: list[dict[str, Any]],
        final_answer: str | None,
    ) -> LectureSegment:
        """Generate the conclusion segment."""
        parts = ["总结一下我们的解题过程。"]

        # Summarize key steps
        if steps:
            parts.append(f"这道题我们分了{len(steps)}个步骤来解决。")

        # Mention final answer if available
        if final_answer:
            parts.append(f"最终答案是：{final_answer}")

        parts.append("希望这个讲解对你有帮助。")

        script = "".join(parts)
        duration = self._estimate_duration(script)

        return LectureSegment(
            step_index=len(steps) + 1,
            title="总结",
            script=script,
            visual_description="回顾解题步骤，显示最终答案",
            timing=ScriptTiming(estimated_duration_seconds=duration),
            key_points=["回顾", "总结"],
        )

    def generate_from_mathnet(
        self,
        problem_id: str,
        problem_markdown: str,
        architecture: dict[str, Any] | None,
        steps: list[dict[str, Any]],
        final_answer: str | None = None,
    ) -> LectureScript:
        """Generate a lecture script from MathNet problem data.

        Args:
            problem_id: The MathNet problem ID
            problem_markdown: The problem text (with LaTeX)
            architecture: The problem architecture (solution strategy)
            steps: List of step data
            final_answer: Optional final answer

        Returns:
            Complete lecture script
        """
        # Generate intro
        intro = self._generate_intro_script(problem_id, problem_markdown, architecture)

        # Generate segments for each step
        segments = []
        for i, step_data in enumerate(steps, 1):
            segment = self._generate_step_segment(i, step_data)
            segments.append(segment)

        # Generate conclusion
        conclusion = self._generate_conclusion_script(problem_id, steps, final_answer)

        return LectureScript(
            problem_id=problem_id,
            intro=intro,
            segments=segments,
            conclusion=conclusion,
        )
