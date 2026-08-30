"""Turn reading annotations into durable Notebook and Mastery sources."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Sequence

from deeptutor.reading.catalog_store import ReadingCatalogStore
from deeptutor.reading.models import ReadingError
from deeptutor.reading.store import ReadingStore


@dataclass(frozen=True, slots=True)
class OrganizedReadingNotes:
    workspace_id: str
    title: str
    markdown: str
    annotation_count: int
    material_ids: tuple[str, ...]

    def to_dict(self) -> dict[str, Any]:
        return {
            "workspace_id": self.workspace_id,
            "title": self.title,
            "markdown": self.markdown,
            "annotation_count": self.annotation_count,
            "material_ids": list(self.material_ids),
        }


def organize_workspace_notes(
    workspace_id: str,
    *,
    material_ids: Sequence[str] = (),
    catalog: ReadingCatalogStore | None = None,
    reading_store: ReadingStore | None = None,
) -> OrganizedReadingNotes:
    catalog = catalog or ReadingCatalogStore()
    reading_store = reading_store or ReadingStore(catalog.root)
    workspace = catalog.get_workspace(workspace_id)
    if workspace is None:
        raise ReadingError(f"reading workspace {workspace_id!r} not found")
    allowed = {tab.material.material_id for tab in workspace.tabs}
    selected = list(dict.fromkeys(material_ids)) if material_ids else list(allowed)
    if any(material_id not in allowed for material_id in selected):
        raise ReadingError("note source does not belong to this reading workspace")

    tabs_by_id = {tab.material.material_id: tab for tab in workspace.tabs}
    lines = [f"# {workspace.title}", "", "Organized from Immersive Reading."]
    annotation_count = 0
    for material_id in selected:
        tab = tabs_by_id[material_id]
        lines.extend(("", f"## {tab.material.title}"))
        annotations = reading_store.annotations(material_id)
        if not annotations:
            lines.extend(("", "_No highlights or notes captured yet._"))
            continue
        outline = reading_store.outline(material_id)
        headings = {entry.locator: entry.title for entry in outline}
        current_locator = 0
        for annotation in annotations:
            annotation_count += 1
            if annotation.locator != current_locator:
                current_locator = annotation.locator
                label = (
                    headings.get(current_locator)
                    or f"{reading_store.manifest(material_id).unit.title()} {current_locator}"
                )
                lines.extend(("", f"### {label}"))
            if annotation.quote:
                lines.extend(("", f"> {annotation.quote.strip()}"))
            if annotation.note:
                lines.extend(("", annotation.note.strip()))
            lines.append(
                f"_Source: {tab.material.title}, locator {annotation.locator}; "
                f"annotation `{annotation.annotation_id}`_"
            )
    return OrganizedReadingNotes(
        workspace_id=workspace_id,
        title=workspace.title,
        markdown="\n".join(lines).strip() + "\n",
        annotation_count=annotation_count,
        material_ids=tuple(selected),
    )


def send_workspace_to_notebook(
    workspace_id: str,
    notebook_ids: Sequence[str],
    *,
    material_ids: Sequence[str] = (),
    title: str = "",
    summary: str = "",
    catalog: ReadingCatalogStore | None = None,
    reading_store: ReadingStore | None = None,
    notebook_manager=None,
) -> dict[str, Any]:
    notes = organize_workspace_notes(
        workspace_id,
        material_ids=material_ids,
        catalog=catalog,
        reading_store=reading_store,
    )
    if not notebook_ids:
        raise ReadingError("choose at least one notebook")
    if notebook_manager is None:
        from deeptutor.services.notebook import notebook_manager
    result = notebook_manager.add_record(
        notebook_ids=list(notebook_ids),
        record_type="reading",
        title=(title or notes.title).strip(),
        summary=summary.strip(),
        user_query="Organize my Immersive Reading notes",
        output=notes.markdown,
        metadata={
            "reading_workspace_id": workspace_id,
            "reading_material_ids": list(notes.material_ids),
            "annotation_count": notes.annotation_count,
        },
    )
    if not result.get("added_to_notebooks"):
        raise ReadingError("none of the selected notebooks exists")
    return {**result, "notes": notes.to_dict()}


def mastery_source_records(
    workspace_id: str,
    *,
    material_ids: Sequence[str] = (),
    catalog: ReadingCatalogStore | None = None,
    reading_store: ReadingStore | None = None,
    max_chars_per_material: int = 12_000,
) -> list[dict[str, str]]:
    """Build bounded, source-labelled inputs for Mastery Path generation."""
    catalog = catalog or ReadingCatalogStore()
    reading_store = reading_store or ReadingStore(catalog.root)
    workspace = catalog.get_workspace(workspace_id)
    if workspace is None:
        raise ReadingError(f"reading workspace {workspace_id!r} not found")
    allowed = {tab.material.material_id for tab in workspace.tabs}
    selected = (
        list(dict.fromkeys(material_ids))
        if material_ids
        else [tab.material.material_id for tab in workspace.tabs]
    )
    if any(material_id not in allowed for material_id in selected):
        raise ReadingError("Mastery source does not belong to this reading workspace")

    tabs = {tab.material.material_id: tab for tab in workspace.tabs}
    records: list[dict[str, str]] = []
    for material_id in selected[:20]:
        manifest = reading_store.manifest(material_id)
        chunks: list[str] = []
        remaining = max(500, max_chars_per_material)
        for locator, text in reading_store.iter_units(material_id):
            block = f"[{manifest.unit} {locator}] {text.strip()}"
            chunks.append(block[:remaining])
            remaining -= len(chunks[-1])
            if remaining <= 0:
                break
        records.append(
            {
                "id": material_id,
                "type": "reading",
                "title": tabs[material_id].material.title,
                "output": "\n\n".join(chunks),
            }
        )
    return records


__all__ = [
    "OrganizedReadingNotes",
    "mastery_source_records",
    "organize_workspace_notes",
    "send_workspace_to_notebook",
]
