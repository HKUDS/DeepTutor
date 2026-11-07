# -*- coding: utf-8 -*-
"""
Markdown Parser
===============

Parser for Markdown documents.
"""

from pathlib import Path
from typing import Union

from ...types import Document
from ..base import BaseComponent


class MarkdownParser(BaseComponent):
    """
    Markdown parser.

    Parses Markdown files into Document objects.
    """

    name = "markdown_parser"

    async def process(self, file_path: Union[str, Path], **kwargs) -> Document:
        """
        Parse a Markdown file into a Document.

        Args:
            file_path: Path to the Markdown file
            **kwargs: Additional arguments

        Returns:
            Parsed Document
        """
        file_path = Path(file_path)

        if not file_path.exists():
            raise FileNotFoundError(f"Markdown file not found: {file_path}")

        self.logger.info(f"Parsing Markdown: {file_path.name}")

        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()

        return Document(
            content=content,
            file_path=str(file_path),
            metadata={
                "filename": file_path.name,
                "parser": self.name,
            },
        )
