"""Course Study loop capability and constants.

``CourseStudyCapability`` (the composer mode) is deliberately NOT re-exported.
It imports the agentic chat pipeline, which imports the loop/tool registries;
re-exporting it here would close the same interpreter-start cycle documented by
``deeptutor.capabilities.reading``. The mode is lazy-loaded from its class-path
string in ``runtime.bootstrap.builtin_capabilities``.
"""

from deeptutor.capabilities.course_study.capability import (
    COURSE_ID_KEY,
    COURSE_STUDY_NAME,
    SUMMARY_CHAR_LIMIT,
    CourseStudyLoopCapability,
)
from deeptutor.capabilities.course_study.tools import (
    COURSE_EDIT_ACTIONS,
    COURSE_HANDOFF_LABELS,
    COURSE_HANDOFF_TARGETS,
    COURSE_ID_KWARG,
    COURSE_STUDY_TOOL_NAMES,
    COURSE_STUDY_TOOL_TYPES,
)

__all__ = [
    "COURSE_EDIT_ACTIONS",
    "COURSE_HANDOFF_LABELS",
    "COURSE_HANDOFF_TARGETS",
    "COURSE_ID_KEY",
    "COURSE_ID_KWARG",
    "COURSE_STUDY_NAME",
    "COURSE_STUDY_TOOL_NAMES",
    "COURSE_STUDY_TOOL_TYPES",
    "SUMMARY_CHAR_LIMIT",
    "CourseStudyLoopCapability",
]
