"""Built-in capability class paths."""

BUILTIN_CAPABILITY_CLASSES: dict[str, str] = {
    "chat": "deeptutor.capabilities.chat:ChatCapability",
    "deep_solve": "deeptutor.capabilities.deep_solve:DeepSolveCapability",
    "deep_question": "deeptutor.capabilities.deep_question:DeepQuestionCapability",
    "deep_research": "deeptutor.capabilities.deep_research:DeepResearchCapability",
    "math_animator": "deeptutor.capabilities.math_animator:MathAnimatorCapability",
}
