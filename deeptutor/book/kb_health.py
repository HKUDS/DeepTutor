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

from deeptutor.knowledge.manager import KnowledgeBaseManager

from .models import Book
from .storage import BookStorage, get_book_storage

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────────────────────────────────────
# Fingerprints
# ─────────────────────────────────────────────────────────────────────────────


def _hash_file(path: Path) -> str:
    """Cheap, change-sensitive fingerprint: name + mtime + size."""
    try:
        stat = path.stat()
    except OSError:
        return ""
    return f"{path.name}:{int(stat.st_mtime)}:{stat.st_size}"


def fingerprint_kb(kb_name: str, manager: KnowledgeBaseManager | None = None) -> str:
    """Return a deterministic fingerprint for the *raw* docs of a KB.

    Returns ``""`` when the KB does not exist (so callers can detect deletion).
    """
    mgr = manager or KnowledgeBaseManager()
    if kb_name not in mgr.list_knowledge_bases():
        return ""
    base_dir: Path = mgr.base_dir / kb_name / "raw"
    if not base_dir.exists():
        return ""
    parts: list[str] = []
    for child in sorted(base_dir.rglob("*")):
        if not child.is_file():
            continue
        token = _hash_file(child)
        if token:
            parts.append(token)
    if not parts:
        return ""
    digest = hashlib.sha256("|".join(parts).encode("utf-8")).hexdigest()
    return digest


def fingerprint_kbs(
    kb_names: list[str], manager: KnowledgeBaseManager | None = None
) -> dict[str, str]:
    mgr = manager or KnowledgeBaseManager()
    return {name: fingerprint_kb(name, manager=mgr) for name in kb_names}


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
    current_fingerprints: dict[str, str] = field(default_factory=dict)
    stale_page_ids: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "book_id": self.book_id,
            "has_drift": self.has_drift,
            "new_kbs": self.new_kbs,
            "removed_kbs": self.removed_kbs,
            "changed_kbs": self.changed_kbs,
            "current_fingerprints": self.current_fingerprints,
            "stale_page_ids": self.stale_page_ids,
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
    current = fingerprint_kbs(book.knowledge_bases, manager=manager)
    stored = dict(book.kb_fingerprints or {})

    if not stored:
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
    stale_pages: list[str] = []
    if has_drift:
        # Any READY page that referenced this KB is stale.
        for page in store.list_pages(book.id):
            if page.status.value == "ready":
                stale_pages.append(page.id)

    return KBDriftReport(
        book_id=book.id,
        has_drift=has_drift,
        new_kbs=new_kbs,
        removed_kbs=removed_kbs,
        changed_kbs=changed_kbs,
        current_fingerprints=current,
        stale_page_ids=stale_pages,
    )


def refresh_book_fingerprints(
    book_id: str,
    storage: BookStorage | None = None,
    manager: KnowledgeBaseManager | None = None,
) -> Book | None:
    """Re-compute and persist KB fingerprints on the book manifest."""
    store = storage or get_book_storage()
    book = store.load_book(book_id)
    if book is None:
        return None
    book.kb_fingerprints = fingerprint_kbs(book.knowledge_bases, manager=manager)
    book.stale_page_ids = []
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
    if not report.has_drift and not book.kb_fingerprints and book.knowledge_bases:
        book.kb_fingerprints = report.current_fingerprints or fingerprint_kbs(
            book.knowledge_bases, manager=manager
        )
        dirty = True

    if report.has_drift:
        book.stale_page_ids = report.stale_page_ids
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
    elif book.stale_page_ids:
        # No drift any more (e.g. a previous false-positive was just fixed) →
        # clear the leftover stale markers so the UI banner disappears.
        book.stale_page_ids = []
        dirty = True
        store.append_log(
            book_id,
            "cleared stale page markers (no drift detected)",
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
