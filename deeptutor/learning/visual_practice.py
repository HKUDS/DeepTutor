"""Source-bound visual questions, conservative keys and explicit assistance (#1611)."""

from __future__ import annotations

from hashlib import sha256
import re
from typing import Any
import unicodedata


def normalized_answer(value: str) -> str:
    text = unicodedata.normalize("NFKC", str(value)).casefold().strip()
    return re.sub(r"\s+", " ", text).rstrip(".。!！")


def _answer_in_quote(answer: str, quote: str) -> bool:
    needle = normalized_answer(answer)
    if not needle:
        return False
    if needle.isascii():
        return re.search(r"(?<![a-z0-9])" + re.escape(needle) + r"(?![a-z0-9])", quote) is not None
    return needle in quote


def prepare_visual(
    request: dict[str, Any],
    *,
    expected_answer: str,
    options: dict[str, str],
    attached_kbs: list[str] | None = None,
    inspected_image_hashes: list[str] | None = None,
) -> tuple[dict[str, Any], list[str]]:
    from deeptutor.multi_user.knowledge_access import resolve_for_rag
    from deeptutor.services.rag.kb_paths import resolve_kb_dir
    from deeptutor.services.rag.source_visuals import retrieve_visual

    task = str(request.get("task") or "identification")
    if task not in {"identification", "relationship", "table_graph", "comparison"}:
        raise ValueError(
            "Visual tasks support identification, relationship, table_graph and comparison."
        )
    refs = request.get("sources")
    if not isinstance(refs, list) or not 1 <= len(refs) <= 2:
        raise ValueError("Select one or two exact source figures/pages; comparisons require two.")
    if task == "comparison" and len(refs) != 2:
        raise ValueError("A visual comparison requires both original sources.")
    resolved = []
    source_text = []
    for ref in refs:
        if not isinstance(ref, dict):
            raise ValueError("Each visual source must be an object.")
        kb_name = str(ref.get("kb_name") or "")
        if attached_kbs is not None and kb_name not in attached_kbs:
            raise ValueError(
                "Visual practice must use a knowledge base attached to this topic/turn."
            )
        resource = resolve_for_rag(kb_name)
        if resource is None:
            raise ValueError("The selected source knowledge base is not accessible.")
        selectors = {
            key: ref[key]
            for key in ("asset_id", "source_path", "page", "region", "source_hash", "figure")
            if ref.get(key) is not None
        }
        evidence = retrieve_visual(
            resolve_kb_dir(resource.base_dir, resource.name), kb_name, **selectors
        )
        if evidence.error or not evidence.images:
            raise ValueError(f"Cannot establish original visual evidence: {evidence.content}")
        record = evidence.images[0][0]
        resolved.append(
            {
                "kb_name": kb_name,
                "asset_id": record.get("asset_id") or "",
                "source_path": record["source_path"],
                "page": record.get("page_number"),
                "source_hash": record["source_document_id"],
                "region": record.get("region"),
                "image_url": evidence.sources[0]["visual_asset_url"],
                "url": evidence.sources[0]["url"],
                "image_sha256": sha256(evidence.images[0][1]).hexdigest(),
                "visible_answer_text": _answer_in_quote(
                    options.get(expected_answer, expected_answer),
                    normalized_answer(record.get("text", "")),
                ),
            }
        )
        source_text.append(
            "\n".join(
                str(record.get(key) or "")
                for key in ("caption", "context", "text", "page_context", "table_html", "notes")
            )
        )
    quote = str(request.get("reference_quote") or "").strip()[:3000]
    # Answer equivalences are explicit and source-specific, never fuzzy
    # substring/keyword overlap. Unknown prose is clarified, not penalized.
    correct_body = options.get(expected_answer, expected_answer)
    raw_aliases = request.get("accepted_answers") or []
    if not isinstance(raw_aliases, list) or len(raw_aliases) > 12:
        raise ValueError("accepted_answers must contain at most 12 verified equivalents.")
    aliases = list(
        dict.fromkeys(
            [correct_body, *[str(x).strip()[:200] for x in raw_aliases if str(x).strip()]]
        )
    )
    text = normalized_answer(re.sub(r"<[^>]+>", " ", "\n".join(source_text)))
    quote_normalized = normalized_answer(re.sub(r"<[^>]+>", " ", quote))
    verified = bool(
        quote_normalized
        and quote_normalized in text
        and _answer_in_quote(correct_body, quote_normalized)
        and request.get("key_status") == "verified"
    )
    cues = str(request.get("answer_cues") or "unverified")
    if cues not in {"none", "visible", "unverified"}:
        raise ValueError(
            "answer_cues must be none, visible or unverified; masking requires independently verified regions."
        )
    # Page text can reveal a table value directly. Treat it as guided reading,
    # even when the caller mistakenly declares no visible cue.
    inspected = (
        all(ref.get("image_sha256") in inspected_image_hashes for ref in resolved)
        if inspected_image_hashes is not None
        else bool(request.get("pixels_inspected"))
    )
    if not inspected:
        verified = False
        cues = "unverified"
    elif any(
        ref.get("page")
        and not ref.get("asset_id")
        and (not ref.get("region") or ref.get("visible_answer_text"))
        for ref in resolved
    ):
        cues = "visible"
    return {
        "task": task,
        "sources": resolved,
        "answer_cues": cues,
        "key_status": "verified" if verified else "unverified",
        "pixels_inspected": inspected,
        "reference_quote": quote,
        "reference_answer": correct_body,
        "hints_used": max(int(request.get("hints_used") or 0), int(cues != "none")),
    }, aliases


def public_visual(context: dict[str, Any]) -> dict[str, Any]:
    return {
        key: context[key]
        for key in (
            "task",
            "sources",
            "answer_cues",
            "key_status",
            "hints_used",
            "pixels_inspected",
        )
        if key in context
    }


def account_for_recent_assistance(context: dict[str, Any], attempts, kp_id: str) -> dict[str, Any]:
    """Use the existing retention session boundary, not a visual scheduler."""
    import time

    from deeptutor.learning.scheduler import _SAME_SESSION_DAYS

    def locations(visual):
        return {(ref.get("source_hash"), ref.get("page")) for ref in visual.get("sources", [])}

    current = locations(context)
    for attempt in reversed(attempts):
        prior = attempt.visual_context
        if (
            not attempt.voided
            and attempt.knowledge_point_id == kp_id
            and (
                prior.get("hints_used")
                or (
                    normalized_answer(prior.get("reference_quote", ""))
                    == normalized_answer(context.get("reference_quote", ""))
                    and normalized_answer(prior.get("reference_answer", ""))
                    == normalized_answer(context.get("reference_answer", ""))
                )
            )
            and prior.get("task") == context.get("task")
            and locations(prior) == current
            and time.time() - attempt.timestamp < _SAME_SESSION_DAYS * 86400
        ):
            return {
                **context,
                "hints_used": max(1, context.get("hints_used", 0)),
                "recently_assisted": True,
            }
    return context


def evaluate_visual(pending, answer: str) -> tuple[str, str]:
    """Return (result, diagnosis); uncertainty produces no mastery evidence."""
    from deeptutor.multi_user.knowledge_access import resolve_for_rag
    from deeptutor.services.rag.kb_paths import resolve_kb_dir
    from deeptutor.services.rag.source_visuals import retrieve_visual

    visual = pending.visual_context
    if not visual.get("pixels_inspected"):
        return (
            "ungraded",
            "No matching source pixels were verified in the tutor's model input. Re-retrieve the original image with a vision-capable model; this attempt does not lower mastery.",
        )
    if visual.get("key_status") != "verified" or not visual.get("sources"):
        return (
            "ungraded",
            "The reference key is not independently supported by source text; clarify it before grading.",
        )
    for ref in visual.get("sources", []):
        resource = resolve_for_rag(ref["kb_name"])
        if resource is None:
            return "ungraded", "Source access is unavailable; this attempt does not lower mastery."
        selectors = {
            key: ref[key]
            for key in ("asset_id", "source_path", "page", "region", "source_hash")
            if ref.get(key) not in (None, "")
        }
        evidence = retrieve_visual(
            resolve_kb_dir(resource.base_dir, resource.name), ref["kb_name"], **selectors
        )
        if evidence.error or not evidence.images:
            return (
                "ungraded",
                "Original source evidence changed or is unavailable; clarify the source before assessment.",
            )
    normalized = normalized_answer(answer)
    aliases = {normalized_answer(alias) for alias in pending.accepted_answers}
    if normalized in aliases:
        return "correct", "Accepted source-specific equivalent terminology."
    if pending.question_type == "choice":
        from deeptutor.learning.pending import is_readable_choice_answer, resolve_choice_submission

        if not is_readable_choice_answer(answer, pending.choice_map):
            return "ungraded", "Clarify the selected answer before assessing it."
        label = resolve_choice_submission(answer, pending.choice_map)
        if label:
            return (
                "correct" if label == pending.expected_answer else "incorrect"
            ), "Compare the chosen answer with the original source evidence."
    return (
        "ungraded",
        "This wording is not a verified equivalent. Ask for clarification or repair the reference; do not infer a wrong answer from surface similarity.",
    )
