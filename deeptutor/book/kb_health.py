"""KB drift detection & log.md health checks for the Book Engine.

This module is intentionally side-effect-free: it inspects the on-disk
representation of a knowledge base (the ``raw/`` documents folder) to derive a
deterministic fingerprint, compares it to the fingerprint snapshot stored on
the Book manifest, and surfaces a structured impact report. The Book Engine
calls this module after compilation to mark stale pages, and the API exposes
it so the frontend can show a "this book is out-of-date" banner.

A second helper (`scan_log_health`) parses the per-book ``log.md`` to detect
recurring failures – useful for maintenance dashboards.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import hashlib
import logging
from pathlib import Path
import re
import time
from typing import Any

from deeptutor.knowledge.manager import KnowledgeBaseManager


def _current_manager() -> KnowledgeBaseManager:
    """The KB manager rooted at the *current user's* knowledge bases.

    Constructing ``KnowledgeBaseManager()`` directly picks up its CWD-relative
    default root, which under multi-user points at the wrong workspace (and
    under any deployment where the process CWD isn't the data dir, at nothing).
    ``current_kb_manager`` resolves through PathService like the knowledge and
    subagent routers do.
    """
    try:
        from deeptutor.multi_user.knowledge_access import current_kb_manager

        return current_kb_manager()
    except Exception:  # noqa: BLE001 - single-user / bare-SDK fallback
        return KnowledgeBaseManager()


from .models import Book
from .storage import BookStorage, get_book_storage

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Fingerprints
# ─────────────────────────────────────────────────────────────────────────────


def _hash_file(path: Path) -> str:
    """Content hash for a raw source document."""
    try:
        digest = hashlib.sha256()
        with open(path, "rb") as handle:
            for block in iter(lambda: handle.read(65536), b""):
                digest.update(block)
        return f"sha256:{digest.hexdigest()}"
    except OSError:
        return ""


# Bumped whenever the formula below changes. A stored fingerprint carrying a
# different scheme is not evidence of drift — it was computed a different way —
# so detect_kb_drift re-baselines instead of marking every page stale.
FINGERPRINT_SCHEME = "sha256-paths-v1"


def _scheme_changed(stored: dict[str, str]) -> bool:
    """Whether a stored baseline was written by a different fingerprint formula."""
    return any(
        value and not value.startswith(f"{FINGERPRINT_SCHEME}:") for value in stored.values()
    )


def digest_documents(documents: dict[str, str]) -> str:
    """Collapse a per-document hash map into one KB fingerprint.

    Keyed by path, so a pure rename changes the fingerprint even though the
    bytes did not — the coarse check exists to answer "did this KB change".
    """
    if not documents:
        return ""
    payload = "|".join(f"{path}:{value}" for path, value in sorted(documents.items()))
    return f"{FINGERPRINT_SCHEME}:{hashlib.sha256(payload.encode('utf-8')).hexdigest()}"


def fingerprint_kb(kb_name: str, manager: KnowledgeBaseManager | None = None) -> str:
    """Return a deterministic fingerprint for the *raw* docs of a KB.

    Returns ``""`` when the KB does not exist (so callers can detect deletion).
    Derived from the per-document map rather than walking raw/ a second time:
    hashing every byte twice per drift check made ``/books/{id}/health`` — an
    endpoint the reader polls — scale with total KB size, and two independent
    passes could also disagree if a file changed between them.
    """
    return digest_documents(fingerprint_kb_documents(kb_name, manager=manager))


def fingerprint_kbs(
    kb_names: list[str], manager: KnowledgeBaseManager | None = None
) -> dict[str, str]:
    mgr = manager or _current_manager()
    return {name: fingerprint_kb(name, manager=mgr) for name in kb_names}


def fingerprint_kb_documents(
    kb_name: str, manager: KnowledgeBaseManager | None = None
) -> dict[str, str]:
    """Return content hashes keyed by stable paths under a KB's ``raw/``."""
    mgr = manager or _current_manager()
    if kb_name not in mgr.list_knowledge_bases():
        return {}
    raw_dir = mgr.base_dir / kb_name / "raw"
    if not raw_dir.exists():
        return {}
    result: dict[str, str] = {}
    for child in sorted(raw_dir.rglob("*")):
        if not child.is_file():
            continue
        value = _hash_file(child)
        if value:
            result[str(child.relative_to(raw_dir).as_posix())] = value
    return result


def fingerprint_kb_documents_batch(
    kb_names: list[str], manager: KnowledgeBaseManager | None = None
) -> dict[str, dict[str, str]]:
    mgr = manager or _current_manager()
    return {name: fingerprint_kb_documents(name, manager=mgr) for name in kb_names}


# ─────────────────────────────────────────────────────────────────────────────
# Drift report
# ─────────────────────────────────────────────────────────────────────────────


@dataclass
class KBDriftReport:
    book_id: str
    has_drift: bool = False
    new_kbs: list[str] = field(default_factory=list)
    removed_kbs: list[str] = field(default_factory=list)
    changed_kbs: list[str] = field(default_factory=list)
    changed_documents: dict[str, list[str]] = field(default_factory=dict)
    current_fingerprints: dict[str, str] = field(default_factory=dict)
    stale_page_ids: list[str] = field(default_factory=list)
    fallback_stale_pages: bool = False

    def to_dict(self) -> dict:
        return {
            "book_id": self.book_id,
            "has_drift": self.has_drift,
            "new_kbs": self.new_kbs,
            "removed_kbs": self.removed_kbs,
            "changed_kbs": self.changed_kbs,
            "changed_documents": self.changed_documents,
            "current_fingerprints": self.current_fingerprints,
            "stale_page_ids": self.stale_page_ids,
            "fallback_stale_pages": self.fallback_stale_pages,
        }


def detect_kb_drift(
    book: Book,
    storage: BookStorage | None = None,
    manager: KnowledgeBaseManager | None = None,
) -> KBDriftReport:
    """Compare ``book.kb_fingerprints`` against current KB state.

    If the book has no stored fingerprints yet (brand-new book that hasn't
    completed its first compile, or a legacy book created before fingerprinting
    was wired up) we treat the *current* state as the baseline rather than
    flagging every selected KB as "newly added". Without this guard the
    health-check would surface a spurious drift warning the moment the user
    opens a freshly-created book.
    """
    store = storage or get_book_storage()
    # One walk over raw/: the coarse per-KB fingerprints are derived from the
    # per-document map rather than recomputed from disk.
    current_documents = fingerprint_kb_documents_batch(book.knowledge_bases, manager=manager)
    current = {name: digest_documents(docs) for name, docs in current_documents.items()}
    stored = dict(book.kb_fingerprints or {})
    stored_documents = dict(book.kb_document_fingerprints or {})

    if not stored or _scheme_changed(stored):
        # No baseline yet (brand-new or pre-fingerprinting book), or a baseline
        # written by an older formula. Neither is evidence that the sources
        # moved, and treating a scheme change as drift would mark every page in
        # every existing book stale at once — which the refresh gate then
        # refuses to clear until they are all recompiled.
        return KBDriftReport(
            book_id=book.id,
            has_drift=False,
            current_fingerprints=current,
        )

    # Only flag *new* KBs that were actually selected for this book — we do
    # not care about KBs the user added to their workspace but never linked
    # to the book.
    new_kbs = [k for k in current if k not in stored and k in book.knowledge_bases]
    removed_kbs = [k for k in stored if k not in current and k in book.knowledge_bases]
    changed_kbs = [
        k for k, v in current.items() if k in stored and stored[k] and v and stored[k] != v
    ]

    has_drift = bool(new_kbs or removed_kbs or changed_kbs)
    changed_documents: dict[str, list[str]] = {}
    for kb_name in changed_kbs:
        before = stored_documents.get(kb_name) or {}
        after = current_documents.get(kb_name) or {}
        changed_documents[kb_name] = sorted(
            set(before) ^ set(after)
            | {key for key in set(before) & set(after) if before[key] != after[key]}
        )
    for kb_name in new_kbs:
        changed_documents[kb_name] = sorted(current_documents.get(kb_name, {}))

    stale_pages: list[str] = []
    fallback = False
    spine = store.load_spine(book.id)
    chapter_anchors = (
        {chapter.id: chapter.source_anchors for chapter in spine.chapters}
        if spine is not None
        else {}
    )
    if has_drift:
        for page in store.list_pages(book.id):
            if page.status.value != "ready":
                continue
            anchors = list(chapter_anchors.get(page.chapter_id, []))
            for block in page.blocks:
                anchors.extend(block.source_anchors)
            page_impacted = False
            for kb_name, refs in changed_documents.items():
                scoped = [
                    anchor
                    for anchor in anchors
                    if anchor.kind == "kb"
                    and (
                        str(anchor.kb_name or "") == kb_name
                        or (not anchor.kb_name and len(book.knowledge_bases) == 1)
                    )
                ]
                if not refs or not scoped:
                    page_impacted = True
                    fallback = not refs or not scoped
                    continue
                known_refs = set(stored_documents.get(kb_name) or {}) | set(
                    current_documents.get(kb_name) or {}
                )
                known_anchors = [
                    anchor
                    for anchor in scoped
                    if any(_anchor_matches(anchor.ref, ref) for ref in known_refs)
                ]
                changed_anchors = [
                    anchor
                    for anchor in scoped
                    if any(_anchor_matches(anchor.ref, ref) for ref in refs)
                ]
                if changed_anchors:
                    page_impacted = True
                elif len(known_anchors) != len(scoped):
                    # At least one anchor cannot be resolved to a known raw
                    # document. That unknown anchor may refer to the changed
                    # file, so absence of a match is not evidence of safety.
                    page_impacted = True
                    fallback = True
            # Removed KBs have no current refs. Scope when explicit KB names
            # exist; otherwise preserve the conservative legacy behavior.
            for kb_name in removed_kbs:
                scoped = [
                    anchor
                    for anchor in anchors
                    if anchor.kind == "kb" and str(anchor.kb_name or "") == kb_name
                ]
                if scoped or anchor_kb_names_exist(anchors):
                    page_impacted = page_impacted or bool(scoped)
                else:
                    page_impacted = True
                    fallback = True
            if page_impacted:
                stale_pages.append(page.id)

    stale_pages = list(dict.fromkeys([*book.stale_page_ids, *stale_pages]))

    return KBDriftReport(
        book_id=book.id,
        has_drift=has_drift,
        new_kbs=new_kbs,
        removed_kbs=removed_kbs,
        changed_kbs=changed_kbs,
        changed_documents=changed_documents,
        current_fingerprints=current,
        stale_page_ids=stale_pages,
        fallback_stale_pages=fallback,
    )


def _anchor_matches(anchor_ref: str, document_ref: str) -> bool:
    anchor = anchor_ref.strip().rstrip("/")
    document = document_ref.strip().rstrip("/")
    if not anchor or not document:
        return False
    return anchor == document or anchor.endswith(f"/{document}") or document.endswith(f"/{anchor}")


def anchor_kb_names_exist(anchors: list[Any]) -> bool:
    return any(str(getattr(anchor, "kb_name", "") or "") for anchor in anchors)


def refresh_book_fingerprints(
    book_id: str,
    storage: BookStorage | None = None,
    manager: KnowledgeBaseManager | None = None,
    *,
    force: bool = False,
) -> Book | None:
    """Re-compute and persist KB fingerprints on the book manifest.

    Refuses by default while pages the last drift marked stale have not been
    recompiled, so "mark as seen" cannot quietly hide work still owed.
    ``force`` overrides that: stale detection deliberately over-marks when it
    cannot resolve an anchor to a source document, and a user who judges a
    flagged page fine must be able to dismiss it rather than face a banner
    nothing will clear.
    """
    store = storage or get_book_storage()
    book = store.load_book(book_id)
    if book is None:
        return None
    if book.stale_page_ids and not force:
        if not book.stale_detected_at:
            raise ValueError(
                "Cannot mark KB drift as seen before all stale pages have been recompiled."
            )
        not_recompiled = [
            page_id
            for page_id in book.stale_page_ids
            if (page := store.load_page(book_id, page_id)) is None
            or page.status.value != "ready"
            or page.updated_at < book.stale_detected_at
        ]
        if not_recompiled:
            raise ValueError(
                "Cannot mark KB drift as seen before these pages are recompiled: "
                + ", ".join(not_recompiled)
            )
    documents = fingerprint_kb_documents_batch(book.knowledge_bases, manager=manager)
    book.kb_document_fingerprints = documents
    book.kb_fingerprints = {name: digest_documents(docs) for name, docs in documents.items()}
    book.stale_page_ids = []
    book.stale_detected_at = 0.0
    store.save_book(book)
    store.append_log(
        book_id,
        f"refreshed kb fingerprints ({len(book.kb_fingerprints)} kbs)",
        op="kb_health",
    )
    return book


def mark_drift_on_book(
    book_id: str,
    storage: BookStorage | None = None,
    manager: KnowledgeBaseManager | None = None,
) -> KBDriftReport | None:
    store = storage or get_book_storage()
    book = store.load_book(book_id)
    if book is None:
        return None
    report = detect_kb_drift(book, storage=store, manager=manager)
    dirty = False

    # Self-heal: when there's no drift but the book is missing a baseline
    # fingerprint (legacy book / new book whose first compile hasn't finished)
    # capture the baseline now so future runs have something to compare to.
    if (
        not report.has_drift
        and book.knowledge_bases
        and (not book.kb_fingerprints or _scheme_changed(book.kb_fingerprints))
    ):
        documents = fingerprint_kb_documents_batch(book.knowledge_bases, manager=manager)
        book.kb_document_fingerprints = documents
        book.kb_fingerprints = report.current_fingerprints or {
            name: digest_documents(docs) for name, docs in documents.items()
        }
        dirty = True

    if report.has_drift:
        book.stale_page_ids = report.stale_page_ids
        book.stale_detected_at = time.time()
        dirty = True
        store.append_log(
            book_id,
            (
                f"detected kb drift: changed={report.changed_kbs} "
                f"new={report.new_kbs} removed={report.removed_kbs} "
                f"→ {len(report.stale_page_ids)} stale pages"
            ),
            op="kb_health",
        )

    if dirty:
        store.save_book(book)
    return report


# ─────────────────────────────────────────────────────────────────────────────
# log.md health check
# ─────────────────────────────────────────────────────────────────────────────


_LOG_LINE = re.compile(r"^- `(?P<ts>[^`]+)` \*\*(?P<op>[^*]+)\*\* — (?P<msg>.+)$")


@dataclass
class LogHealthReport:
    book_id: str
    total_entries: int = 0
    error_entries: int = 0
    block_failures: int = 0
    last_compile_at: str = ""
    last_error_at: str = ""
    repeated_failures: list[dict] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "book_id": self.book_id,
            "total_entries": self.total_entries,
            "error_entries": self.error_entries,
            "block_failures": self.block_failures,
            "last_compile_at": self.last_compile_at,
            "last_error_at": self.last_error_at,
            "repeated_failures": self.repeated_failures,
        }


def scan_log_health(book_id: str, storage: BookStorage | None = None) -> LogHealthReport:
    store = storage or get_book_storage()
    log_path: Path = store.path_service.get_book_log_file(book_id)
    report = LogHealthReport(book_id=book_id)
    if not log_path.exists():
        return report

    counter: dict[tuple[str, str], int] = {}
    try:
        with open(log_path, encoding="utf-8") as f:
            for line in f:
                m = _LOG_LINE.match(line.strip())
                if not m:
                    continue
                report.total_entries += 1
                ts = m.group("ts")
                op = m.group("op").strip()
                msg = m.group("msg").strip()
                if op in {"compile_page", "page_compiled", "page_planned"}:
                    report.last_compile_at = ts
                if "error" in op.lower() or "fail" in op.lower():
                    report.error_entries += 1
                    report.last_error_at = ts
                if op == "block_error":
                    report.block_failures += 1
                counter[(op, msg[:80])] = counter.get((op, msg[:80]), 0) + 1
    except OSError as exc:
        logger.warning(f"Could not read log {log_path}: {exc}")
        return report

    # Only report repeated entries whose *operation* denotes a failure. Keying
    # the failure test on the op (not the free-text message) avoids both false
    # positives (a success whose message mentions "error"/"failure") and false
    # negatives (a failure op whose message happens not to).
    repeated: list[dict[str, str | int]] = [
        {"signature": f"{op}:{msg}", "count": v}
        for (op, msg), v in counter.items()
        if v >= 3 and ("error" in op.lower() or "fail" in op.lower())
    ]
    repeated.sort(key=lambda r: r["count"] if isinstance(r["count"], int) else 0, reverse=True)
    report.repeated_failures = repeated[:10]
    return report


__all__ = [
    "KBDriftReport",
    "LogHealthReport",
    "detect_kb_drift",
    "fingerprint_kb",
    "fingerprint_kbs",
    "mark_drift_on_book",
    "refresh_book_fingerprints",
    "scan_log_health",
]
