#!/usr/bin/env python
"""
Document Validator - Validation utilities for document uploads
"""

import mimetypes
import os
import re
from typing import ClassVar
import unicodedata


class DocumentValidator:
    """Document validation utilities"""

    # Maximum file size in bytes (200MB), applied uniformly to every format.
    MAX_FILE_SIZE: ClassVar[int] = 200 * 1024 * 1024

    # Allowed file extensions
    ALLOWED_EXTENSIONS: ClassVar[set[str]] = {
        ".pdf",
        ".txt",
        ".md",
        ".doc",
        ".docx",
        ".rtf",
        ".html",
        ".htm",
        ".xml",
        ".json",
        ".csv",
        ".xlsx",
        ".xls",
        ".pptx",
        ".ppt",
    }

    # MIME type mapping for additional validation
    ALLOWED_MIME_TYPES: ClassVar[set[str]] = {
        "application/pdf",
        "text/plain",
        "text/markdown",
        "application/msword",
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        "application/rtf",
        "text/html",
        "application/xml",
        "text/xml",
        "application/json",
        "text/csv",
        "application/vnd.ms-excel",
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        "application/vnd.ms-powerpoint",
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
    }

    @staticmethod
    def validate_upload_safety(
        filename: str, file_size: int | None, allowed_extensions: set[str] | None = None
    ) -> str:
        """
        Validate file upload safety

        Args:
            filename: Name of the file
            file_size: Size of the file in bytes, or None to skip size validation
            allowed_extensions: Optional override for allowed extensions

        Returns:
            Sanitized filename safe for filesystem use

        Raises:
            ValueError: If validation fails
        """
        # Check file size (skip if size is None)
        if file_size is not None and file_size > DocumentValidator.MAX_FILE_SIZE:
            raise ValueError(
                f"File too large: {file_size} bytes. Maximum allowed: {DocumentValidator.MAX_FILE_SIZE} bytes"
            )

        # Sanitize filename - remove path components and dangerous characters
        # Normalize Unicode and strip both POSIX and Windows path components.
        normalized_filename = unicodedata.normalize("NFC", filename)
        safe_name = normalized_filename.replace("\\", "/").rsplit("/", 1)[-1]
        # Remove null bytes and other control characters
        safe_name = re.sub(r"[\x00-\x1f\x7f]", "", safe_name)
        # Replace problematic characters
        safe_name = re.sub(r'[<>:"/\\|?*]', "_", safe_name)
        stem, ext = os.path.splitext(safe_name)
        ext = ext.lower()
        safe_name = f"{stem}{ext}"

        if not safe_name or safe_name in (".", "..") or safe_name.strip("_") == "":
            raise ValueError("Invalid filename")

        # Check file extension
        exts_to_check = allowed_extensions or DocumentValidator.ALLOWED_EXTENSIONS
        if ext not in exts_to_check:
            raise ValueError(
                f"Unsupported file type: {ext}. Allowed types: {', '.join(exts_to_check)}"
            )

        # Additional MIME type validation for the legacy/default policy. For
        # caller-provided extension policies (for example the KB router's
        # FileTypeRouter list), the extension set is already the source of
        # truth; mimetypes is extension-derived and incomplete for many code
        # and config formats.
        guessed_mime, _ = mimetypes.guess_type(safe_name.lower())
        if (
            allowed_extensions is None
            and guessed_mime
            and guessed_mime not in DocumentValidator.ALLOWED_MIME_TYPES
        ):
            raise ValueError(
                f"MIME type validation failed: {guessed_mime}. File may be malicious or corrupted."
            )

        return safe_name

    @staticmethod
    def get_file_info(filename: str, file_size: int) -> dict:
        """
        Get file information

        Args:
            filename: Name of the file
            file_size: Size of the file in bytes

        Returns:
            Dictionary with file information
        """
        _, ext = os.path.splitext(filename.lower())
        return {
            "filename": filename,
            "extension": ext,
            "size_bytes": file_size,
            "size_mb": round(file_size / (1024 * 1024), 2),
            "is_allowed": ext in DocumentValidator.ALLOWED_EXTENSIONS,
        }

    @staticmethod
    def validate_file(path: str) -> dict:
        """
        Validate that a file exists, is readable, and has valid content.

        Args:
            path: Path to the file to validate

        Returns:
            File info dictionary

        Raises:
            ValueError: If file is missing or validation fails
        """
        if not os.path.exists(path):
            raise ValueError(f"File not found: {path}")

        if not os.path.isfile(path):
            raise ValueError(f"Not a file: {path}")

        if not os.access(path, os.R_OK):
            raise ValueError(f"File not readable: {path}")

        size = os.path.getsize(path)
        filename = os.path.basename(path)

        # Validate using validate_upload_safety
        safe_name = DocumentValidator.validate_upload_safety(filename, size)

        return DocumentValidator.get_file_info(safe_name, size)
