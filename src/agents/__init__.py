"""
Agents Module - Agent system for DeepTutor.

This module provides a unified BaseAgent class and module-specific agents:
- solve: Question solving agents (MainSolver, SolveAgent, etc.)
- question: Question generation agents (ReAct architecture)
"""

from .base_agent import BaseAgent

__all__ = ["BaseAgent"]
