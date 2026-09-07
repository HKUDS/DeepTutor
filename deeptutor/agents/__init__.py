"""
Agents Module - Unified agent system for OpenTutor.

This module provides a unified BaseAgent class and module-specific agents:
- research: Deep research agents (DecomposeAgent, ResearchAgent, etc.)
- question: Question generation agents (ReAct architecture, separate base)
- loop: ``AgentLoop`` + ``AgenticLoopPipeline`` — the single-loop engine and
  the host that assembles a turn for it
- chat: ``AgenticChatPipeline`` — chat's binding of that loop (Deep Solve and
  the other chat-protocol modes run here too, via loop capabilities). A mode
  whose protocol is not chat's subclasses the host instead — see
  ``deeptutor.capabilities.mastery.pipeline``.

Note: ``co_writer`` and ``book`` are independent top-level modules under
``deeptutor/`` (e.g. ``deeptutor.co_writer``, ``deeptutor.book``). They
still inherit from :class:`BaseAgent` defined here but are not part of
the ``deeptutor.agents`` package.

Usage:
    from deeptutor.agents.base_agent import BaseAgent

    class MyAgent(BaseAgent):
        async def process(self, *args, **kwargs):
            ...
"""

from importlib import import_module

__all__ = ["BaseAgent"]


def __getattr__(name: str):
    if name == "BaseAgent":
        value = import_module(f"{__name__}.base_agent").BaseAgent
    else:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    globals()[name] = value
    return value
