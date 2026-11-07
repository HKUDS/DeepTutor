# -*- coding: utf-8 -*-
"""
Personalization Module
======================

Provides personalized learning experience through memory management and
event-driven updates.

Components:
- Memory Agents: Three specialized ReAct agents (Reflection, Summary, Weakness)
- PersonalizationService: Service layer for memory management
- TraceToolkit: Five tools for agents to explore trace forest
- ReActRunner: ReAct loop with parallel tool call support
"""

from .agents import ReflectionAgent, SummaryAgent, WeaknessAgent
from .memory_reader import MemoryReader, get_memory_reader_instance
from .react_runner import ReActRunner
from .service import PersonalizationService, get_personalization_service
from .trace_forest import TraceForest
from .trace_tools import TraceToolkit
from .trace_tree import TraceNode, TraceTree

__all__ = [
    # Agents
    "ReflectionAgent",
    "SummaryAgent",
    "WeaknessAgent",
    # Tools & Runner
    "TraceToolkit",
    "ReActRunner",
    # Reader
    "MemoryReader",
    "get_memory_reader_instance",
    # Service
    "PersonalizationService",
    "get_personalization_service",
    # Trace memory
    "TraceNode",
    "TraceTree",
    "TraceForest",
]
