"""Import-cheap catalog for DeepTutor's built-in tools.

The runtime registry needs to know which names exist at process boot, but it
does not need the implementation classes until a turn actually mounts one.
Keeping the class paths here prevents registry construction from importing the
entire capability graph (and, historically, depending on a lucky import order
to avoid a cycle).
"""

from __future__ import annotations

from dataclasses import dataclass
import importlib
from typing import Iterator, Sequence

from deeptutor.core.tool_protocol import BaseTool


@dataclass(frozen=True, slots=True)
class BuiltinToolSpec:
    name: str
    class_path: str

    def load_class(self) -> type[BaseTool]:
        module_path, class_name = self.class_path.rsplit(":", 1)
        module = importlib.import_module(module_path)
        tool_type = getattr(module, class_name)
        if not isinstance(tool_type, type) or not issubclass(tool_type, BaseTool):
            raise TypeError(f"Built-in tool {self.name!r} did not resolve to a BaseTool class")
        return tool_type

    def create(self) -> BaseTool:
        tool = self.load_class()()
        if tool.name != self.name:
            raise RuntimeError(
                f"Built-in tool catalog drift: {self.class_path} declares {tool.name!r}, "
                f"expected {self.name!r}"
            )
        return tool


def _specs(module: str, members: tuple[tuple[str, str], ...]) -> tuple[BuiltinToolSpec, ...]:
    return tuple(BuiltinToolSpec(name, f"{module}:{class_name}") for name, class_name in members)


BUILTIN_TOOL_SPECS: tuple[BuiltinToolSpec, ...] = (
    *_specs(
        "deeptutor.tools.builtin",
        (
            ("brainstorm", "BrainstormTool"),
            ("rag", "RAGTool"),
            ("kb_files", "KbFilesTool"),
            ("web_search", "WebSearchTool"),
            ("reason", "ReasonTool"),
            ("paper_search", "PaperSearchToolWrapper"),
            ("read_source", "ReadSourceTool"),
            ("read_memory", "ReadMemoryTool"),
            ("write_memory", "WriteMemoryTool"),
            ("read_skill", "ReadSkillTool"),
            ("load_tools", "LoadToolsTool"),
            ("web_fetch", "WebFetchTool"),
            ("list_notebook", "ListNotebookTool"),
            ("write_note", "WriteNoteTool"),
            ("question_bank", "QuestionBankTool"),
            ("github", "GithubTool"),
            ("ask_user", "AskUserTool"),
            ("cron", "CronTool"),
            ("geogebra_analysis", "GeoGebraAnalysisTool"),
        ),
    ),
    BuiltinToolSpec("exec", "deeptutor.tools.exec_tool:ExecTool"),
    *_specs(
        "deeptutor.tools.workspace",
        (
            ("workspace_list", "WorkspaceListTool"),
            ("workspace_read", "WorkspaceReadTool"),
            ("workspace_search", "WorkspaceSearchTool"),
            ("workspace_present", "WorkspacePresentTool"),
            ("workspace_export", "WorkspaceExportTool"),
        ),
    ),
    BuiltinToolSpec("submit_visualization", "deeptutor.visualizers.tool:SubmitVisualizationTool"),
    BuiltinToolSpec("imagegen", "deeptutor.tools.media_gen_tool:ImagegenTool"),
    BuiltinToolSpec("videogen", "deeptutor.tools.media_gen_tool:VideogenTool"),
    *_specs(
        "deeptutor.tools.mastery_nav",
        (
            ("mastery_topics", "MasteryTopicsTool"),
            ("mastery_sessions", "MasterySessionsTool"),
            ("mastery_open_session", "MasteryOpenSessionTool"),
            ("mastery_new_session", "MasteryNewSessionTool"),
        ),
    ),
    *_specs(
        "deeptutor.capabilities.mastery.tools",
        (
            ("mastery_status", "MasteryStatusTool"),
            ("mastery_quiz", "MasteryQuizTool"),
            ("mastery_grade", "MasteryGradeTool"),
            ("mastery_skip_question", "MasterySkipQuestionTool"),
            ("mastery_assess", "MasteryAssessTool"),
            ("mastery_build", "MasteryBuildTool"),
            ("mastery_mode", "MasteryModeTool"),
            ("mastery_profile", "MasteryProfileTool"),
            ("mastery_revise", "MasteryReviseTool"),
            ("mastery_paths", "MasteryPathsTool"),
            ("mastery_switch", "MasterySwitchTool"),
            ("mastery_leave", "MasteryLeaveTool"),
        ),
    ),
    *_specs(
        "deeptutor.capabilities.solve.tools",
        (
            ("solve_plan", "SolvePlanTool"),
            ("solve_finish_step", "SolveFinishStepTool"),
            ("solve_replan", "SolveReplanTool"),
        ),
    ),
    *_specs(
        "deeptutor.capabilities.obsidian.tools",
        (
            ("obsidian_search", "ObsidianSearchTool"),
            ("obsidian_read", "ObsidianReadTool"),
            ("obsidian_list", "ObsidianListTool"),
            ("obsidian_backlinks", "ObsidianBacklinksTool"),
            ("obsidian_links", "ObsidianLinksTool"),
            ("obsidian_tags", "ObsidianTagsTool"),
            ("obsidian_create_note", "ObsidianCreateNoteTool"),
            ("obsidian_append", "ObsidianAppendTool"),
            ("obsidian_set_property", "ObsidianSetPropertyTool"),
        ),
    ),
    *_specs(
        "deeptutor.capabilities.marginnote4.tools",
        (
            ("marginnote_search", "MarginNoteSearchTool"),
            ("marginnote_read", "MarginNoteReadTool"),
            ("marginnote_list", "MarginNoteListTool"),
            ("marginnote_documents", "MarginNoteDocumentsTool"),
            ("marginnote_links", "MarginNoteLinksTool"),
            ("marginnote_tags", "MarginNoteTagsTool"),
            ("marginnote_cards", "MarginNoteCardsTool"),
        ),
    ),
    BuiltinToolSpec(
        "consult_subagent", "deeptutor.capabilities.subagent.tools:ConsultSubagentTool"
    ),
    *_specs(
        "deeptutor.capabilities.ima.tools",
        (
            ("ima_list", "ImaListTool"),
            ("ima_read", "ImaReadTool"),
            ("ima_note_search", "ImaNoteSearchTool"),
            ("ima_add_url", "ImaAddUrlTool"),
            ("ima_write_note", "ImaWriteNoteTool"),
        ),
    ),
    *_specs(
        "deeptutor.capabilities.reading.tools",
        (
            ("reading_list_tabs", "ReadingListTabsTool"),
            ("reading_switch_tab", "ReadingSwitchTabTool"),
            ("material_outline", "MaterialOutlineTool"),
            ("search_material", "SearchMaterialTool"),
            ("read_material", "ReadMaterialTool"),
            ("reader_goto", "ReaderGotoTool"),
            ("reader_annotate", "ReaderAnnotateTool"),
        ),
    ),
    *_specs(
        "deeptutor.capabilities.setup.tools",
        (
            ("inspect_setup", "InspectSetupTool"),
            ("apply_setting", "ApplySettingTool"),
            ("request_credential", "RequestCredentialTool"),
            ("run_setup_job", "RunSetupJobTool"),
        ),
    ),
    BuiltinToolSpec(
        "propose_partner", "deeptutor.capabilities.partner_authoring.tools:ProposePartnerTool"
    ),
    BuiltinToolSpec("invoke_other", "deeptutor.capabilities.partner_group.tools:InvokeOtherTool"),
    *_specs(
        "deeptutor.capabilities.course_study.tools",
        (
            ("course_overview", "CourseOverviewTool"),
            ("course_material", "CourseMaterialTool"),
            ("course_edit", "CourseEditTool"),
            ("course_handoff", "CourseHandoffTool"),
        ),
    ),
    *_specs(
        "deeptutor.tools.partner_memory",
        (
            ("partner_read", "PartnerReadTool"),
            ("partner_memorize", "PartnerMemorizeTool"),
            ("partner_search", "PartnerSearchTool"),
        ),
    ),
)

BUILTIN_TOOL_NAMES: tuple[str, ...] = tuple(spec.name for spec in BUILTIN_TOOL_SPECS)
PARTNER_BUILTIN_TOOL_NAMES: tuple[str, ...] = (
    "partner_read",
    "partner_memorize",
    "partner_search",
)
BUILTIN_TOOL_SPEC_BY_NAME: dict[str, BuiltinToolSpec] = {
    spec.name: spec for spec in BUILTIN_TOOL_SPECS
}

TOOL_ALIASES: dict[str, tuple[str, dict[str, object]]] = {
    "rag_hybrid": ("rag", {"mode": "hybrid"}),
    "rag_naive": ("rag", {"mode": "naive"}),
    "rag_search": ("rag", {}),
}

if len(BUILTIN_TOOL_SPEC_BY_NAME) != len(BUILTIN_TOOL_SPECS):
    raise RuntimeError("Duplicate name in the built-in tool catalog")


class LazyBuiltinToolTypes(Sequence[type[BaseTool]]):
    """Compatibility sequence that imports a class only when it is iterated."""

    def __init__(self, specs: tuple[BuiltinToolSpec, ...]) -> None:
        self._specs = specs

    def __len__(self) -> int:
        return len(self._specs)

    def __getitem__(self, index):  # noqa: ANN001, ANN204
        if isinstance(index, slice):
            return tuple(spec.load_class() for spec in self._specs[index])
        return self._specs[index].load_class()

    def __iter__(self) -> Iterator[type[BaseTool]]:
        return (spec.load_class() for spec in self._specs)


__all__ = [
    "BUILTIN_TOOL_NAMES",
    "BUILTIN_TOOL_SPEC_BY_NAME",
    "BUILTIN_TOOL_SPECS",
    "BuiltinToolSpec",
    "LazyBuiltinToolTypes",
    "PARTNER_BUILTIN_TOOL_NAMES",
    "TOOL_ALIASES",
]
