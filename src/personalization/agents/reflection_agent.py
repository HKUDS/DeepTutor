# -*- coding: utf-8 -*-
"""
Reflection Agent
================

Evaluates system response quality and compares with past interactions.
Produces ``reflection.md``.
"""
from __future__ import annotations

from typing import Any

from src.agents.base_agent import BaseAgent


class ReflectionAgent(BaseAgent):
    """Memory agent that writes ``reflection.md``."""

    def __init__(
        self,
        language: str = "en",
        temperature: float = 0.5,
        **kwargs: Any,
    ) -> None:
        super().__init__(
            module_name="personalization",
            agent_name="reflection_agent",
            language=language,
            **kwargs,
        )
        self._temperature = temperature

    def get_temperature(self) -> float:
        return self._temperature

    async def process(self, *args: Any, **kwargs: Any) -> Any:
        raise NotImplementedError("Use ReActRunner.run() instead")
