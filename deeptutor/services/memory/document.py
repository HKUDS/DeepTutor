"""Markdown documents with footnote-style citations.

Each L2/L3 file is a markdown document of the form::

    # <Title>

    ## <section_a>
    - <text> [^1][^2] <!--m_xxx-->
    - <text> [^1] <!--m_yyy-->

    ## <section_b>
    - <text> [^3] <!--m_zzz-->

    ---

    [^1]: notebook:abc
    [^2]: chat:def
    [^3]: chat:ghi

Footnote labels are *integers* assigned per-document in first-appearance
order over the bullet stream. Two entries citing the same source share a
label, so duplicate footnote rows disappear from the rendered view.

The HTML comment after each bullet (``<!--m_xxx-->``) is the entry id
anchor. It survives round-trips and is used by audit / dedup line views
and by ``DELETE /entry/{id}``. Parser also accepts the *legacy* format
where the bullet ends in ``[^m_xxx]`` and footnote rows are
``[^m_xxx]: ref1, ref2`` — this lets pre-existing docs continue working
until the next save migrates them to the new layout.

Parsing and serialization are pure functions — no I/O, no LLM. The
round-trip ``serialize(parse(x))`` is idempotent for any document
produced by ``serialize``.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import re

_ENTRY_ID_RE = r"m_[0-9A-HJKMNP-TV-Z]{26}"

_TITLE_RE = re.compile(r"^#\s+(.+?)\s*$")
_SECTION_RE = re.compile(r"^##\s+(.+?)\s*$")

# New bullet:  "- text [^1], [^3] <!--m_xxx-->"
# Markers are optional (an entry may cite no refs); commas + whitespace
# between markers are tolerated so the rendered superscripts read
# ``¹, ³`` instead of the visually-merged ``¹³``.
_NEW_BULLET_RE = re.compile(
    rf"^\s*-\s+(?P<text>.*?)(?P<markers>(?:\s*,?\s*\[\^[^\]]+\])*)\s*<!--\s*(?P<id>{_ENTRY_ID_RE})\s*-->\s*$"
)
# Legacy bullet: "- text[^m_xxx]"
_OLD_BULLET_RE = re.compile(rf"^\s*-\s+(?P<text>.*?)\[\^(?P<id>{_ENTRY_ID_RE})\]\s*$")

# Legacy footnote def: "[^m_xxx]: ref1, ref2"
_OLD_FOOTNOTE_RE = re.compile(rf"^\[\^(?P<id>{_ENTRY_ID_RE})\]:\s*(?P<refs>.*?)\s*$")
# New footnote def: "[^1]: notebook:abc"   (label is non-m_xxx)
_NEW_FOOTNOTE_RE = re.compile(r"^\[\^(?P<label>[^\]]+)\]:\s*(?P<ref>.*?)\s*$")

_MARKER_RE = re.compile(r"\[\^([^\]]+)\]")


@dataclass
class Entry:
    id: str
    section: str
    text: str
    refs: list[str] = field(default_factory=list)


@dataclass
class Document:
    title: str = ""
    sections: list[tuple[str, list[Entry]]] = field(default_factory=list)

    def all_entries(self) -> list[Entry]:
        return [e for _, entries in self.sections for e in entries]

    def find(self, entry_id: str) -> Entry | None:
        for _, entries in self.sections:
            for entry in entries:
                if entry.id == entry_id:
                    return entry
        return None

    def section_entries(self, name: str) -> list[Entry]:
        """Return the entry list for ``name``, creating the section if absent."""
        for section, entries in self.sections:
            if section == name:
                return entries
        new_entries: list[Entry] = []
        self.sections.append((name, new_entries))
        return new_entries

    def remove(self, entry_id: str) -> bool:
        for _, entries in self.sections:
            for i, entry in enumerate(entries):
                if entry.id == entry_id:
                    del entries[i]
                    return True
        return False


def parse(md: str) -> Document:
    """Parse memory md in either the new (ref-keyed) or legacy (entry-keyed) format."""
    raw_lines = md.splitlines()

    # Pass 1 — collect every footnote definition. We accept BOTH:
    # * new ref-keyed: ``[^1]: notebook:abc``  → ref by label
    # * old entry-keyed: ``[^m_xxx]: r1, r2``  → refs by entry id
    refs_by_entry: dict[str, list[str]] = {}
    ref_by_label: dict[str, str] = {}
    for raw in raw_lines:
        line = raw.rstrip()
        m_old_fn = _OLD_FOOTNOTE_RE.match(line)
        if m_old_fn:
            refs_raw = m_old_fn.group("refs")
            refs_by_entry[m_old_fn.group("id")] = [
                r.strip() for r in refs_raw.split(",") if r.strip()
            ]
            continue
        m_new_fn = _NEW_FOOTNOTE_RE.match(line)
        if m_new_fn:
            label = m_new_fn.group("label")
            if label.startswith("m_"):
                # Skip — that was an entry-keyed row already handled above.
                continue
            ref_by_label[label] = m_new_fn.group("ref").strip()

    # Pass 2 — title, sections, bullets.
    doc = Document()
    current_entries: list[Entry] | None = None
    current_section: str | None = None
    for raw in raw_lines:
        line = raw.rstrip()

        if not doc.title:
            m_title = _TITLE_RE.match(line)
            if m_title:
                doc.title = m_title.group(1).strip()
                continue

        m_section = _SECTION_RE.match(line)
        if m_section:
            current_section = m_section.group(1).strip()
            current_entries = []
            doc.sections.append((current_section, current_entries))
            continue

        # New format first: bullet ends with HTML-comment entry-id anchor.
        m_new_b = _NEW_BULLET_RE.match(line)
        if m_new_b and current_entries is not None and current_section is not None:
            entry_id = m_new_b.group("id")
            text = m_new_b.group("text").rstrip()
            markers = _MARKER_RE.findall(m_new_b.group("markers") or "")
            entry_refs: list[str] = []
            for marker in markers:
                ref = ref_by_label.get(marker)
                if ref is not None and ref not in entry_refs:
                    entry_refs.append(ref)
            current_entries.append(
                Entry(id=entry_id, section=current_section, text=text, refs=entry_refs)
            )
            continue

        # Legacy bullet: refs come from refs_by_entry built in pass 1.
        m_old_b = _OLD_BULLET_RE.match(line)
        if m_old_b and current_entries is not None and current_section is not None:
            entry_id = m_old_b.group("id")
            text = m_old_b.group("text").strip()
            current_entries.append(
                Entry(
                    id=entry_id,
                    section=current_section,
                    text=text,
                    refs=list(refs_by_entry.get(entry_id, [])),
                )
            )
            continue

    return doc


def serialize(doc: Document) -> str:
    """Render the doc in the new consolidated, ref-keyed format.

    Every unique ref across all entries gets one footnote label, assigned
    in first-appearance order. Bullets cite their refs as ``[^1][^3]``
    inline. The entry id is preserved as a trailing HTML comment so the
    round-trip ``parse(serialize(d)) == d``.
    """
    # 1. Build the consolidated ref → label map in first-appearance order.
    ref_order: list[str] = []
    ref_to_label: dict[str, int] = {}
    for entry in doc.all_entries():
        for ref in entry.refs:
            if ref in ref_to_label:
                continue
            ref_to_label[ref] = len(ref_order) + 1
            ref_order.append(ref)

    lines: list[str] = []
    if doc.title:
        lines.append(f"# {doc.title}")
        lines.append("")

    for section, entries in doc.sections:
        if not entries:
            continue
        lines.append(f"## {section}")
        lines.append("")
        for entry in entries:
            # ``, ``-separate markers so the rendered superscripts read
            # "¹, ²" not "¹²" — important when the same bullet cites two
            # different sources.
            markers = ", ".join(f"[^{ref_to_label[r]}]" for r in entry.refs if r in ref_to_label)
            text = entry.text.rstrip()
            if markers:
                lines.append(f"- {text} {markers} <!--{entry.id}-->")
            else:
                lines.append(f"- {text} <!--{entry.id}-->")
        lines.append("")

    if ref_order:
        lines.append("---")
        lines.append("")
        for i, ref in enumerate(ref_order, start=1):
            lines.append(f"[^{i}]: {ref}")
        lines.append("")

    return "\n".join(lines).rstrip() + "\n"


__all__ = ["Document", "Entry", "parse", "serialize"]
