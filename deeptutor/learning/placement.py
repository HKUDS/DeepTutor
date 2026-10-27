"""Open the conversation that belongs to one mastery phase.

Outline planning is one session for the whole path. Study and review each
have one session per knowledge point. Callers that used to reopen whichever
conversation moved last go through :func:`resolve_placed_session` instead.
"""

from __future__ import annotations

import re
from typing import Any

from deeptutor.capabilities.mastery.mode import MODES, OUTLINE, admission_error
from deeptutor.learning.storage import LearningStore
from deeptutor.learning.topic_generation import _MAX_OBJECTIVES_PER_MODULE

_BUBBLE_CHAR_BUDGET = 12_000
#: A lecture is a document, not a chat reply. The chat default truncates one
#: at roughly a page, which is shorter than the thing being written.
_LECTURE_MAX_TOKENS = 4_000


def _point_name(progress: Any, knowledge_point_id: str) -> str:
    for module in getattr(progress, "modules", []) or []:
        for point in module.knowledge_points:
            if point.id == knowledge_point_id:
                return str(point.name or "").strip()
    return ""


def _module_id_for_point(progress: Any, knowledge_point_id: str) -> str:
    for module in getattr(progress, "modules", []) or []:
        if any(point.id == knowledge_point_id for point in module.knowledge_points):
            return str(module.id)
    return ""


def _module_name(modules: list[dict[str, Any]], module_id: str) -> str:
    for module in modules:
        if str(module.get("id") or "") == module_id:
            return str(module.get("name") or "").strip()
    return ""


async def resolve_placed_session(
    path_id: str,
    mode: str,
    knowledge_point_id: str = "",
    *,
    store: LearningStore | None = None,
) -> dict[str, Any]:
    """Return the session for this phase, creating an empty one when needed."""
    from deeptutor.services.session import get_session_store

    placed_mode = str(mode or "").strip().lower()
    if placed_mode not in MODES:
        raise ValueError(f"mode must be one of: {', '.join(MODES)}")
    point_id = "" if placed_mode == OUTLINE else str(knowledge_point_id or "").strip()
    if placed_mode != OUTLINE and not point_id:
        raise ValueError("A study or review conversation needs a knowledge point.")

    learning = store or LearningStore()
    progress = learning.load(path_id)
    has_outline = progress is not None and any(module.knowledge_points for module in progress.modules)
    refusal = admission_error(placed_mode, has_outline=has_outline)
    if refusal:
        raise ValueError(refusal)
    if placed_mode != OUTLINE and progress is not None and not _point_name(progress, point_id):
        raise ValueError("That knowledge point is not on this outline.")

    existing = learning.find_placed_session(path_id, placed_mode, point_id)
    if existing:
        return {"session_id": existing, "created": False, "mode": placed_mode, "knowledge_point_id": point_id}

    title = "Outline"
    if placed_mode != OUTLINE and progress is not None:
        title = _point_name(progress, point_id) or placed_mode
    session_store = get_session_store()
    created = await session_store.create_session(title=title[:100])
    session_id = str(created.get("session_id") or created.get("id") or "")
    if not session_id:
        raise RuntimeError("The conversation could not be opened.")
    await session_store.update_session_preferences(
        session_id,
        {
            "workspace_mode": "mastery_path",
            "capability": "mastery_path",
            "mastery_path_id": path_id,
            "mastery_session_mode": placed_mode,
            "mastery_knowledge_point_id": point_id,
        },
    )
    try:
        learning.bind_session(path_id, session_id, mode=placed_mode, knowledge_point_id=point_id)
    except Exception:
        winner = learning.find_placed_session(path_id, placed_mode, point_id)
        if winner and winner != session_id:
            return {
                "session_id": winner,
                "created": False,
                "mode": placed_mode,
                "knowledge_point_id": point_id,
            }
        raise
    return {"session_id": session_id, "created": True, "mode": placed_mode, "knowledge_point_id": point_id}


async def _bubbles(session_id: str) -> list[dict[str, Any]]:
    from deeptutor.services.session import get_session_store

    session_store = get_session_store()
    reader = getattr(session_store, "list_bubble_texts", None)
    if callable(reader):
        rows = await reader(session_id)
    else:
        rows = await session_store.get_messages(session_id)
    bubbles: list[dict[str, Any]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        content = str(row.get("content") or "").strip()
        role = str(row.get("role") or "")
        if role not in {"user", "assistant"} or not content:
            continue
        try:
            message_id = int(row.get("id") or 0)
        except (TypeError, ValueError):
            message_id = 0
        bubbles.append({"id": message_id, "role": role, "content": content})
    return bubbles


def lecture_status(store: LearningStore, path_id: str, knowledge_point_id: str, bubbles: list[dict[str, Any]]) -> dict[str, Any]:
    """What review should render, and what the learner still has to decide.

    Three states, and the UI must not collapse them. ``confirmed`` is a
    lecture somebody committed; ``draft_only`` is the rolling summary of a
    study conversation nobody has confirmed yet — shown, but marked, so it is
    never mistaken for settled content; ``none`` means this point has nothing
    to read. A confirmed lecture can still be ``stale`` against study, and
    that is reported separately because it is a much weaker signal than
    "unconfirmed" and deserves a chip rather than a warning.
    """
    saved = store.get_lecture(path_id, knowledge_point_id) or {
        "body": "",
        "covered_message_id": 0,
        "revision": 0,
        "confirmed_at": 0,
        "source": "",
        "updated_at": 0,
    }
    draft = store.get_lecture_draft(path_id, knowledge_point_id)
    latest = max((int(row["id"]) for row in bubbles), default=0)
    covered = int(saved["covered_message_id"] or 0)
    body = str(saved["body"] or "")
    draft_body = str((draft or {}).get("body") or "")
    if body:
        status = "confirmed"
    elif draft_body:
        status = "draft_only"
    else:
        status = "none"
    return {
        # What review renders. A draft-only point renders its draft rather
        # than an empty page, and ``status`` is what tells the reader which
        # one they are looking at.
        "body": body or draft_body,
        "confirmed_body": body,
        "status": status,
        "revision": int(saved["revision"] or 0),
        "source": str(saved["source"] or ""),
        "confirmed_at": float(saved["confirmed_at"] or 0),
        "covered_message_id": covered,
        "latest_message_id": latest,
        "has_study": bool(bubbles),
        "stale": bool(body) and latest > covered,
        "draft": {
            "session_id": str(draft["session_id"]),
            "body": draft_body,
            "diff": list(draft.get("diff") or []),
            "base_revision": int(draft["base_revision"] or 0),
            "covered_message_id": int(draft["covered_message_id"] or 0),
            "origin": str(draft["origin"] or ""),
            "updated_at": float(draft["updated_at"] or 0),
        }
        if draft and draft_body
        else None,
        # Study moved on while a confirmed lecture sits in review. Weaker than
        # a draft: the reader has settled content, it is just behind.
        "stale_from_study": bool(body) and draft is not None,
    }


async def study_bubbles(path_id: str, knowledge_point_id: str, *, store: LearningStore | None = None) -> list[dict[str, Any]]:
    learning = store or LearningStore()
    session_id = learning.find_placed_session(path_id, "study", knowledge_point_id)
    if not session_id:
        return []
    return await _bubbles(session_id)


def _transcript(bubbles: list[dict[str, Any]]) -> str:
    lines: list[str] = []
    used = 0
    for row in bubbles:
        speaker = "Learner" if row["role"] == "user" else "Tutor"
        piece = f"{speaker}: {row['content'].strip()}"
        if used and used + len(piece) > _BUBBLE_CHAR_BUDGET:
            break
        lines.append(piece)
        used += len(piece)
    return "\n\n".join(lines)


# --------------------------------------------------------------------------
# Section-level diffs
#
# A lecture is one markdown document, but the learner edits it a section at a
# time and reads it a section at a time. Diffing whole bodies produces "the
# entire document changed" for a one-line edit, which is useless to review.
# Splitting on headings gives blocks a stable name, so a revision card can say
# *which* part of the lecture it is about to change.
# --------------------------------------------------------------------------

_HEADING_RE = re.compile(r"^(#{1,6})[ \t]+(.+?)[ \t]*$", re.MULTILINE)
#: A lecture section is identified by its heading text, not its position:
#: inserting a section must not renumber every section below it.
_PREAMBLE = "（引言）"


def split_sections(body: str) -> list[tuple[str, str]]:
    """Split markdown into ``(heading, text)`` blocks, preamble first."""
    text = str(body or "")
    matches = list(_HEADING_RE.finditer(text))
    if not matches:
        return [(_PREAMBLE, text)] if text.strip() else []
    sections: list[tuple[str, str]] = []
    if text[: matches[0].start()].strip():
        sections.append((_PREAMBLE, text[: matches[0].start()]))
    for index, match in enumerate(matches):
        end = matches[index + 1].start() if index + 1 < len(matches) else len(text)
        heading = match.group(2).strip()
        sections.append((heading, text[match.start() : end]))
    return sections


def lecture_diff(before: str, after: str) -> list[dict[str, Any]]:
    """Section-level changes between two lecture bodies.

    ``op`` is ``added`` / ``removed`` / ``replaced`` and ``heading`` names the
    block, so the card can render the change against a title the learner
    recognises even after a rewrite has moved the section.
    """
    old = dict(split_sections(before))
    new = dict(split_sections(after))
    changes: list[dict[str, Any]] = []
    for heading, text in new.items():
        if heading not in old:
            changes.append({"op": "added", "heading": heading, "before": "", "after": text})
        elif old[heading].strip() != text.strip():
            changes.append(
                {"op": "replaced", "heading": heading, "before": old[heading], "after": text}
            )
    for heading, text in old.items():
        if heading not in new:
            changes.append({"op": "removed", "heading": heading, "before": text, "after": ""})
    return changes


_LECTURE_ROLL_SYSTEM = """You maintain one learner's study lecture as a markdown document.

Rules that matter more than fluency:
- Keep every heading that already exists, in its existing order and wording.
  The learner may have renamed or rewritten a section; that wording is theirs
  now and you must not restyle it.
- Merge new material into the section it belongs to. Add a new section only
  when the new material genuinely starts a new topic.
- Add nothing the transcript did not discuss. No invented examples, no
  filling in the obvious next chapter.
- Write in the language of the transcript.
- Output the document itself. No preamble, no code fence, no commentary."""


async def write_lecture_draft(
    path_id: str,
    knowledge_point_id: str,
    *,
    session_id: str = "",
    store: LearningStore | None = None,
    request_id: str = "",
    force: bool = False,
) -> dict[str, Any]:
    """Roll this point's lecture draft forward from its study conversation.

    Deliberately not "rewrite the lecture". A full rewrite from the whole
    transcript is non-idempotent — the same conversation produces different
    prose each time — and it silently discards anything the learner edited by
    hand. So the existing draft is an *input*: only bubbles past its watermark
    are summarised, and they are merged into the sections already there.
    """
    from deeptutor.services.llm.factory import complete

    learning = store or LearningStore()
    progress = learning.load(path_id)
    point_name = _point_name(progress, knowledge_point_id) if progress is not None else ""
    if not point_name:
        raise ValueError("That knowledge point is not on this outline.")
    bubbles = await study_bubbles(path_id, knowledge_point_id, store=learning)
    if not bubbles:
        raise ValueError("This knowledge point has no study conversation to summarize.")

    study_session = session_id or learning.find_placed_session(path_id, "study", knowledge_point_id)
    existing = learning.get_lecture_draft(path_id, knowledge_point_id, session_id=study_session)
    if existing and request_id and existing["request_id"] == request_id and not force:
        return lecture_status(learning, path_id, knowledge_point_id, bubbles)

    covered_before = int((existing or {}).get("covered_message_id") or 0)
    fresh = [row for row in bubbles if int(row["id"]) > covered_before and row["role"] != "user"]
    if not fresh and existing and not force:
        # Nothing new was actually taught. Returning the current draft is the
        # honest answer, and it keeps a client polling this endpoint from
        # paying for an LLM call that would produce the same document.
        return lecture_status(learning, path_id, knowledge_point_id, bubbles)

    previous_body = str((existing or {}).get("body") or "")
    confirmed = learning.get_lecture(path_id, knowledge_point_id) or {}
    base_body = previous_body or str(confirmed.get("body") or "")
    base_revision = int(
        (existing or {}).get("base_revision") or confirmed.get("revision") or 0
    )

    if previous_body:
        instruction = (
            f"Knowledge point: {point_name}\n\n"
            "Here is the lecture as it stands. Keep its structure and wording, "
            "and merge in what was said since.\n\n"
            f"--- CURRENT LECTURE ---\n{previous_body}\n--- END LECTURE ---\n\n"
            f"--- NEW CONVERSATION ---\n{_transcript(fresh)}\n--- END ---"
        )
    else:
        instruction = (
            f"Knowledge point: {point_name}\n\n"
            "Write a study lecture covering only what the transcript discusses.\n\n"
            f"{_transcript(fresh if fresh else bubbles)}"
        )

    body = await complete(
        instruction,
        system_prompt=_LECTURE_ROLL_SYSTEM,
        max_tokens=_LECTURE_MAX_TOKENS,
    )
    text = str(body or "").strip()
    if not text:
        raise RuntimeError("The lecture could not be written.")
    # A model that echoed the fence instead of the document would put one
    # around every future merge, since the fence becomes the draft's own text.
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n", "", text)
        text = re.sub(r"\n?```$", "", text).strip()

    covered = max(int(row["id"]) for row in bubbles)
    learning.save_lecture_draft(
        path_id,
        knowledge_point_id,
        session_id=study_session,
        body=text,
        base_revision=base_revision,
        covered_message_id=covered,
        diff=lecture_diff(base_body, text),
        request_id=request_id,
        origin="study_roll",
    )
    return lecture_status(learning, path_id, knowledge_point_id, bubbles)


async def revise_lecture_draft(
    path_id: str,
    knowledge_point_id: str,
    *,
    session_id: str,
    instruction: str,
    store: LearningStore | None = None,
    quoted_text: str = "",
    section_heading: str = "",
    request_id: str = "",
) -> dict[str, Any]:
    """Propose a lecture revision from a learner's own words.

    Never writes the confirmed lecture. This is the counterpart of
    ``mastery_revise(action=preview)`` for outline content: the model produces
    a candidate, the learner applies it from a card under the reply. Writing
    straight through meant a long markdown document got rewritten wholesale
    and the learner only noticed afterwards that a paragraph they had written
    themselves was gone.
    """
    from deeptutor.services.llm.factory import complete

    learning = store or LearningStore()
    progress = learning.load(path_id)
    point_name = _point_name(progress, knowledge_point_id) if progress is not None else ""
    if not point_name:
        raise ValueError("That knowledge point is not on this outline.")

    confirmed = learning.get_lecture(path_id, knowledge_point_id) or {}
    current = str(confirmed.get("body") or "")
    origin = "chat_revision"
    if not current:
        # No confirmed lecture yet: revise the study draft if there is one, so
        # a learner in review is never told "there is nothing to edit" for a
        # lecture they can plainly see on screen.
        draft = learning.get_lecture_draft(path_id, knowledge_point_id)
        current = str((draft or {}).get("body") or "")
        origin = "chat_revision_of_draft"
    if not current:
        raise ValueError("This knowledge point has no lecture to revise yet.")

    target = f"\nTarget section: {section_heading}\n" if section_heading else ""
    quote = f'\nText to change (verbatim): "{quoted_text}"\n' if quoted_text else ""
    body = await complete(
        (
            f"Knowledge point: {point_name}\n"
            f"{target}{quote}\n"
            f"The learner asks: {instruction}\n\n"
            "Apply exactly what was asked and nothing else. Keep every other "
            "section's wording byte-for-byte. Output the full document.\n\n"
            f"--- CURRENT LECTURE ---\n{current}\n--- END LECTURE ---"
        ),
        system_prompt=_LECTURE_ROLL_SYSTEM,
        max_tokens=_LECTURE_MAX_TOKENS,
    )
    text = str(body or "").strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-zA-Z]*\n", "", text)
        text = re.sub(r"\n?```$", "", text).strip()
    if not text:
        raise RuntimeError("The lecture could not be revised.")
    changes = lecture_diff(current, text)
    if not changes:
        raise ValueError("That request did not change the lecture. Say so instead of saving.")

    draft = learning.save_lecture_draft(
        path_id,
        knowledge_point_id,
        session_id=session_id,
        body=text,
        base_revision=int(confirmed.get("revision") or 0),
        covered_message_id=int(confirmed.get("covered_message_id") or 0),
        diff=changes,
        request_id=request_id,
        origin=origin,
    )
    return {
        "preview_id": int(draft["updated_at"] * 1000),
        "session_id": draft["session_id"],
        "base_revision": draft["base_revision"],
        "changes": changes,
        "body": text,
        "origin": origin,
    }


def commit_lecture_draft(
    store: LearningStore,
    path_id: str,
    knowledge_point_id: str,
    *,
    session_id: str = "",
    source: str = "learner_confirmed",
    expected_revision: int | None = None,
) -> dict[str, Any]:
    """Promote a draft to the confirmed lecture review will show.

    Conflict, not overwrite: a reviewer's stale tab must not replace a lecture
    that study rolled up in the meantime. ``expected_revision`` is checked
    against the confirmed lecture, and the draft's own ``base_revision`` is
    checked against it too — the second catches the case a client cannot see
    (its own draft was written against a lecture that has since moved).
    """
    draft = store.get_lecture_draft(path_id, knowledge_point_id, session_id=session_id)
    if draft is None:
        raise ValueError("There is no lecture draft to confirm. Write it first.")
    body = str(draft["body"] or "").strip()
    if not body:
        raise ValueError("That lecture draft is empty.")

    current = store.get_lecture(path_id, knowledge_point_id) or {}
    current_revision = int(current.get("revision") or 0)
    if expected_revision is not None and current_revision != int(expected_revision):
        raise ValueError(
            "This lecture changed while you were reading it. Reload before confirming."
        )
    base = int(draft["base_revision"] or 0)
    if base and current_revision and base != current_revision:
        raise ValueError(
            "This draft was written against an older lecture. Reload and revise again."
        )

    revision = store.save_lecture(
        path_id,
        knowledge_point_id,
        body,
        int(draft["covered_message_id"] or 0),
        source=source,
        # Optimistic, not blind: the reads above are only a friendly error
        # message. The write itself has to prove the revision it inspected is
        # still current, or two cards confirmed a second apart both "succeed"
        # and one of the two bodies silently loses.
        expected_revision=current_revision,
    )
    store.delete_lecture_draft(path_id, knowledge_point_id, session_id=draft["session_id"])
    return {
        "status": "confirmed",
        "knowledge_point_id": knowledge_point_id,
        "revision": revision,
        "source": source,
        "body": body,
    }


def abandon_lecture_draft(
    store: LearningStore,
    path_id: str,
    knowledge_point_id: str,
    *,
    session_id: str = "",
) -> dict[str, Any]:
    """Throw away an unapplied revision without touching the lecture."""
    removed = store.delete_lecture_draft(path_id, knowledge_point_id, session_id=session_id)
    return {"status": "abandoned" if removed else "nothing_to_abandon"}


def revert_lecture_confirmation(
    store: LearningStore,
    path_id: str,
    knowledge_point_id: str,
    *,
    session_id: str = "",
) -> dict[str, Any]:
    """Undo an implicit confirmation, putting its text back as a draft.

    Confirming on the learner's behalf when they walk away from a point is
    what keeps review from being empty. It is still a decision made for them,
    so it has to be reversible — and reversing it must not lose the text, so
    the draft is written *before* the confirmed row is dropped. If there is no
    conversation left to hold a draft, the confirmation is not undone at all:
    an explicit "cannot undo" beats silently deleting the only copy.
    """
    saved = store.get_lecture(path_id, knowledge_point_id)
    if saved is None or str(saved.get("source") or "") != "implicit":
        raise ValueError("Only a lecture saved automatically can be undone.")
    body = str(saved.get("body") or "")
    study_session = session_id or store.find_placed_session(path_id, "study", knowledge_point_id)
    if not study_session:
        raise ValueError(
            "This point has no study conversation left to hold the lecture, "
            "so undoing would delete the only copy."
        )
    store.save_lecture_draft(
        path_id,
        knowledge_point_id,
        session_id=study_session,
        body=body,
        base_revision=0,
        covered_message_id=int(saved.get("covered_message_id") or 0),
        diff=[],
        origin="study_roll",
    )
    store.delete_lecture(path_id, knowledge_point_id)
    return {"status": "reverted", "knowledge_point_id": knowledge_point_id}


def auto_confirm_lecture(
    path_id: str, knowledge_point_id: str, *, store: LearningStore | None = None
) -> bool:
    """Confirm whatever study rolled up, when the learner leaves the point.

    This is the answer to "what if they never press the button": they still
    walk forward, and a lecture nobody confirmed is worth less than a correct
    one marked as saved automatically. Returns whether anything was saved.
    """
    learning = store or LearningStore()
    draft = learning.get_lecture_draft(path_id, knowledge_point_id)
    if draft is None or not str(draft["body"] or "").strip():
        return False
    try:
        commit_lecture_draft(learning, path_id, knowledge_point_id, source="implicit")
    except ValueError:
        return False
    except RuntimeError:
        # A lost race with another writer (the learner's own button, or a
        # review tab) is not a failure worth surfacing: whoever won saved a
        # lecture from the same conversation.
        return False
    return True



def _new_point_names(current_ids: set[str], modules: list[dict[str, Any]]) -> list[str]:
    names: list[str] = []
    for module in modules:
        for point in module.get("knowledge_points") or []:
            if str(point.get("id") or "") not in current_ids:
                names.append(str(point.get("name") or "").strip())
    return [name for name in names if name]


def relocate_new_points(
    modules: list[dict[str, Any]],
    current_ids: set[str],
    target_module_id: str,
) -> list[dict[str, Any]]:
    """Move points the preview added into the module the learner confirmed."""
    moved: list[dict[str, Any]] = []
    placed: list[dict[str, Any]] = []
    for module in modules:
        kept = []
        for point in list(module.get("knowledge_points") or []):
            if str(point.get("id") or "") in current_ids:
                kept.append(point)
            else:
                moved.append(dict(point))
        placed.append({**module, "knowledge_points": kept})
    if not moved:
        return modules
    target = next((module for module in placed if str(module.get("id") or "") == target_module_id), None)
    if target is None:
        raise ValueError("Choose a module on this outline.")
    if len(target["knowledge_points"]) + len(moved) > _MAX_OBJECTIVES_PER_MODULE:
        raise ValueError(
            f"A module may hold at most {_MAX_OBJECTIVES_PER_MODULE} knowledge points."
        )
    target["knowledge_points"] = [*target["knowledge_points"], *moved]
    return placed


async def commit_outline_addition(
    path_id: str,
    *,
    preview_id: int,
    session_id: str,
    module_id: str,
    store: LearningStore | None = None,
) -> dict[str, Any]:
    """Save a study/review preview into the outline and note it on the outline session."""
    from deeptutor.learning.models import LearningModule
    from deeptutor.learning.service import LearningService
    from deeptutor.services.session import get_session_store

    learning = store or LearningStore()
    progress = learning.load(path_id)
    if progress is None:
        raise ValueError("Mastery topic not found")
    current_ids = {point.id for module in progress.modules for point in module.knowledge_points}
    with learning._connect() as conn:
        row = conn.execute(
            """SELECT payload_json FROM mastery_events
               WHERE id = ? AND path_id = ? AND session_id = ?
               AND event_type = 'path.modules_previewed'""",
            (int(preview_id), path_id, session_id),
        ).fetchone()
    if row is None:
        raise ValueError("Preview is unavailable in this path/session. Create a fresh preview.")
    import json

    payload = json.loads(row["payload_json"])
    modules = relocate_new_points(list(payload.get("modules") or []), current_ids, module_id)
    service = LearningService(learning)
    preview, _proposed = service.preview_module_revision(
        path_id,
        [LearningModule.model_validate(module) for module in modules],
        expected_revision=progress.version,
        session_id=session_id,
    )
    _progress, receipt = service.commit_module_revision(
        path_id,
        int(preview["preview_id"]),
        session_id=session_id,
        learner_confirmed=True,
    )
    names = _new_point_names(current_ids, modules)
    module_label = _module_name(modules, module_id) or module_id
    note = (
        f"Added {', '.join(names)} to module {module_label}."
        if names
        else f"Updated module {module_label}."
    )
    outline = await resolve_placed_session(path_id, OUTLINE, store=learning)
    await get_session_store().add_message(
        str(outline["session_id"]),
        "assistant",
        note,
        capability="mastery_path",
        metadata={"outline_addition": True, "preview_id": int(preview["preview_id"])},
    )
    return {"status": "committed", "note": note, **receipt}
