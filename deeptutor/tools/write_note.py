"""Create or edit a single notebook record from the chat agent.

Replaces the older ``save_to_notebook`` tool. Two modes:

* **append**: create a NEW record in the target notebook. The body is
  either an auto-rendered transcript (when ``content`` is empty — the
  default; mirrors a human clicking 'Save to notebook' on the recent
  chat) or an agent-authored markdown body (when ``content`` is
  provided — for the 'write a summary into the notebook' use case).
* **edit**: update an EXISTING record's title and/or body and/or
  summary. The agent must know the ``record_id`` (typically obtained
  via the ``list_notebook`` tool).
* **append_to**: add markdown to the END of an EXISTING record's body,
  leaving its title and summary alone. The server concatenates, so the
  agent never has to rewrite text it cannot see (read it first with
  ``read_note`` if it needs to reason over the whole record).

The append mode preserves the actual conversation by default; the
agent does not author the body unless it explicitly chooses to. This
matches the user's expectation that the saved record reflect what was
actually said, not a summary the LLM invented.

Dependency-injected for tests (``notebook_manager``,
``conversation_history``, ``current_user_message``); the chat pipeline
wires in the live values via ``_augment_tool_kwargs``.
"""

from __future__ import annotations

from dataclasses import dataclass
import logging
from typing import Any, Iterable

from deeptutor.services.notebook.service import NotebookCorruptedError
from deeptutor.tools.read_note import MAX_BODY_CHARS as READ_BODY_CHARS

logger = logging.getLogger(__name__)

# Length sanity caps. Generous because the tool now legitimately needs
# to support saving arbitrarily long transcripts (the user requested
# "保存任意长度的对话记录"). The 200k cap below corresponds to roughly
# 50k tokens of conversation — well beyond any reasonable single chat
# session — and still leaves headroom in the notebook UI.
MAX_TITLE_CHARS = 200
MAX_NOTE_CHARS = 4_000
MAX_CONTENT_CHARS = 200_000
# Append-mode ``turns_to_include`` accepts integers 1..N OR the
# literal string "all" to capture every turn currently in scope. Tests
# pin the default to 3 (= a sensible "couple of recent turns" slice).
DEFAULT_TURNS_TO_INCLUDE = 3
ALL_TURNS_SENTINEL = "all"

VALID_MODES = ("append", "edit", "append_to")


@dataclass(frozen=True)
class WriteOutcome:
    """Result of a single ``write_note`` invocation."""

    ok: bool
    mode: str = ""
    record_id: str = ""
    notebook_id: str = ""
    notebook_name: str = ""
    error: str = ""
    unchanged: bool = False


def write_note(
    *,
    mode: str,
    notebook_id: str,
    record_id: str = "",
    title: str = "",
    content: str = "",
    turns_to_include: Any = DEFAULT_TURNS_TO_INCLUDE,
    note: str = "",
    allow_shrink: bool = False,
    conversation_history: Iterable[dict[str, Any]] | None = None,
    current_user_message: str = "",
    notebook_manager: Any = None,
) -> WriteOutcome:
    """Dispatch on ``mode`` and forward to the append / edit helpers.

    Errors are returned as ``WriteOutcome(ok=False, error=...)`` rather
    than raising — the chat loop converts the result back into an
    LLM-visible tool result.
    """
    cleaned_mode = (mode or "").strip().lower()
    if cleaned_mode not in VALID_MODES:
        return WriteOutcome(
            ok=False,
            error=(
                f"Unknown mode {mode!r}. Use one of: "
                + ", ".join(repr(m) for m in VALID_MODES)
                + "."
            ),
        )

    nid = (notebook_id or "").strip()
    if not nid:
        return WriteOutcome(ok=False, mode=cleaned_mode, error="notebook_id is required.")

    manager = notebook_manager
    if manager is None:
        from deeptutor.services.notebook import get_notebook_manager

        manager = get_notebook_manager()

    notebooks = manager.list_notebooks()
    if not isinstance(notebooks, list) or not notebooks:
        return WriteOutcome(
            ok=False,
            mode=cleaned_mode,
            error="No notebooks are available for this user.",
        )
    matched = next(
        (nb for nb in notebooks if str(nb.get("id") or "").strip() == nid),
        None,
    )
    if matched is None:
        valid_ids = ", ".join(f"`{nb.get('id')}`" for nb in notebooks if nb.get("id"))
        return WriteOutcome(
            ok=False,
            mode=cleaned_mode,
            error=(f"Unknown notebook_id {nid!r}. Valid ids: {valid_ids or '(none)'}."),
        )

    notebook_name = str(matched.get("name") or matched.get("title") or nid)

    if cleaned_mode == "append":
        return _do_append(
            manager=manager,
            notebook_id=nid,
            notebook_name=notebook_name,
            title=title,
            content=content,
            turns_to_include=turns_to_include,
            note=note,
            conversation_history=list(conversation_history or []),
            current_user_message=str(current_user_message or "").strip(),
        )
    if cleaned_mode == "append_to":
        return _do_append_to(
            manager=manager,
            notebook_id=nid,
            notebook_name=notebook_name,
            record_id=record_id,
            content=content,
        )
    return _do_edit(
        manager=manager,
        notebook_id=nid,
        notebook_name=notebook_name,
        record_id=record_id,
        title=title,
        content=content,
        note=note,
        allow_shrink=allow_shrink,
    )


# ---------------------------------------------------------------------------
# Append mode
# ---------------------------------------------------------------------------


def _do_append(
    *,
    manager: Any,
    notebook_id: str,
    notebook_name: str,
    title: str,
    content: str,
    turns_to_include: Any,
    note: str,
    conversation_history: list[dict[str, Any]],
    current_user_message: str,
) -> WriteOutcome:
    cleaned_title = (title or "").strip()
    if not cleaned_title:
        return WriteOutcome(
            ok=False,
            mode="append",
            notebook_id=notebook_id,
            notebook_name=notebook_name,
            error="title must not be empty in append mode.",
        )
    if len(cleaned_title) > MAX_TITLE_CHARS:
        cleaned_title = cleaned_title[:MAX_TITLE_CHARS].rstrip() + "…"
    cleaned_note = (note or "").strip()
    if len(cleaned_note) > MAX_NOTE_CHARS:
        cleaned_note = cleaned_note[:MAX_NOTE_CHARS].rstrip() + "…"

    explicit_content = (content or "").strip()
    if explicit_content:
        # Agent-authored body: trust it. This is for the
        # "save a summary into the notebook" use case.
        transcript = explicit_content
    else:
        # Default: render the real conversation. Agent does not author.
        transcript = _format_transcript(
            conversation_history=conversation_history,
            current_user_message=current_user_message,
            turns_to_include=_coerce_turns(turns_to_include),
        )

    if not transcript.strip():
        return WriteOutcome(
            ok=False,
            mode="append",
            notebook_id=notebook_id,
            notebook_name=notebook_name,
            error=(
                "Nothing to save: the chat history is empty and no "
                "explicit content was provided. Either wait until "
                "there's a user+assistant exchange, or pass `content` "
                "directly."
            ),
        )

    body_parts: list[str] = []
    if cleaned_note:
        body_parts.append(f"**Note:** {cleaned_note}")
    body_parts.append(transcript)
    cleaned_content = "\n\n---\n\n".join(body_parts).strip()
    if len(cleaned_content) > MAX_CONTENT_CHARS:
        cleaned_content = cleaned_content[:MAX_CONTENT_CHARS].rstrip() + "\n…[truncated]"

    from deeptutor.services.notebook.service import RecordType

    user_query_for_record = current_user_message or _last_user_message(conversation_history)

    try:
        outcome = manager.add_record(
            notebook_ids=[notebook_id],
            record_type=RecordType.CHAT,
            title=cleaned_title,
            user_query=user_query_for_record,
            output=cleaned_content,
            summary=cleaned_note or _summary_from_transcript(transcript),
            metadata={
                "source": "write_note_tool",
                "mode": "append",
                "note_provided": bool(cleaned_note),
                "explicit_content": bool(explicit_content),
            },
        )
    except Exception as exc:
        logger.warning("write_note(append): add_record failed", exc_info=True)
        return WriteOutcome(
            ok=False,
            mode="append",
            notebook_id=notebook_id,
            notebook_name=notebook_name,
            error=f"Save failed: {exc}",
        )

    record = (outcome or {}).get("record") if isinstance(outcome, dict) else None
    record_id = str((record or {}).get("id") or "")
    if not record_id:
        return WriteOutcome(
            ok=False,
            mode="append",
            notebook_id=notebook_id,
            notebook_name=notebook_name,
            error="Notebook service did not return a record id.",
        )
    # A record id comes back even when no notebook accepted the write — the
    # service skips notebooks that are missing or damaged. Reporting success
    # off the id alone would tell the model it saved something it did not.
    added_to = (outcome or {}).get("added_to_notebooks") or []
    if notebook_id not in added_to:
        return WriteOutcome(
            ok=False,
            mode="append",
            notebook_id=notebook_id,
            notebook_name=notebook_name,
            error=(
                f"Notebook {notebook_name!r} did not accept the record. "
                "Its file may be missing or damaged."
            ),
        )
    return WriteOutcome(
        ok=True,
        mode="append",
        record_id=record_id,
        notebook_id=notebook_id,
        notebook_name=notebook_name,
    )


def _coerce_turns(raw: Any) -> int | None:
    """Return a positive integer or ``None`` meaning 'all turns'."""
    if isinstance(raw, str) and raw.strip().lower() == ALL_TURNS_SENTINEL:
        return None
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return DEFAULT_TURNS_TO_INCLUDE
    return max(1, value)


# ---------------------------------------------------------------------------
# Append-to mode
# ---------------------------------------------------------------------------


def _do_append_to(
    *,
    manager: Any,
    notebook_id: str,
    notebook_name: str,
    record_id: str,
    content: str,
) -> WriteOutcome:
    """Extend an existing record's body without rewriting what is already there.

    Append-at-the-server is the whole point: the agent saves the next step of
    a long record without first reproducing text it may never have read, so a
    stale or partial copy cannot silently replace real history (#2049).
    """
    rid = (record_id or "").strip()
    if not rid:
        return WriteOutcome(
            ok=False,
            mode="append_to",
            notebook_id=notebook_id,
            notebook_name=notebook_name,
            error=(
                "append_to needs `record_id` — the record to extend. To save "
                "this as a NEW record use mode='append'."
            ),
        )
    cleaned_content = (content or "").strip()
    if not cleaned_content:
        return WriteOutcome(
            ok=False,
            mode="append_to",
            notebook_id=notebook_id,
            notebook_name=notebook_name,
            record_id=rid,
            error="append_to needs `content`: the markdown to add to the end of the record.",
        )

    # The manager joins under its per-notebook lock and owns both the size rule
    # and the "record missing" answer; a read-modify-write or a second read here
    # would drop a save that landed in between, or disagree with the lock-time
    # check — and would parse the whole notebook a second time to say so.
    try:
        updated = manager.append_to_record(
            notebook_id, rid, cleaned_content, max_chars=MAX_CONTENT_CHARS
        )
    except NotebookCorruptedError as exc:
        logger.warning("write_note(append_to): could not read notebook", exc_info=True)
        return WriteOutcome(
            ok=False,
            mode="append_to",
            notebook_id=notebook_id,
            notebook_name=notebook_name,
            record_id=rid,
            error=f"Could not read notebook {notebook_name!r}: {exc}",
        )
    except ValueError as exc:
        logger.info("write_note(append_to): refused: %s", exc)
        return WriteOutcome(
            ok=False,
            mode="append_to",
            notebook_id=notebook_id,
            notebook_name=notebook_name,
            record_id=rid,
            error=(
                f"Appending that much would grow this record past "
                f"{MAX_CONTENT_CHARS} characters. Append a shorter amount, or "
                "keep it as a new record with mode='append'."
            ),
        )
    except Exception as exc:
        logger.warning("write_note(append_to): append failed", exc_info=True)
        return WriteOutcome(
            ok=False,
            mode="append_to",
            notebook_id=notebook_id,
            notebook_name=notebook_name,
            record_id=rid,
            error=f"Append failed: {exc}",
        )
    if updated is None:
        return WriteOutcome(
            ok=False,
            mode="append_to",
            notebook_id=notebook_id,
            notebook_name=notebook_name,
            record_id=rid,
            error=(
                f"Record {rid!r} not found in notebook {notebook_id!r} "
                "(the whole notebook may have been removed). Call `list_notebook` "
                "with this notebook_id first to discover valid record ids."
            ),
        )
    if not updated.appended:
        return WriteOutcome(
            ok=True,
            mode="append_to",
            unchanged=True,
            record_id=rid,
            notebook_id=notebook_id,
            notebook_name=notebook_name,
        )
    return WriteOutcome(
        ok=True,
        mode="append_to",
        record_id=rid,
        notebook_id=notebook_id,
        notebook_name=notebook_name,
    )


# ---------------------------------------------------------------------------
# Edit mode
# ---------------------------------------------------------------------------


def _do_edit(
    *,
    manager: Any,
    notebook_id: str,
    notebook_name: str,
    record_id: str,
    title: str,
    content: str,
    note: str,
    allow_shrink: bool = False,
) -> WriteOutcome:
    rid = (record_id or "").strip()
    if not rid:
        return WriteOutcome(
            ok=False,
            mode="edit",
            notebook_id=notebook_id,
            notebook_name=notebook_name,
            error="record_id is required in edit mode.",
        )

    try:
        existing = manager.get_record(notebook_id, rid) if hasattr(manager, "get_record") else None
    except Exception as exc:
        # A damaged notebook file raises here. Report it as a tool result the
        # model can act on rather than letting it escape into the agent loop.
        logger.warning("write_note(edit): could not read notebook", exc_info=True)
        return WriteOutcome(
            ok=False,
            mode="edit",
            notebook_id=notebook_id,
            notebook_name=notebook_name,
            error=f"Could not read notebook {notebook_name!r}: {exc}",
        )
    if existing is None:
        return WriteOutcome(
            ok=False,
            mode="edit",
            notebook_id=notebook_id,
            notebook_name=notebook_name,
            error=(
                f"Record {rid!r} not found in notebook {notebook_id!r}. "
                "Call `list_notebook` with this notebook_id first to "
                "discover valid record ids."
            ),
        )

    cleaned_title = (title or "").strip()
    if cleaned_title and len(cleaned_title) > MAX_TITLE_CHARS:
        cleaned_title = cleaned_title[:MAX_TITLE_CHARS].rstrip() + "…"
    cleaned_content = (content or "").strip()
    if cleaned_content and len(cleaned_content) > MAX_CONTENT_CHARS:
        cleaned_content = cleaned_content[:MAX_CONTENT_CHARS].rstrip() + "\n…[truncated]"
    cleaned_note = (note or "").strip()
    if cleaned_note and len(cleaned_note) > MAX_NOTE_CHARS:
        cleaned_note = cleaned_note[:MAX_NOTE_CHARS].rstrip() + "…"

    if cleaned_content:
        stored_body = str(existing.get("output") or "")
        # ``read_note`` hands back at most READ_BODY_CHARS characters, so a body
        # longer than that was never seen in one piece. A shorter replacement is
        # therefore a rewrite built from a prefix, and saving it deletes the
        # rest of the record with no way to get it back.
        if (
            not allow_shrink
            and len(stored_body) > READ_BODY_CHARS
            and len(cleaned_content) < len(stored_body)
        ):
            return WriteOutcome(
                ok=False,
                mode="edit",
                notebook_id=notebook_id,
                notebook_name=notebook_name,
                record_id=rid,
                error=(
                    f"edit would replace a {len(stored_body)}-character body with "
                    f"{len(cleaned_content)} characters, and `read_note` returns at "
                    f"most {READ_BODY_CHARS} of them at a time — the text being "
                    "dropped was never shown to you. Use mode='append_to' to add "
                    "without rewriting; shortening an archived record is done in "
                    "the notebook UI."
                ),
            )

    if not (cleaned_title or cleaned_content or cleaned_note):
        return WriteOutcome(
            ok=False,
            mode="edit",
            notebook_id=notebook_id,
            notebook_name=notebook_name,
            error=("edit mode requires at least one of `title`, `content`, or `note` to change."),
        )

    update_kwargs: dict[str, Any] = {}
    if cleaned_title:
        update_kwargs["title"] = cleaned_title
    if cleaned_content:
        update_kwargs["output"] = cleaned_content
    if cleaned_note:
        update_kwargs["summary"] = cleaned_note

    try:
        updated = manager.update_record(notebook_id, rid, **update_kwargs)
    except Exception as exc:
        logger.warning("write_note(edit): update_record failed", exc_info=True)
        return WriteOutcome(
            ok=False,
            mode="edit",
            notebook_id=notebook_id,
            notebook_name=notebook_name,
            error=f"Edit failed: {exc}",
        )
    if updated is None:
        return WriteOutcome(
            ok=False,
            mode="edit",
            notebook_id=notebook_id,
            notebook_name=notebook_name,
            error="Notebook service rejected the update (record vanished?).",
        )

    return WriteOutcome(
        ok=True,
        mode="edit",
        record_id=rid,
        notebook_id=notebook_id,
        notebook_name=notebook_name,
    )


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def _format_transcript(
    *,
    conversation_history: list[dict[str, Any]],
    current_user_message: str,
    turns_to_include: int | None,
) -> str:
    """Render a slice of the chat as a markdown Q&A block.

    ``turns_to_include=None`` means "every turn currently in scope" —
    used when the agent passes ``turns_to_include='all'``. Otherwise
    we slice the most-recent N user+assistant pairs.

    The "current turn" (the one this tool is being called from)
    appears LAST: the user's latest message + a placeholder marker
    because the assistant's response isn't finalised yet.
    """
    pairs: list[tuple[str, str]] = []
    pending_user: str | None = None
    for entry in conversation_history:
        role = str(entry.get("role") or "").strip().lower()
        content = entry.get("content")
        text = _coerce_text(content)
        if not text:
            continue
        if role == "user":
            if pending_user is not None:
                pairs.append((pending_user, ""))
            pending_user = text
            continue
        if role == "assistant":
            pairs.append((pending_user or "", text))
            pending_user = None
            continue
    if pending_user is not None:
        pairs.append((pending_user, ""))
    if current_user_message:
        pairs.append((current_user_message, ""))

    if turns_to_include is None:
        selected = pairs
    else:
        selected = pairs[-turns_to_include:] if pairs else []

    blocks: list[str] = []
    for user_text, assistant_text in selected:
        if user_text:
            blocks.append(f"### User\n\n{user_text}")
        if assistant_text:
            blocks.append(f"### Assistant\n\n{assistant_text}")
        elif user_text:
            blocks.append("### Assistant\n\n_(assistant response in progress)_")
    return "\n\n---\n\n".join(blocks)


def _coerce_text(content: Any) -> str:
    if isinstance(content, list):
        return "\n".join(
            str(part.get("text") or "")
            for part in content
            if isinstance(part, dict) and part.get("type") == "text"
        ).strip()
    return str(content or "").strip()


def _last_user_message(conversation_history: list[dict[str, Any]]) -> str:
    """Return the most-recent non-empty user message text, or ``""``."""
    for entry in reversed(conversation_history):
        if str(entry.get("role") or "").lower() != "user":
            continue
        text = _coerce_text(entry.get("content"))
        if text:
            return text
    return ""


def _summary_from_transcript(transcript: str, *, limit: int = 240) -> str:
    """Pick a first non-heading, non-blank line to use as the summary."""
    for line in transcript.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or line == "---":
            continue
        return line[:limit].rstrip() + ("…" if len(line) > limit else "")
    return ""


__all__ = [
    "ALL_TURNS_SENTINEL",
    "DEFAULT_TURNS_TO_INCLUDE",
    "MAX_CONTENT_CHARS",
    "MAX_NOTE_CHARS",
    "MAX_TITLE_CHARS",
    "VALID_MODES",
    "WriteOutcome",
    "write_note",
]
