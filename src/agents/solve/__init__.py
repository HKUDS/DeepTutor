#!/usr/bin/env python
"""
Solve Agent System - Dual-Loop Architecture
Analysis Loop + Solve Loop
"""

from pathlib import Path
import sys

# Add project root to path for logs import
_project_root = Path(__file__).parent.parent.parent.parent
if str(_project_root) not in sys.path:
    sys.path.insert(0, str(_project_root))

# Infrastructure
from src.agents.base_agent import BaseAgent
from src.logging import Logger, get_logger

from .utils import (
    ConfigValidator,
    PerformanceMonitor,
)

# Backwards compatibility
SolveAgentLogger = Logger

# Memory system
# Analysis loop
from .analysis_loop import (
    InvestigateAgent,
    NoteAgent,
)

# Main controller
from .main_solver import MainSolver

# Session management
from .session_manager import SolverSessionManager, get_solver_session_manager
from .memory import (
    InvestigateMemory,
    KnowledgeItem,
    Reflections,
    SolveChainStep,
    SolveMemory,
    ToolCallRecord,
)

# Solve loop
from .solve_loop import (
    ManagerAgent,
    PrecisionAnswerAgent,
    ResponseAgent,
    SolveAgent,
    ToolAgent,
)

__all__ = [
    # Infrastructure
    "BaseAgent",
    "Logger",
    "get_logger",
    "SolveAgentLogger",  # Backwards compatibility
    "PerformanceMonitor",
    "ConfigValidator",
    # Memory system
    "InvestigateMemory",
    "KnowledgeItem",
    "Reflections",
    "SolveMemory",
    "SolveChainStep",
    "ToolCallRecord",
    # Analysis Loop
    "InvestigateAgent",
    "NoteAgent",
    # Solve Loop
    "ManagerAgent",
    "SolveAgent",
    "ResponseAgent",
    "PrecisionAnswerAgent",
    "ToolAgent",
    # Main Controller
    "MainSolver",
    # Session Management
    "SolverSessionManager",
    "get_solver_session_manager",
]
