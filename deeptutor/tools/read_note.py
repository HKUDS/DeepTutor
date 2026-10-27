"""Read one notebook record in full, body included.

``list_notebook`` reports only a clipped summary per record, and
``write_note`` in edit mode replaces the whole body. Without a read, the
agent could not safely update a record it wrote in an earlier
conversation, so the only safe pattern was a new record per step
(issue #2049). This closes that: the body comes back verbatim, so the
agent can quote it, reason over it, or hand it to ``write_note``.

Stateless and synchronous, like ``list_notebook``; the chat pipeline
auto-mounts it under the same ``has_notebooks`` gate.
"""

from __future__ import annotations

from dataclasses import dataclass
import logging
from typing import Any

logger = logging.getLogger(__name__)

# A record body is agent-authored markdown and can be long (``write_note``
# accepts up to 200k characters for a new record). Handing that back
# unfiltered would spend the whole context window on one note, so the body
# is capped and the truncation is stated in the rendered text — a silently
# shortened body would be worse than a long one, because the agent would
# rewrite the record from an incomplete copy.
MAX_BODY_CHARS = 12_000
# ``list_notebook`` caps its drill-down for the same reason: a notebook with
# thousands of records must not turn an error message into a wall of ids.
MAX_VALID_IDS_LISTED = 20


def _missing_record_error(manager: Any, notebook_id: str, record_id: str) -> str:
    """Say which ids do exist, so the model can correct itself in one round.

    A tool that only says "not found" gets re-called verbatim; the sibling
    ``list_notebook`` answers the same way for notebooks.
    """
    try:
        records = manager.get_records(notebook_id) or []
    except Exception:  # pragma: no cover — defensive
        records = []
    ids = [str(rec.get("id")) for rec in records if rec.get("id")]
    valid = ", ".join(f"`{rid}`" for rid in ids[:MAX_VALID_IDS_LISTED])
    if len(ids) > MAX_VALID_IDS_LISTED:
        valid += f", … (+{len(ids) - MAX_VALID_IDS_LISTED} more)"
    return (
        f"Unknown record_id {record_id!r} in notebook {notebook_id!r}. "
        f"Valid record ids: {valid or '(this notebook has no records)'}. "
        "Call `list_notebook` with this notebook_id to see them with their titles."
    )


@dataclass(frozen=True)
class ReadOutcome:
    """Result of one ``read_note`` invocation."""

    ok: bool
    text: str = ""
    error: str = ""
    summary: dict[str, Any] | None = None


def read_notebook_record(
    *,
    notebook_id: str = "",
    record_id: str = "",
    notebook_manager: Any = None,
) -> ReadOutcome:
    """Return one record's header, summary and full body.

    Errors out cleanly as ``ReadOutcome(ok=False, error=...)`` instead of
    raising — the chat loop turns errors into tool results for the model.
    """
    manager = notebook_manager
    if manager is None:
        from deeptutor.services.notebook import get_notebook_manager

        manager = get_notebook_manager()

    nid = (notebook_id or "").strip()
    rid = (record_id or "").strip()
    try:
        notebooks = manager.list_notebooks() or []
    except Exception as exc:
        logger.warning("read_note: list_notebooks failed", exc_info=True)
        return ReadOutcome(ok=False, error=f"Failed to load notebooks: {exc}")
    if not any(str(nb.get("id") or "").strip() == nid for nb in notebooks):
        known = [str(nb.get("id")) for nb in notebooks if nb.get("id")]
        valid = ", ".join(f"`{nb_id}`" for nb_id in known[:MAX_VALID_IDS_LISTED])
        if len(known) > MAX_VALID_IDS_LISTED:
            valid += f", … (+{len(known) - MAX_VALID_IDS_LISTED} more)"
        return ReadOutcome(
            ok=False,
            error=(
                f"Unknown notebook_id {nid!r}. Valid ids: {valid or '(none)'}. "
                "Call `list_notebook` with no arguments to see every notebook."
            ),
        )
    if not rid:
        return ReadOutcome(
            ok=False,
            error=(
                "record_id is required. Call `list_notebook` with this "
                "notebook_id to see its record ids."
            ),
        )
    try:
        record = manager.get_record(nid, rid)
    except Exception as exc:
        logger.warning("read_note: get_record failed", exc_info=True)
        return ReadOutcome(ok=False, error=f"Failed to load the record: {exc}")
    if record is None:
        return ReadOutcome(ok=False, error=_missing_record_error(manager, nid, rid))

    body = str(record.get("output") or "")
    summarized = str(record.get("summary") or "").strip()
    truncated = len(body) > MAX_BODY_CHARS
    lines = [f"**{str(record.get('title') or '').strip() or '(untitled)'}** (`{rid}`)"]
    if summarized:
        lines.append("")
        lines.append(f"Summary: {summarized}")
    lines.append("")
    if truncated:
        # Cut on a line boundary: a mid-line cut can leave a fenced block or a
        # table row open, and the hint asks the model to quote what it keeps
        # back into ``write_note``.
        shown = body[:MAX_BODY_CHARS]
        if "\n" in shown:
            shown = shown.rsplit("\n", 1)[0]
        cut_at = len(shown)
        # Close a fenced block the cut ran into: an unterminated fence swallows
        # the notice and renders the rest of the note as code.
        if shown.count("```") % 2 == 1:
            shown += "\n```"
        lines.append(shown)
        lines.append("")
        lines.append(
            f"_(body truncated: {len(body)} characters in the record, showing the first {cut_at}.)_"
        )
    else:
        lines.append(body if body else "_(this record has no body yet)_")
    return ReadOutcome(
        ok=True,
        text="\n".join(lines),
        summary={
            "mode": "record",
            "notebook_id": nid,
            "record_id": rid,
            "chars": len(body),
            "truncated": truncated,
        },
    )
