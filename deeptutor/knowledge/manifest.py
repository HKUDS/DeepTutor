"""Document inventory of a knowledge base — the facts retrieval cannot answer.

Retrieval answers "what does the material say". It cannot answer "how many
files are in this knowledge base", "did I upload X", or "list what's in here":
those are questions about the KB's *inventory*, and no amount of passage
similarity produces them. Asked one anyway, a model with only ``rag`` in hand
either guesses from the passages it happened to retrieve or declines.

This module owns the inventory as plain facts read off disk, so the two
consumers can never disagree:

* the chat system prompt embeds a manifest (:func:`render_manifest_note`), so
  counts are answerable with no tool round-trip — the failure mode where a
  weaker model simply never calls the tool;
* the ``kb_files`` tool enumerates on demand (:func:`render_manifest_report`)
  for the full list, which a system-prompt manifest deliberately truncates.

Most inventories are a directory walk. A *connected* KB whose documents live
behind an API has no directory, but that does not always mean the inventory is
unknowable: when the service exposes a listing call, this module reads it through
:data:`_REMOTE_INVENTORY_READERS` and reports the result exactly like a local one
(Tencent IMA's ``get_knowledge_list`` is the first such reader). Only when there
is no reader, or the call fails, does a KB fall back to being reported as
non-enumerable. A remote listing may be bounded by a request budget, in which
case the count is flagged as a lower bound rather than being presented as a total.

Deliberately NOT reported: how many documents made it into the *index*. Every
per-file index record available is unreliable — LlamaIndex's ``docstore.json``
counts nodes (chunk-level, so it drifts with the chunking config and costs a
multi-MB JSON parse to read), ``metadata.json``'s ``file_hashes`` is only
written on the incremental-add path (KBs built by the create path have none),
and ``last_indexed_count`` is the size of the last batch rather than a total. A
confidently wrong count is worse than no count, so a manifest carries the
document set plus the KB's index *status* and stops there.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass
import fnmatch
import os
from pathlib import Path
from typing import Any

from deeptutor.knowledge.kb_types import (
    IMA_KB_TYPE,
    LIGHTRAG_SERVER_KB_TYPE,
    SUBAGENT_KB_TYPE,
    external_root_of,
)

# Documents listed per KB in the system-prompt manifest. Bounded because the
# manifest rides in every turn's prompt prefix; ``kb_files`` serves the tail.
MANIFEST_NOTE_LIMIT = 20

# ``kb_files`` defaults: generous enough to enumerate an ordinary KB in one
# call, capped so a pathological KB cannot flood the context window.
KB_FILES_DEFAULT_LIMIT = 200
KB_FILES_MAX_LIMIT = 1000

# Why a KB's documents cannot be listed. Reason *codes* — the data layer never
# produces user-facing copy; the renderers localise these.
UNAVAILABLE_REMOTE = "remote"
UNAVAILABLE_AGENT = "agent"
UNAVAILABLE_MISSING = "missing"

# KB types that hold no local document set at all: their content lives behind
# an API. Reporting them as "0 documents" would be a lie, so they are reported
# as non-enumerable unless a remote reader below can list them for real.
_NON_DOCUMENT_KB_TYPES: dict[str, str] = {
    LIGHTRAG_SERVER_KB_TYPE: UNAVAILABLE_REMOTE,
    IMA_KB_TYPE: UNAVAILABLE_REMOTE,
    SUBAGENT_KB_TYPE: UNAVAILABLE_AGENT,
}

# The document names a connected KB's own service can list, plus whether that
# listing is complete. ``None`` means the inventory could not be read at all, so
# the KB is reported as non-enumerable — the pre-reader behaviour.
RemoteInventoryReader = Callable[[Mapping[str, Any]], "tuple[list[str], bool] | None"]


def _ima_inventory(entry: Mapping[str, Any]) -> tuple[list[str], bool] | None:
    """List a connected Tencent IMA library through its own browse API."""
    from deeptutor.services.rag.pipelines.ima.inventory import read_inventory

    inventory = read_inventory(entry)
    if inventory is None:
        return None
    return list(inventory.documents), inventory.complete


# Connected KB types whose inventory is readable over their API. Imported lazily
# inside each reader so this module stays free of service-layer imports.
_REMOTE_INVENTORY_READERS: dict[str, RemoteInventoryReader] = {
    IMA_KB_TYPE: _ima_inventory,
}


@dataclass(frozen=True)
class KbDocument:
    """One document in a knowledge base."""

    name: str
    """POSIX path relative to the KB's document root (folders included)."""

    size: int
    """Size in bytes, or ``0`` when the file could not be stat'ed."""


@dataclass(frozen=True)
class KbManifest:
    """What one knowledge base actually contains, as facts rather than passages."""

    name: str
    provider: str = ""
    status: str = ""
    kb_type: str = ""
    total: int = 0
    """Documents in the KB — always the full count, ignoring ``pattern``."""

    matched: int = 0
    """Documents matching ``pattern`` (equal to ``total`` when unfiltered)."""

    documents: tuple[KbDocument, ...] = ()
    """The matching documents, truncated to the caller's limit."""

    pattern: str = ""
    unavailable: str = ""
    """Reason code from this module's ``UNAVAILABLE_*`` set; ``""`` when listable."""

    total_is_lower_bound: bool = False
    """True when a bounded remote listing stopped early — ``total`` is "at least"."""

    @property
    def enumerable(self) -> bool:
        return not self.unavailable

    @property
    def omitted(self) -> int:
        """Matching documents beyond the truncation limit."""
        return max(0, self.matched - len(self.documents))


def iter_kb_documents(root: Path) -> Iterator[Path]:
    """Yield the documents under ``root``, recursing into folders.

    Order is a depth-first walk with every level sorted — a folder's own files
    before its subfolders — so a truncated listing always shows the top of the
    tree and repeated calls agree.

    A *document* is a non-hidden regular file. Hidden entries (``.DS_Store``,
    ``.obsidian/``) are OS/editor bookkeeping rather than anything the user
    added, and a manifest that counts ``.DS_Store`` as a document is simply
    wrong — so they are skipped at every level. Symlinked directories are not
    followed, so a linked folder pointing into itself cannot loop.

    This is the canonical definition of "a document in a KB":
    :meth:`KnowledgeBaseManager.get_info`'s ``raw_documents`` statistic reads it
    too. The ``GET /knowledge/{kb}/files`` endpoint is a different thing — a
    directory browser that also reports folders, for the KB file-manager UI.
    """
    if not root.is_dir():
        return
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(name for name in dirnames if not name.startswith("."))
        current = Path(dirpath)
        for filename in sorted(filenames):
            if filename.startswith("."):
                continue
            path = current / filename
            if path.is_file():
                yield path


def document_root(kb_dir: Path, entry: Mapping[str, Any]) -> Path | None:
    """Where ``entry``'s documents live on this machine, or ``None`` if nowhere.

    Ordinary indexed KBs own ``<kb_dir>/raw``. A connected KB that points at a
    real folder (``linked``, ``obsidian``) is enumerated in place. A remote
    LightRAG server and a connected subagent have no local document set at all.
    """
    external = external_root_of(entry)
    if external:
        return Path(str(external)).expanduser()
    if str(entry.get("type") or "").strip() in _NON_DOCUMENT_KB_TYPES:
        return None
    return kb_dir / "raw"


def build_manifest(
    *,
    name: str,
    kb_dir: Path,
    entry: Mapping[str, Any] | None = None,
    limit: int = MANIFEST_NOTE_LIMIT,
    pattern: str = "",
) -> KbManifest:
    """Read ``name``'s document inventory off disk.

    ``entry`` is the KB's ``kb_config.json`` record (provider / status / type);
    it is read but never trusted for counts, which come from the filesystem.
    ``pattern`` filters by name — a glob when it contains wildcards, otherwise a
    case-insensitive substring. Only the retained documents are stat'ed, so a
    large KB costs one directory walk rather than thousands of syscalls.
    """
    record: Mapping[str, Any] = entry or {}
    kb_type = str(record.get("type") or "").strip()
    manifest_fields: dict[str, Any] = {
        "name": name,
        "provider": str(record.get("rag_provider") or "").strip(),
        "status": str(record.get("status") or "").strip(),
        "kb_type": kb_type,
        "pattern": pattern.strip(),
    }

    reader = _REMOTE_INVENTORY_READERS.get(kb_type)
    if reader is not None:
        return _remote_manifest(manifest_fields, record, reader=reader, limit=limit)

    root = document_root(kb_dir, record)
    if root is None:
        return KbManifest(**manifest_fields, unavailable=_NON_DOCUMENT_KB_TYPES[kb_type])
    if not root.is_dir():
        # An external folder that moved, or a KB whose indexing never got as far
        # as creating ``raw/``. Either way the document set is unknown, not empty.
        return KbManifest(**manifest_fields, unavailable=UNAVAILABLE_MISSING)

    all_names = [path.relative_to(root).as_posix() for path in iter_kb_documents(root)]
    matched_names = _filter_names(all_names, manifest_fields["pattern"])
    kept = matched_names[: max(0, limit)]
    return KbManifest(
        **manifest_fields,
        total=len(all_names),
        matched=len(matched_names),
        documents=tuple(KbDocument(name=rel, size=_size_of(root / rel)) for rel in kept),
    )


def _remote_manifest(
    fields: dict[str, Any],
    entry: Mapping[str, Any],
    *,
    reader: RemoteInventoryReader,
    limit: int,
) -> KbManifest:
    """Build a manifest from a connected service's own document listing.

    Failing to reach the service is reported as non-enumerable rather than as an
    empty KB — the same distinction the local path draws for a missing folder.
    Sizes are unknown over an API, so documents carry ``0`` and the renderers
    omit the size rather than printing a misleading "0 B".
    """
    try:
        listing = reader(entry)
    except Exception:
        listing = None
    if listing is None:
        return KbManifest(**fields, unavailable=UNAVAILABLE_REMOTE)

    names, complete = listing
    matched_names = _filter_names(names, fields["pattern"])
    kept = matched_names[: max(0, limit)]
    return KbManifest(
        **fields,
        total=len(names),
        matched=len(matched_names),
        documents=tuple(KbDocument(name=name, size=0) for name in kept),
        total_is_lower_bound=not complete,
    )


def _filter_names(names: Sequence[str], pattern: str) -> list[str]:
    if not pattern:
        return list(names)
    if any(char in pattern for char in "*?["):
        lowered = pattern.lower()
        return [
            name
            for name in names
            if fnmatch.fnmatch(name.lower(), lowered)
            or fnmatch.fnmatch(name.rsplit("/", 1)[-1].lower(), lowered)
        ]
    needle = pattern.lower()
    return [name for name in names if needle in name.lower()]


def _size_of(path: Path) -> int:
    try:
        return path.stat().st_size
    except OSError:
        return 0


# ---------------------------------------------------------------------------
# Rendering. Localised here (not by the caller) so the system-prompt manifest
# and the tool report describe the same facts in the same words.
# ---------------------------------------------------------------------------

_STATUS_LABELS: dict[str, dict[str, str]] = {
    "en": {
        "ready": "index ready",
        "needs_reindex": "needs reindexing, retrieval may be incomplete",
        "processing": "still indexing, retrieval may be incomplete",
        "initializing": "still indexing, retrieval may be incomplete",
        "error": "indexing failed, retrieval may be unavailable",
    },
    "zh": {
        "ready": "索引就绪",
        "needs_reindex": "需要重建索引，检索结果可能不完整",
        "processing": "正在索引，检索结果可能不完整",
        "initializing": "正在索引，检索结果可能不完整",
        "error": "索引失败，检索可能不可用",
    },
}

# Complete sentences, so the manifest note and the tool report can share one
# wording instead of each phrasing the same fact its own way.
_UNAVAILABLE_LABELS: dict[str, dict[str, str]] = {
    "en": {
        UNAVAILABLE_REMOTE: "Hosted on a remote server; its document list cannot be read.",
        UNAVAILABLE_AGENT: "A connected agent, not a document collection.",
        UNAVAILABLE_MISSING: (
            "Its document folder cannot be read right now — it may still be "
            "under construction, or be an external folder that has moved."
        ),
    },
    "zh": {
        UNAVAILABLE_REMOTE: "由远端服务器托管，无法读取文档清单。",
        UNAVAILABLE_AGENT: "是连接的智能体，不是文档集合。",
        UNAVAILABLE_MISSING: "当前读不到它的文档目录——可能仍在创建中，也可能是外部文件夹已移动。",
    },
}

_NOTE_TEXT: dict[str, dict[str, str]] = {
    "en": {
        "header": (
            "[Knowledge Base Inventory]\n"
            "What the attached knowledge bases actually contain, read from the "
            "knowledge bases themselves."
        ),
        "empty": "no documents yet",
        "total": "{count} document{plural}",
        "omitted": "and {count} more, use kb_files for the full list",
        "authority": (
            "Answer questions about document counts, file names, and whether a "
            "given file is present from this inventory — it is authoritative. "
            "Retrieved passages only show what a search happened to match and "
            "must never be used to infer how many documents a knowledge base "
            "holds or whether one exists in it. Call kb_files for the full list "
            "or to filter by name."
        ),
    },
    "zh": {
        "header": "[知识库清单]\n以下是已挂载知识库的真实文档构成，直接读取自各知识库本身。",
        "empty": "暂无文档",
        "total": "共 {count} 个文档",
        "omitted": "另有 {count} 个未列出，可用 kb_files 查看完整清单",
        "authority": (
            "回答文档数量、文件名、某个文件是否存在这类问题时，一律以本清单为准，"
            "它是权威事实。检索到的片段只代表某次搜索命中的内容，"
            "绝不能用来推断知识库有多少文档、或某个文档是否存在。"
            "需要完整清单或按名称筛选时，调用 kb_files。"
        ),
    },
}

_REPORT_TEXT: dict[str, dict[str, str]] = {
    "en": {
        "heading": 'Knowledge base "{name}"{qualifier}: {total} document{plural}.',
        "empty": 'Knowledge base "{name}"{qualifier} holds no documents.',
        "unavailable": 'Knowledge base "{name}": {reason}',
        "matched": 'Matching "{pattern}": {count}.',
        "no_match": 'No document name matches "{pattern}".',
        "omitted": "Showing the first {shown}; {omitted} more not listed "
        "(narrow with pattern, or raise limit).",
    },
    "zh": {
        "heading": "知识库「{name}」{qualifier}共 {total} 个文档。",
        "empty": "知识库「{name}」{qualifier}暂无文档。",
        "unavailable": "知识库「{name}」：{reason}",
        "matched": "匹配「{pattern}」的有 {count} 个。",
        "no_match": "没有文档名匹配「{pattern}」。",
        "omitted": "以下列出前 {shown} 个，另有 {omitted} 个未列出（可用 pattern 缩小范围或提高 limit）。",
    },
}


def _lang(language: str) -> str:
    return "zh" if str(language or "en").lower().startswith("zh") else "en"


def _colon(language: str) -> str:
    return "：" if language == "zh" else ": "


def _total_label(manifest: KbManifest, text: Mapping[str, str]) -> str:
    """The document count, marked as a lower bound when the listing was bounded."""
    count = f"{manifest.total}+" if manifest.total_is_lower_bound else str(manifest.total)
    return text["total"].format(count=count, plural="" if manifest.total == 1 else "s")


def _total_number(manifest: KbManifest) -> str:
    return f"{manifest.total}+" if manifest.total_is_lower_bound else str(manifest.total)


def _qualifier(manifest: KbManifest, language: str) -> str:
    """Parenthesised provider + index status, e.g. ``(llamaindex, index ready)``."""
    parts = [part for part in (manifest.provider, _status_label(manifest, language)) if part]
    if not parts:
        return ""
    return f"（{'，'.join(parts)}）" if language == "zh" else f" ({', '.join(parts)})"


def _status_label(manifest: KbManifest, language: str) -> str:
    return _STATUS_LABELS[language].get(manifest.status, "")


def render_manifest_note(manifests: Sequence[KbManifest], *, language: str) -> str:
    """The system-prompt block: one line per KB, plus the authority rule.

    Empty when there is nothing to describe, so the caller can concatenate it
    unconditionally.
    """
    if not manifests:
        return ""
    language = _lang(language)
    text = _NOTE_TEXT[language]
    lines = [f"- {_note_line(manifest, language)}" for manifest in manifests]
    return "\n".join([text["header"], *lines, text["authority"]])


def _note_line(manifest: KbManifest, language: str) -> str:
    text = _NOTE_TEXT[language]
    head = f"{manifest.name}{_qualifier(manifest, language)}{_colon(language)}"
    if not manifest.enumerable:
        return f"{head}{_UNAVAILABLE_LABELS[language][manifest.unavailable]}"
    if not manifest.total:
        return f"{head}{text['empty']}"
    listed = "; ".join(document.name for document in manifest.documents)
    if manifest.omitted:
        tail = text["omitted"].format(count=manifest.omitted)
        listed = f"{listed}（{tail}）" if language == "zh" else f"{listed} ({tail})"
    return f"{head}{_total_label(manifest, text)} — {listed}"


def render_manifest_report(manifest: KbManifest, *, language: str) -> str:
    """The ``kb_files`` tool's answer for one knowledge base."""
    language = _lang(language)
    text = _REPORT_TEXT[language]
    qualifier = _qualifier(manifest, language)
    if not manifest.enumerable:
        reason = _UNAVAILABLE_LABELS[language][manifest.unavailable]
        return text["unavailable"].format(name=manifest.name, reason=reason)
    if not manifest.total:
        return text["empty"].format(name=manifest.name, qualifier=qualifier)

    lines = [
        text["heading"].format(
            name=manifest.name,
            qualifier=qualifier,
            total=_total_number(manifest),
            plural="" if manifest.total == 1 else "s",
        )
    ]
    if manifest.pattern:
        if not manifest.matched:
            lines.append(text["no_match"].format(pattern=manifest.pattern))
            return "\n".join(lines)
        lines.append(text["matched"].format(pattern=manifest.pattern, count=manifest.matched))
    if manifest.omitted:
        lines.append(
            text["omitted"].format(shown=len(manifest.documents), omitted=manifest.omitted)
        )
    lines.extend(
        f"{index}. {document.name}{_size_suffix(document.size)}"
        for index, document in enumerate(manifest.documents, start=1)
    )
    return "\n".join(lines)


def _size_suffix(size: int) -> str:
    """`` (1.2 MB)``, or nothing when the size is unknown (remote listings)."""
    return f" ({_human_size(size)})" if size > 0 else ""


def _human_size(size: int) -> str:
    if size < 1024:
        return f"{size} B"
    value = float(size)
    for unit in ("KB", "MB", "GB"):
        value /= 1024
        if value < 1024:
            return f"{value:.1f} {unit}"
    return f"{value:.1f} TB"


__all__ = [
    "KB_FILES_DEFAULT_LIMIT",
    "KB_FILES_MAX_LIMIT",
    "MANIFEST_NOTE_LIMIT",
    "UNAVAILABLE_AGENT",
    "UNAVAILABLE_MISSING",
    "UNAVAILABLE_REMOTE",
    "KbDocument",
    "KbManifest",
    "build_manifest",
    "document_root",
    "iter_kb_documents",
    "render_manifest_note",
    "render_manifest_report",
]
