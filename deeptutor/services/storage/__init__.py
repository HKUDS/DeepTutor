"""Pluggable storage backends for chat-session artifacts.

Currently exposes :mod:`attachment_store` (session-facing paths + public URLs)
and :mod:`blob_store` (content-addressed bytes shared across identical uploads).
"""

from deeptutor.services.storage.attachment_store import (
    AttachmentStore,
    LocalDiskAttachmentStore,
    get_attachment_store,
)
from deeptutor.services.storage.blob_store import ContentAddressedBlobStore, sha256_hex

__all__ = [
    "AttachmentStore",
    "ContentAddressedBlobStore",
    "LocalDiskAttachmentStore",
    "get_attachment_store",
    "sha256_hex",
]
