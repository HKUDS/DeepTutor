"""Conservative QTI scoring classification; no uploaded program is executed."""

from __future__ import annotations

from collections.abc import Mapping

from .fill_scoring import portable
from .profile import diagnostic


def classify(document: dict, score_snapshot: Mapping | None = None) -> tuple[str, dict, list[dict]]:
    kind = document["questionType"]
    responses = document["responses"]
    diagnostics: list[dict] = []
    per_response = {row["id"]: "external" for row in responses}
    if kind in {"single_choice", "multi_choice", "true_false"}:
        answer = document["author"]["correctAnswer"]
        if answer:
            # Choice all-or-nothing scoring agrees with the host only after an
            # accepted snapshot is supplied by the authority layer. Raw author
            # keys alone are not acceptance evidence.
            if score_snapshot and score_snapshot.get("choiceExactSet") is True:
                per_response = {row["id"]: "equivalent" for row in responses}
                return "equivalent", per_response, diagnostics
            diagnostics.append(
                diagnostic(
                    "SCORING_AUTHORITY_UNPROVEN",
                    "Choice key is preserved for author review; equivalent score is unproven",
                    severity="warning",
                )
            )
    elif kind == "fill_blank":
        if portable(document["author"]["fillSpec"]):
            return "equivalent", {row["id"]: "equivalent" for row in responses}, diagnostics
        diagnostics.append(
            diagnostic(
                "FILL_TRIM_NOT_PORTABLE",
                "Application normalization or semantic grading is not literal QTI mapping; external scoring remains required",
                severity="warning",
            )
        )
    else:
        diagnostics.append(
            diagnostic(
                "EXTERNAL_SCORING_REQUIRED",
                "Reference and rubric require an external scorer",
                severity="warning",
            )
        )
    return "external", per_response, diagnostics
