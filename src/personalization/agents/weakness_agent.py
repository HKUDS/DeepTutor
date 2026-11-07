# -*- coding: utf-8 -*-
"""
Weakness Agent
==============

Diagnoses potential knowledge gaps from the user's interactions.
Produces ``weakness.md``.
"""
from __future__ import annotations

from typing import Any

from src.agents.base_agent import BaseAgent


class WeaknessAgent(BaseAgent):
    """Memory agent that writes ``weakness.md``."""

    def __init__(
        self,
        language: str = "en",
        temperature: float = 0.5,
        **kwargs: Any,
    ) -> None:
        super().__init__(
            module_name="personalization",
            agent_name="weakness_agent",
            language=language,
            **kwargs,
        )
        self._temperature = temperature

    def get_temperature(self) -> float:
        return self._temperature

    async def process(self, *args: Any, **kwargs: Any) -> Any:
        raise NotImplementedError("Use ReActRunner.run() instead")
