"""Immutable output-blob persistence for knowledge-card generation (KB-02).

The worker normalizes executor output to a bounded ``{title, body}`` payload and
atomically persists it here — content-addressed by the SHA-256 of the sanitized
payload — *before* attempting to apply it to the card (§7.9.1, requirement 5).
This guarantees a running attempt with a complete durable output blob can be
reconciled after a crash, while a crash before the blob exists must become
``unknown`` (the provider result cannot be confirmed).

Blobs are immutable: the ref is the content hash, so a blob is never
overwritten. Only sanitized data is ever persisted — full private URLs, auth
material and base64/media payloads are rejected by :func:`sanitize_blob` before
anything is written.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re
import threading
from typing import Any

from deeptutor.learning.knowledge_cards.config import KnowledgeCardLimits
from deeptutor.learning.knowledge_cards.errors import OutputValidationError
from deeptutor.services.file_io import atomic_write_text
from deeptutor.services.media.redaction import looks_like_base64_payload, redact_text

#: Module-level lock so blob existence checks + writes are atomic across store
#: instances in the process (same CAS convention as LearningStore/MediaStore).
_blob_lock = threading.Lock()

#: Blob content keys the executor may return; anything else is dropped.
_ALLOWED_BLOB_KEYS = ("title", "body")

#: Payloads that look like a provider envelope / raw response wrapper.
#: Plain ``data:`` / ``base64,`` substrings are NOT markers on their own —
#: legitimate educational prose such as ``The data: shows 42% growth`` or
#: ``base64, hex`` must pass through. Raw envelope leakage is caught
#: structurally below (:data:`_PROVIDER_ENVELOPE_KEY_RE` /
#: :data:`_DATA_URI_RE` / :data:`_SSE_JSON_DATA_RE`) and real base64 media by
#: :func:`looks_like_base64_payload`.
_PROVIDER_ENVELOPE_MARKERS = (
    '"provider"',
    '"raw_response"',
    '"model"',
    '"id"',
    '"choices"',
)

#: Provider-envelope keys in JSON-key position, matched against the *raw*
#: title/body.  Embedded provider JSON keeps its literal quotes in the raw
#: strings — matching against ``json.dumps(payload)`` escapes them
#: (``\"model\"``), so the quote-based markers could never fire.  Requiring the
#: ``:`` after the quoted key keeps prose that merely mentions a model/ID/
#: choices/tokens, or quotes a word without a following colon, from being
#: mistaken for an envelope.
_PROVIDER_ENVELOPE_KEY_RE = re.compile(
    r"\"(?:"
    + "|".join(re.escape(marker.strip('"')) for marker in _PROVIDER_ENVELOPE_MARKERS)
    + r")\"\s*:",
    re.IGNORECASE,
)

#: A raw data URI (RFC 2397) — ``data:text/plain,...``, ``data:image/png,...``,
#: ``data:;base64,...`` — requiring a MIME-type/parameter token immediately
#: after ``data:`` (no whitespace). The base64 form is also caught precisely by
#: :func:`looks_like_base64_payload`; prose like ``The data: shows`` (space
#: after the colon) never matches.
_DATA_URI_RE = re.compile(r"\bdata:[a-z0-9]+[/;,]", re.IGNORECASE)

#: An SSE/streaming provider envelope line carrying JSON (``data: {`` /
#: ``data: [``) embedded in the payload text.
_SSE_JSON_DATA_RE = re.compile(r"data:\s*[\[\{]", re.IGNORECASE)


def default_blob_root() -> Path:
    """Per-path blob root under the persistent learning store root."""
    from deeptutor.services.path_service import get_path_service

    return get_path_service().get_workspace_dir() / "learning" / "knowledge_card_blobs"


def sanitize_blob(title: str, body: str) -> tuple[str, str]:
    """Sanitize title/body before any blob or card metadata is persisted.

    Fail-closed: full URLs collapse to ``[url]``, secret-looking values are
    redacted, and any base64/media payload collapses the whole value to a
    placeholder. This mirrors the media runtime redaction contract (§10.5/§14)
    so a provider output can never smuggle a private URL, credential or binary
    envelope into a durable record.
    """
    safe_title = redact_text(title)
    safe_body = redact_text(body)
    return safe_title, safe_body


def validate_blob_payload(payload: dict[str, Any], *, limits: KnowledgeCardLimits) -> None:
    """Validate and bound a normalized output blob payload.

    ``payload`` must be a mapping containing string ``title``/``body`` within the
    configured size bounds, must not look like a provider envelope, and must not
    embed a base64/media payload. Raises :class:`OutputValidationError` without
    touching any durable record.
    """
    if not isinstance(payload, dict):
        raise OutputValidationError("draft output must be a {title, body} mapping")
    title = payload.get("title")
    body = payload.get("body")
    if not isinstance(title, str) or not isinstance(body, str):
        raise OutputValidationError(
            "draft output title/body must be strings, got "
            f"{type(title).__name__}/{type(body).__name__}"
        )
    if len(title) > limits.max_title_chars:
        raise OutputValidationError(f"draft title exceeds {limits.max_title_chars} characters")
    if len(body) > limits.max_body_chars:
        raise OutputValidationError(f"draft body exceeds {limits.max_body_chars} characters")
    serialized = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    if len(serialized.encode("utf-8")) > limits.max_blob_bytes:
        raise OutputValidationError(f"draft output blob exceeds {limits.max_blob_bytes} bytes")
    if looks_like_base64_payload(title) or looks_like_base64_payload(body):
        raise OutputValidationError(
            "draft output embeds a base64/media payload; refusing to persist"
        )
    raw = f"{title}\n{body}"
    if _PROVIDER_ENVELOPE_KEY_RE.search(raw):
        raise OutputValidationError(
            "draft output looks like a raw provider envelope; refusing to persist"
        )
    if _DATA_URI_RE.search(raw) or _SSE_JSON_DATA_RE.search(raw):
        raise OutputValidationError(
            "draft output looks like a raw data-URI/SSE provider envelope; refusing to persist"
        )


def blob_payload_hash(payload: dict[str, Any]) -> str:
    """Deterministic SHA-256 of the canonicalized blob payload (the content id)."""
    canonical = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


class KnowledgeCardBlobStore:
    """Content-addressed, immutable storage of generation output blobs."""

    def __init__(self, root: Path | None = None) -> None:
        self._root = Path(root) if root is not None else default_blob_root()
        self._blobs_dir = self._root / "blobs"
        self._blobs_dir.mkdir(parents=True, exist_ok=True)

    @property
    def root(self) -> Path:
        return self._root

    def save_blob(self, payload: dict[str, Any]) -> tuple[str, str]:
        """Atomically persist a sanitized payload; returns ``(blob_ref, blob_hash)``.

        The blob is content-addressed by the SHA-256 of the payload, so a repeat
        save of the same bytes is a no-op and a blob can never be mutated after
        the fact. Raises :class:`OutputValidationError` for unsafe/unbounded
        payloads before anything is written.
        """
        with _blob_lock:
            digest = blob_payload_hash(payload)
            #: Content-addressed ref, relative to the blob root's ``blobs/`` dir.
            #: A bare filename (no separators) so refs are path-safe everywhere.
            relative = f"{digest}.json"
            path = self._blobs_dir / relative
            if not path.exists():
                atomic_write_text(path, json.dumps(payload, ensure_ascii=False, indent=2))
            return relative, digest

    def load_blob(self, blob_ref: str) -> dict[str, Any] | None:
        """Load a previously persisted blob by its relative ref (``None`` if gone)."""
        if not blob_ref or "/" in blob_ref or ".." in blob_ref or "\\" in blob_ref:
            return None
        path = self._blobs_dir / Path(blob_ref).name
        if not path.exists():
            return None
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return None
        if not isinstance(data, dict):
            return None
        return data

    def blob_exists(self, blob_ref: str) -> bool:
        if not blob_ref or "/" in blob_ref or ".." in blob_ref or "\\" in blob_ref:
            return False
        return (self._blobs_dir / Path(blob_ref).name).exists()


__all__ = [
    "KnowledgeCardBlobStore",
    "blob_payload_hash",
    "default_blob_root",
    "sanitize_blob",
    "validate_blob_payload",
]
