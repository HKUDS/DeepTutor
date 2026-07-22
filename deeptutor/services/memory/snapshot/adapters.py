"""Workspace → ``Entity`` adapters.

One pure read-only function per surface. Adapters never mutate
workspace state. They read whatever lives under
``data/user/workspace/`` (or, for chat/quiz, the chat history SQLite
DB; for kb-list, the kb config JSON; for the ``partner`` surface, the
per-partner conversation JSONL under ``data/partners/``).

Each adapter returns a ``list[Entity]`` with stable ``id`` and a
deterministic ``fingerprint`` so the diff engine can detect changes
across refreshes.
"""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import logging
import sqlite3

from deeptutor.services.memory.paths import Surface
from deeptutor.services.memory.snapshot.entity import Entity
from deeptutor.services.path_service import get_path_service

logger = logging.getLogger(__name__)


# ── Helpers ──────────────────────────────────────────────────────────


def _sha1(*parts: object) -> str:
    h = hashlib.sha1(usedforsecurity=False)
    for part in parts:
        if part is None:
            continue
        if isinstance(part, (dict, list)):
            blob = json.dumps(part, sort_keys=True, ensure_ascii=False)
        else:
            blob = str(part)
        h.update(blob.encode("utf-8"))
        h.update(b"\0")
    return h.hexdigest()[:16]


def _iso(ts: float | int | str | None) -> str:
    if isinstance(ts, str):
        try:
            datetime.fromisoformat(ts.replace("Z", "+00:00"))
            return ts
        except Exception:
            pass
    if isinstance(ts, (int, float)):
        try:
            return datetime.fromtimestamp(float(ts), tz=timezone.utc).isoformat()
        except Exception:
            pass
    return ""


# ── Adapters ─────────────────────────────────────────────────────────


def read_notebook_entities() -> list[Entity]:
    ps = get_path_service()
    index_file = ps.get_notebook_index_file()
    if not index_file.exists():
        return []
    try:
        index = json.loads(index_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    notebooks = index.get("notebooks") or []
    out: list[Entity] = []
    for nb in notebooks:
        if not isinstance(nb, dict):
            continue
        nb_id = nb.get("id")
        nb_name = nb.get("name") or nb_id
        if not nb_id:
            continue
        nb_file = ps.get_notebook_file(nb_id)
        if not nb_file.exists():
            continue
        try:
            nb_data = json.loads(nb_file.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        for r in nb_data.get("records") or []:
            if not isinstance(r, dict):
                continue
            rid = r.get("id")
            if not rid:
                continue
            title = r.get("title", "") or ""
            user_query = r.get("user_query", "") or ""
            output = r.get("output", "") or ""
            summary = r.get("summary", "") or ""
            content = "\n\n".join(
                part
                for part in (
                    f"# {title}" if title else "",
                    f"**User query**: {user_query}" if user_query else "",
                    f"**Summary**: {summary}" if summary else "",
                    output,
                )
                if part
            )
            out.append(
                Entity(
                    id=rid,
                    label=f"{title} · {nb_name}" if title else f"({rid}) · {nb_name}",
                    ts=_iso(r.get("created_at")),
                    content=content,
                    metadata={
                        "notebook_id": nb_id,
                        "notebook_name": nb_name,
                        "record_type": r.get("record_type", ""),
                        "kb_name": r.get("kb_name"),
                    },
                    fingerprint=_sha1(title, user_query, output, summary),
                )
            )
    return out


def read_cowriter_entities() -> list[Entity]:
    docs_dir = get_path_service().get_co_writer_docs_dir()
    if not docs_dir.exists():
        return []
    out: list[Entity] = []
    for entry in sorted(docs_dir.iterdir()):
        manifest = entry / "manifest.json"
        if not manifest.exists():
            continue
        try:
            m = json.loads(manifest.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        doc_id = m.get("id")
        if not doc_id:
            continue
        title = m.get("title", "") or ""
        content = m.get("content", "") or ""
        out.append(
            Entity(
                id=doc_id,
                label=title or doc_id,
                ts=_iso(m.get("updated_at") or m.get("created_at")),
                content=content,
                metadata={"doc_id": doc_id, "title": title},
                fingerprint=_sha1(title, content),
            )
        )
    return out


def read_book_entities() -> list[Entity]:
    books_dir = get_path_service().get_book_dir()
    if not books_dir.exists():
        return []
    out: list[Entity] = []
    for entry in sorted(books_dir.iterdir()):
        if not entry.is_dir():
            continue
        manifest_path = entry / "manifest.json"
        if not manifest_path.exists():
            continue
        try:
            m = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        book_id = m.get("id")
        if not book_id:
            continue
        title = m.get("title", "") or ""
        description = m.get("description", "") or ""
        # Pull page titles + chapter outline from spine for L2 to chew on.
        spine_path = entry / "spine.json"
        page_titles: list[str] = []
        if spine_path.exists():
            try:
                spine = json.loads(spine_path.read_text(encoding="utf-8"))
                page_titles = [
                    str(p.get("title") or p.get("id") or "")
                    for p in (spine.get("pages") or [])
                    if isinstance(p, dict)
                ]
            except (OSError, json.JSONDecodeError):
                page_titles = []
        content = "\n\n".join(
            part
            for part in (
                f"# {title}",
                description,
                "## Pages\n" + "\n".join(f"- {p}" for p in page_titles) if page_titles else "",
            )
            if part
        )
        out.append(
            Entity(
                id=book_id,
                label=title or book_id,
                ts=_iso(m.get("updated_at") or m.get("created_at")),
                content=content,
                metadata={
                    "book_id": book_id,
                    "page_count": m.get("page_count", 0),
                    "chapter_count": m.get("chapter_count", 0),
                    "knowledge_bases": m.get("knowledge_bases", []),
                    "status": m.get("status", ""),
                },
                fingerprint=_sha1(title, description, m.get("updated_at"), len(page_titles)),
            )
        )
    return out


def _partner_display_name(partner_dir, partner_id: str) -> str:
    """Read ``name`` out of a partner's ``config.yaml`` for tagging.

    Falls back to the directory id when the config is missing or unreadable.
    """
    cfg = partner_dir / "config.yaml"
    if not cfg.exists():
        return partner_id
    try:
        import yaml

        data = yaml.safe_load(cfg.read_text(encoding="utf-8")) or {}
    except Exception:
        return partner_id
    if isinstance(data, dict):
        name = data.get("name")
        if isinstance(name, str) and name.strip():
            return name.strip()
    return partner_id


def _partner_session_entity(path, partner_id: str, partner_name: str) -> Entity | None:
    """Build one Entity from a partner session JSONL file.

    The conversation is inlined as ``user / assistant`` blocks (mirroring
    :func:`read_chat_entities`) so L2 sees the actual dialogue, and the
    originating partner is tagged into both the label and the metadata so
    the consolidator carries provenance into L2/L3.
    """
    records: list[dict] = []
    try:
        with path.open("r", encoding="utf-8") as fh:
            for raw in fh:
                raw = raw.strip()
                if not raw:
                    continue
                try:
                    obj = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                if isinstance(obj, dict):
                    records.append(obj)
    except OSError:
        return None

    blocks: list[str] = []
    for r in records:
        role = r.get("role") or ""
        body = (r.get("content") or "").strip()
        if not body:
            continue
        blocks.append(f"### {role}\n{body}")
    if not blocks:
        return None

    session_key = path.stem
    archived = session_key.startswith("_archived_")
    last = records[-1]
    last_ts = last.get("timestamp", "")
    last_content = last.get("content", "")
    return Entity(
        id=f"{partner_id}:{session_key}",
        label=f"{session_key} · {partner_name}",
        ts=_iso(last_ts),
        content="\n\n".join(blocks),
        metadata={
            "partner_id": partner_id,
            "partner_name": partner_name,
            "session_key": session_key,
            "archived": archived,
            "message_count": len(blocks),
        },
        fingerprint=_sha1(len(blocks), last_ts, last_content),
    )


def read_partner_entities() -> list[Entity]:
    """One Entity per partner conversation *session* (archived + active),
    tagged with the originating partner. Surfaced under the ``partner``
    surface (UI label "伙伴").

    Partner runtimes persist conversations as JSONL under
    ``data/partners/<id>/sessions/*.jsonl`` — a store entirely separate from
    the chat-history SQLite DB the ``chat`` adapter reads. This adapter
    bridges that store into the memory pipeline so partner conversations
    consolidate into L2/L3 like every other surface.

    Partners are anchored to the admin workspace, so we only surface them
    when the active scope IS the admin's own memory; a regular user's memory
    view must not see the admin's partner conversations.
    """
    from deeptutor.multi_user.paths import get_admin_path_service

    admin_root = get_admin_path_service().workspace_root.resolve()
    if get_path_service().workspace_root.resolve() != admin_root:
        return []
    partners_root = admin_root / "partners"
    if not partners_root.exists():
        return []

    out: list[Entity] = []
    for partner_dir in sorted(partners_root.iterdir()):
        if not partner_dir.is_dir():
            continue
        sessions_dir = partner_dir / "sessions"
        if not sessions_dir.is_dir():
            continue
        partner_id = partner_dir.name
        partner_name = _partner_display_name(partner_dir, partner_id)
        for sess_file in sorted(sessions_dir.glob("*.jsonl")):
            entity = _partner_session_entity(sess_file, partner_id, partner_name)
            if entity is not None:
                out.append(entity)
    return out


def read_kb_entities() -> list[Entity]:
    """KB *list* snapshot — one Entity per registered knowledge base.

    KB queries stay event-driven and live in the trace store; the L2
    consolidator combines both signals.
    """
    kb_root = get_path_service().get_knowledge_bases_root()
    cfg_file = kb_root / "kb_config.json"
    if not cfg_file.exists():
        return []
    try:
        cfg = json.loads(cfg_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    kbs = cfg.get("knowledge_bases") or {}
    if not isinstance(kbs, dict):
        return []
    out: list[Entity] = []
    for kb_name, kb_data in sorted(kbs.items()):
        if not isinstance(kb_name, str):
            continue
        if not isinstance(kb_data, dict):
            kb_data = {}
        description = kb_data.get("description", "") or ""
        versions = kb_data.get("index_versions") or []
        sigs = sorted(v.get("signature", "") for v in versions if isinstance(v, dict))
        earliest_created = min(
            (
                v.get("created_at", "")
                for v in versions
                if isinstance(v, dict) and v.get("created_at")
            ),
            default="",
        )
        content = "\n\n".join(
            part
            for part in (
                f"# {kb_name}",
                description,
                f"Index versions: {len(versions)}",
            )
            if part
        )
        out.append(
            Entity(
                id=kb_name,
                label=kb_name,
                ts=earliest_created,
                content=content,
                metadata={
                    "kb_name": kb_name,
                    "version_count": len(versions),
                    "rag_provider": kb_data.get("rag_provider", ""),
                },
                fingerprint=_sha1(description, sigs),
            )
        )
    return out


def read_chat_entities() -> list[Entity]:
    """One Entity per chat session. ``content`` inlines all turns as
    ``user / assistant`` blocks so L2 sees the actual conversation."""
    db_path = get_path_service().get_chat_history_db()
    if not db_path.exists():
        return []
    out: list[Entity] = []
    try:
        with sqlite3.connect(f"file:{db_path}?mode=ro", uri=True) as conn:
            conn.row_factory = sqlite3.Row
            sessions = conn.execute(
                "SELECT id, title, created_at, updated_at FROM sessions ORDER BY updated_at DESC"
            ).fetchall()
            for sess in sessions:
                sid = sess["id"]
                msgs = conn.execute(
                    "SELECT id, role, content, capability, created_at "
                    "FROM messages WHERE session_id = ? "
                    "ORDER BY created_at ASC, id ASC",
                    (sid,),
                ).fetchall()
                blocks: list[str] = []
                for m in msgs:
                    role = m["role"]
                    body = (m["content"] or "").strip()
                    if not body:
                        continue
                    blocks.append(f"### {role}\n{body}")
                content = "\n\n".join(blocks)
                last_msg_id = msgs[-1]["id"] if msgs else 0
                out.append(
                    Entity(
                        id=sid,
                        label=sess["title"] or sid,
                        ts=_iso(sess["updated_at"]),
                        content=content,
                        metadata={
                            "session_id": sid,
                            "message_count": len(msgs),
                        },
                        fingerprint=_sha1(last_msg_id, sess["updated_at"]),
                    )
                )
    except sqlite3.Error as exc:
        logger.warning("chat snapshot scan failed: %s", exc)
        return []
    return out


def read_quiz_entities() -> list[Entity]:
    """One Entity per recorded quiz attempt (notebook_entries row)."""
    db_path = get_path_service().get_chat_history_db()
    if not db_path.exists():
        return []
    out: list[Entity] = []
    try:
        with sqlite3.connect(f"file:{db_path}?mode=ro", uri=True) as conn:
            conn.row_factory = sqlite3.Row
            rows = conn.execute(
                "SELECT id, session_id, turn_id, question_id, question, "
                "question_type, options_json, correct_answer, explanation, "
                "difficulty, user_answer, is_correct, bookmarked, "
                "created_at FROM notebook_entries "
                "ORDER BY created_at DESC"
            ).fetchall()
            for r in rows:
                qid = r["question_id"] or f"row_{r['id']}"
                entity_id = f"{r['session_id']}:{qid}"
                question = (r["question"] or "").strip()
                user_answer = (r["user_answer"] or "").strip()
                correct = (r["correct_answer"] or "").strip()
                explanation = (r["explanation"] or "").strip()
                is_correct = bool(int(r["is_correct"] or 0))
                content = "\n\n".join(
                    part
                    for part in (
                        f"**Question**: {question}" if question else "",
                        f"**User answer**: {user_answer}" if user_answer else "",
                        f"**Correct answer**: {correct}" if correct else "",
                        f"**Explanation**: {explanation}" if explanation else "",
                    )
                    if part
                )
                out.append(
                    Entity(
                        id=entity_id,
                        label=question[:80] or qid,
                        ts=_iso(r["created_at"]),
                        content=content,
                        metadata={
                            "session_id": r["session_id"],
                            "turn_id": r["turn_id"],
                            "question_id": qid,
                            "question_type": r["question_type"],
                            "difficulty": r["difficulty"],
                            "is_correct": is_correct,
                            "bookmarked": bool(int(r["bookmarked"] or 0)),
                        },
                        fingerprint=_sha1(question, user_answer, correct, is_correct),
                    )
                )
    except sqlite3.Error as exc:
        logger.warning("quiz snapshot scan failed: %s", exc)
        return []
    return out


# ── Dispatch ─────────────────────────────────────────────────────────


_READERS = {
    "notebook": read_notebook_entities,
    "cowriter": read_cowriter_entities,
    "book": read_book_entities,
    "partner": read_partner_entities,
    "kb": read_kb_entities,
    "chat": read_chat_entities,
    "quiz": read_quiz_entities,
}


def read_entities(surface: Surface) -> list[Entity]:
    reader = _READERS.get(surface)
    if reader is None:
        return []
    try:
        return reader()
    except Exception as exc:
        logger.warning("snapshot adapter failed surface=%s: %s", surface, exc)
        return []


SUPPORTED_SURFACES: tuple[Surface, ...] = tuple(_READERS.keys())  # type: ignore[arg-type,assignment]
