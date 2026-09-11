"""Import-free descriptors for built-in turn capabilities."""

from __future__ import annotations

from dataclasses import dataclass

from deeptutor.core.capability_protocol import CapabilityManifest


@dataclass(frozen=True, slots=True)
class BuiltinCapabilitySpec:
    class_path: str
    manifest: CapabilityManifest


def _manifest(
    name: str,
    description: str,
    *,
    stages: list[str],
    tools_used: list[str],
    cli_aliases: list[str],
    config_defaults: dict[str, object] | None = None,
) -> CapabilityManifest:
    return CapabilityManifest(
        name=name,
        description=description,
        stages=stages,
        tools_used=tools_used,
        cli_aliases=cli_aliases,
        config_defaults=config_defaults or {},
    )


BUILTIN_CAPABILITY_CLASSES: dict[str, str] = {
    "chat": "deeptutor.agents.chat.capability:ChatCapability",
    "ask_questions": ("deeptutor.capabilities.ask_questions.capability:AskQuestionsCapability"),
    "deep_solve": "deeptutor.capabilities.solve.capability:DeepSolveCapability",
    "deep_question": "deeptutor.agents.question.capability:DeepQuestionCapability",
    "deep_research": "deeptutor.agents.research.capability:DeepResearchCapability",
    "math_animator": "deeptutor.agents.math_animator.capability:MathAnimatorCapability",
    "visualize": "deeptutor.agents.visualize.capability:VisualizeCapability",
    "mastery_path": "deeptutor.capabilities.mastery.capability:MasteryPathCapability",
    "immersive_reading": "deeptutor.capabilities.reading.mode:ImmersiveReadingCapability",
    "course_study": "deeptutor.capabilities.course_study.mode:CourseStudyCapability",
    "immersive_watching": "deeptutor.capabilities.watching.mode:ImmersiveWatchingCapability",
}


BUILTIN_CAPABILITY_SPECS: dict[str, BuiltinCapabilitySpec] = {
    "chat": BuiltinCapabilitySpec(
        BUILTIN_CAPABILITY_CLASSES["chat"],
        _manifest(
            "chat",
            "Agentic chat: an exploring agent loop with tools, followed by a respond stage that streams the answer.",
            stages=["exploring", "responding"],
            tools_used=[
                "brainstorm",
                "web_search",
                "paper_search",
                "reason",
                "geogebra_analysis",
                "imagegen",
                "videogen",
            ],
            cli_aliases=["chat"],
        ),
    ),
    "ask_questions": BuiltinCapabilitySpec(
        BUILTIN_CAPABILITY_CLASSES["ask_questions"],
        _manifest(
            "ask_questions",
            "Ask the user high-value questions to fill in missing context, then complete the original request with their answers.",
            stages=["responding"],
            tools_used=["ask_user"],
            cli_aliases=["ask"],
        ),
    ),
    "deep_solve": BuiltinCapabilitySpec(
        BUILTIN_CAPABILITY_CLASSES["deep_solve"],
        _manifest(
            "deep_solve",
            "Multi-step problem solving driven by the chat agent loop.",
            stages=["responding"],
            tools_used=[
                "solve_plan",
                "solve_finish_step",
                "solve_replan",
                "rag",
                "exec",
                "geogebra_analysis",
                "reason",
            ],
            cli_aliases=["solve"],
        ),
    ),
    "deep_question": BuiltinCapabilitySpec(
        BUILTIN_CAPABILITY_CLASSES["deep_question"],
        _manifest(
            "deep_question",
            "Fast question generation (Template batches -> Generate).",
            stages=["ideation", "generation"],
            tools_used=["rag", "web_search", "exec"],
            cli_aliases=["quiz"],
        ),
    ),
    "deep_research": BuiltinCapabilitySpec(
        BUILTIN_CAPABILITY_CLASSES["deep_research"],
        _manifest(
            "deep_research",
            "Agentic-loop deep research with iterative report generation.",
            stages=["rephrasing", "decomposing", "researching", "reporting"],
            tools_used=["rag", "web_search", "paper_search", "exec"],
            cli_aliases=["research"],
        ),
    ),
    "math_animator": BuiltinCapabilitySpec(
        BUILTIN_CAPABILITY_CLASSES["math_animator"],
        _manifest(
            "math_animator",
            "Generate math animations or storyboard images with Manim.",
            stages=[
                "concept_analysis",
                "concept_design",
                "code_generation",
                "code_retry",
                "summary",
                "render_output",
            ],
            tools_used=[],
            cli_aliases=["animate"],
            config_defaults={
                "output_mode": "video",
                "quality": "medium",
                "style_hint": "",
            },
        ),
    ),
    "visualize": BuiltinCapabilitySpec(
        BUILTIN_CAPABILITY_CLASSES["visualize"],
        _manifest(
            "visualize",
            "Generate a validated visualization with any installed visualizer type, or render a Manim animation/storyboard artifact.",
            stages=[
                "analyzing",
                "generating",
                "reviewing",
                "concept_analysis",
                "concept_design",
                "code_generation",
                "code_retry",
                "summary",
                "render_output",
            ],
            tools_used=["submit_visualization"],
            cli_aliases=["visualize", "viz"],
        ),
    ),
    "mastery_path": BuiltinCapabilitySpec(
        BUILTIN_CAPABILITY_CLASSES["mastery_path"],
        _manifest(
            "mastery_path",
            "Mastery-based tutoring: a dedicated agent loop drives an adaptive mastery path with a hard, per-type mastery gate and spaced review.",
            stages=["responding"],
            tools_used=[
                "mastery_status",
                "mastery_quiz",
                "mastery_grade",
                "mastery_skip_question",
                "mastery_assess",
                "mastery_build",
                "mastery_mode",
                "mastery_profile",
                "mastery_revise",
                "mastery_paths",
                "mastery_switch",
                "mastery_leave",
                "rag",
                "read_source",
                "ask_user",
            ],
            cli_aliases=["mastery"],
        ),
    ),
    "immersive_reading": BuiltinCapabilitySpec(
        BUILTIN_CAPABILITY_CLASSES["immersive_reading"],
        _manifest(
            "immersive_reading",
            "Read a document alongside the assistant, which cites the exact page or section behind every claim.",
            stages=["responding"],
            tools_used=[
                "reading_list_tabs",
                "reading_switch_tab",
                "material_outline",
                "search_material",
                "read_material",
                "reader_goto",
                "reader_annotate",
                "web_search",
                "exec",
                "reason",
            ],
            cli_aliases=["reading", "read"],
        ),
    ),
    "course_study": BuiltinCapabilitySpec(
        BUILTIN_CAPABILITY_CLASSES["course_study"],
        _manifest(
            "course_study",
            "Sense a course's learning state, recommend the best next action, and hand the learner to the right teaching surface.",
            stages=["responding"],
            tools_used=[
                "course_overview",
                "course_material",
                "course_edit",
                "course_handoff",
                "rag",
                "web_search",
                "exec",
                "reason",
            ],
            cli_aliases=["course"],
        ),
    ),
    "immersive_watching": BuiltinCapabilitySpec(
        BUILTIN_CAPABILITY_CLASSES["immersive_watching"],
        _manifest(
            "immersive_watching",
            "Learn alongside a YouTube video with timestamp-grounded tutoring.",
            stages=["responding"],
            tools_used=["web_search", "exec", "reason"],
            cli_aliases=["watching", "watch"],
        ),
    ),
}


__all__ = [
    "BUILTIN_CAPABILITY_CLASSES",
    "BUILTIN_CAPABILITY_SPECS",
    "BuiltinCapabilitySpec",
]
