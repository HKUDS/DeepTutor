"""Strict question content v1 adapters; grading stays with learning_assessment."""

from __future__ import annotations

from collections.abc import Mapping
import hashlib
import json
import re
from typing import Any

from deeptutor.services.practice.fill_blanks import (
    legacy_single_blank_spec,
    normalize_fill_spec,
)

_BANK_TYPES = {
    "single_choice",
    "multi_choice",
    "true_false",
    "fill_blank",
    "short_answer",
    "written",
}
_TYPES = _BANK_TYPES | {"coding"}
_CHOICE = {"single_choice", "multi_choice", "true_false"}
_ID = re.compile(r"^[A-Za-z0-9_:.-]{1,200}$")
_MARKER = re.compile(r"\{\{blank:([A-Za-z0-9_-]{1,80})\}\}")
_NEAR_MARKER = re.compile(r"\{\{[ \t\r\n]*[bB][lL][aA][nN][kK]")
_MAX_BYTES = 400_000


def _string(value: Any, name: str, limit: int = 100_000) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{name} must be a string")
    try:
        size = len(value.encode("utf-8"))
    except UnicodeEncodeError as exc:
        raise ValueError(f"{name} contains invalid Unicode") from exc
    if size > limit:
        raise ValueError(f"{name} exceeds {limit} bytes")
    return value


def _id(value: Any, name: str) -> str:
    text = _string(value, name, 200)
    if not _ID.fullmatch(text):
        raise ValueError(f"{name} is invalid")
    return text


def _object(value: Any, name: str, keys: set[str]) -> dict[str, Any]:
    if not isinstance(value, dict) or set(value) != keys:
        raise ValueError(f"{name} has invalid fields")
    return value


def _array(value: Any, name: str, limit: int) -> list[Any]:
    if not isinstance(value, list) or len(value) > limit:
        raise ValueError(f"{name} must be an array of at most {limit} entries")
    return value


def _json_safe(value: Any, name: str, *, depth: int = 0) -> Any:
    if depth > 24:
        raise ValueError(f"{name} is too deeply nested")
    if value is None or isinstance(value, bool):
        return value
    if isinstance(value, str):
        return _string(value, name, _MAX_BYTES)
    if type(value) is int and abs(value) <= 2**53 - 1:
        return value
    if isinstance(value, list) and len(value) <= 2000:
        return [_json_safe(item, name, depth=depth + 1) for item in value]
    if isinstance(value, dict) and len(value) <= 2000:
        return {
            _string(key, name, 200): _json_safe(item, name, depth=depth + 1)
            for key, item in value.items()
        }
    raise ValueError(f"{name} is not safe JSON")


def _part(value: Any, name: str, assets: dict[str, dict[str, Any]]) -> dict[str, str]:
    if not isinstance(value, dict):
        raise ValueError(f"{name} must be an object")
    kind = value.get("kind")
    if kind in {"text", "math", "code"}:
        if set(value) not in ({"kind", "text"}, {"kind", "text", "language"}):
            raise ValueError(f"{name} has invalid fields")
        result = {"kind": kind, "text": _string(value["text"], f"{name}.text")}
        if "language" in value:
            tag = _string(value["language"], f"{name}.language", 35)
            if not re.fullmatch(r"[A-Za-z]{2,8}(?:-[A-Za-z0-9]{1,8})*|und", tag):
                raise ValueError(f"{name} has invalid language")
            result["language"] = tag
        return result
    if kind in {"image", "audio", "video"}:
        _object(value, name, {"kind", "assetId"})
        asset_id = _id(value["assetId"], f"{name}.assetId")
        asset = assets.get(asset_id)
        if asset is None or asset["kind"] != kind or asset["role"] != "prompt":
            raise ValueError(f"{name} references an unknown or non-prompt asset")
        return {"kind": kind, "assetId": asset_id}
    raise ValueError(f"{name} has unsupported kind")


def _validate_markers(question: str, spec: dict[str, Any] | None) -> None:
    markers = list(_MARKER.finditer(question))
    for near in _NEAR_MARKER.finditer(question):
        if not any(match.start() == near.start() for match in markers):
            raise ValueError("Malformed blank marker")
    if markers:
        if spec is None or [m.group(1) for m in markers] != [b["id"] for b in spec["blanks"]]:
            raise ValueError("Blank markers must match ordered fill spec IDs")


def _legacy_options(value: Any, *, true_false: bool = False) -> list[dict[str, str]]:
    if value is None:
        value = {}
    if not isinstance(value, Mapping) or len(value) > 10:
        raise ValueError("Invalid legacy options")
    result = []
    for key, text in value.items():
        allowed = "TF" if true_false else "ABCDEFGHIJ"
        if not isinstance(key, str) or len(key) != 1 or key not in allowed:
            raise ValueError("Legacy options have invalid IDs")
        result.append({"id": key, "text": _string(text, "option text", 20_000)})
    return result


def _legacy_document(
    payload: Any, source_format: str, question_id: str | None, language: str, provenance: Any
) -> dict[str, Any]:
    if not isinstance(payload, Mapping):
        raise ValueError("Legacy question must be an object")
    if source_format == "bank-v1" and question_id is None and payload.get("question_id") is None:
        from deeptutor.services.practice.importing import normalize_question

        # Preserve the existing bank import identity and its established
        # source-alias normalization at this one legacy boundary.
        payload = {**payload, **normalize_question(dict(payload))}
    raw_type = _string(payload.get("question_type"), "question_type", 40)
    aliases = (
        {"multiple_choice": "single_choice", "fill_in_blank": "fill_blank"}
        if source_format == "bank-v1"
        else {
            "choice": "single_choice",
            "multiple_choice": "multi_choice",
            "concept": "true_false",
            "fill_in_blank": "fill_blank",
        }
    )
    kind = aliases.get(raw_type, raw_type)
    if kind not in (_BANK_TYPES if source_format == "bank-v1" else _TYPES):
        raise ValueError("Unsupported legacy question type")
    question = _string(payload.get("question"), "question")
    if not question:
        raise ValueError("Question is empty")
    shared = _string(payload.get("shared_context", ""), "shared_context")
    answer = _string(payload.get("correct_answer", ""), "correct_answer")
    explanation = _string(payload.get("explanation", ""), "explanation")
    options = _legacy_options(payload.get("options"), true_false=kind == "true_false")
    if kind in {"single_choice", "multi_choice"} and len(options) < 2:
        raise ValueError("Choice question needs options")
    if kind in _CHOICE and kind != "true_false" and answer.strip():
        selected = [token.strip() for token in answer.split(",")]
        valid = {item["id"] for item in options}
        if not selected or any(token not in valid for token in selected):
            raise ValueError("Choice answer must name option IDs")
        if kind == "single_choice" and len(selected) != 1:
            raise ValueError("Single choice needs one answer")
    spec = payload.get("fill_spec")
    if spec is not None:
        if kind != "fill_blank":
            raise ValueError("Only fill blank may have fill_spec")
        spec = normalize_fill_spec(spec)
    elif kind == "fill_blank" and answer.strip():
        spec = legacy_single_blank_spec(kind, answer)
    if kind == "fill_blank":
        _validate_markers(question, spec)
    elif _NEAR_MARKER.search(question):
        raise ValueError("Blank marker in non-fill question")
    if question_id is not None and payload.get("question_id") not in (None, question_id):
        raise ValueError("Question ID conflict")
    source_id = question_id if question_id is not None else payload.get("question_id")
    if source_id is None:
        # Keep the historical quiz identity when adapting an ID-less legacy item.
        identity = {
            "question": question,
            "question_type": kind,
            "options": {o["id"]: o["text"] for o in options},
            "correct_answer": answer,
        }
        if spec is not None:
            identity["fill_spec"] = spec
        source_id = (
            "import:"
            + hashlib.sha256(
                json.dumps(identity, sort_keys=True, ensure_ascii=False).encode("utf-8")
            ).hexdigest()
        )
    item_id = _id(source_id, "itemId")
    difficulty = _string(payload.get("difficulty", ""), "difficulty", 64)
    topic = _string(payload.get("topic", ""), "topic", 200)
    tags = [_string(tag, "tag", 100) for tag in _array(payload.get("tags", []), "tags", 20)]
    source_assets = []
    for raw_asset in _array(payload.get("assets", []), "assets", 100):
        if not isinstance(raw_asset, Mapping) or set(raw_asset) != {"asset_id", "role", "sha256"}:
            raise ValueError("Invalid source asset link")
        if raw_asset["role"] not in {"prompt", "answer", "source"}:
            raise ValueError("Invalid source asset role")
        source_assets.append(
            {
                "id": raw_asset["asset_id"],
                "kind": "opaque",
                "role": raw_asset["role"],
                "mimeType": None,
                "sha256": raw_asset["sha256"],
            }
        )
    response_ids = (
        [blank["id"] for blank in spec["blanks"]]
        if kind == "fill_blank" and spec
        else ["response-1"]
    )
    interaction_kind = (
        "choice" if kind in _CHOICE else "text_entry" if kind == "fill_blank" else "extended_text"
    )
    interactions = [
        {
            "id": f"interaction-{index}",
            "kind": interaction_kind,
            "cardinality": "multiple" if kind == "multi_choice" else "single",
            "options": options if index == 1 else [],
            "responseIds": [rid],
        }
        for index, rid in enumerate(response_ids, 1)
    ]
    result = {
        "schemaVersion": 1,
        "itemId": item_id,
        "questionType": kind,
        "language": language,
        "subject": {"topic": topic, "difficulty": difficulty, "tags": tags},
        "body": [{"kind": "text", "text": question}],
        "materials": (
            [
                {
                    "id": "material-1",
                    "role": "shared_context",
                    "body": [{"kind": "text", "text": shared}],
                }
            ]
            if shared
            else []
        ),
        "assets": source_assets,
        "interactions": interactions,
        "responses": [
            {
                "id": rid,
                "interactionId": f"interaction-{index}",
                "baseType": "identifier" if kind in _CHOICE else "string",
                "cardinality": "multiple" if kind == "multi_choice" else "single",
            }
            for index, rid in enumerate(response_ids, 1)
        ],
        "author": {"correctAnswer": answer, "explanation": explanation, "fillSpec": spec},
        "provenance": provenance,
    }
    return _validate_document(result)


def _validate_document(value: Any) -> dict[str, Any]:
    keys = {
        "schemaVersion",
        "itemId",
        "questionType",
        "language",
        "subject",
        "body",
        "materials",
        "assets",
        "interactions",
        "responses",
        "author",
        "provenance",
    }
    value = _object(value, "QuestionDocument", keys)
    if type(value["schemaVersion"]) is not int or value["schemaVersion"] != 1:
        raise ValueError("Unsupported question content version")
    item_id = _id(value["itemId"], "itemId")
    kind = value["questionType"]
    if kind not in _TYPES or not isinstance(kind, str):
        raise ValueError("Unsupported question type")
    language = _string(value["language"], "language", 35)
    if not language or not re.fullmatch(r"[A-Za-z]{2,8}(?:-[A-Za-z0-9]{1,8})*|und", language):
        raise ValueError("Invalid language tag")
    subject = _object(value["subject"], "subject", {"topic", "difficulty", "tags"})
    normalized_subject = {
        "topic": _string(subject["topic"], "topic", 200),
        "difficulty": _string(subject["difficulty"], "difficulty", 64),
        "tags": [_string(tag, "tag", 100) for tag in _array(subject["tags"], "tags", 20)],
    }
    assets = []
    asset_ids: set[str] = set()
    for raw in _array(value["assets"], "assets", 100):
        asset = _object(raw, "asset", {"id", "kind", "role", "mimeType", "sha256"})
        asset_id = _id(asset["id"], "asset.id")
        if asset_id in asset_ids or asset["kind"] not in {"image", "audio", "video", "opaque"}:
            raise ValueError("Duplicate or unsupported asset")
        if asset["role"] not in {"prompt", "answer", "source"}:
            raise ValueError("Invalid asset role")
        if asset["kind"] == "opaque" and asset["mimeType"] is not None:
            raise ValueError("Opaque source asset cannot invent a MIME type")
        if asset["kind"] != "opaque" and not isinstance(asset["mimeType"], str):
            raise ValueError("Typed asset requires a MIME type")
        digest = _string(asset["sha256"], "asset.sha256", 64)
        if not re.fullmatch(r"[a-f0-9]{64}", digest):
            raise ValueError("Invalid asset hash")
        assets.append(
            {
                "id": asset_id,
                "kind": asset["kind"],
                "role": asset["role"],
                "mimeType": (
                    _string(asset["mimeType"], "asset.mimeType", 100)
                    if asset["mimeType"] is not None
                    else None
                ),
                "sha256": digest,
            }
        )
        asset_ids.add(asset_id)
    asset_map = {asset["id"]: asset for asset in assets}
    body = [_part(part, "body part", asset_map) for part in _array(value["body"], "body", 200)]
    if not body:
        raise ValueError("Question body is empty")
    materials = []
    material_ids: set[str] = set()
    for raw in _array(value["materials"], "materials", 100):
        if not isinstance(raw, dict) or set(raw) not in (
            {"id", "role", "body"},
            {"id", "role", "body", "visibility"},
        ):
            raise ValueError("material has invalid fields")
        mat = raw
        mat_id = _id(mat["id"], "material.id")
        if mat_id in material_ids:
            raise ValueError("Duplicate material ID")
        role = _string(mat["role"], "material.role", 40)
        if role not in {
            "shared_context",
            "instruction",
            "passage",
            "dialogue",
            "figure",
            "audio",
            "transcript",
            "answer_key",
            "explanation",
        }:
            raise ValueError("Unsupported material role")
        visibility = mat.get("visibility")
        if visibility is None and role in {"transcript", "answer_key", "explanation"}:
            raise ValueError("Sensitive material requires explicit visibility")
        if visibility is None:
            visibility = "learner"
        if visibility not in {"learner", "author"}:
            raise ValueError("Invalid material visibility")
        if role in {"answer_key", "explanation"} and visibility != "author":
            raise ValueError("Answer material cannot be learner-visible")
        parts = [
            _part(part, "material part", asset_map)
            for part in _array(mat["body"], "material body", 200)
        ]
        if not parts:
            raise ValueError("Material body is empty")
        normalized_material = {"id": mat_id, "role": role, "body": parts}
        if "visibility" in mat:
            normalized_material["visibility"] = visibility
        materials.append(normalized_material)
        material_ids.add(mat_id)
    interactions = []
    interaction_ids: set[str] = set()
    used_response_ids: list[str] = []
    for raw in _array(value["interactions"], "interactions", 20):
        inter = _object(raw, "interaction", {"id", "kind", "cardinality", "options", "responseIds"})
        inter_id = _id(inter["id"], "interaction.id")
        if inter_id in interaction_ids or inter["kind"] not in {
            "choice",
            "text_entry",
            "extended_text",
        }:
            raise ValueError("Duplicate or unsupported interaction")
        cardinality = inter["cardinality"]
        if cardinality not in {"single", "multiple"}:
            raise ValueError("Invalid cardinality")
        options = []
        option_ids: set[str] = set()
        for option in _array(inter["options"], "options", 10):
            opt = _object(option, "option", {"id", "text"})
            oid = _id(opt["id"], "option.id")
            if oid in option_ids:
                raise ValueError("Duplicate option ID")
            options.append({"id": oid, "text": _string(opt["text"], "option.text", 20_000)})
            option_ids.add(oid)
        if inter["kind"] == "choice" and kind != "true_false" and len(options) < 2:
            raise ValueError("Choice interaction needs at least two options")
        if inter["kind"] != "choice" and options:
            raise ValueError("Only choice interactions may have options")
        response_ids = [
            _id(rid, "responseId") for rid in _array(inter["responseIds"], "responseIds", 20)
        ]
        if not response_ids or len(set(response_ids)) != len(response_ids):
            raise ValueError("Invalid interaction response IDs")
        used_response_ids.extend(response_ids)
        interactions.append(
            {
                "id": inter_id,
                "kind": inter["kind"],
                "cardinality": cardinality,
                "options": options,
                "responseIds": response_ids,
            }
        )
        interaction_ids.add(inter_id)
    responses = []
    seen_responses: set[str] = set()
    for raw in _array(value["responses"], "responses", 20):
        response = _object(raw, "response", {"id", "interactionId", "baseType", "cardinality"})
        rid = _id(response["id"], "response.id")
        iid = _id(response["interactionId"], "response.interactionId")
        if rid in seen_responses or iid not in interaction_ids:
            raise ValueError("Duplicate response or unknown interaction")
        if response["baseType"] not in {"identifier", "string"} or response["cardinality"] not in {
            "single",
            "multiple",
        }:
            raise ValueError("Unsupported response type or cardinality")
        responses.append(
            {
                "id": rid,
                "interactionId": iid,
                "baseType": response["baseType"],
                "cardinality": response["cardinality"],
            }
        )
        seen_responses.add(rid)
    if len(used_response_ids) != len(set(used_response_ids)) or used_response_ids != [
        r["id"] for r in responses
    ]:
        raise ValueError("Responses must match interaction order exactly")
    by_interaction = {inter["id"]: inter for inter in interactions}
    if any(r["id"] not in by_interaction[r["interactionId"]]["responseIds"] for r in responses):
        raise ValueError("Response ownership mismatch")
    if kind != "fill_blank" and len(interactions) != 1:
        raise ValueError("Only fill blanks may have multiple interactions")
    if kind == "fill_blank" and len(interactions) != len(responses):
        raise ValueError("Fill blanks need one interaction per response")
    if kind == "true_false" and [option["id"] for option in interactions[0]["options"]] not in (
        [],
        ["T", "F"],
    ):
        raise ValueError("True/false options must be empty or ordered T/F")
    expected_kind = (
        "choice" if kind in _CHOICE else "text_entry" if kind == "fill_blank" else "extended_text"
    )
    if any(inter["kind"] != expected_kind for inter in interactions):
        raise ValueError("Question and interaction kind conflict")
    for inter in interactions:
        required_cardinality = "multiple" if kind == "multi_choice" else "single"
        if inter["cardinality"] != required_cardinality:
            raise ValueError("Question cardinality conflict")
        if kind == "fill_blank" and len(inter["responseIds"]) != 1:
            raise ValueError("Each blank needs one response")
    expected_base = "identifier" if kind in _CHOICE else "string"
    if any(
        r["baseType"] != expected_base
        or r["cardinality"] != by_interaction[r["interactionId"]]["cardinality"]
        for r in responses
    ):
        raise ValueError("Response type or cardinality conflict")
    author = _object(value["author"], "author", {"correctAnswer", "explanation", "fillSpec"})
    answer = _string(author["correctAnswer"], "correctAnswer")
    explanation = _string(author["explanation"], "explanation")
    spec = normalize_fill_spec(author["fillSpec"]) if author["fillSpec"] is not None else None
    if kind != "fill_blank" and spec is not None:
        raise ValueError("fillSpec requires fill_blank")
    if kind == "fill_blank":
        if spec is None and answer:
            spec = legacy_single_blank_spec(kind, answer)
        if spec is None or [b["id"] for b in spec["blanks"]] != [r["id"] for r in responses]:
            raise ValueError("Fill responses must match ordered fillSpec IDs")
        _validate_markers("\0".join(part["text"] for part in body if part["kind"] == "text"), spec)
    if kind in _CHOICE - {"true_false"} and answer.strip():
        selected = answer.split(",")
        option_ids = {option["id"] for option in interactions[0]["options"]}
        if (
            not selected
            or any(token not in option_ids for token in selected)
            or len(set(selected)) != len(selected)
            or (kind == "single_choice" and len(selected) != 1)
            or (kind == "multi_choice" and selected != sorted(selected))
        ):
            raise ValueError("Choice answer is invalid")
    if kind == "true_false" and answer.strip():
        if answer != answer.strip() or answer.casefold() not in {
            "t",
            "f",
            "true",
            "false",
            "对",
            "错",
            "正确",
            "错误",
            "是",
            "否",
            "yes",
            "no",
            "y",
            "n",
            "1",
            "0",
            "√",
            "×",
            "✓",
            "✗",
        }:
            raise ValueError("True/false answer is invalid")
    if value["provenance"] is not None:
        if not isinstance(value["provenance"], dict):
            raise ValueError("provenance must be an object")
        provenance = _json_safe(value["provenance"], "provenance")
    else:
        provenance = None
    result = {
        "schemaVersion": 1,
        "itemId": item_id,
        "questionType": kind,
        "language": language,
        "subject": normalized_subject,
        "body": body,
        "materials": materials,
        "assets": assets,
        "interactions": interactions,
        "responses": responses,
        "author": {"correctAnswer": answer, "explanation": explanation, "fillSpec": spec},
        "provenance": provenance,
    }
    if (
        len(
            json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
                "utf-8"
            )
        )
        > _MAX_BYTES
    ):
        raise ValueError("Question content exceeds size limit")
    return result


def normalize_question_document(
    payload: Any,
    *,
    source_format: str,
    question_id: str | None = None,
    language: str = "und",
    provenance: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Validate one versioned item or adapt a source-specific legacy record."""
    if source_format not in {"bank-v1", "quiz-v1", "content-v1"}:
        raise ValueError("Unsupported source format")
    if source_format == "content-v1":
        checked = _validate_document(payload)
        if question_id is not None and checked["itemId"] != _id(question_id, "question_id"):
            raise ValueError("Question ID conflict")
        if provenance is not None:
            checked["provenance"] = _json_safe(provenance, "provenance")
        return checked
    return _legacy_document(payload, source_format, question_id, language, provenance)


def _flat_text(parts: list[dict[str, str]], name: str) -> str:
    if len(parts) != 1 or set(parts[0]) != {"kind", "text"} or parts[0]["kind"] != "text":
        raise ValueError(f"{name} cannot be represented in a legacy question")
    return parts[0]["text"]


def project_legacy_question(
    document: Any,
    *,
    target_format: str = "bank-v1",
    allow_asset_sidecar: bool = False,
    allow_verified_prompt_assets: bool = False,
) -> dict[str, Any]:
    """Project only representations supported by the existing flat consumers."""
    doc = _validate_document(document)
    if target_format not in {"bank-v1", "quiz-v1"}:
        raise ValueError("Unsupported target format")
    kind = doc["questionType"]
    if not doc["author"]["correctAnswer"].strip() and doc["author"]["fillSpec"] is None:
        raise ValueError("Unanswered candidate cannot be projected into a learner bank or quiz")
    if target_format == "bank-v1" and kind == "coding":
        raise ValueError("Coding quiz is unsupported in the bank")
    opaque_sidecar = (
        allow_asset_sidecar
        and target_format == "bank-v1"
        and all(asset["kind"] == "opaque" for asset in doc["assets"])
    )
    qti_prompt_sidecar = (
        allow_verified_prompt_assets
        and target_format == "bank-v1"
        and all(
            asset["kind"] == "image"
            and asset["role"] == "prompt"
            and asset["mimeType"] in {"image/png", "image/jpeg", "image/webp"}
            for asset in doc["assets"]
        )
    )
    if doc["assets"] and not (opaque_sidecar or qti_prompt_sidecar):
        raise ValueError("Legacy question needs a trusted opaque asset sidecar")
    if (
        qti_prompt_sidecar
        and doc["assets"]
        and len(doc["body"]) >= 2
        and (
            set(doc["body"][0]) == {"kind", "text"}
            and doc["body"][0]["kind"] == "text"
            and all(
                set(part) == {"kind", "assetId"}
                and part["kind"] == "image"
                and any(asset["id"] == part["assetId"] for asset in doc["assets"])
                for part in doc["body"][1:]
            )
            and len(doc["body"]) - 1 == len(doc["assets"])
            and {part["assetId"] for part in doc["body"][1:]}
            == {asset["id"] for asset in doc["assets"]}
        )
    ):
        # The bank keeps text for grading compatibility; its QTI-owned
        # trailing images are rendered from the verified canonical sidecar.
        prompt = doc["body"][0]["text"]
    else:
        prompt = _flat_text(doc["body"], "body")
    shared = ""
    if doc["materials"]:
        if len(doc["materials"]) != 1 or doc["materials"][0]["role"] != "shared_context":
            raise ValueError("Legacy question cannot preserve material hierarchy")
        shared = _flat_text(doc["materials"][0]["body"], "material")
    if doc["subject"]["tags"] and target_format == "quiz-v1":
        raise ValueError("Quiz cannot preserve subject tags")
    inter = doc["interactions"][0]
    options = {option["id"]: option["text"] for option in inter["options"]}
    if (
        target_format == "bank-v1"
        and kind != "true_false"
        and any(key not in "ABCDEFGHIJ" or len(key) != 1 for key in options)
    ):
        raise ValueError("Bank options require A-J IDs")
    if target_format == "bank-v1":
        result = {
            "question_id": doc["itemId"],
            "question": f"{shared}\n\n{prompt}" if shared else prompt,
            "question_type": kind,
            "options": options,
            "correct_answer": doc["author"]["correctAnswer"],
            "explanation": doc["author"]["explanation"],
            "difficulty": doc["subject"]["difficulty"],
            "tags": doc["subject"]["tags"],
        }
        if doc["author"]["fillSpec"] is not None:
            result["fill_spec"] = doc["author"]["fillSpec"]
        return result
    type_map = {
        "single_choice": "choice",
        "multi_choice": "multiple_choice",
        "fill_blank": "fill_in_blank",
        "short_answer": "short_answer",
        "written": "written",
        "coding": "coding",
        "true_false": "concept",
    }
    result = {
        "question_id": doc["itemId"],
        "question": prompt,
        "question_type": type_map[kind],
        "options": None if kind == "true_false" else options or None,
        "correct_answer": doc["author"]["correctAnswer"],
        "explanation": doc["author"]["explanation"],
        "topic": doc["subject"]["topic"],
        "difficulty": doc["subject"]["difficulty"],
    }
    if shared:
        result["shared_context"] = shared
    if doc["author"]["fillSpec"] is not None:
        result["fill_spec"] = doc["author"]["fillSpec"]
    return result


def public_question_content(document: Any) -> dict[str, Any]:
    """Return only learner-visible structure, with no answer or private provenance."""
    doc = _validate_document(document)
    return {
        key: (
            [asset for asset in value if asset["role"] == "prompt"]
            if key == "assets"
            else [
                material for material in value if material.get("visibility", "learner") == "learner"
            ]
            if key == "materials"
            else value
        )
        for key, value in doc.items()
        if key not in {"author", "provenance"}
    }


def qti_mapping_contract(document: Any) -> dict[str, Any]:
    """Describe the active bounded QTI 3 profile without producing an artifact.

    Keep the original descriptor envelope, but derive capability and diagnostics
    from the real adapter. Without verified asset paths or authority snapshots,
    the report cannot claim packaged images or equivalent scoring.
    """
    # Lazy import avoids a core/adapter dependency cycle at module initialization.
    from .qti3.mapping import preflight
    from .qti3.profile import PROFILE_VERSION

    doc = _validate_document(document)
    checked = preflight(doc)
    inter = doc["interactions"][0]
    qti_kind = {
        "single_choice": "choiceInteraction",
        "multi_choice": "choiceInteraction",
        "true_false": "choiceInteraction",
        "fill_blank": "textEntryInteraction",
        "short_answer": "extendedTextInteraction",
        "written": "extendedTextInteraction",
    }.get(doc["questionType"])
    return {
        "profileVersion": 1,
        "conversionImplemented": True,
        "supportedProfile": PROFILE_VERSION,
        "interactions": [
            {
                "id": row["id"],
                "qtiType": qti_kind,
                "cardinality": row["cardinality"],
                "responseIds": row["responseIds"],
            }
            for row in doc["interactions"]
        ],
        "interaction": qti_kind,
        "cardinality": inter["cardinality"],
        "materialMapping": "ordered_content_parts",
        "scoringMapping": checked["scoring"],
        "unsupported": [
            row["code"] for row in checked["diagnostics"] if row["severity"] == "error"
        ],
        "lossDiagnostics": [
            row["code"] for row in checked["diagnostics"] if row["severity"] == "warning"
        ],
        **checked,
    }
