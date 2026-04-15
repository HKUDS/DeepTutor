"""
Agents Module - Unified agent system for OpenTutor.

This module provides a unified BaseAgent class and module-specific agents:
- solve: Question solving agents (MainSolver, SolveAgent, etc.)
- research: Deep research agents (DecomposeAgent, ResearchAgent, etc.)
- guide: Guided learning agents (ChatAgent, DesignAgent, etc.)
- co_writer: Co-writing agents (EditAgent, NarratorAgent)
- question: Question generation agents (ReAct architecture, separate base)
- chat: Lightweight conversational agent with session management
- structure_note: Structure Note generation workflow and artifact management

Usage:
    from deeptutor.agents.base_agent import BaseAgent

    class MyAgent(BaseAgent):
        async def process(self, *args, **kwargs):
            ...
"""

from .base_agent import BaseAgent
from .chat import ChatAgent, SessionManager

__all__ = ["BaseAgent", "ChatAgent", "SessionManager"]
