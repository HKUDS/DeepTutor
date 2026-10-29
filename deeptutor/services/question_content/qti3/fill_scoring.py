"""Finite literal fill-points QTI grammar; no general expression interpreter."""

from __future__ import annotations

import hashlib
import re

# Tree construction/types and XSD validation only; parsing uses defusedxml.
from lxml import etree  # nosec B410

from deeptutor.services.practice.fill_blanks import normalize_fill_spec, point_string, point_units

from .profile import QTI_NS

_Q = "{" + QTI_NS + "}"
RESERVED_OUTCOMES = {"SCORE", "MAXSCORE", "NORMALIZED_SCORE"}


def response_id(value: str, *, reserve: bool = True) -> str:
    from .mapping import qti_id

    candidate = qti_id(value, prefix="response")
    if reserve and (candidate in RESERVED_OUTCOMES or candidate.startswith("POINTS_")):
        return "response_" + hashlib.sha256(value.encode("utf-8")).hexdigest()[:20]
    return candidate


def points_id(rid: str) -> str:
    return "POINTS_" + hashlib.sha256(rid.encode("utf-8")).hexdigest()[:20]


def xml_text(value: str) -> bool:
    return all(
        char in "\t\n\r"
        or 0x20 <= ord(char) <= 0xD7FF
        or 0xE000 <= ord(char) <= 0xFFFD
        or 0x10000 <= ord(char) <= 0x10FFFF
        for char in value
    )


def portable(spec: dict) -> bool:
    return spec["version"] == 2 and all(
        blank["comparison_policy"] == "qti_literal_v1"
        and all(
            xml_text(answer["value"]) and not any(c in answer["value"] for c in "\t\r\n")
            for answer in blank["accepted_answers"]
        )
        for blank in spec["blanks"]
    )


def _node(parent, name: str, text: str | None = None, **attrs):
    node = etree.SubElement(parent, _Q + name, attrib=attrs)
    node.text = text
    return node


def _base(parent, value: str):
    return _node(parent, "qti-base-value", value, **{"base-type": "float"})


def append_outcomes(root, spec: dict, response_ids: list[str]) -> None:
    total = point_string(sum(point_units(blank["max_score"]) for blank in spec["blanks"]))
    pairs = [
        (points_id(rid), blank["max_score"], "0.00000")
        for rid, blank in zip(response_ids, spec["blanks"], strict=True)
    ]
    pairs += [
        ("SCORE", total, "0.00000"),
        ("MAXSCORE", total, total),
        ("NORMALIZED_SCORE", "1.00000", "0.00000"),
    ]
    for name, maximum, default in pairs:
        node = _node(
            root,
            "qti-outcome-declaration",
            identifier=name,
            cardinality="single",
            **{"base-type": "float", "normal-maximum": maximum},
        )
        _node(_node(node, "qti-default-value"), "qti-value", default)


def append_program(root, spec: dict, response_ids: list[str]) -> None:
    total = point_string(sum(point_units(blank["max_score"]) for blank in spec["blanks"]))
    program = _node(root, "qti-response-processing")
    _base(_node(program, "qti-set-outcome-value", identifier="MAXSCORE"), total)
    for rid in response_ids:
        condition = _node(program, "qti-response-condition")
        response_if = _node(condition, "qti-response-if")
        _node(_node(response_if, "qti-is-null"), "qti-variable", identifier=rid)
        _base(_node(response_if, "qti-set-outcome-value", identifier=points_id(rid)), "0.00000")
        response_else = _node(condition, "qti-response-else")
        _node(
            _node(response_else, "qti-set-outcome-value", identifier=points_id(rid)),
            "qti-map-response",
            identifier=rid,
        )
    total_node = _node(_node(program, "qti-set-outcome-value", identifier="SCORE"), "qti-sum")
    for rid in response_ids:
        _node(total_node, "qti-variable", identifier=points_id(rid))
    normalized = _node(
        _node(program, "qti-set-outcome-value", identifier="NORMALIZED_SCORE"), "qti-divide"
    )
    _node(normalized, "qti-variable", identifier="SCORE")
    _node(normalized, "qti-variable", identifier="MAXSCORE")


def _number(value: str | None) -> str:
    """Bounded standards numeric lexical form -> exact five-decimal points."""
    if not isinstance(value, str) or not re.fullmatch(
        r"(?:0|[1-9][0-9]{0,3})(?:\.[0-9]{1,5})?", value
    ):
        raise ValueError("Unsupported map points")
    whole, _, fraction = value.partition(".")
    units = int(whole) * 100000 + int(fraction.ljust(5, "0") or "0")
    if units > 1000 * 100000:
        raise ValueError("Unsupported map points")
    return point_string(units)


def read_spec(declarations: list) -> dict | None:
    """Retain bounded point references; only recognize() proves the total program."""
    blanks = []
    try:
        for node in declarations:
            if (
                set(node.attrib) != {"identifier", "cardinality", "base-type"}
                or len(node.findall(_Q + "qti-mapping")) != 1
                or len(node.findall(_Q + "qti-correct-response")) > 1
                or any(
                    child.tag not in {_Q + "qti-correct-response", _Q + "qti-mapping"}
                    for child in node
                )
                or node.get("cardinality") != "single"
                or node.get("base-type") != "string"
            ):
                return None
            mapping = node.find(_Q + "qti-mapping")
            if mapping is None or set(mapping.attrib) - {
                "default-value",
                "lower-bound",
                "upper-bound",
            }:
                return None
            if (
                _number(mapping.get("default-value")) != "0.00000"
                or _number(mapping.get("lower-bound", "0")) != "0.00000"
            ):
                return None
            if not 1 <= len(mapping) <= 20:
                return None
            answers = []
            for entry in mapping:
                if (
                    entry.tag != _Q + "qti-map-entry"
                    or len(entry)
                    or set(entry.attrib) != {"map-key", "mapped-value", "case-sensitive"}
                    or entry.get("case-sensitive") not in {"true", "1"}
                ):
                    return None
                answers.append(
                    {"value": entry.get("map-key"), "score": _number(entry.get("mapped-value"))}
                )
            maximum = _number(mapping.get("upper-bound", "1"))
            correct = node.find(_Q + "qti-correct-response")
            expected = next(
                (answer["value"] for answer in answers if answer["score"] == maximum), None
            )
            if correct is not None and (
                correct.attrib
                or len(correct) != 1
                or correct[0].attrib
                or len(correct[0])
                or correct[0].tag != _Q + "qti-value"
                or correct[0].text != expected
            ):
                return None
            blanks.append(
                {
                    "id": node.get("identifier"),
                    "label": "",
                    "max_score": maximum,
                    "accepted_answers": answers,
                    "comparison_policy": "qti_literal_v1",
                    "rubric": "",
                }
            )
        return normalize_fill_spec(
            {"version": 2, "policy_version": "fill-grading/v2", "blanks": blanks}
        )
    except (ValueError, TypeError, KeyError):
        return None


def _signature(node):
    if not isinstance(node.tag, str):
        raise ValueError("Non-element scoring node")
    text = node.text or ""
    # Operator indentation has no meaning; literal numeric strings do.
    if len(node):
        if text.strip() or any((child.tail or "").strip() for child in node):
            raise ValueError("Unsupported scoring text")
        text = ""
    return (
        node.tag,
        tuple(sorted(node.attrib.items())),
        text,
        tuple(_signature(child) for child in node),
    )


def recognize(root, declarations: list, spec: dict | None) -> bool:
    if spec is None or not portable(spec):
        return False
    response_ids = [node.get("identifier") for node in declarations]
    names = RESERVED_OUTCOMES | {points_id(rid) for rid in response_ids}
    if names.intersection(response_ids) or len(names) != 3 + len(response_ids):
        return False
    expected = etree.Element(_Q + "qti-assessment-item")
    # Match declaration grammar as well as the arithmetic AST. Extra mappings,
    # alternative cardinality, stale primary keys or hidden attrs are not proof.
    for declaration, blank in zip(declarations, spec["blanks"], strict=True):
        original = _node(
            expected,
            "qti-response-declaration",
            identifier=declaration.get("identifier"),
            cardinality="single",
            **{"base-type": "string"},
        )
        primary = next(
            answer["value"]
            for answer in blank["accepted_answers"]
            if answer["score"] == blank["max_score"]
        )
        _node(_node(original, "qti-correct-response"), "qti-value", primary)
        mapping = _node(
            original,
            "qti-mapping",
            **{
                "default-value": "0.00000",
                "lower-bound": "0.00000",
                "upper-bound": blank["max_score"],
            },
        )
        for answer in blank["accepted_answers"]:
            _node(
                mapping,
                "qti-map-entry",
                **{
                    "map-key": answer["value"],
                    "mapped-value": answer["score"],
                    "case-sensitive": "true",
                },
            )
        try:
            if _signature(declaration) != _signature(original):
                return False
        except ValueError:
            return False
    append_outcomes(expected, spec, response_ids)
    append_program(expected, spec, response_ids)
    actual_outcomes = root.findall(_Q + "qti-outcome-declaration")
    expected_outcomes = expected.findall(_Q + "qti-outcome-declaration")
    program = root.find(_Q + "qti-response-processing")
    try:
        return (
            program is not None
            and len(root.findall(_Q + "qti-response-processing")) == 1
            and len(actual_outcomes) == len(expected_outcomes)
            and all(
                _signature(a) == _signature(e)
                for a, e in zip(actual_outcomes, expected_outcomes, strict=True)
            )
            and _signature(program) == _signature(expected.find(_Q + "qti-response-processing"))
        )
    except ValueError:
        return False
