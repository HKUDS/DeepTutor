"""Line-numbered view of a memory document + line-level edit ops.

The audit / dedup modes ask the LLM to operate on a memory document
the same way an IDE assistant operates on source code: it sees
numbered lines and emits structured edits referencing those numbers.

To keep the document's invariants intact, the LLM only ever sees a
**sanitized** view — section headers (``## name``) and entry bullets
(``- text [^m_xxx]``). The footnote block is hidden and rebuilt by
:func:`apply_edits` from the surviving entries' refs.

Editing model
-------------
Three op types: ``ReplaceLineOp``, ``DeleteLinesOp``, ``InsertAfterOp``.
Apply in **descending line order** so earlier lines never shift under
later edits. Each op carries a free-form ``reason`` for observability;
audit/dedup prompts require it. Refs are mandatory on replace / insert
of an entry (validated by the runtime).

Public API
----------
* :func:`render_view` — turn a :class:`Document` into a list of numbered
  :class:`Line` rows + lookup tables.
* :func:`apply_edits` — apply a batch of edits to a document; pure
  function (returns a new document) so callers can preview without
  mutating shared state.
* :func:`parse_edits_payload` — tolerant JSON → typed edit list parser.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import json
import logging
import re
from typing import Iterable, Literal, Union

from deeptutor.services.memory.document import Document, Entry
from deeptutor.services.memory.ids import is_entry_id, new_entry_id

logger = logging.getLogger(__name__)

LineKind = Literal["title", "blank", "section", "bullet"]


@dataclass(frozen=True)
class Line:
    number: int  # 1-based, matches what the LLM sees
    kind: LineKind
    text: str  # rendered text (no leading "n: ")
    entry_id: str | None = None  # for bullet lines, the m_xxx id
    section: str | None = None  # for bullet lines, owning section name


@dataclass(frozen=True)
class LineView:
    """Snapshot of the sanitized document seen by audit / dedup LLMs."""

    lines: list[Line]
    entry_by_id: dict[str, Entry]
    entries_in_order: list[Entry]

    def render(self, *, with_numbers: bool = True) -> str:
        if with_numbers:
            width = max(2, len(str(len(self.lines))))
            return "\n".join(f"{line.number:>{width}}: {line.text}" for line in self.lines)
        return "\n".join(line.text for line in self.lines)

    def line(self, number: int) -> Line | None:
        return self.lines[number - 1] if 1 <= number <= len(self.lines) else None


# ── Edit ops ────────────────────────────────────────────────────────────


@dataclass(frozen=True)
class ReplaceLineOp:
    line: int
    new_text: str
    refs: list[str]
    reason: str = ""
    op: Literal["replace"] = "replace"


@dataclass(frozen=True)
class DeleteLinesOp:
    line_start: int
    line_end: int  # inclusive
    reason: str = ""
    op: Literal["delete"] = "delete"


@dataclass(frozen=True)
class InsertAfterOp:
    after_line: int
    text: str
    refs: list[str]
    # ``section`` is optional: when None, the engine uses the section
    # containing ``after_line``. If after_line is 0 (top-of-doc) or
    # points at a title/blank, section MUST be provided.
    section: str | None = None
    reason: str = ""
    op: Literal["insert"] = "insert"


Edit = Union[ReplaceLineOp, DeleteLinesOp, InsertAfterOp]


@dataclass
class EditResult:
    op: Edit
    status: Literal["applied", "rejected"]
    detail: str = ""


@dataclass
class EditReport:
    applied: list[EditResult] = field(default_factory=list)
    rejected: list[EditResult] = field(default_factory=list)

    @property
    def all_results(self) -> list[EditResult]:
        return self.applied + self.rejected


# ── Render: Document → LineView ─────────────────────────────────────────


def render_view(doc: Document) -> LineView:
    """Produce the numbered view the LLM operates on."""
    lines: list[Line] = []
    entries_in_order: list[Entry] = []
    entry_by_id: dict[str, Entry] = {}

    if doc.title:
        lines.append(Line(number=len(lines) + 1, kind="title", text=f"# {doc.title}"))
        lines.append(Line(number=len(lines) + 1, kind="blank", text=""))

    for section_name, entries in doc.sections:
        if not entries:
            continue
        lines.append(Line(number=len(lines) + 1, kind="section", text=f"## {section_name}"))
        for entry in entries:
            lines.append(
                Line(
                    number=len(lines) + 1,
                    kind="bullet",
                    text=f"- {entry.text} [^{entry.id}]",
                    entry_id=entry.id,
                    section=section_name,
                )
            )
            entries_in_order.append(entry)
            entry_by_id[entry.id] = entry
        lines.append(Line(number=len(lines) + 1, kind="blank", text=""))

    # Strip the trailing blank so the rendered view doesn't end with an
    # empty line — keeps line counts predictable.
    while lines and lines[-1].kind == "blank":
        lines.pop()

    return LineView(
        lines=lines,
        entry_by_id=entry_by_id,
        entries_in_order=entries_in_order,
    )


# ── Apply edits ─────────────────────────────────────────────────────────


def apply_edits(doc: Document, edits: Iterable[Edit]) -> tuple[Document, EditReport]:
    """Apply a batch of edits, in reverse line order, to a fresh copy.

    Returns ``(new_doc, report)``. ``new_doc`` is always returned; if
    any edit was rejected, those are captured in ``report.rejected`` and
    the rest are still applied. The caller decides what to do with a
    partial-success batch (audit/dedup just write the partial result).

    Reverse order avoids line-number drift: removing line 5 does not
    affect the meaning of "line 3" since 3 < 5 and we process 5 first.
    """
    view = render_view(doc)
    edit_list = _sort_reverse(list(edits))
    report = EditReport()

    # Work on a deep-ish copy: the entry list per section is fresh, but
    # Entry instances themselves are reused (and possibly mutated in
    # place by replace).
    new_doc = Document(
        title=doc.title,
        sections=[(name, list(entries)) for name, entries in doc.sections],
    )

    for edit in edit_list:
        try:
            detail = _apply_one(edit, new_doc, view)
            report.applied.append(EditResult(op=edit, status="applied", detail=detail))
        except _Reject as exc:
            logger.warning("line-edit rejected: %s — %s", _short(edit), exc)
            report.rejected.append(EditResult(op=edit, status="rejected", detail=str(exc)))

    _drop_empty_sections(new_doc)
    return new_doc, report


class _Reject(Exception):
    """Internal sentinel — signals one edit is unsafe; siblings still apply."""


def _apply_one(edit: Edit, doc: Document, view: LineView) -> str:
    if isinstance(edit, ReplaceLineOp):
        return _apply_replace(edit, doc, view)
    if isinstance(edit, DeleteLinesOp):
        return _apply_delete(edit, doc, view)
    if isinstance(edit, InsertAfterOp):
        return _apply_insert(edit, doc, view)
    raise _Reject(f"unknown edit type {type(edit).__name__}")


def _apply_replace(edit: ReplaceLineOp, doc: Document, view: LineView) -> str:
    line = view.line(edit.line)
    if line is None:
        raise _Reject(f"line {edit.line} out of range")
    if line.kind != "bullet" or not line.entry_id:
        raise _Reject(f"line {edit.line} is not an editable entry")
    if not edit.new_text.strip():
        raise _Reject("new_text empty")
    if not edit.refs:
        raise _Reject("replace requires non-empty refs")

    entry = _entry_in_doc(doc, line.entry_id)
    if entry is None:
        raise _Reject(f"entry {line.entry_id} not found in current doc")
    entry.text = edit.new_text.strip()
    entry.refs = list(edit.refs)
    return f"replace {entry.id}"


def _apply_delete(edit: DeleteLinesOp, doc: Document, view: LineView) -> str:
    if edit.line_end < edit.line_start:
        raise _Reject(f"line_end {edit.line_end} < line_start {edit.line_start}")
    ids_to_drop: set[str] = set()
    for n in range(edit.line_start, edit.line_end + 1):
        line = view.line(n)
        if line is None or line.kind != "bullet" or not line.entry_id:
            continue  # section/blank lines are removed only as a side-effect of empties
        ids_to_drop.add(line.entry_id)
    if not ids_to_drop:
        raise _Reject("range covers no entries")
    for _name, entries in doc.sections:
        entries[:] = [e for e in entries if e.id not in ids_to_drop]
    return f"deleted {len(ids_to_drop)} entries"


def _apply_insert(edit: InsertAfterOp, doc: Document, view: LineView) -> str:
    if not edit.text.strip():
        raise _Reject("insert text empty")
    if not edit.refs:
        raise _Reject("insert requires non-empty refs")

    section = edit.section
    if section is None:
        if edit.after_line < 1 or edit.after_line > len(view.lines):
            raise _Reject(
                "after_line out of range; for top-of-doc insert provide `section` explicitly"
            )
        anchor = view.line(edit.after_line)
        section = anchor.section if anchor and anchor.section else None
        if section is None and anchor and anchor.kind == "section":
            section = anchor.text.lstrip("# ").strip()
        if section is None:
            raise _Reject("no section context for insert; supply `section`")

    entry = Entry(
        id=new_entry_id(),
        section=section,
        text=edit.text.strip(),
        refs=list(edit.refs),
    )
    target = _section_entries(doc, section)
    # When inserting after a bullet inside an existing section, honor
    # the local position; otherwise append at end.
    anchor = view.line(edit.after_line) if 1 <= edit.after_line <= len(view.lines) else None
    if anchor and anchor.kind == "bullet" and anchor.section == section and anchor.entry_id:
        for idx, existing in enumerate(target):
            if existing.id == anchor.entry_id:
                target.insert(idx + 1, entry)
                break
        else:
            target.append(entry)
    else:
        target.append(entry)
    return f"inserted {entry.id} into {section!r}"


# ── Parse edits payload ─────────────────────────────────────────────────


_REF_WRAPPER_CHARS = "`[](){}<>^ \t\n\r"
_ENTRY_ID_REF_RE = re.compile(r"^m_[0-9A-HJKMNP-TV-Z]{26}$")


def _clean_refs(raw_refs: object, *, layer: str | None) -> list[str]:
    """Strip wrappers + drop garbage refs from one ``refs`` array.

    Two cleanups, in order:

    1. **Wrapper strip**. The audit / dedup line-numbered view shows each
       bullet as ``- text [^m_xxx]``. LLMs sometimes copy the marker
       (``^m_xxx``) wholesale into the new refs array — caret and all.
       Strip ``` ` [ ] ( ) { } < > ^ ``` plus whitespace from both sides.

    2. **Layer-shape filter**. After stripping, an L2 doc whose refs
       still look like ``m_<ULID>`` (an entry id from the line view) is
       almost certainly hallucinated — real L2 refs are ``surface:id``.
       Drop them. L3 ref shape *is* ``m_<ULID>`` so the filter is a
       no-op there.
    """
    if not isinstance(raw_refs, list):
        return []
    out: list[str] = []
    for r in raw_refs:
        if not r:
            continue
        s = str(r).strip(_REF_WRAPPER_CHARS).strip()
        if not s:
            continue
        if layer == "L2" and _ENTRY_ID_REF_RE.match(s):
            continue
        out.append(s)
    return out


def parse_edits_payload(raw: str, *, layer: str | None = None) -> list[Edit]:
    """Tolerant JSON parse → list[Edit].

    Accepts ``{"edits": [...]}`` or a top-level ``[...]``. Each entry's
    ``op`` field discriminates the type. Unknown ops are dropped.

    ``layer`` (``"L2"`` / ``"L3"``) controls ref-shape filtering — see
    :func:`_clean_refs`. Omit it (or pass ``None``) when the caller
    can't or shouldn't filter by layer; refs are still stripped of
    wrapper characters.
    """
    snippet = _extract_json(raw)
    if snippet is None:
        return []
    try:
        data = json.loads(snippet)
    except json.JSONDecodeError:
        logger.warning("line-edit parse: malformed JSON")
        return []
    items = data.get("edits") if isinstance(data, dict) else data
    if not isinstance(items, list):
        return []

    edits: list[Edit] = []
    for raw_op in items:
        if not isinstance(raw_op, dict):
            continue
        kind = raw_op.get("op")
        try:
            if kind == "replace":
                edits.append(
                    ReplaceLineOp(
                        line=int(raw_op.get("line", 0)),
                        new_text=str(raw_op.get("new_text", "")).strip(),
                        refs=_clean_refs(raw_op.get("refs", []), layer=layer),
                        reason=str(raw_op.get("reason", "")).strip(),
                    )
                )
            elif kind == "delete":
                edits.append(
                    DeleteLinesOp(
                        line_start=int(raw_op.get("line_start", raw_op.get("line", 0))),
                        line_end=int(raw_op.get("line_end", raw_op.get("line", 0))),
                        reason=str(raw_op.get("reason", "")).strip(),
                    )
                )
            elif kind == "insert":
                section = raw_op.get("section")
                edits.append(
                    InsertAfterOp(
                        after_line=int(raw_op.get("after_line", 0)),
                        text=str(raw_op.get("text", "")).strip(),
                        refs=_clean_refs(raw_op.get("refs", []), layer=layer),
                        section=str(section).strip() if section else None,
                        reason=str(raw_op.get("reason", "")).strip(),
                    )
                )
        except (TypeError, ValueError):
            continue
    return edits


# ── Helpers ─────────────────────────────────────────────────────────────


def _sort_reverse(edits: list[Edit]) -> list[Edit]:
    def key(e: Edit) -> tuple[int, int]:
        if isinstance(e, ReplaceLineOp):
            return (e.line, 0)
        if isinstance(e, DeleteLinesOp):
            return (e.line_end, 1)  # delete sorts before insert at same line
        if isinstance(e, InsertAfterOp):
            return (e.after_line, 2)
        return (0, 9)

    return sorted(edits, key=key, reverse=True)


def _entry_in_doc(doc: Document, entry_id: str) -> Entry | None:
    if not is_entry_id(entry_id):
        return None
    for _section, entries in doc.sections:
        for entry in entries:
            if entry.id == entry_id:
                return entry
    return None


def _section_entries(doc: Document, name: str) -> list[Entry]:
    for section, entries in doc.sections:
        if section == name:
            return entries
    new_entries: list[Entry] = []
    doc.sections.append((name, new_entries))
    return new_entries


def _drop_empty_sections(doc: Document) -> None:
    doc.sections[:] = [(name, entries) for name, entries in doc.sections if entries]


def _short(edit: Edit) -> str:
    if isinstance(edit, ReplaceLineOp):
        return f"replace L{edit.line}"
    if isinstance(edit, DeleteLinesOp):
        return f"delete L{edit.line_start}-{edit.line_end}"
    if isinstance(edit, InsertAfterOp):
        return f"insert@L{edit.after_line}"
    return repr(edit)


_FENCE_RE = re.compile(r"^```[a-zA-Z]*\s*|\s*```$")


def _extract_json(raw: str) -> str | None:
    text = _FENCE_RE.sub("", raw.strip())
    # Find the outermost {...} or [...].
    obj_start = text.find("{")
    arr_start = text.find("[")
    if obj_start == -1 and arr_start == -1:
        return None
    if obj_start == -1:
        start = arr_start
    elif arr_start == -1:
        start = obj_start
    else:
        start = min(obj_start, arr_start)
    end_obj = text.rfind("}")
    end_arr = text.rfind("]")
    end = max(end_obj, end_arr)
    if end <= start:
        return None
    return text[start : end + 1]


__all__ = [
    "DeleteLinesOp",
    "Edit",
    "EditReport",
    "EditResult",
    "InsertAfterOp",
    "Line",
    "LineView",
    "ReplaceLineOp",
    "apply_edits",
    "parse_edits_payload",
    "render_view",
]
