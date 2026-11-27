"""Versioned, conservative source and answer contracts for fill-in-blank practice."""

from __future__ import annotations

from collections.abc import Mapping
from decimal import Decimal
import hashlib
import json
import math
import re
from typing import Any

POLICY_VERSION = "fill-grading/v2"
_BLANK_ID = re.compile(r"^[A-Za-z0-9_-]{1,80}$")
_POLICIES = {"comparison_v1", "numeric_text_v1", "exact_v1", "semantic_v1"}
_NUMERIC = re.compile(r"^[+-]?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?$")
_MAX_ANSWER_BYTES = 20_000
_MAX_CANONICAL_VALUE_BYTES = 200_000
_MAX_SPEC_BYTES = 16_384
_JS_TRIM = "\u0009\u000a\u000b\u000c\u000d\u0020\u00a0\u1680\u2000-\u200a\u2028\u2029\u202f\u205f\u3000\ufeff"
_TRIM_START = re.compile(rf"^[{_JS_TRIM}]+")
_TRIM_END = re.compile(rf"[{_JS_TRIM}]+$")


def _utf8(value: Any, field: str, limit: int, *, nonblank: bool = False) -> str:
    if not isinstance(value, str):
        raise ValueError(f"Invalid {field}")
    try:
        encoded = value.encode("utf-8", errors="strict")
    except UnicodeEncodeError as exc:
        raise ValueError(f"Invalid Unicode in {field}") from exc
    if len(encoded) > limit or (nonblank and not _trim(value)):
        raise ValueError(f"Invalid {field}")
    return value


def _trim(value: str) -> str:
    return _TRIM_END.sub("", _TRIM_START.sub("", value))


def canonical_json(value: Any) -> str:
    """Compact UTF-8 JSON using the protocol's ASCII-key/codepoint ordering."""

    def validate(item: Any) -> None:
        if item is None or isinstance(item, bool):
            return
        if isinstance(item, str):
            _utf8(item, "canonical string", _MAX_CANONICAL_VALUE_BYTES)
            return
        if isinstance(item, int):
            if abs(item) > 2**53 - 1:
                raise ValueError("Invalid canonical integer")
            return
        if isinstance(item, list):
            for child in item:
                validate(child)
            return
        if isinstance(item, dict):
            for key, child in item.items():
                if not isinstance(key, str) or not key.isascii():
                    raise ValueError("Canonical keys must be ASCII")
                validate(child)
            return
        raise ValueError("Invalid canonical value")

    validate(value)
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    )


POLICY_VERSION_V2 = "fill-grading/v2"
_POINTS = re.compile(r"(?:0|[1-9][0-9]*)\.[0-9]{5}\Z")


def point_units(value: Any) -> int:
    """Parse canonical five-place points without binary floating arithmetic."""
    if not isinstance(value, str) or not _POINTS.fullmatch(value):
        raise ValueError("Invalid fill points")
    whole, fraction = value.split(".")
    units = int(whole) * 100_000 + int(fraction)
    if units > 2**53 - 1:
        raise ValueError("Invalid fill points")
    return units


def point_string(units: int) -> str:
    if type(units) is not int or not 0 <= units <= 2**53 - 1:
        raise ValueError("Invalid fill point units")
    return f"{units // 100_000}.{units % 100_000:05d}"


def _match_key(policy: str, value: str) -> str:
    if policy == "qti_literal_v1":
        return value
    token = _trim(value)
    if policy == "comparison_v1":
        token = {"＜": "<", "＞": ">", "＝": "="}.get(token, token)
        if token not in {"<", ">", "="}:
            raise ValueError("Invalid comparison answer")
    elif policy == "numeric_text_v1" and not _NUMERIC.fullmatch(token):
        raise ValueError("Invalid numeric answer")
    return token


def normalize_fill_spec(value: Any) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise ValueError("Invalid fill specification")
    if (
        set(value) != {"version", "policy_version", "blanks"}
        or type(value["version"]) is not int
        or value["version"] != 2
        or value["policy_version"] != POLICY_VERSION_V2
    ):
        raise ValueError("Unsupported fill specification")
    blanks = value["blanks"]
    if not isinstance(blanks, list) or not 1 <= len(blanks) <= 20:
        raise ValueError("A fill specification needs 1–20 blanks")
    seen = set()
    normalized = []
    for blank in blanks:
        if not isinstance(blank, dict) or set(blank) != {
            "id",
            "label",
            "max_score",
            "accepted_answers",
            "comparison_policy",
            "rubric",
        }:
            raise ValueError("Invalid fill blank")
        bid = blank["id"]
        if not isinstance(bid, str) or not _BLANK_ID.fullmatch(bid) or bid in seen:
            raise ValueError("Invalid or duplicate blank ID")
        seen.add(bid)
        maximum = point_units(blank["max_score"])
        if not 0 < maximum <= 100_000_000:
            raise ValueError("Invalid blank maximum score")
        policy = blank["comparison_policy"]
        if not isinstance(policy, str) or policy not in _POLICIES | {"qti_literal_v1"}:
            raise ValueError("Unsupported fill grading policy")
        label = _utf8(blank["label"], "blank label", 120)
        rubric = _utf8(blank["rubric"], "blank rubric", 2_000)
        answers = blank["accepted_answers"]
        if not isinstance(answers, list) or not 1 <= len(answers) <= 20:
            raise ValueError("A fill blank needs 1–20 accepted answers")
        keys = set()
        accepted = []
        for answer in answers:
            if not isinstance(answer, dict) or set(answer) != {"value", "score"}:
                raise ValueError("Invalid scored fill answer")
            text = _utf8(answer["value"], "accepted answer", 2_000, nonblank=True)
            units = point_units(answer["score"])
            if units > maximum:
                raise ValueError("Fill answer score exceeds blank maximum")
            key = _match_key(policy, text)
            if key in keys:
                raise ValueError("Duplicate matching fill answer")
            keys.add(key)
            accepted.append({"value": text, "score": answer["score"]})
        if not any(point_units(answer["score"]) == maximum for answer in accepted):
            raise ValueError("Fill blank requires a full-credit answer")
        normalized.append(
            {
                "id": bid,
                "label": label,
                "max_score": blank["max_score"],
                "accepted_answers": accepted,
                "comparison_policy": policy,
                "rubric": rubric,
            }
        )
    result = {"version": 2, "policy_version": POLICY_VERSION_V2, "blanks": normalized}
    if len(canonical_json(result).encode("utf-8")) > _MAX_SPEC_BYTES:
        raise ValueError("Fill specification exceeds size limit")
    return result


def ratio_string(value: int | float | None) -> str | None:
    """Use the receipt's existing JS-compatible full-precision number spelling."""
    return _js_number_string(value)


def _ratio_number(value: Any) -> float:
    if isinstance(value, bool) or not isinstance(value, (str, int, float)):
        raise ValueError("Invalid fill ratio")
    if isinstance(value, str) and not re.fullmatch(
        r"(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:e-?[0-9]+)?", value
    ):
        raise ValueError("Invalid fill ratio")
    try:
        number = float(value)
    except ValueError as exc:
        raise ValueError("Invalid fill ratio") from exc
    if (
        not math.isfinite(number)
        or not 0 <= number <= 1
        or number == 0
        and math.copysign(1, number) < 0
    ):
        raise ValueError("Invalid fill ratio")
    return number


def ratio_point_units(maximum: int, ratio: Any) -> int:
    number = _ratio_number(ratio)
    if isinstance(ratio, str) and ratio != ratio_string(number):
        raise ValueError("Invalid canonical fill ratio")
    units = math.floor(number * maximum + 0.5)
    if abs(number - units / maximum) > 1e-12:
        raise ValueError("Fill ratio does not represent exact points")
    return units


def quantize_semantic_ratio(blank: Mapping[str, Any], ratio: Any) -> float:
    maximum = point_units(blank["max_score"])
    units = math.floor(_ratio_number(ratio) * maximum + 0.5)
    return units / maximum


def aggregate_fill_scores(spec_value: Any, rows_value: Any) -> dict[str, Any]:
    """Validate ordered observations and derive safe points without answer keys."""
    spec = normalize_fill_spec(spec_value)
    if not isinstance(rows_value, list) or len(rows_value) != len(spec["blanks"]):
        raise ValueError("Incomplete fill results")
    points = []
    maxima = []
    review = False
    for blank, row in zip(spec["blanks"], rows_value, strict=True):
        if not isinstance(row, Mapping) or row.get("blank_id", row.get("blankId")) != blank["id"]:
            raise ValueError("Fill result IDs must match source order")
        maximum = point_units(blank["max_score"])
        maxima.append(maximum)
        outcome = row.get("outcome")
        needs_review = row.get("needs_human_review", row.get("needsHumanReview", False))
        if type(needs_review) is not bool or outcome not in {
            "correct",
            "partial",
            "incorrect",
            "ungradable",
        }:
            raise ValueError("Invalid fill result")
        if outcome == "ungradable":
            if row.get("score") is not None or not needs_review:
                raise ValueError("Invalid ungradable fill result")
            earned = None
        else:
            number = _ratio_number(row.get("score"))
            if (
                outcome == "correct"
                and number != 1
                or outcome == "incorrect"
                and number != 0
                or outcome == "partial"
                and not 0 < number < 1
            ):
                raise ValueError("Inconsistent fill outcome")
            earned = ratio_point_units(maximum, row.get("score"))
        review = review or needs_review or outcome == "ungradable"
        points.append(earned)
    maximum_total = sum(maxima)
    earned_total = None if review else sum(points)
    outcome = (
        "ungradable"
        if review
        else "correct"
        if all(row["outcome"] == "correct" for row in rows_value)
        else "incorrect"
        if all(row["outcome"] == "incorrect" for row in rows_value)
        else "partial"
    )
    score = None if review else earned_total / maximum_total
    return {
        "outcome": outcome,
        "score": score,
        "needs_human_review": review,
        "earned_score": None if earned_total is None else point_string(earned_total),
        "max_score": point_string(maximum_total),
        "per_blank": [
            {
                "blank_id": blank["id"],
                "earned_score": None if earned is None else point_string(earned),
                "max_score": point_string(maximum),
            }
            for blank, earned, maximum in zip(spec["blanks"], points, maxima, strict=True)
        ],
    }


def legacy_single_blank_spec(question_type: str, correct_answer: str) -> dict[str, Any] | None:
    """Build a safe synthetic slot for legacy single blanks, never split the key."""
    if question_type not in {"fill_blank", "fill_in_blank"}:
        return None
    _utf8(correct_answer, "reference answer", 100_000, nonblank=True)
    token = _trim(correct_answer)
    if token in {"<", ">", "=", "＜", "＞", "＝"}:
        policy = "comparison_v1"
    elif _NUMERIC.fullmatch(token):
        policy = "numeric_text_v1"
    else:
        policy = "semantic_v1"
    return normalize_fill_spec(
        {
            "version": 2,
            "policy_version": POLICY_VERSION,
            "blanks": [
                {
                    "id": "blank-1",
                    "label": "",
                    "max_score": "1.00000",
                    "accepted_answers": [{"value": correct_answer, "score": "1.00000"}],
                    "comparison_policy": policy,
                    "rubric": "",
                }
            ],
        }
    )


def fill_spec_for_entry(entry: Mapping[str, Any]) -> dict[str, Any] | None:
    kind = str(entry.get("question_type") or "")
    if kind not in {"fill_blank", "fill_in_blank"}:
        return None
    raw_spec = entry.get("fill_spec")
    if raw_spec not in (None, ""):
        if isinstance(raw_spec, str):
            try:
                raw_spec = json.loads(raw_spec)
            except json.JSONDecodeError as exc:
                raise ValueError("Invalid stored fill specification") from exc
        return normalize_fill_spec(raw_spec)
    answer = entry.get("correct_answer")
    if not isinstance(answer, str) or not answer:
        return None
    return legacy_single_blank_spec(kind, answer)


def fill_source_revision(source: Mapping[str, Any], fill_spec: Any) -> str:
    """Create the v2 fill source identity while leaving the v1 revision untouched."""
    from .learning_ai_review import source_snapshot_fields

    spec = normalize_fill_spec(fill_spec)
    source_canonical = canonical_json(source_snapshot_fields(source))
    spec_canonical = canonical_json(spec)
    base_revision = hashlib.sha256(source_canonical.encode("utf-8")).hexdigest()
    frozen = canonical_json(["learning-ai-source/v2", base_revision, spec_canonical])
    return hashlib.sha256(frozen.encode("utf-8")).hexdigest()


def answer_hash_v2(answer: Any) -> str:
    parsed = answer if isinstance(answer, dict) else answer
    canonical = canonical_json(parsed)
    if len(canonical.encode("utf-8")) > _MAX_ANSWER_BYTES:
        raise ValueError("Structured fill answer exceeds size limit")
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def frozen_input_v2(
    *,
    owner_id: str,
    operation_id: str,
    entry_id: str,
    logical_question_id: str,
    revision: str,
    base_version: int,
    answer: Any,
    accounting: Mapping[str, Any],
    source_snapshot: list[Any],
    fill_spec: Any,
) -> tuple[str, str, str]:
    from .learning_ai_review import _accounting

    if (
        not isinstance(base_version, int)
        or isinstance(base_version, bool)
        or not 0 <= base_version <= 2**53 - 1
    ):
        raise ValueError("Invalid review version")
    spec = normalize_fill_spec(fill_spec)
    binding = _accounting(accounting)
    normalized_answer = parse_structured_answer(spec, answer)
    answer_canonical = canonical_json(normalized_answer)
    snapshot_canonical = canonical_json(source_snapshot)
    spec_canonical = canonical_json(spec)
    frozen = canonical_json(
        [
            "learning-ai-review/v2",
            owner_id,
            operation_id,
            entry_id,
            logical_question_id,
            revision,
            base_version,
            answer_canonical,
            binding["operation_id"],
            binding["generation"],
            binding["executor_fence"],
            snapshot_canonical,
            spec_canonical,
        ]
    )
    if len(frozen.encode("utf-8")) > _MAX_CANONICAL_VALUE_BYTES:
        raise ValueError("Frozen input exceeds size limit")
    return (
        frozen,
        hashlib.sha256(frozen.encode("utf-8")).hexdigest(),
        answer_hash_v2(normalized_answer),
    )


def _js_number_string(value: int | float | None) -> str | None:
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("Invalid score for result hash")
    number = float(value)
    if not 0 <= number <= 1:
        raise ValueError("Invalid score for result hash")
    if number == 0:
        return "0"
    if number.is_integer():
        return str(int(number))
    absolute = abs(number)
    shortest = repr(number).lower()
    if 1e-6 <= absolute < 1e21:
        fixed = format(Decimal(shortest), "f")
        return fixed.rstrip("0").rstrip(".") if "." in fixed else fixed
    mantissa, exponent = shortest.split("e") if "e" in shortest else (shortest, "0")
    mantissa = mantissa.rstrip("0").rstrip(".") if "." in mantissa else mantissa
    exponent_value = int(exponent)
    return f"{mantissa}e{'+' if exponent_value >= 0 else ''}{exponent_value}"


def grade_result_hash_v2(grade: Mapping[str, Any]) -> str:
    required = {
        "schema_version",
        "status",
        "owner_id",
        "operation_id",
        "entry_id",
        "question_id",
        "revision",
        "base_version",
        "answer_hash",
        "input_hash",
        "accounting_operation_id",
        "accounting_generation",
        "executor_fence",
        "outcome",
        "score",
        "feedback",
        "needs_human_review",
        "blank_results",
        "policy_version",
    }
    if not isinstance(grade, Mapping) or set(grade) != required or grade["schema_version"] != 2:
        raise ValueError("Invalid v2 grade receipt")
    if grade["status"] != "completed" or grade["policy_version"] not in {
        POLICY_VERSION,
        POLICY_VERSION_V2,
    }:
        raise ValueError("Invalid v2 grade status or policy")
    if not isinstance(grade["blank_results"], list) or not grade["blank_results"]:
        raise ValueError("Missing per-blank results")
    projected: list[dict[str, Any]] = []
    blank_fields = {"blank_id", "outcome", "score", "feedback", "needs_human_review", "provenance"}
    for row in grade["blank_results"]:
        if not isinstance(row, Mapping) or set(row) != blank_fields:
            raise ValueError("Invalid per-blank result")
        if row["outcome"] not in {"correct", "partial", "incorrect", "ungradable"}:
            raise ValueError("Invalid per-blank outcome")
        if row["provenance"] not in {"rule", "ai"} or type(row["needs_human_review"]) is not bool:
            raise ValueError("Invalid per-blank provenance")
        score = row["score"]
        _js_number_string(score)
        if row["outcome"] == "correct" and score != 1:
            raise ValueError("Invalid correct score")
        if row["outcome"] == "incorrect" and score != 0:
            raise ValueError("Invalid incorrect score")
        if row["outcome"] == "partial" and (score is None or not 0 < score < 1):
            raise ValueError("Invalid partial score")
        if row["outcome"] == "ungradable" and score is not None:
            raise ValueError("Invalid ungradable score")
        _utf8(row["blank_id"], "blank ID", 80, nonblank=True)
        _utf8(row["feedback"], "blank feedback", 16_384)
        projected.append({**row, "score": _js_number_string(score)})
    tuple_v1 = [
        2,
        grade["status"],
        grade["owner_id"],
        grade["operation_id"],
        grade["entry_id"],
        grade["question_id"],
        grade["revision"],
        grade["base_version"],
        grade["answer_hash"],
        grade["input_hash"],
        grade["accounting_operation_id"],
        grade["accounting_generation"],
        grade["executor_fence"],
        grade["outcome"],
        _js_number_string(grade["score"]),
        grade["feedback"],
        grade["needs_human_review"],
    ]
    canonical = canonical_json(
        [
            "learning-ai-grade/v2",
            *tuple_v1,
            canonical_json(projected),
            grade["policy_version"],
        ]
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def parse_structured_answer(spec_value: Any, answer_value: Any) -> dict[str, Any]:
    spec = normalize_fill_spec(spec_value)
    if not isinstance(answer_value, dict) or set(answer_value) != {"version", "values"}:
        raise ValueError("Invalid structured fill answer")
    if type(answer_value["version"]) is not int or answer_value["version"] != 1:
        raise ValueError("Unsupported structured fill answer")
    values = answer_value["values"]
    if not isinstance(values, list) or len(values) != len(spec["blanks"]):
        raise ValueError("Fill answer does not cover every blank")
    normalized: list[dict[str, str]] = []
    for blank, item in zip(spec["blanks"], values, strict=True):
        if not isinstance(item, dict) or set(item) != {"blankId", "value"}:
            raise ValueError("Invalid fill answer value")
        if item["blankId"] != blank["id"]:
            raise ValueError("Fill answer IDs must match source order")
        value = _utf8(item["value"], "blank answer", _MAX_ANSWER_BYTES, nonblank=True)
        normalized.append({"blankId": blank["id"], "value": value})
    result = {"version": 1, "values": normalized}
    if len(canonical_json(result).encode("utf-8")) > _MAX_ANSWER_BYTES:
        raise ValueError("Structured fill answer exceeds size limit")
    return result


def compare_answer(policy: str, accepted_answers: list[str], answer: str) -> bool | None:
    """Return a deterministic match, mismatch, or None when semantics are needed."""
    if policy not in _POLICIES or policy == "semantic_v1":
        return None
    value = _trim(_utf8(answer, "blank answer", _MAX_ANSWER_BYTES))
    expected = [_trim(_utf8(item, "accepted answer", 2_000)) for item in accepted_answers]
    if not value or not expected or any(not item for item in expected):
        return None
    if policy == "comparison_v1":
        normalized = {"＜": "<", "＞": ">", "＝": "="}
        tokens = {"<", ">", "="}
        if value not in tokens | set(normalized) or any(
            item not in tokens | set(normalized) for item in expected
        ):
            return None
        return normalized.get(value, value) in {normalized.get(item, item) for item in expected}
    if policy == "numeric_text_v1" and any(
        not _NUMERIC.fullmatch(item) for item in [value, *expected]
    ):
        return None
    return value in expected


def evaluate_rules(spec_value: Any, answer_value: Any) -> dict[str, Any]:
    spec = normalize_fill_spec(spec_value)
    answer = parse_structured_answer(spec, answer_value)
    rule_results: list[dict[str, Any]] = []
    unresolved: list[str] = []
    for blank, submitted in zip(spec["blanks"], answer["values"], strict=True):
        if blank["comparison_policy"] == "semantic_v1":
            unresolved.append(blank["id"])
            continue
        try:
            key = _match_key(blank["comparison_policy"], submitted["value"])
        except ValueError:
            unresolved.append(blank["id"])
            continue
        earned = next(
            (
                point_units(item["score"])
                for item in blank["accepted_answers"]
                if _match_key(blank["comparison_policy"], item["value"]) == key
            ),
            0,
        )
        maximum = point_units(blank["max_score"])
        rule_results.append(
            {
                "blankId": blank["id"],
                "outcome": "correct"
                if earned == maximum
                else "incorrect"
                if earned == 0
                else "partial",
                "score": earned / maximum,
                "feedback": "",
            }
        )
    return {"answer": answer, "rule_results": rule_results, "unresolved_ids": unresolved}
