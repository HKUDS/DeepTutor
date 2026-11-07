# -*- coding: utf-8 -*-
"""
Text Parser
===========

Parser for plain text documents (.txt files).
"""

from pathlib import Path
from typing import Union

from ...types import Document
from ..base import BaseComponent


class TextParser(BaseComponent):
    """
    Plain text parser.

    Parses text files (.txt) into Document objects.
    Also handles common text-based formats.
    """

    name = "text_parser"

    # Supported extensions
    SUPPORTED_EXTENSIONS = {".txt", ".text", ".log", ".csv", ".tsv"}

    async def process(self, file_path: Union[str, Path], **kwargs) -> Document:
        """
        Parse a text file into a Document.

        Args:
            file_path: Path to the text file
            **kwargs: Additional arguments

        Returns:
            Parsed Document
        """
        file_path = Path(file_path)

        if not file_path.exists():
            raise FileNotFoundError(f"Text file not found: {file_path}")

        self.logger.info(f"Parsing text file: {file_path.name}")

        # Try different encodings
        content = None
        encodings = ["utf-8", "utf-8-sig", "gbk", "gb2312", "latin-1"]

        for encoding in encodings:
            try:
                with open(file_path, "r", encoding=encoding) as f:
                    content = f.read()
                break
            except UnicodeDecodeError:
                continue

        if content is None:
            # Last resort: read as binary and decode with error handling
            with open(file_path, "rb") as f:
                content = f.read().decode("utf-8", errors="replace")

        return Document(
            content=content,
            file_path=str(file_path),
            metadata={
                "filename": file_path.name,
                "parser": self.name,
                "extension": file_path.suffix.lower(),
                "size_bytes": file_path.stat().st_size,
            },
        )

    @classmethod
    def can_parse(cls, file_path: Union[str, Path]) -> bool:
        """
        Check if this parser can handle the given file.

        Args:
            file_path: Path to check

        Returns:
            True if file can be parsed
        """
        suffix = Path(file_path).suffix.lower()
        return suffix in cls.SUPPORTED_EXTENSIONS
