"""Narrow, explicit QTI 2.1/2.2 item grammar over canonical QuestionDocument v1."""

from __future__ import annotations

from collections.abc import Mapping

from defusedxml.lxml import fromstring as defused_fromstring

# Tree construction/types and XSD validation only; parsing uses defusedxml.
from lxml import etree  # nosec B410

from deeptutor.services.question_content.qti3 import parse_item as parse_qti3
from deeptutor.services.question_content.qti3 import serialize_item as serialize_qti3
from deeptutor.services.question_content.qti3.fill_scoring import read_spec, recognize
from deeptutor.services.question_content.qti3.profile import QTI_NS as QTI3_NS

from .profile import DIALECTS, diagnostic
from .xml import safe_root, validate_xml

_XML_LANG = "{http://www.w3.org/XML/1998/namespace}lang"
_QTI3_MATCH_CORRECT = "https://purl.imsglobal.org/spec/qti/v3p0/rptemplates/match_correct.xml"


def _match_correct(version: str) -> str:
    # The 2.x information model names this URI (without .xml) as the full
    # template identifier. The corresponding XML document has a .xml URL.
    return f"http://www.imsglobal.org/question/qti_v2p{version[-1]}/rptemplates/match_correct"


def _is_match_correct(source: etree._Element, version: str) -> bool:
    return (
        not len(source)
        and set(source.attrib) == {"template"}
        and source.get("template") in {_match_correct(version), _match_correct(version) + ".xml"}
    )


_TO_2 = {
    "qti-assessment-item": "assessmentItem",
    "qti-response-declaration": "responseDeclaration",
    "qti-correct-response": "correctResponse",
    "qti-value": "value",
    "qti-mapping": "mapping",
    "qti-map-entry": "mapEntry",
    "qti-outcome-declaration": "outcomeDeclaration",
    "qti-item-body": "itemBody",
    "qti-text-entry-interaction": "textEntryInteraction",
    "qti-choice-interaction": "choiceInteraction",
    "qti-simple-choice": "simpleChoice",
    "qti-extended-text-interaction": "extendedTextInteraction",
    "qti-rubric-block": "rubricBlock",
    "qti-response-processing": "responseProcessing",
    "qti-default-value": "defaultValue",
    "qti-base-value": "baseValue",
    "qti-response-condition": "responseCondition",
    "qti-response-if": "responseIf",
    "qti-response-else": "responseElse",
    "qti-is-null": "isNull",
    "qti-variable": "variable",
    "qti-set-outcome-value": "setOutcomeValue",
    "qti-map-response": "mapResponse",
    "qti-sum": "sum",
    "qti-divide": "divide",
    "div": "div",
    "p": "p",
    "img": "img",
}
_TO_3 = {value: key for key, value in _TO_2.items()}
_ATTR_TO_2 = {
    "time-dependent": "timeDependent",
    "base-type": "baseType",
    "response-identifier": "responseIdentifier",
    "max-choices": "maxChoices",
    "external-scored": "externalScored",
    "normal-maximum": "normalMaximum",
    "default-value": "defaultValue",
    "lower-bound": "lowerBound",
    "upper-bound": "upperBound",
    "map-key": "mapKey",
    "mapped-value": "mappedValue",
    "case-sensitive": "caseSensitive",
}
_ATTR_TO_3 = {value: key for key, value in _ATTR_TO_2.items()}
_ALLOWED_ATTRS = {
    "assessmentItem": {"identifier", "title", "adaptive", "timeDependent", _XML_LANG},
    "responseDeclaration": {"identifier", "cardinality", "baseType"},
    "correctResponse": set(),
    "value": set(),
    "mapping": {"defaultValue", "lowerBound", "upperBound"},
    "mapEntry": {"mapKey", "mappedValue", "caseSensitive"},
    "outcomeDeclaration": {
        "identifier",
        "cardinality",
        "baseType",
        "externalScored",
        "normalMaximum",
    },
    "itemBody": set(),
    "textEntryInteraction": {"responseIdentifier", "id"},
    "choiceInteraction": {"responseIdentifier", "shuffle", "maxChoices", "id"},
    "simpleChoice": {"identifier"},
    "extendedTextInteraction": {"responseIdentifier", "id"},
    "rubricBlock": {"view", "use"},
    "responseProcessing": {"template"},
    "defaultValue": set(),
    "baseValue": {"baseType"},
    "responseCondition": set(),
    "responseIf": set(),
    "responseElse": set(),
    "isNull": set(),
    "variable": {"identifier"},
    "setOutcomeValue": {"identifier"},
    "mapResponse": {"identifier"},
    "sum": set(),
    "divide": set(),
    "div": {"class"},
    "p": {"class"},
    "img": {"src", "alt"},
}


def _blocked(code: str, message: str, *, member_path: str = "") -> dict:
    return {
        "document": None,
        "content": "blocked",
        "scoring": "unavailable",
        "bankAdmission": "blocked",
        "diagnostics": [diagnostic(code, message, location=member_path)],
        "identifierMap": {},
        "assetReferences": [],
        "responseScoring": {},
    }


def _from_qti3(root: etree._Element, version: str) -> etree._Element:
    ns = DIALECTS[version].item_ns

    def copy(source: etree._Element, *, root_node: bool = False) -> etree._Element:
        if not isinstance(source.tag, str) or not source.tag.startswith(f"{{{QTI3_NS}}}"):
            raise ValueError("Unsupported QTI 3 element namespace")
        local = source.tag.rsplit("}", 1)[-1]
        if local not in _TO_2:
            raise ValueError("Unsupported QTI 3 element")
        if local == "qti-response-processing":
            if not (
                (
                    len(source)
                    and not source.attrib
                    and recognize(
                        root,
                        root.findall(f"{{{QTI3_NS}}}qti-response-declaration"),
                        read_spec(root.findall(f"{{{QTI3_NS}}}qti-response-declaration")),
                    )
                )
                or (
                    not len(source)
                    and set(source.attrib) == {"template"}
                    and source.get("template") == _QTI3_MATCH_CORRECT
                )
            ):
                raise ValueError("Unsupported QTI 3 response-processing template")
        target = etree.Element(f"{{{ns}}}{_TO_2[local]}", nsmap={None: ns} if root_node else None)
        for key, value in source.attrib.items():
            name = _ATTR_TO_2.get(key, key)
            if version == "2.1" and name == "externalScored":
                continue  # 2.1 has no externalScored attribute.
            if local == "qti-response-processing" and name == "template":
                value = _match_correct(version)
            target.set(name, value)
        target.text = source.text
        target.tail = source.tail
        for child in source:
            if child.tag == f"{{{QTI3_NS}}}qti-content-body":
                if local != "qti-rubric-block":
                    raise ValueError("QTI content-body outside rubric")
                for grandchild in child:
                    target.append(copy(grandchild))
                continue
            target.append(copy(child))
        return target

    return copy(root, root_node=True)


def serialize_item(
    document: dict,
    *,
    version: str,
    asset_paths: Mapping[str, str] | None = None,
    score_snapshot: dict | None = None,
    origin_label: str | None = None,
) -> dict:
    if version not in DIALECTS:
        return {**_blocked("QTI_VERSION_UNSUPPORTED", "Unsupported QTI 2 version"), "xml": None}
    base = serialize_qti3(
        document, asset_paths=asset_paths, score_snapshot=score_snapshot, origin_label=origin_label
    )
    if base.get("xml") is None:
        return base
    try:
        transformed = _from_qti3(
            defused_fromstring(base["xml"], forbid_dtd=True, forbid_entities=True), version
        )
        xml = etree.tostring(transformed, encoding="UTF-8", xml_declaration=True)
        issues = validate_xml(xml, kind="item", version=version)
    except (ValueError, etree.XMLSyntaxError) as exc:
        issues = [diagnostic("QTI2_MAPPING_BLOCKED", str(exc)[:200])]
        xml = None
    result = {
        **base,
        "xml": xml if not issues else None,
        "diagnostics": [*base.get("diagnostics", []), *issues],
    }
    if issues:
        result["content"] = result["bankAdmission"] = "blocked"
    elif version == "2.1" and result["scoring"] == "external":
        result["diagnostics"].append(
            diagnostic(
                "QTI21_EXTERNAL_SCORING_REQUIRED",
                "QTI 2.1 has no externalScored marker; scorer guidance requires manual processing",
                severity="warning",
            )
        )
    return result


def _to_qti3(root: etree._Element, version: str) -> etree._Element:
    ns = DIALECTS[version].item_ns

    def copy(source: etree._Element, *, root_node: bool = False) -> etree._Element:
        if not isinstance(source.tag, str) or not source.tag.startswith(f"{{{ns}}}"):
            raise ValueError("Unsupported QTI 2 element namespace")
        local = source.tag.rsplit("}", 1)[-1]
        if local not in _TO_3:
            raise ValueError(f"Unsupported QTI 2 element: {local}")
        if set(source.attrib) - _ALLOWED_ATTRS[local]:
            raise ValueError(f"Unsupported QTI 2 attributes on {local}")
        target = etree.Element(
            f"{{{QTI3_NS}}}{_TO_3[local]}", nsmap={None: QTI3_NS} if root_node else None
        )
        for key, value in source.attrib.items():
            target.set(_ATTR_TO_3.get(key, key), value)
        target.text = source.text
        target.tail = source.tail
        if local == "rubricBlock":
            body = etree.SubElement(target, f"{{{QTI3_NS}}}qti-content-body")
            for child in source:
                body.append(copy(child))
            return target
        for child in source:
            if child.tag == f"{{{ns}}}responseProcessing":
                if local != "assessmentItem":
                    raise ValueError("Response processing has unexpected location")
                if _is_match_correct(child, version):
                    etree.SubElement(
                        target,
                        f"{{{QTI3_NS}}}qti-response-processing",
                        template=_QTI3_MATCH_CORRECT,
                    )
                elif (
                    not len(child)
                    and set(child.attrib) == {"template"}
                    and child.get("template")
                    in {
                        _match_correct(version).replace("match_correct", "map_response"),
                        _match_correct(version).replace("match_correct", "map_response") + ".xml",
                    }
                ):
                    etree.SubElement(
                        target,
                        f"{{{QTI3_NS}}}qti-response-processing",
                        template=_QTI3_MATCH_CORRECT.replace("match_correct", "map_response"),
                    )
                elif len(child) and not child.attrib:
                    target.append(copy(child))
                else:
                    raise ValueError(
                        "Unsupported QTI 2 response-processing rules cannot be imported"
                    )
                continue
            target.append(copy(child))
        return target

    return copy(root, root_node=True)


def parse_item(
    data: bytes,
    *,
    version: str,
    member_path: str = "item.xml",
    asset_map: Mapping[str, dict] | None = None,
    trusted_export: bool = False,
) -> dict:
    if version not in DIALECTS:
        return _blocked(
            "QTI_VERSION_UNSUPPORTED", "Unsupported QTI 2 version", member_path=member_path
        )
    issues = validate_xml(data, kind="item", version=version)
    if issues:
        return {
            **_blocked(
                "QTI2_ITEM_XSD_INVALID", "QTI 2 item XSD validation failed", member_path=member_path
            ),
            "diagnostics": issues,
        }
    try:
        root = safe_root(data, kind="item", version=version)
        converted = _to_qti3(root, version)
        program = converted.find(f"{{{QTI3_NS}}}qti-response-processing")
        declarations = converted.findall(f"{{{QTI3_NS}}}qti-response-declaration")
        if (
            program is not None
            and len(program)
            and not recognize(converted, declarations, read_spec(declarations))
        ):
            raise ValueError("Unsupported QTI 2 response-processing rules cannot be imported")
        internal = etree.tostring(converted, encoding="UTF-8", xml_declaration=True)
        result = parse_qti3(
            internal, member_path=member_path, asset_map=asset_map, trusted_export=trusted_export
        )
        if version == "2.1" and result.get("scoring") == "external":
            result["diagnostics"] = [
                *result.get("diagnostics", []),
                diagnostic(
                    "QTI21_EXTERNAL_SCORING_REQUIRED",
                    "QTI 2.1 lacks an externalScored marker; scorer must process guidance manually",
                    location=member_path,
                    severity="warning",
                ),
            ]
        return result
    except (ValueError, KeyError, TypeError, etree.XMLSyntaxError) as exc:
        return _blocked("QTI2_MAPPING_BLOCKED", str(exc)[:200], member_path=member_path)


__all__ = ["serialize_item", "parse_item"]
