"""Canonical QTI item preflight and deterministic identity mapping."""

from __future__ import annotations

from collections.abc import Mapping
import hashlib
import re
from urllib.parse import urlsplit

from deeptutor.services.question_content.core import normalize_question_document

from .fill_scoring import xml_text
from .profile import diagnostic
from .scoring import classify

_QTI_ID = re.compile(r"^[A-Za-z_][A-Za-z0-9_.-]{0,199}$")


def qti_id(value: str, *, prefix: str) -> str:
    if _QTI_ID.fullmatch(value):
        return value
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()[:20]
    return f"{prefix}_{digest}"


def preflight(
    document: dict,
    *,
    asset_paths: Mapping[str, str] | None = None,
    score_snapshot: dict | None = None,
) -> dict:
    diagnostics: list[dict] = []
    try:
        doc = normalize_question_document(document, source_format="content-v1")
    except ValueError as exc:
        return {
            "content": "blocked",
            "scoring": "unavailable",
            "bankAdmission": "blocked",
            "diagnostics": [diagnostic("CANONICAL_INVALID", str(exc))],
            "responseScoring": {},
        }
    if doc["questionType"] == "coding":
        diagnostics.append(
            diagnostic(
                "INTERACTION_UNSUPPORTED", "Coding interaction is outside the QTI 3 item profile"
            )
        )
    # v1 can represent ordered text and prompt images. Its flat bank consumer
    # cannot preserve arbitrary rich or language-tagged parts.
    for name, parts in [
        ("body", doc["body"]),
        *[(f"material:{m['id']}", m["body"]) for m in doc["materials"]],
    ]:
        for part in parts:
            if part["kind"] in {"math", "code", "audio", "video"} or "language" in part:
                diagnostics.append(
                    diagnostic(
                        "CONTENT_PART_UNREPRESENTABLE",
                        f"{name} part has no proven QTI/bank roundtrip",
                        location=name,
                    )
                )
            if part["kind"] == "image" and (not asset_paths or part["assetId"] not in asset_paths):
                diagnostics.append(
                    diagnostic(
                        "PROMPT_ASSET_UNRESOLVED", "Prompt image is not verified", location=name
                    )
                )
    if (
        not doc["body"]
        or doc["body"][0]["kind"] != "text"
        or any(part["kind"] != "image" for part in doc["body"][1:])
    ):
        diagnostics.append(
            diagnostic(
                "BODY_FLAT_PROJECTION_BLOCKED",
                "Bank body needs text followed only by prompt images",
            )
        )
    if len(doc["materials"]) > 1 or any(
        m["role"] != "shared_context"
        or m.get("visibility", "learner") != "learner"
        or len(m["body"]) != 1
        or m["body"][0]["kind"] != "text"
        for m in doc["materials"]
    ):
        diagnostics.append(
            diagnostic(
                "MATERIAL_HIERARCHY_UNREPRESENTABLE", "Bank cannot preserve this material hierarchy"
            )
        )
    if any(a["role"] == "prompt" and a["kind"] != "image" for a in doc["assets"]):
        diagnostics.append(
            diagnostic("PROMPT_MEDIA_UNSUPPORTED", "Only verified prompt images are supported")
        )
    if any(
        a["role"] == "prompt"
        and a["kind"] == "image"
        and a["mimeType"] not in {"image/png", "image/jpeg", "image/webp"}
        for a in doc["assets"]
    ):
        diagnostics.append(
            diagnostic(
                "PROMPT_IMAGE_MIME_UNSUPPORTED",
                "Only PNG, JPEG and WebP prompt images are supported",
            )
        )
    if any(
        a["role"] == "prompt" and (not asset_paths or a["id"] not in asset_paths)
        for a in doc["assets"]
    ):
        diagnostics.append(diagnostic("PROMPT_ASSET_UNRESOLVED", "Prompt asset path is missing"))
    for href in (asset_paths or {}).values():
        if (
            not isinstance(href, str)
            or not href
            or href.startswith(("/", "\\"))
            or "\\" in href
            or "%" in href
            or urlsplit(href).scheme
            or urlsplit(href).netloc
            or urlsplit(href).query
            or urlsplit(href).fragment
        ):
            diagnostics.append(diagnostic("PROMPT_ASSET_PATH_INVALID", "Unsafe prompt image href"))
    if any(part["kind"] == "image" for part in doc["body"]):
        diagnostics.append(
            diagnostic(
                "IMAGE_DESCRIPTION_UNAVAILABLE",
                "Canonical v1 has no image description; export uses a neutral image label",
                severity="warning",
            )
        )
    if doc["questionType"] in {"single_choice", "multi_choice"} and any(
        option["id"] not in "ABCDEFGHIJ" or len(option["id"]) != 1
        for option in doc["interactions"][0]["options"]
    ):
        diagnostics.append(diagnostic("BANK_OPTION_ID_UNSUPPORTED", "Bank option IDs must be A–J"))
    if doc["questionType"] == "true_false" and doc["interactions"][0]["options"] not in (
        [],
        [{"id": "T", "text": "True"}, {"id": "F", "text": "False"}],
    ):
        # Only a canonical T/F order is safe; localization is a presentation concern.
        if [o["id"] for o in doc["interactions"][0]["options"]] != ["T", "F"]:
            diagnostics.append(
                diagnostic("TRUE_FALSE_OPTION_UNSUPPORTED", "True/false needs T/F options")
            )
    if doc["author"]["fillSpec"] is not None and any(
        not xml_text(answer["value"])
        for blank in doc["author"]["fillSpec"]["blanks"]
        for answer in blank["accepted_answers"]
    ):
        diagnostics.append(
            diagnostic(
                "FILL_XML_TEXT_UNREPRESENTABLE", "A fill answer contains characters outside XML 1.0"
            )
        )
    score, response_score, score_diags = classify(doc, score_snapshot)
    diagnostics.extend(score_diags)
    blocked = any(d["severity"] == "error" for d in diagnostics)
    answer = doc["author"]["correctAnswer"].strip()
    spec = doc["author"]["fillSpec"]
    admission = "blocked" if blocked else "ready" if answer or spec else "review"
    return {
        "content": "blocked" if blocked else "supported",
        "scoring": score,
        "bankAdmission": admission,
        "diagnostics": diagnostics,
        "responseScoring": response_score,
    }
