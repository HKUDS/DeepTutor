# -*- coding: utf-8 -*-
"""
File Type Router
================

Centralized file type classification and routing for RAG pipelines.
Determines the appropriate processing method for each document type.
"""

from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import List

from src.logging import get_logger

logger = get_logger("FileTypeRouter")


class DocumentType(Enum):
    """Document type classification"""

    PDF = "pdf"  # Requires MinerU complex parsing
    TEXT = "text"  # Plain text, direct read
    MARKDOWN = "markdown"  # Structured text
    DOCX = "docx"  # Word documents
    IMAGE = "image"  # Images (may need OCR)
    UNKNOWN = "unknown"  # Unsupported


@dataclass
class FileClassification:
    """
    Result of file classification.

    Attributes:
        needs_mineru: Files requiring MinerU parsing (PDF, etc.)
        text_files: Files that can be read directly as text
        unsupported: Files with unsupported formats
    """

    needs_mineru: List[str]
    text_files: List[str]
    unsupported: List[str]


class FileTypeRouter:
    """
    File type router for RAG pipelines.

    Classifies files before processing to route them to appropriate handlers:
    - PDF files -> MinerU parser (complex document parsing)
    - Text files -> Direct read (fast, simple)
    - Unsupported -> Skip with warning

    Usage:
        router = FileTypeRouter()
        classification = router.classify_files(file_paths)

        # Process PDF files with MinerU
        for pdf in classification.needs_mineru:
            await rag.process_document_complete(pdf, ...)

        # Process text files directly
        for txt in classification.text_files:
            content = await FileTypeRouter.read_text_file(txt)
            await rag.lightrag.ainsert(content)
    """

    # Extensions requiring MinerU parsing (complex document formats)
    MINERU_EXTENSIONS = {".pdf"}

    # Extensions for direct text reading
    TEXT_EXTENSIONS = {
        # Plain text
        ".txt",
        ".text",
        ".log",
        # Markup languages
        ".md",
        ".markdown",
        ".rst",
        ".asciidoc",
        # Data formats
        ".json",
        ".yaml",
        ".yml",
        ".toml",
        ".csv",
        ".tsv",
        # LaTeX
        ".tex",
        ".latex",
        ".bib",
        # Code files
        ".py",
        ".js",
        ".ts",
        ".jsx",
        ".tsx",
        ".java",
        ".c",
        ".cpp",
        ".h",
        ".hpp",
        ".go",
        ".rs",
        ".rb",
        ".php",
        ".swift",
        ".kt",
        ".scala",
        ".r",
        ".sql",
        ".sh",
        ".bash",
        ".zsh",
        ".ps1",
        # Web
        ".html",
        ".htm",
        ".xml",
        ".css",
        ".scss",
        ".sass",
        ".less",
        # Config
        ".ini",
        ".cfg",
        ".conf",
        ".env",
        ".properties",
    }

    # Word document extensions (special handling)
    DOCX_EXTENSIONS = {".docx", ".doc"}

    # Image extensions (may need OCR)
    IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".tiff", ".tif"}

    @classmethod
    def get_document_type(cls, file_path: str) -> DocumentType:
        """
        Classify a single file by its type.

        Args:
            file_path: Path to the file

        Returns:
            DocumentType enum value
        """
        ext = Path(file_path).suffix.lower()

        if ext in cls.MINERU_EXTENSIONS:
            return DocumentType.PDF
        elif ext in cls.TEXT_EXTENSIONS:
            return DocumentType.TEXT
        elif ext in cls.DOCX_EXTENSIONS:
            return DocumentType.DOCX
        elif ext in cls.IMAGE_EXTENSIONS:
            return DocumentType.IMAGE
        else:
            # Try to detect if it's a text file by content
            if cls._is_text_file(file_path):
                return DocumentType.TEXT
            return DocumentType.UNKNOWN

    @classmethod
    def _is_text_file(cls, file_path: str, sample_size: int = 8192) -> bool:
        """
        Detect if a file is text-based by examining its content.

        Args:
            file_path: Path to the file
            sample_size: Number of bytes to sample

        Returns:
            True if file appears to be text
        """
        try:
            with open(file_path, "rb") as f:
                chunk = f.read(sample_size)

            # Check for null bytes (binary file indicator)
            if b"\x00" in chunk:
                return False

            # Try to decode as UTF-8
            chunk.decode("utf-8")
            return True
        except (UnicodeDecodeError, IOError, OSError):
            return False

    @classmethod
    def classify_files(cls, file_paths: List[str]) -> FileClassification:
        """
        Classify a list of files by processing method.

        Args:
            file_paths: List of file paths to classify

        Returns:
            FileClassification with files grouped by processing method
        """
        needs_mineru = []
        text_files = []
        unsupported = []

        for path in file_paths:
            doc_type = cls.get_document_type(path)

            if doc_type == DocumentType.PDF:
                needs_mineru.append(path)
            elif doc_type in (DocumentType.TEXT, DocumentType.MARKDOWN):
                text_files.append(path)
            elif doc_type == DocumentType.DOCX:
                # DOCX files need special handling
                # For now, route to MinerU which can handle them
                needs_mineru.append(path)
            elif doc_type == DocumentType.IMAGE:
                # Images might need OCR - route to MinerU if multimodal is enabled
                needs_mineru.append(path)
            else:
                unsupported.append(path)

        logger.debug(
            f"Classified {len(file_paths)} files: "
            f"{len(needs_mineru)} MinerU, {len(text_files)} text, {len(unsupported)} unsupported"
        )

        return FileClassification(
            needs_mineru=needs_mineru,
            text_files=text_files,
            unsupported=unsupported,
        )

    @classmethod
    async def read_text_file(cls, file_path: str) -> str:
        """
        Read a text file with automatic encoding detection.

        Args:
            file_path: Path to the text file

        Returns:
            File content as string
        """
        encodings = ["utf-8", "utf-8-sig", "gbk", "gb2312", "gb18030", "latin-1", "cp1252"]

        for encoding in encodings:
            try:
                with open(file_path, "r", encoding=encoding) as f:
                    return f.read()
            except UnicodeDecodeError:
                continue

        # Last resort: read with error replacement
        with open(file_path, "rb") as f:
            return f.read().decode("utf-8", errors="replace")

    @classmethod
    def needs_mineru(cls, file_path: str) -> bool:
        """
        Quick check if a single file needs MinerU parsing.

        Args:
            file_path: Path to the file

        Returns:
            True if file requires MinerU
        """
        doc_type = cls.get_document_type(file_path)
        return doc_type in (DocumentType.PDF, DocumentType.DOCX, DocumentType.IMAGE)

    @classmethod
    def is_text_readable(cls, file_path: str) -> bool:
        """
        Check if a file can be read directly as text.

        Args:
            file_path: Path to the file

        Returns:
            True if file can be read as text
        """
        doc_type = cls.get_document_type(file_path)
        return doc_type in (DocumentType.TEXT, DocumentType.MARKDOWN)

    @classmethod
    def get_extensions_for_provider(cls, provider: str) -> set[str]:
        """
        Get supported file extensions for a specific RAG provider.

        Args:
            provider: RAG provider name (llamaindex, lightrag, raganything, raganything_docling)

        Returns:
            Set of supported file extensions (with leading dot, e.g., {".pdf", ".txt"})
        """
        # Base text extensions supported by all providers
        text_extensions = cls.TEXT_EXTENSIONS.copy()

        if provider == "llamaindex":
            # LlamaIndex: PDF + all text files (reads any text file directly)
            return cls.MINERU_EXTENSIONS | text_extensions

        elif provider == "lightrag":
            # LightRAG: PDF + all text files (uses FileTypeRouter)
            return cls.MINERU_EXTENSIONS | text_extensions

        elif provider in ("raganything", "raganything_docling"):
            # RAGAnything: PDF + Word + Images + all text files (full multimodal via MinerU)
            return (
                cls.MINERU_EXTENSIONS | cls.DOCX_EXTENSIONS | cls.IMAGE_EXTENSIONS | text_extensions
            )

        else:
            # Default: same as llamaindex (most conservative)
            logger.warning(f"Unknown provider '{provider}', using default extensions")
            return cls.MINERU_EXTENSIONS | text_extensions

    @classmethod
    def get_glob_patterns_for_provider(cls, provider: str) -> list[str]:
        """
        Get glob patterns for file searching based on RAG provider.

        Args:
            provider: RAG provider name (llamaindex, lightrag, raganything, raganything_docling)

        Returns:
            List of glob patterns (e.g., ["*.pdf", "*.txt", "*.md"])
        """
        extensions = cls.get_extensions_for_provider(provider)
        return [f"*{ext}" for ext in sorted(extensions)]
