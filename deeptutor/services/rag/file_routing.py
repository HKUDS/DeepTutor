"""
File Type Router
================

Centralized file type classification and routing for the RAG pipeline.
Determines the appropriate processing method for each document type.
"""

from dataclasses import dataclass
from enum import Enum
import logging
from pathlib import Path
from typing import List

logger = logging.getLogger(__name__)


class DocumentType(Enum):
    """Document type classification."""

    PDF = "pdf"
    TEXT = "text"
    MARKDOWN = "markdown"
    DOCX = "docx"
    SPREADSHEET = "spreadsheet"
    PRESENTATION = "presentation"
    IMAGE = "image"
    UNKNOWN = "unknown"


@dataclass
class FileClassification:
    """Result of file classification."""

    parser_files: List[str]
    text_files: List[str]
    image_files: List[str]
    unsupported: List[str]


class FileTypeRouter:
    """File type router for the RAG pipeline.

    Classifies files before processing to route them to appropriate handlers:
    - PDF / Office files -> parser-based text extraction
    - Text files -> Direct read (fast, simple)
    - Unsupported -> Skip with warning
    """

    PDF_EXTENSIONS = {".pdf"}
    OFFICE_EXTENSIONS = {".docx", ".xlsx", ".pptx"}
    PARSER_EXTENSIONS = PDF_EXTENSIONS | OFFICE_EXTENSIONS

    TEXT_EXTENSIONS = {
        # Plain text & docs
        ".txt",
        ".text",
        ".log",
        ".md",
        ".markdown",
        ".rst",
        ".asciidoc",
        # Data / config
        ".json",
        ".jsonc",
        ".json5",
        ".yaml",
        ".yml",
        ".toml",
        ".csv",
        ".tsv",
        ".ini",
        ".cfg",
        ".conf",
        ".env",
        ".properties",
        # Typesetting
        ".tex",
        ".latex",
        ".bib",
        # JavaScript / TypeScript family
        ".js",
        ".mjs",
        ".cjs",
        ".ts",
        ".mts",
        ".cts",
        ".jsx",
        ".tsx",
        # Web frameworks
        ".vue",
        ".svelte",
        # Python
        ".py",
        # JVM languages
        ".java",
        ".kt",
        ".kts",
        ".scala",
        ".groovy",
        ".gradle",
        # Systems languages
        ".c",
        ".h",
        ".cpp",
        ".cc",
        ".cxx",
        ".hpp",
        ".hh",
        ".hxx",
        ".cs",
        ".go",
        ".rs",
        ".zig",
        ".nim",
        # Apple platforms
        ".swift",
        ".m",
        ".mm",
        # Scripting
        ".rb",
        ".php",
        ".pl",
        ".pm",
        ".lua",
        ".r",
        ".jl",
        ".dart",
        # Functional
        ".hs",
        ".clj",
        ".cljs",
        ".cljc",
        ".ex",
        ".exs",
        ".erl",
        ".ml",
        ".mli",
        ".fs",
        ".fsx",
        ".lisp",
        ".lsp",
        ".scm",
        ".rkt",
        # Web markup / styles
        ".html",
        ".htm",
        ".xml",
        ".svg",
        ".css",
        ".scss",
        ".sass",
        ".less",
        # Smart contracts
        ".sol",
        # Shells / editors
        ".sh",
        ".bash",
        ".zsh",
        ".fish",
        ".ps1",
        ".vim",
        # Query / IDL
        ".sql",
        ".graphql",
        ".gql",
        ".proto",
        # Build / infra
        ".cmake",
        ".mk",
        ".tf",
        ".hcl",
        ".nginxconf",
        ".dockerfile",
    }

    IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".bmp", ".tiff", ".tif"}

    @classmethod
    def get_document_type(cls, file_path: str) -> DocumentType:
        """Classify a single file by its type."""
        ext = Path(file_path).suffix.lower()

        if ext in cls.PDF_EXTENSIONS:
            return DocumentType.PDF
        elif ext in cls.TEXT_EXTENSIONS:
            return DocumentType.TEXT
        elif ext == ".docx":
            return DocumentType.DOCX
        elif ext == ".xlsx":
            return DocumentType.SPREADSHEET
        elif ext == ".pptx":
            return DocumentType.PRESENTATION
        elif ext in cls.IMAGE_EXTENSIONS:
            return DocumentType.IMAGE
        else:
            if cls._is_text_file(file_path):
                return DocumentType.TEXT
            return DocumentType.UNKNOWN

    @classmethod
    def _is_text_file(cls, file_path: str, sample_size: int = 8192) -> bool:
        """Detect if a file is text-based by examining its content."""
        try:
            with open(file_path, "rb") as f:
                chunk = f.read(sample_size)

            if b"\x00" in chunk:
                return False

            chunk.decode("utf-8")
            return True
        except (UnicodeDecodeError, IOError, OSError):
            return False

    @classmethod
    def classify_files(cls, file_paths: List[str]) -> FileClassification:
        """Classify a list of files by processing method."""
        parser_files = []
        text_files = []
        image_files = []
        unsupported = []

        for path in file_paths:
            doc_type = cls.get_document_type(path)

            if doc_type in (
                DocumentType.PDF,
                DocumentType.DOCX,
                DocumentType.SPREADSHEET,
                DocumentType.PRESENTATION,
            ):
                parser_files.append(path)
            elif doc_type in (DocumentType.TEXT, DocumentType.MARKDOWN):
                text_files.append(path)
            elif doc_type == DocumentType.IMAGE:
                image_files.append(path)
            else:
                unsupported.append(path)

        logger.debug(
            f"Classified {len(file_paths)} files: "
            f"{len(parser_files)} parser, {len(text_files)} text, "
            f"{len(image_files)} image, {len(unsupported)} unsupported"
        )

        return FileClassification(
            parser_files=parser_files,
            text_files=text_files,
            image_files=image_files,
            unsupported=unsupported,
        )

    TEXT_DECODING_CANDIDATES = (
        "utf-8",
        "utf-8-sig",
        "gbk",
        "gb2312",
        "gb18030",
        "latin-1",
        "cp1252",
    )

    @classmethod
    def decode_bytes(cls, data: bytes) -> str:
        """Decode raw bytes using the same fallback chain as read_text_file.

        Used by the chat-attachment extractor so path-based and bytes-based
        callers share one source of truth for supported encodings.
        """
        for encoding in cls.TEXT_DECODING_CANDIDATES:
            try:
                return data.decode(encoding)
            except UnicodeDecodeError:
                continue
        return data.decode("utf-8", errors="replace")

    @classmethod
    async def read_text_file(cls, file_path: str) -> str:
        """Read a text file with automatic encoding detection."""
        for encoding in cls.TEXT_DECODING_CANDIDATES:
            try:
                with open(file_path, "r", encoding=encoding) as f:
                    return f.read()
            except UnicodeDecodeError:
                continue

        with open(file_path, "rb") as f:
            return f.read().decode("utf-8", errors="replace")

    @classmethod
    def needs_parser(cls, file_path: str) -> bool:
        """Quick check if a single file needs parser processing."""
        doc_type = cls.get_document_type(file_path)
        return doc_type in (
            DocumentType.PDF,
            DocumentType.DOCX,
            DocumentType.SPREADSHEET,
            DocumentType.PRESENTATION,
            DocumentType.IMAGE,
        )

    @classmethod
    def is_text_readable(cls, file_path: str) -> bool:
        """Check if a file can be read directly as text."""
        doc_type = cls.get_document_type(file_path)
        return doc_type in (DocumentType.TEXT, DocumentType.MARKDOWN)

    @classmethod
    def get_supported_extensions(cls) -> set[str]:
        """Get the set of all supported file extensions."""
        return cls.PARSER_EXTENSIONS | cls.TEXT_EXTENSIONS | cls.IMAGE_EXTENSIONS

    @classmethod
    def has_supported_extension(cls, file_path: str | Path) -> bool:
        """Return True when ``file_path`` has a supported extension.

        The check is case-insensitive so files such as ``Report.PDF`` are
        discovered consistently across upload, CLI, folder sync, and reindex.
        """
        return Path(file_path).suffix.lower() in cls.get_supported_extensions()

    @classmethod
    def collect_supported_files(cls, directory: str | Path, recursive: bool = False) -> list[Path]:
        """Collect supported files from a directory with case-insensitive suffix matching."""
        root = Path(directory)
        if not root.exists() or not root.is_dir():
            return []

        paths = root.rglob("*") if recursive else root.iterdir()
        return sorted(
            (path for path in paths if path.is_file() and cls.has_supported_extension(path)),
            key=lambda path: str(path).lower(),
        )

    @classmethod
    def get_glob_patterns(cls) -> list[str]:
        """Get glob patterns for file searching."""
        return [f"*{ext}" for ext in sorted(cls.get_supported_extensions())]
