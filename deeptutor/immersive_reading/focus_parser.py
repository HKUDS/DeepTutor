"""Focus grading output parsing and normalization."""

from __future__ import annotations

from deeptutor.utils.json_parser import parse_json_response


def parse_focus_check_output(raw: str, *, passed_threshold: int) -> tuple[int, bool, str, list[str], list[str]]:
    empty_message = "The model returned an empty Focus-Check response. Please try again."
    invalid_message = "The model returned an invalid Focus-Check response. Please try again."
    invalid_score_message = "The model returned an invalid Focus-Check score. Please try again."

    if not raw or not raw.strip():
        raise RuntimeError(empty_message)

    try:
        parsed = parse_json_response(raw)
    except Exception as exc:
        raise RuntimeError(invalid_message) from exc

    if (
        not isinstance(parsed, dict)
        or not isinstance(parsed.get("passed"), bool)
        or "score" not in parsed
    ):
        raise RuntimeError(invalid_message)

    try:
        score = max(0, min(100, int(parsed["score"])))
    except (TypeError, ValueError) as exc:
        raise RuntimeError(invalid_score_message) from exc

    passed = bool(parsed.get("passed")) and score >= passed_threshold
    raw_strengths = parsed.get("strengths")
    raw_missing_points = parsed.get("missing_points")
    strengths = [str(item) for item in raw_strengths if str(item).strip()] if isinstance(raw_strengths, list) else []
    missing_points = [str(item) for item in raw_missing_points if str(item).strip()] if isinstance(raw_missing_points, list) else []
    feedback = str(parsed.get("feedback") or ("通过" if passed else "请重新阅读后再试。"))

    return score, passed, feedback, strengths, missing_points
