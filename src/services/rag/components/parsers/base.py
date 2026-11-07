# -*- coding: utf-8 -*-
"""
Base Parser
===========

Base class for document parsers.
"""

from pathlib import Path
from typing import Union

from ...types import Document
from ..base import BaseComponent


class BaseParser(BaseComponent):
    """
    Base class for document parsers.

    Parsers convert raw files into Document objects.
    """

    name = "base_parser"

    async def process(self, file_path: Union[str, Path], **kwargs) -> Document:
        """
        Parse a file into a Document.

        Args:
            file_path: Path to the file to parse
            **kwargs: Additional arguments

        Returns:
            Parsed Document
        """
        raise NotImplementedError("Subclasses must implement process()")
