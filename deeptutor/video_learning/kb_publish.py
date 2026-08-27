"""Publish Immersive Watching marks into a personal knowledge base.

One Markdown learning note is kept per source video. Marks stay owner-scoped on
the TimedLearningMaterial; publishing is an explicit, idempotent copy into the
writable personal KB and never mutates Invidious.
"""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import re
from typing import Any

from deeptutor.video_learning.service import TimedMediaError

NOTE_DIR = "video-learning"
MAX_TRANSCRIPT_CHARS = 12_000
MAX_MARKS_IN_NOTE = 200


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


def _clip(value: Any, limit: int) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    return text[:limit]


def format_timestamp(seconds: float) -> str:
    total = max(0, int(round(float(seconds or 0))))
    hours, rem = divmod(total, 3600)
    minutes, secs = divmod(rem, 60)
    if hours:
        return f"{hours:d}:{minutes:02d}:{secs:02d}"
    return f"{minutes:d}:{secs:02d}"


def note_relative_path(material: dict[str, Any]) -> str:
    source = material.get("source") if isinstance(material.get("source"), dict) else {}
    provider = re.sub(r"[^a-z0-9_-]+", "-", str(source.get("provider") or "video").lower()).strip("-") or "video"
    video_id = re.sub(r"[^A-Za-z0-9_-]+", "-", str(source.get("video_id") or material.get("material_id") or "unknown")).strip("-")
    return f"{NOTE_DIR}/{provider}-{video_id}.md"


def watching_jump_url(material_id: str, start_seconds: float) -> str:
    start = max(0.0, float(start_seconds or 0.0))
    return f"/home?watching_material={material_id}&t={start:.3f}".rstrip("0").rstrip(".")


def timed_media_ref(material_id: str, start_seconds: float, end_seconds: float | None = None) -> str:
    start = max(0.0, float(start_seconds or 0.0))
    if end_seconds is None:
        return f"{material_id}#t={start:.3f}".rstrip("0").rstrip(".")
    end = max(start, float(end_seconds or start))
    return (
        f"{material_id}#t={start:.3f}-{end:.3f}"
        .replace(".000-", "-")
        .rstrip("0")
        .rstrip(".")
    )


def parse_timed_media_ref(ref: str) -> dict[str, Any] | None:
    raw = str(ref or "").strip()
    if not raw or "#t=" not in raw:
        return None
    material_id, _, stamp = raw.partition("#t=")
    material_id = material_id.strip()
    stamp = stamp.strip()
    if not material_id or not stamp:
        return None
    if "-" in stamp:
        start_raw, _, end_raw = stamp.partition("-")
    else:
        start_raw, end_raw = stamp, ""
    try:
        start = float(start_raw)
        end = float(end_raw) if end_raw else start
    except ValueError:
        return None
    return {
        "material_id": material_id,
        "start_seconds": max(0.0, start),
        "end_seconds": max(0.0, end),
    }


def _marks(material: dict[str, Any]) -> list[dict[str, Any]]:
    learning = material.get("learning") if isinstance(material.get("learning"), dict) else {}
    rows = learning.get("marks")
    if not isinstance(rows, list):
        return []
    out = [row for row in rows if isinstance(row, dict)]
    out.sort(key=lambda row: (float(row.get("start_seconds") or 0), float(row.get("end_seconds") or 0)))
    return out[:MAX_MARKS_IN_NOTE]


def content_hash(markdown: str) -> str:
    return hashlib.sha256(markdown.encode("utf-8")).hexdigest()


def render_video_learning_note(material: dict[str, Any]) -> str:
    """Render one searchable Markdown note for the current material."""
    material_id = str(material.get("material_id") or "").strip()
    if not material_id:
        raise TimedMediaError("Timed media material is missing an id.")
    source = material.get("source") if isinstance(material.get("source"), dict) else {}
    metadata = material.get("metadata") if isinstance(material.get("metadata"), dict) else {}
    transcript = material.get("transcript") if isinstance(material.get("transcript"), dict) else {}
    cues = transcript.get("cues") if isinstance(transcript.get("cues"), list) else []
    marks = _marks(material)
    title = _clip(metadata.get("title") or source.get("video_id") or material_id, 200)
    author = _clip(metadata.get("author") or "", 120)
    url = str(source.get("url") or "").strip()
    provider = str(source.get("provider") or "video")
    video_id = str(source.get("video_id") or "")
    duration = float(source.get("duration_seconds") or metadata.get("duration_seconds") or 0)

    frontmatter = {
        "deeptutor_type": "video_learning_note",
        "material_id": material_id,
        "provider": provider,
        "video_id": video_id,
        "source_url": url,
        "title": title,
        "author": author,
        "duration_seconds": duration,
        "marks": [
            {
                "id": str(row.get("mark_id") or ""),
                "kind": str(row.get("kind") or "key_point"),
                "start_seconds": float(row.get("start_seconds") or 0),
                "end_seconds": float(row.get("end_seconds") or 0),
                "quote": _clip(row.get("quote") or "", 400),
                "note": _clip(row.get("note") or "", 400),
                "ref": timed_media_ref(
                    material_id,
                    float(row.get("start_seconds") or 0),
                    float(row.get("end_seconds") or 0),
                ),
            }
            for row in marks
        ],
    }

    lines: list[str] = ["---", json.dumps(frontmatter, ensure_ascii=False, indent=2), "---", ""]
    lines.append(f"# {title}")
    lines.append("")
    meta_bits = [bit for bit in (provider, author, format_timestamp(duration) if duration else "") if bit]
    if meta_bits:
        lines.append(" · ".join(meta_bits))
        lines.append("")
    if url:
        lines.append(f"Source: [{url}]({url})")
        lines.append("")
    lines.append(
        "This note is a private DeepTutor learning export. Timestamp links open "
        "Immersive Watching and seek to the marked span."
    )
    lines.append("")

    lines.append("## Learning marks")
    lines.append("")
    if not marks:
        lines.append("_No marks yet._")
        lines.append("")
    else:
        for row in marks:
            kind = str(row.get("kind") or "key_point").replace("_", " ")
            start = float(row.get("start_seconds") or 0)
            end = float(row.get("end_seconds") or start)
            jump = watching_jump_url(material_id, start)
            lines.append(
                f"### {kind.title()} · [{format_timestamp(start)}–{format_timestamp(end)}]({jump})"
            )
            lines.append("")
            quote = _clip(row.get("quote") or "", 800)
            note = _clip(row.get("note") or "", 800)
            if quote:
                lines.append(f"> {quote}")
                lines.append("")
            if note:
                lines.append(note)
                lines.append("")
            lines.append(f"Anchor: `{timed_media_ref(material_id, start, end)}`")
            lines.append("")

    notes = material.get("learning", {}).get("notes") if isinstance(material.get("learning"), dict) else []
    if isinstance(notes, list) and notes:
        lines.append("## Viewer notes")
        lines.append("")
        for row in notes[-50:]:
            if not isinstance(row, dict):
                continue
            text = _clip(row.get("text") or "", 500)
            quote = _clip(row.get("quote") or "", 500)
            if not text:
                continue
            when = float(row.get("time_seconds") or 0)
            jump = watching_jump_url(material_id, when)
            lines.append(f"- [{format_timestamp(when)}]({jump}) {text}")
            if quote:
                lines.append(f"  > {quote}")
        lines.append("")

    transcript_bits: list[str] = []
    for cue in cues:
        if not isinstance(cue, dict):
            continue
        text = str(cue.get("text") or "").strip()
        if not text:
            continue
        start = float(cue.get("start") or 0)
        transcript_bits.append(f"[{format_timestamp(start)}]({watching_jump_url(material_id, start)}) {text}")
    transcript_body = "\n\n".join(transcript_bits)
    if len(transcript_body) > MAX_TRANSCRIPT_CHARS:
        transcript_body = transcript_body[:MAX_TRANSCRIPT_CHARS].rstrip() + "\n\n…"
    lines.append("## Transcript excerpts")
    lines.append("")
    lines.append(transcript_body or "_Transcript unavailable._")
    lines.append("")
    return "\n".join(lines)


def learning_publish_state(material: dict[str, Any]) -> dict[str, Any] | None:
    learning = material.get("learning") if isinstance(material.get("learning"), dict) else {}
    row = learning.get("kb_publish")
    return row if isinstance(row, dict) else None


async def publish_material_to_kb(
    material: dict[str, Any],
    *,
    kb_name: str = "default",
) -> dict[str, Any]:
    """Write/update the stable learning note and index it into a writable KB."""
    from deeptutor.knowledge.add_documents import add_documents
    from deeptutor.multi_user.knowledge_access import assert_writable, manager_for_resource

    resource = assert_writable(kb_name or "default")
    manager = manager_for_resource(resource)
    markdown = render_video_learning_note(material)
    digest = content_hash(markdown)
    rel_path = note_relative_path(material)
    raw_dir = manager.get_raw_path(resource.name)
    target = (raw_dir / rel_path).resolve()
    try:
        target.relative_to(raw_dir.resolve())
    except ValueError as exc:
        raise TimedMediaError("Invalid video learning note path.") from exc

    previous = learning_publish_state(material) or {}
    if (
        str(previous.get("kb_name") or "") == resource.name
        and str(previous.get("path") or "") == rel_path
        and str(previous.get("content_hash") or "") == digest
        and target.is_file()
    ):
        return {
            "material": material,
            "kb_name": resource.name,
            "kb_id": resource.id,
            "path": rel_path,
            "content_hash": digest,
            "updated": False,
            "published_at": previous.get("published_at") or utcnow(),
        }

    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(markdown, encoding="utf-8")
    indexed = await add_documents(
        kb_name=resource.name,
        source_files=[str(target)],
        base_dir=str(resource.base_dir),
        allow_duplicates=True,
    )
    published_at = utcnow()
    learning = material.setdefault("learning", {})
    if not isinstance(learning, dict):
        learning = {}
        material["learning"] = learning
    learning["kb_publish"] = {
        "kb_name": resource.name,
        "kb_id": resource.id,
        "path": rel_path,
        "title": _clip((material.get("metadata") or {}).get("title") or "", 200),
        "content_hash": digest,
        "published_at": published_at,
        "indexed_count": int(indexed or 0),
    }
    return {
        "material": material,
        "kb_name": resource.name,
        "kb_id": resource.id,
        "path": rel_path,
        "content_hash": digest,
        "updated": True,
        "published_at": published_at,
        "indexed_count": int(indexed or 0),
    }


def ideation_text_for_material(material: dict[str, Any]) -> str:
    """Compact prompt text used when creating a Book from timed media."""
    return render_video_learning_note(material)


def source_chunks_for_material(material: dict[str, Any]) -> list[dict[str, Any]]:
    material_id = str(material.get("material_id") or "")
    metadata = material.get("metadata") if isinstance(material.get("metadata"), dict) else {}
    title = str(metadata.get("title") or material_id)
    chunks: list[dict[str, Any]] = []
    for row in _marks(material):
        start = float(row.get("start_seconds") or 0)
        end = float(row.get("end_seconds") or start)
        quote = _clip(row.get("quote") or row.get("note") or title, 800)
        if not quote:
            continue
        chunks.append(
            {
                "chunk_id": f"timed::{row.get('mark_id') or timed_media_ref(material_id, start, end)}",
                "source": "timed_media",
                "ref": timed_media_ref(material_id, start, end),
                "text": quote,
                "score": 1.0,
                "query": title,
                "metadata": {
                    "material_id": material_id,
                    "kind": row.get("kind") or "key_point",
                    "start_seconds": start,
                    "end_seconds": end,
                    "jump_url": watching_jump_url(material_id, start),
                    "title": title,
                },
            }
        )
    if not chunks:
        transcript = material.get("transcript") if isinstance(material.get("transcript"), dict) else {}
        cues = transcript.get("cues") if isinstance(transcript.get("cues"), list) else []
        preview = " ".join(
            str(cue.get("text") or "").strip()
            for cue in cues[:40]
            if isinstance(cue, dict) and str(cue.get("text") or "").strip()
        )
        if preview:
            chunks.append(
                {
                    "chunk_id": f"timed::{material_id}::transcript",
                    "source": "timed_media",
                    "ref": timed_media_ref(material_id, 0.0),
                    "text": _clip(preview, 1200),
                    "score": 0.5,
                    "query": title,
                    "metadata": {
                        "material_id": material_id,
                        "kind": "transcript",
                        "start_seconds": 0.0,
                        "end_seconds": 0.0,
                        "jump_url": watching_jump_url(material_id, 0.0),
                        "title": title,
                    },
                }
            )
    return chunks


__all__ = [
    "content_hash",
    "ideation_text_for_material",
    "learning_publish_state",
    "note_relative_path",
    "parse_timed_media_ref",
    "publish_material_to_kb",
    "render_video_learning_note",
    "source_chunks_for_material",
    "timed_media_ref",
    "watching_jump_url",
]
