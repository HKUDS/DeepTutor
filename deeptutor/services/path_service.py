#!/usr/bin/env python
"""
PathService - centralized runtime storage layout for ``data/user``.

Runtime data is constrained to:

data/user/
├── chat_history.db
├── logs/
├── settings/
└── workspace/
    ├── memory/
    ├── notebook/
    ├── co-writer/
    ├── guide/
    └── chat/
        ├── chat/
        ├── deep_solve/
        ├── deep_question/
        ├── deep_research/
        ├── math_animator/
        └── _detached_code_execution/
"""

from pathlib import Path
from typing import Literal

AgentModule = Literal[
    "solve",
    "chat",
    "question",
    "research",
    "co-writer",
    "guide",
    "run_code_workspace",
    "logs",
    "math_animator",
]

ChatWorkspaceFeature = Literal[
    "chat",
    "deep_solve",
    "deep_question",
    "deep_research",
    "math_animator",
    "_detached_code_execution",
]

WorkspaceFeature = Literal[
    "memory",
    "notebook",
    "co-writer",
    "guide",
    "chat",
]


class PathService:
    """Singleton runtime path manager rooted at ``data/user``."""

    _instance: "PathService | None" = None

    _AGENT_TO_WORKSPACE: dict[str, tuple[str, str | None]] = {
        "solve": ("chat", "deep_solve"),
        "chat": ("chat", "chat"),
        "question": ("chat", "deep_question"),
        "research": ("chat", "deep_research"),
        "math_animator": ("chat", "math_animator"),
        "co-writer": ("co-writer", None),
        "guide": ("guide", None),
        "run_code_workspace": ("chat", "_detached_code_execution"),
    }
    _PRIVATE_SUFFIXES = {".json", ".sqlite", ".db", ".md", ".yaml", ".yml", ".py", ".log"}

    def __new__(cls) -> "PathService":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return

        self._project_root = Path(__file__).resolve().parent.parent.parent
        self._user_data_dir = (self._project_root / "data" / "user").resolve()
        self._initialized = True

    @classmethod
    def get_instance(cls) -> "PathService":
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    @classmethod
    def reset_instance(cls) -> None:
        cls._instance = None

    @property
    def project_root(self) -> Path:
        return self._project_root

    @property
    def user_data_dir(self) -> Path:
        return self._user_data_dir

    def get_user_root(self) -> Path:
        return self._user_data_dir

    def get_chat_history_db(self) -> Path:
        return self._user_data_dir / "chat_history.db"

    def get_public_outputs_root(self) -> Path:
        return self._user_data_dir

    def is_public_output_path(self, path: str | Path) -> bool:
        candidate = Path(path)
        if not candidate.is_absolute():
            candidate = (self.get_public_outputs_root() / candidate).resolve()
        else:
            candidate = candidate.resolve()

        root = self.get_public_outputs_root().resolve()
        try:
            relative = candidate.relative_to(root)
        except ValueError:
            return False

        if not candidate.is_file():
            return False
        if candidate.suffix.lower() in self._PRIVATE_SUFFIXES:
            return False

        parts = relative.parts
        if parts[:3] == ("workspace", "co-writer", "audio"):
            return True

        if len(parts) >= 5 and parts[:3] == ("workspace", "chat", "deep_solve") and "artifacts" in parts[4:]:
            return True

        if len(parts) >= 5 and parts[:3] == ("workspace", "chat", "math_animator") and "artifacts" in parts[4:]:
            return True

        if len(parts) >= 5 and parts[:2] == ("workspace", "chat") and "code_runs" in parts[3:]:
            return True

        if len(parts) >= 4 and parts[:3] == ("workspace", "chat", "_detached_code_execution"):
            return True

        return False

    def get_workspace_dir(self) -> Path:
        return self._user_data_dir / "workspace"

    def get_settings_dir(self) -> Path:
        return self._user_data_dir / "settings"

    def get_settings_file(self, name: str) -> Path:
        if "." not in name:
            name = f"{name}.json"
        return self.get_settings_dir() / name

    def get_runtime_config_file(self, name: str) -> Path:
        if not name.endswith(".yaml"):
            name = f"{name}.yaml"
        return self.get_settings_dir() / name

    def get_workspace_feature_dir(self, feature: WorkspaceFeature) -> Path:
        return self.get_workspace_dir() / feature

    def get_chat_workspace_root(self) -> Path:
        return self.get_workspace_feature_dir("chat")

    def get_chat_feature_dir(self, feature: ChatWorkspaceFeature) -> Path:
        return self.get_chat_workspace_root() / feature

    def get_task_workspace(self, feature: str, task_id: str) -> Path:
        task_root = self._resolve_feature_root(feature)
        return task_root / task_id

    def get_session_workspace(self, feature: str, session_id: str) -> Path:
        session_root = self._resolve_feature_root(feature)
        return session_root / session_id

    def _resolve_feature_root(self, feature: str) -> Path:
        if feature in {"chat", "deep_solve", "deep_question", "deep_research", "math_animator", "_detached_code_execution"}:
            return self.get_chat_feature_dir(feature)  # type: ignore[arg-type]
        if feature in {"memory", "notebook", "co-writer", "guide"}:
            return self.get_workspace_feature_dir(feature)  # type: ignore[arg-type]
        raise ValueError(f"Unknown workspace feature: {feature}")

    def get_agent_base_dir(self) -> Path:
        return self.get_workspace_dir()

    def get_agent_dir(self, module: AgentModule) -> Path:
        if module == "logs":
            return self.get_logs_dir()
        root_name, child_name = self._AGENT_TO_WORKSPACE[module]
        base = self.get_workspace_feature_dir(root_name)  # type: ignore[arg-type]
        return base / child_name if child_name else base

    def get_session_file(self, module: AgentModule) -> Path:
        return self.get_agent_dir(module) / "sessions.json"

    def get_task_dir(self, module: AgentModule, task_id: str) -> Path:
        return self.get_agent_dir(module) / task_id

    def get_notebook_dir(self) -> Path:
        return self.get_workspace_feature_dir("notebook")

    def get_notebook_file(self, notebook_id: str) -> Path:
        return self.get_notebook_dir() / f"{notebook_id}.json"

    def get_notebook_index_file(self) -> Path:
        return self.get_notebook_dir() / "notebooks_index.json"

    def get_memory_dir(self) -> Path:
        new_dir = self.project_root / "data" / "memory"
        old_dir = self.get_workspace_feature_dir("memory")
        if old_dir.exists() and not new_dir.exists():
            new_dir.mkdir(parents=True, exist_ok=True)
            for f in old_dir.iterdir():
                if f.is_file() and f.suffix == ".md":
                    target = new_dir / f.name
                    if not target.exists():
                        import shutil
                        shutil.copy2(f, target)
        return new_dir

    def get_solve_dir(self) -> Path:
        return self.get_chat_feature_dir("deep_solve")

    def get_solve_session_file(self) -> Path:
        return self.get_session_file("solve")

    def get_solve_task_dir(self, task_id: str) -> Path:
        return self.get_task_dir("solve", task_id)

    def get_chat_dir(self) -> Path:
        return self.get_chat_feature_dir("chat")

    def get_chat_session_file(self) -> Path:
        return self.get_session_file("chat")

    def get_question_dir(self) -> Path:
        return self.get_chat_feature_dir("deep_question")

    def get_question_batch_dir(self, batch_id: str) -> Path:
        return self.get_task_dir("question", batch_id)

    def get_research_dir(self) -> Path:
        return self.get_chat_feature_dir("deep_research")

    def get_research_reports_dir(self) -> Path:
        return self.get_research_dir() / "reports"

    def get_co_writer_dir(self) -> Path:
        return self.get_workspace_feature_dir("co-writer")

    def get_co_writer_history_file(self) -> Path:
        return self.get_co_writer_dir() / "history.json"

    def get_co_writer_tool_calls_dir(self) -> Path:
        return self.get_co_writer_dir() / "tool_calls"

    def get_co_writer_audio_dir(self) -> Path:
        return self.get_co_writer_dir() / "audio"

    def get_guide_dir(self) -> Path:
        return self.get_workspace_feature_dir("guide")

    def get_guide_session_file(self, session_id: str) -> Path:
        return self.get_guide_dir() / f"session_{session_id}.json"

    def get_run_code_workspace_dir(self) -> Path:
        return self.get_chat_feature_dir("_detached_code_execution")

    def get_logs_dir(self) -> Path:
        return self.get_user_root() / "logs"

    def get_goal_root_dir(self) -> Path:
        return self.get_user_root() / "goal"

    def get_goal_session_dir(self, session_id: str) -> Path:
        return self.get_goal_root_dir() / session_id

    def ensure_agent_dir(self, module: AgentModule) -> Path:
        path = self.get_agent_dir(module)
        path.mkdir(parents=True, exist_ok=True)
        return path

    def ensure_task_dir(self, module: AgentModule, task_id: str) -> Path:
        path = self.get_task_dir(module, task_id)
        path.mkdir(parents=True, exist_ok=True)
        return path

    def ensure_workspace_dir(self) -> Path:
        path = self.get_workspace_dir()
        path.mkdir(parents=True, exist_ok=True)
        return path

    def ensure_notebook_dir(self) -> Path:
        path = self.get_notebook_dir()
        path.mkdir(parents=True, exist_ok=True)
        return path

    def ensure_memory_dir(self) -> Path:
        path = self.get_memory_dir()
        path.mkdir(parents=True, exist_ok=True)
        return path

    def ensure_settings_dir(self) -> Path:
        path = self.get_settings_dir()
        path.mkdir(parents=True, exist_ok=True)
        return path

    def ensure_goal_root_dir(self) -> Path:
        path = self.get_goal_root_dir()
        path.mkdir(parents=True, exist_ok=True)
        return path

    def ensure_all_directories(self) -> None:
        self.ensure_settings_dir()
        self.ensure_workspace_dir()
        self.ensure_memory_dir()
        self.ensure_notebook_dir()
        self.ensure_goal_root_dir()
        self.get_logs_dir().mkdir(parents=True, exist_ok=True)
        for feature in ("co-writer", "guide"):
            self.get_workspace_feature_dir(feature).mkdir(parents=True, exist_ok=True)
        for feature in (
            "chat",
            "deep_solve",
            "deep_question",
            "deep_research",
            "math_animator",
            "_detached_code_execution",
        ):
            self.get_chat_feature_dir(feature).mkdir(parents=True, exist_ok=True)
        self.get_co_writer_tool_calls_dir().mkdir(parents=True, exist_ok=True)
        self.get_co_writer_audio_dir().mkdir(parents=True, exist_ok=True)
        self.get_research_reports_dir().mkdir(parents=True, exist_ok=True)


def get_path_service() -> PathService:
    return PathService.get_instance()


__all__ = [
    "AgentModule",
    "ChatWorkspaceFeature",
    "PathService",
    "WorkspaceFeature",
    "get_path_service",
]
