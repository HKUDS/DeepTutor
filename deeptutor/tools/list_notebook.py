"""List the user's notebooks or the records inside a single notebook.

Two modes, picked by whether ``notebook_id`` is supplied:

* **Index mode** (``notebook_id`` empty): list every notebook the
  active user owns — id, name, description, record count, last-updated.
  Equivalent to the sidebar view a human sees.
* **Drill-down mode** (``notebook_id`` supplied): list every record
  inside one notebook — record id, title, type, summary, created_at.
  Equivalent to opening a notebook and skimming entries.

The tool itself is stateless and synchronous; the chat pipeline auto-
mounts it only when the active user actually has notebooks, so empty
runs are impossible by construction. Output is markdown so the LLM can
quote the rendered list back to the user without reformatting.
"""

from __future__ import annotations

from dataclasses import dataclass
import datetime as _dt
import logging
from typing import Any

logger = logging.getLogger(__name__)

# Defensive ceilings so a freak case (user with thousands of notebooks
# or a notebook with thousands of records) can't blow up the LLM's
# context window. The cap is recorded in the rendered output so the
# model knows truncation happened.
MAX_NOTEBOOKS_RENDERED = 50
MAX_RECORDS_RENDERED = 80
MAX_TITLE_PREVIEW = 100
MAX_SUMMARY_PREVIEW = 240


@dataclass(frozen=True)
class ListOutcome:
    """Result of one ``list_notebook`` invocation."""

    ok: bool
    text: str = ""
    error: str = ""
    # Structured echo for the frontend / downstream tools. Kept tiny:
    # callers needing the full dump should call the manager directly.
    summary: dict[str, Any] | None = None


def list_notebooks_or_records(
    *,
    notebook_id: str = "",
    notebook_manager: Any = None,
) -> ListOutcome:
    """Run the list operation. Empty ``notebook_id`` → index mode.

    Errors out cleanly as ``ListOutcome(ok=False, error=...)`` instead
    of raising — the chat loop converts errors back into LLM-visible
    tool results, not exceptions.
    """
    manager = notebook_manager
    if manager is None:
        from deeptutor.services.notebook import get_notebook_manager

        manager = get_notebook_manager()

    nid = (notebook_id or "").strip()
    if not nid:
        return _render_index(manager)
    return _render_records(manager, nid)


def _render_index(manager: Any) -> ListOutcome:
    notebooks = manager.list_notebooks() or []
    if not isinstance(notebooks, list) or not notebooks:
        return ListOutcome(
            ok=True,
            text="The user has no notebooks yet.",
            summary={"mode": "index", "count": 0},
        )
    total = len(notebooks)
    sliced = notebooks[:MAX_NOTEBOOKS_RENDERED]
    lines: list[str] = ["**User notebooks**"]
    for nb in sliced:
        nb_id = str(nb.get("id") or "").strip()
        name = str(nb.get("name") or nb.get("title") or "").strip() or nb_id
        description = _clip(str(nb.get("description") or "").strip(), 200)
        count = nb.get("record_count")
        if not isinstance(count, int):
            try:
                count = int(count or 0)
            except (TypeError, ValueError):
                count = 0
        updated = _format_timestamp(nb.get("updated_at"))
        bullet = f"- `{nb_id}` — **{name}** ({count} records"
        if updated:
            bullet += f", updated {updated}"
        bullet += ")"
        if description:
            bullet += f"\n  {description}"
        lines.append(bullet)
    if total > len(sliced):
        lines.append(
            f"\n_(showing {len(sliced)} of {total} notebooks — call with "
            "a specific notebook_id to drill in.)_"
        )
    return ListOutcome(
        ok=True,
        text="\n".join(lines),
        summary={"mode": "index", "count": total},
    )


def _render_records(manager: Any, notebook_id: str) -> ListOutcome:
    # Validate the id against the user's actual notebooks first so the
    # error message can tell the model the right ids to choose from.
    notebooks = manager.list_notebooks() or []
    matched = next(
        (nb for nb in notebooks if str(nb.get("id") or "").strip() == notebook_id),
        None,
    )
    if matched is None:
        valid_ids = ", ".join(f"`{nb.get('id')}`" for nb in notebooks if nb.get("id"))
        return ListOutcome(
            ok=False,
            error=(f"Unknown notebook_id {notebook_id!r}. Valid ids: {valid_ids or '(none)'}."),
        )

    try:
        records = manager.get_records(notebook_id) or []
    except Exception as exc:  # pragma: no cover — defensive
        logger.warning("list_notebook: get_records failed", exc_info=True)
        return ListOutcome(ok=False, error=f"Failed to load records: {exc}")

    notebook_name = str(matched.get("name") or matched.get("title") or notebook_id)
    if not records:
        return ListOutcome(
            ok=True,
            text=f"Notebook **{notebook_name}** (`{notebook_id}`) has no records yet.",
            summary={"mode": "records", "notebook_id": notebook_id, "count": 0},
        )

    total = len(records)
    # Newest first — the most-recent record is typically the one the
    # user wants to find or edit.
    sorted_records = sorted(
        records,
        key=lambda r: r.get("created_at") or 0,
        reverse=True,
    )
    sliced = sorted_records[:MAX_RECORDS_RENDERED]
    lines: list[str] = [
        f"**Records in notebook `{notebook_id}` — {notebook_name}**",
    ]
    for rec in sliced:
        rid = str(rec.get("id") or "").strip()
        title = _clip(str(rec.get("title") or "").strip(), MAX_TITLE_PREVIEW)
        rtype = str(rec.get("type") or "").strip()
        summary = _clip(
            str(rec.get("summary") or "").strip(),
            MAX_SUMMARY_PREVIEW,
        )
        created = _format_timestamp(rec.get("created_at"))
        head = f"- `{rid}` — **{title or '(untitled)'}**"
        if rtype:
            head += f" [{rtype}]"
        if created:
            head += f" — {created}"
        lines.append(head)
        if summary:
            lines.append(f"  {summary}")
    if total > len(sliced):
        lines.append(f"\n_(showing {len(sliced)} most-recent of {total} records.)_")
    return ListOutcome(
        ok=True,
        text="\n".join(lines),
        summary={"mode": "records", "notebook_id": notebook_id, "count": total},
    )


def _clip(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[:limit].rstrip() + "…"


def _format_timestamp(raw: Any) -> str:
    """Render an epoch-seconds value as ``YYYY-MM-DD`` for at-a-glance scan.

    Falls back to ``""`` on missing / unparseable inputs so the caller
    can omit the field cleanly.
    """
    if raw is None:
        return ""
    try:
        ts = float(raw)
    except (TypeError, ValueError):
        return ""
    if ts <= 0:
        return ""
    try:
        return _dt.datetime.fromtimestamp(ts).strftime("%Y-%m-%d")
    except (OverflowError, OSError, ValueError):
        return ""


__all__ = [
    "MAX_NOTEBOOKS_RENDERED",
    "MAX_RECORDS_RENDERED",
    "ListOutcome",
    "list_notebooks_or_records",
]
