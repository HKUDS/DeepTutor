# -*- coding: utf-8 -*-
"""
Base Component
==============

Base classes and protocols for RAG components.
"""

from typing import Any, Protocol, runtime_checkable


@runtime_checkable
class Component(Protocol):
    """
    Base protocol for all RAG components.

    All components must implement:
    - name: str - Component identifier
    - process(data, **kwargs) -> Any - Process input data
    """

    name: str

    async def process(self, data: Any, **kwargs) -> Any:
        """
        Process input data.

        Args:
            data: Input data to process
            **kwargs: Additional arguments

        Returns:
            Processed output
        """
        ...


class BaseComponent:
    """
    Base class with common functionality for components.

    Provides:
    - Logger initialization
    - Default name from class name
    """

    name: str = "base"

    def __init__(self):
        from src.logging import get_logger

        self.logger = get_logger(self.__class__.__name__)

    async def process(self, data: Any, **kwargs) -> Any:
        """
        Process input data.

        Override this method in subclasses.
        """
        raise NotImplementedError("Subclasses must implement process()")
