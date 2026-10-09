"""Course outline for Guided practice. File rows are stable; model rows are grounded."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from deeptutor.learning.sequence.schema import SequenceError, evidence_key

_DOC_SUFFIXES = frozenset(
    {
        ".pdf",
        ".md",
        ".markdown",
        ".txt",
        ".docx",
        ".pptx",
        ".html",
        ".htm",
        ".tex",
        ".ipynb",
        ".epub",
    }
)
_MAX_FILE_MODULES = 36


def _relative_posix(path: str) -> str | None:
    rel = path.replace("\\", "/").strip()
    if not rel or rel.startswith("/"):
        return None
    parts: list[str] = []
    for part in rel.split("/"):
        if part in {"", "."}:
            continue
        if part == ".." or part.startswith("."):
            return None
        parts.append(part)
    if not parts:
        return None
    return "/".join(parts)


def _label(value: Any, limit: int) -> str:
    if not isinstance(value, str):
        return ""
    return " ".join(value.split())[:limit]


def modules_from_files(paths: list[str]) -> list[dict[str, str]]:
    """Group raw documents into at most 36 modules, sorted by relative path."""
    chosen: list[tuple[str, dict[str, str]]] = []
    seen: set[str] = set()
    for raw in paths:
        if not isinstance(raw, str):
            continue
        posix = _relative_posix(raw)
        if posix is None or posix in seen:
            continue
        if Path(posix).suffix.casefold() not in _DOC_SUFFIXES:
            continue
        label = _label(Path(posix).stem.replace("_", " ").replace("-", " "), 200)
        if not label:
            continue
        seen.add(posix)
        parts = posix.split("/")
        chosen.append(
            (
                posix,
                {
                    "id": "m_" + hashlib.sha256(posix.encode("utf-8")).hexdigest()[:12],
                    "category": parts[0] if len(parts) > 1 else "",
                    "name": label,
                    "topic": label,
                },
            )
        )
    chosen.sort(key=lambda item: item[0])
    return [module for _path, module in chosen[:_MAX_FILE_MODULES]]


def list_kb_documents(kb_name: str) -> list[str]:
    """Relative document paths in the knowledge base, or [] when it has no raw files."""
    raw_dir = _raw_dir(kb_name)
    if raw_dir is None or not raw_dir.is_dir():
        return []
    root = raw_dir.resolve()
    found: list[str] = []
    for entry in raw_dir.rglob("*"):
        if not entry.is_file():
            continue
        try:
            entry.resolve().relative_to(root)
            rel = entry.relative_to(raw_dir).as_posix()
        except (OSError, ValueError):
            continue
        if _relative_posix(rel) is None:
            continue
        if entry.suffix.casefold() not in _DOC_SUFFIXES:
            continue
        found.append(rel)
    found.sort()
    return found


def _raw_dir(kb_name: str) -> Path | None:
    try:
        from deeptutor.knowledge.kb_types import supports_local_raw_files
        from deeptutor.multi_user.knowledge_access import manager_for_resource, resolve_kb

        resource = resolve_kb(kb_name)
        manager = manager_for_resource(resource)
        if not supports_local_raw_files(manager.get_kb_entry(resource.name)):
            return None
        return manager.get_knowledge_base_path(resource.name) / "raw"
    except Exception:
        return None


def grounded_modules(data: Any, corpus: str) -> list[dict[str, str]]:
    """Accept 3 to 12 modules. A quote of 8+ characters must be in the corpus."""
    if not isinstance(data, dict):
        raise SequenceError(422, "The model did not return a course outline.")
    modules = data.get("modules")
    if not isinstance(modules, list) or not 3 <= len(modules) <= 12:
        raise SequenceError(422, "The model did not return a course outline.")
    corpus_key = evidence_key(corpus)
    rows: list[dict[str, str]] = []
    for item in modules:
        if not isinstance(item, dict):
            raise SequenceError(422, "The model did not return a course outline.")
        category = _label(item.get("category"), 80)
        name = _label(item.get("name"), 160)
        topic = _label(item.get("topic"), 200)
        if not category or not name or not topic:
            raise SequenceError(422, "The model did not return a course outline.")
        evidence = item.get("evidence") if isinstance(item.get("evidence"), str) else ""
        quote = evidence_key(evidence)
        if len(quote) < 8 or quote not in corpus_key:
            raise SequenceError(422, "A module is not supported by the retrieved material.")
        rows.append({"category": category, "name": name, "topic": topic})
    return rows
