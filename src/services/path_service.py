#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
PathService - Centralized path management for user data directories.

This module provides a singleton service for managing all paths related to
the data/user directory structure:

data/user/
├── agent/                    # All Agent interaction history
│   ├── solve/
│   │   ├── sessions.json
│   │   └── {task_id}/
│   ├── chat/
│   │   └── sessions.json
│   ├── question/
│   │   └── {batch_id}/
│   ├── research/
│   │   └── reports/
│   ├── co-writer/
│   │   ├── history.json
│   │   └── tool_calls/
│   ├── guide/
│   │   └── {session_id}.json
│   ├── run_code_workspace/
│   └── logs/
│
├── workspace/
│   └── notebook/
│
└── settings/
    ├── interface.json
    ├── llm_configs.json
    └── ...
"""

from pathlib import Path
from typing import Literal

# Module types that have agent directories
AgentModule = Literal["solve", "chat", "question", "research", "co-writer", "guide", "run_code_workspace", "logs"]


class PathService:
    """
    Singleton service for centralized path management.
    
    Provides consistent path resolution for all user data directories,
    eliminating scattered path calculations across the codebase.
    """
    
    _instance: "PathService | None" = None
    
    def __new__(cls) -> "PathService":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance._initialized = False
        return cls._instance
    
    def __init__(self):
        if self._initialized:
            return
        
        # Calculate project root from this file's location
        # This file: src/services/path_service.py
        # Project root: 3 levels up (src/services/ -> src/ -> project_root/)
        self._project_root = Path(__file__).resolve().parent.parent.parent
        self._user_data_dir = self._project_root / "data" / "user"
        self._initialized = True
    
    @classmethod
    def get_instance(cls) -> "PathService":
        """Get the singleton instance of PathService."""
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance
    
    @classmethod
    def reset_instance(cls) -> None:
        """Reset the singleton instance (mainly for testing)."""
        cls._instance = None
    
    # =========================================================================
    # Core Properties
    # =========================================================================
    
    @property
    def project_root(self) -> Path:
        """Get the project root directory."""
        return self._project_root
    
    @property
    def user_data_dir(self) -> Path:
        """Get the user data directory (data/user/)."""
        return self._user_data_dir
    
    # =========================================================================
    # Agent Directory Methods
    # =========================================================================
    
    def get_agent_base_dir(self) -> Path:
        """Get the base agent directory (data/user/agent/)."""
        return self._user_data_dir / "agent"
    
    def get_agent_dir(self, module: AgentModule) -> Path:
        """
        Get the directory for a specific agent module.
        
        Args:
            module: The agent module name (solve, chat, question, etc.)
        
        Returns:
            Path to data/user/agent/{module}/
        """
        return self.get_agent_base_dir() / module
    
    def get_session_file(self, module: AgentModule) -> Path:
        """
        Get the sessions file path for a specific agent module.
        
        Args:
            module: The agent module name
        
        Returns:
            Path to data/user/agent/{module}/sessions.json
        """
        return self.get_agent_dir(module) / "sessions.json"
    
    def get_task_dir(self, module: AgentModule, task_id: str) -> Path:
        """
        Get the task directory for a specific task within an agent module.
        
        Args:
            module: The agent module name
            task_id: The unique task identifier
        
        Returns:
            Path to data/user/agent/{module}/{task_id}/
        """
        return self.get_agent_dir(module) / task_id
    
    # =========================================================================
    # Workspace Directory Methods
    # =========================================================================
    
    def get_workspace_dir(self) -> Path:
        """Get the workspace directory (data/user/workspace/)."""
        return self._user_data_dir / "workspace"
    
    def get_notebook_dir(self) -> Path:
        """Get the notebook directory (data/user/workspace/notebook/)."""
        return self.get_workspace_dir() / "notebook"
    
    def get_notebook_file(self, notebook_id: str) -> Path:
        """
        Get the file path for a specific notebook.
        
        Args:
            notebook_id: The notebook identifier
        
        Returns:
            Path to data/user/workspace/notebook/{notebook_id}.json
        """
        return self.get_notebook_dir() / f"{notebook_id}.json"
    
    def get_notebook_index_file(self) -> Path:
        """Get the notebook index file path."""
        return self.get_notebook_dir() / "notebooks_index.json"
    
    def get_memory_dir(self) -> Path:
        """Get the memory directory for personalization (data/user/workspace/memory/)."""
        return self.get_workspace_dir() / "memory"
    
    # =========================================================================
    # Settings Directory Methods
    # =========================================================================
    
    def get_settings_dir(self) -> Path:
        """Get the settings directory (data/user/settings/)."""
        return self._user_data_dir / "settings"
    
    def get_settings_file(self, name: str) -> Path:
        """
        Get the settings file path for a specific settings type.
        
        Args:
            name: The settings file name (without .json extension)
        
        Returns:
            Path to data/user/settings/{name}.json
        """
        if not name.endswith(".json"):
            name = f"{name}.json"
        return self.get_settings_dir() / name
    
    # =========================================================================
    # Convenience Methods for Specific Modules
    # =========================================================================
    
    # Solve module
    def get_solve_dir(self) -> Path:
        """Get the solve module directory."""
        return self.get_agent_dir("solve")
    
    def get_solve_session_file(self) -> Path:
        """Get the solve sessions file path."""
        return self.get_session_file("solve")
    
    def get_solve_task_dir(self, task_id: str) -> Path:
        """Get a specific solve task directory."""
        return self.get_task_dir("solve", task_id)
    
    # Chat module
    def get_chat_dir(self) -> Path:
        """Get the chat module directory."""
        return self.get_agent_dir("chat")
    
    def get_chat_session_file(self) -> Path:
        """Get the chat sessions file path."""
        return self.get_session_file("chat")
    
    # Question module
    def get_question_dir(self) -> Path:
        """Get the question module directory."""
        return self.get_agent_dir("question")
    
    def get_question_batch_dir(self, batch_id: str) -> Path:
        """Get a specific question batch directory."""
        return self.get_task_dir("question", batch_id)
    
    # Research module
    def get_research_dir(self) -> Path:
        """Get the research module directory."""
        return self.get_agent_dir("research")
    
    def get_research_reports_dir(self) -> Path:
        """Get the research reports directory."""
        return self.get_research_dir() / "reports"
    
    # Co-writer module
    def get_co_writer_dir(self) -> Path:
        """Get the co-writer module directory."""
        return self.get_agent_dir("co-writer")
    
    def get_co_writer_history_file(self) -> Path:
        """Get the co-writer history file path."""
        return self.get_co_writer_dir() / "history.json"
    
    def get_co_writer_tool_calls_dir(self) -> Path:
        """Get the co-writer tool calls directory."""
        return self.get_co_writer_dir() / "tool_calls"
    
    def get_co_writer_audio_dir(self) -> Path:
        """Get the co-writer audio directory."""
        return self.get_co_writer_dir() / "audio"
    
    # Guide module
    def get_guide_dir(self) -> Path:
        """Get the guide module directory."""
        return self.get_agent_dir("guide")
    
    def get_guide_session_file(self, session_id: str) -> Path:
        """Get a specific guide session file."""
        return self.get_guide_dir() / f"session_{session_id}.json"
    
    # Code execution workspace
    def get_run_code_workspace_dir(self) -> Path:
        """Get the code execution workspace directory."""
        return self.get_agent_dir("run_code_workspace")
    
    # Logs
    def get_logs_dir(self) -> Path:
        """Get the user logs directory."""
        return self.get_agent_dir("logs")
    
    # =========================================================================
    # Directory Creation Utilities
    # =========================================================================
    
    def ensure_agent_dir(self, module: AgentModule) -> Path:
        """
        Ensure an agent module directory exists.
        
        Args:
            module: The agent module name
        
        Returns:
            The ensured directory path
        """
        path = self.get_agent_dir(module)
        path.mkdir(parents=True, exist_ok=True)
        return path
    
    def ensure_task_dir(self, module: AgentModule, task_id: str) -> Path:
        """
        Ensure a task directory exists within an agent module.
        
        Args:
            module: The agent module name
            task_id: The task identifier
        
        Returns:
            The ensured directory path
        """
        path = self.get_task_dir(module, task_id)
        path.mkdir(parents=True, exist_ok=True)
        return path
    
    def ensure_workspace_dir(self) -> Path:
        """Ensure the workspace directory exists."""
        path = self.get_workspace_dir()
        path.mkdir(parents=True, exist_ok=True)
        return path
    
    def ensure_notebook_dir(self) -> Path:
        """Ensure the notebook directory exists."""
        path = self.get_notebook_dir()
        path.mkdir(parents=True, exist_ok=True)
        return path
    
    def ensure_memory_dir(self) -> Path:
        """Ensure the memory directory exists for personalization."""
        path = self.get_memory_dir()
        path.mkdir(parents=True, exist_ok=True)
        return path
    
    def ensure_settings_dir(self) -> Path:
        """Ensure the settings directory exists."""
        path = self.get_settings_dir()
        path.mkdir(parents=True, exist_ok=True)
        return path
    
    def ensure_all_directories(self) -> None:
        """
        Ensure all required directories exist.
        Called during system initialization.
        """
        # Agent directories
        agent_modules: list[AgentModule] = [
            "solve", "chat", "question", "research", 
            "co-writer", "guide", "run_code_workspace", "logs"
        ]
        for module in agent_modules:
            self.ensure_agent_dir(module)
        
        # Co-writer subdirectories
        self.get_co_writer_tool_calls_dir().mkdir(parents=True, exist_ok=True)
        self.get_co_writer_audio_dir().mkdir(parents=True, exist_ok=True)
        
        # Research subdirectories
        self.get_research_reports_dir().mkdir(parents=True, exist_ok=True)
        
        # Workspace directories
        self.ensure_notebook_dir()
        self.ensure_memory_dir()
        
        # Settings directory
        self.ensure_settings_dir()


# Convenience function for quick access
def get_path_service() -> PathService:
    """Get the PathService singleton instance."""
    return PathService.get_instance()


__all__ = ["PathService", "get_path_service", "AgentModule"]
