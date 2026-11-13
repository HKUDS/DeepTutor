"""QTI 3 item XML mapping for the narrow canonical bank profile."""

from __future__ import annotations

from collections.abc import Mapping
import json
import posixpath
import re
from urllib.parse import unquote, urlsplit

# Tree construction/types and XSD validation only; parsing uses defusedxml.
from lxml import etree  # nosec B410

from deeptutor.services.practice.fill_blanks import normalize_fill_spec
from deeptutor.services.question_content.core import normalize_question_document

from .fill_scoring import append_outcomes, append_program, portable, read_spec, recognize
from .fill_scoring import response_id as qti_response_id
from .mapping import preflight, qti_id
from .profile import PROFILE_VERSION, QTI_NS, diagnostic
from .xml import safe_root, validate_xml

_Q = "{" + QTI_NS + "}"
_XML = "{http://www.w3.org/XML/1998/namespace}"
_MARKER = re.compile(r"\{\{blank:([A-Za-z0-9_-]{1,80})\}\}")
_GUIDANCE_PREFIX = "Reactutor scorer guidance v1: "


def _node(
    parent: etree._Element, name: str, text: str | None = None, **attrs: str
) -> etree._Element:
    element = etree.SubElement(parent, _Q + name, attrib=attrs)
    if text is not None:
        element.text = text
    return element


def _append_text(parent: etree._Element, text: str) -> None:
    if len(parent):
        parent[-1].tail = (parent[-1].tail or "") + text
    else:
        parent.text = (parent.text or "") + text


def _safe_href(value: str, member_path: str) -> str:
    if not value or value.startswith(("/", "\\")) or "\\" in value or "%" in value:
        raise ValueError("Unsafe asset href")
    parsed = urlsplit(value)
    if parsed.scheme or parsed.netloc or parsed.query or parsed.fragment or unquote(value) != value:
        raise ValueError("Remote or encoded asset href")
    resolved = posixpath.normpath(posixpath.join(posixpath.dirname(member_path), value))
    if resolved == ".." or resolved.startswith("../") or resolved.startswith("/"):
        raise ValueError("Asset href escapes package")
    return resolved


def _render_body_block(element: etree._Element) -> tuple[str, list[etree._Element]]:
    """Flatten a small, ordered QTI HTML subset into the bank's text stem."""
    local = element.tag.removeprefix(_Q)
    if local not in {
        "p",
        "div",
        "blockquote",
        "br",
        "em",
        "strong",
        "u",
        "qti-text-entry-interaction",
    }:
        raise ValueError(f"Unsupported item body element: {local}")
    allowed_attrs = {
        "p": {"class"},
        "div": set(),
        "blockquote": {"class"},
        "br": set(),
        "em": set(),
        "strong": set(),
        "u": set(),
        "qti-text-entry-interaction": {"response-identifier", "id"},
    }
    if set(element.attrib) - allowed_attrs[local]:
        raise ValueError(f"Unsupported {local} attributes")
    if local == "p" and element.get("class") not in {None, "reactutor-prompt"}:
        raise ValueError("Unsupported paragraph style")
    if local == "blockquote" and element.get("class") not in {None, "postcard"}:
        raise ValueError("Unsupported block quote style")
    if local == "br":
        if len(element) or (element.text or "").strip():
            raise ValueError("Line break has unsupported content")
        return "\n", []
    if local == "qti-text-entry-interaction":
        rid = element.get("response-identifier")
        if not rid or len(element) or (element.text or "").strip():
            raise ValueError("Text-entry interaction has unsupported content")
        return "{{blank:" + rid + "}}", [element]
    text = element.text or ""
    entries: list[etree._Element] = []
    for child in element:
        fragment, nested = _render_body_block(child)
        text += fragment + (child.tail or "")
        entries.extend(nested)
    if local in {"p", "blockquote"}:
        # XML indentation around <br/> is formatting whitespace, whereas
        # the resulting single line break carries the authored line order.
        text = re.sub(r"\n(?:[ \t]*\n)+[ \t]*", "\n", text)
        text = re.sub(r"\n[ \t]+", "\n", text)
    if local in {"em", "strong", "u"}:
        if "\n" in text or "{{blank:" in text:
            raise ValueError("Complex inline formatting around an interaction is unsupported")
        left, right = {"em": ("*", "*"), "strong": ("**", "**"), "u": ("<u>", "</u>")}[local]
        return left + text + right, entries
    if local == "blockquote":
        return "\n".join("> " + line for line in text.strip().splitlines()), entries
    if local == "div":
        return text.strip(), entries
    return text.strip("\n"), entries


def _trusted_identifiers(
    guidance: dict,
    item_id: str,
    response_ids: list[str],
    interactions: list[etree._Element],
    option_ids: list[str],
) -> dict:
    """Restore only owned metadata whose bijections agree with XML declarations.

    Older owned artifacts carried ordered canonicalIds only. Reconstruct their
    deterministic map; never decode uploaded identifier spelling heuristically.
    """
    canonical = guidance.get("canonicalIds")
    if not isinstance(canonical, dict) or set(canonical) != {
        "item",
        "responses",
        "interactions",
        "options",
    }:
        raise ValueError("Missing trusted canonical identifiers")
    explicit = guidance.get("identifierMap")
    forward = {}
    for group, prefix in (
        ("item", "item"),
        ("responses", "response"),
        ("interactions", "interaction"),
        ("options", "option"),
    ):
        names = [canonical[group]] if group == "item" else canonical[group]
        if (
            not isinstance(names, list)
            or len(names) > 20
            or any(not isinstance(name, str) or not name for name in names)
            or len(names) != len(set(names))
        ):
            raise ValueError("Invalid trusted canonical identifiers")
        forward[group] = {
            name: (
                qti_response_id(name)
                if group == "responses" and guidance.get("questionType") == "fill_blank"
                else qti_id(name, prefix=prefix)
            )
            for name in names
        }
        if len(set(forward[group].values())) != len(names):
            raise ValueError("Trusted identifier collision")
    if explicit is not None and explicit != forward:
        raise ValueError("Trusted identifier map conflicts with canonical identifiers")
    if (
        list(forward["item"].values()) != [item_id]
        or list(forward["responses"].values()) != response_ids
    ):
        raise ValueError("Trusted identifiers conflict with QTI declarations")
    mapped_interactions = list(forward["interactions"].values())
    if len(mapped_interactions) != len(interactions) or any(
        node.get("id") != mapped
        for node, mapped in zip(interactions, mapped_interactions, strict=True)
        if explicit is not None or node.get("id") is not None
    ):
        raise ValueError("Trusted interaction identifiers conflict with QTI body")
    mapped_options = list(forward["options"].values())
    if mapped_options != option_ids and not (not mapped_options and option_ids == ["T", "F"]):
        raise ValueError("Trusted option identifiers conflict with QTI body")
    return {
        group: {mapped: original for original, mapped in mapping.items()}
        for group, mapping in forward.items()
    }


def serialize_item(
    document: dict,
    *,
    asset_paths: Mapping[str, str] | None = None,
    score_snapshot: dict | None = None,
    origin_label: str | None = None,
) -> dict:
    report = preflight(document, asset_paths=asset_paths, score_snapshot=score_snapshot)
    empty_map: dict[str, dict[str, str]] = {
        "item": {},
        "responses": {},
        "interactions": {},
        "options": {},
    }
    result = {**report, "xml": None, "identifierMap": empty_map, "assetReferences": []}
    if report["content"] == "blocked":
        return result
    doc = normalize_question_document(document, source_format="content-v1")
    identity = result["identifierMap"]
    item_id = qti_id(doc["itemId"], prefix="item")
    identity["item"][doc["itemId"]] = item_id
    for row in doc["responses"]:
        identity["responses"][row["id"]] = qti_response_id(
            row["id"], reserve=doc["questionType"] == "fill_blank"
        )
    for row in doc["interactions"]:
        identity["interactions"][row["id"]] = qti_id(row["id"], prefix="interaction")
        for option in row["options"]:
            identity["options"][option["id"]] = qti_id(option["id"], prefix="option")
    if any(len(set(mapping.values())) != len(mapping) for mapping in identity.values()):
        result["diagnostics"].append(
            diagnostic("IDENTIFIER_COLLISION", "Canonical identifiers collide in a QTI namespace")
        )
        result["content"] = result["bankAdmission"] = "blocked"
        return result
    fill_spec = doc["author"]["fillSpec"]
    literal_program = fill_spec is not None and portable(fill_spec)
    root = etree.Element(
        _Q + "qti-assessment-item",
        nsmap={None: QTI_NS},
        attrib={
            "identifier": item_id,
            "title": item_id,
            "adaptive": "false",
            "time-dependent": "false",
            _XML + "lang": doc["language"],
        },
    )
    for response in doc["responses"]:
        rid = identity["responses"][response["id"]]
        declaration = _node(
            root,
            "qti-response-declaration",
            identifier=rid,
            cardinality=response["cardinality"],
            **{"base-type": response["baseType"]},
        )
        values: list[str] = []
        if doc["questionType"] == "fill_blank":
            spec = doc["author"]["fillSpec"]
            blank = next(row for row in spec["blanks"] if row["id"] == response["id"])
            values = [
                next(
                    answer["value"]
                    for answer in blank["accepted_answers"]
                    if answer["score"] == blank["max_score"]
                )
            ]
        elif doc["questionType"] in {"single_choice", "multi_choice"}:
            values = [
                identity["options"][part]
                for part in doc["author"]["correctAnswer"].split(",")
                if part
            ]
        elif doc["questionType"] == "true_false":
            values = [
                "T"
                if doc["author"]["correctAnswer"].casefold()
                in {"t", "true", "对", "正确", "是", "yes", "y", "1", "√", "✓"}
                else "F"
            ]
        elif doc["questionType"] in {"short_answer", "written"} and doc["author"]["correctAnswer"]:
            values = [doc["author"]["correctAnswer"]]
        if values:
            correct = _node(declaration, "qti-correct-response")
            for value in values:
                _node(correct, "qti-value", value)
        if doc["questionType"] == "fill_blank":
            mapping = _node(
                declaration,
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
    if literal_program:
        append_outcomes(root, fill_spec, list(identity["responses"].values()))
    else:
        outcome_attrs = {"base-type": "float"}
        if report["scoring"] != "equivalent":
            outcome_attrs["external-scored"] = "human"
        _node(
            root,
            "qti-outcome-declaration",
            identifier="SCORE",
            cardinality="single",
            **outcome_attrs,
        )
    body = _node(root, "qti-item-body")
    if origin_label:
        rubric = _node(body, "qti-rubric-block", view="candidate", use="instructions")
        _node(_node(rubric, "qti-content-body"), "p", origin_label)
    if doc["materials"]:
        shared = _node(body, "div", **{"class": "reactutor-shared-context"})
        _node(shared, "p", doc["materials"][0]["body"][0]["text"])
    prompt = _node(body, "p", **{"class": "reactutor-prompt"})
    stem = doc["body"][0]["text"]
    if doc["questionType"] == "fill_blank":
        last = 0
        for match in _MARKER.finditer(stem):
            _append_text(prompt, stem[last : match.start()])
            _node(
                prompt,
                "qti-text-entry-interaction",
                **{
                    "response-identifier": identity["responses"][match.group(1)],
                    "id": identity["interactions"][
                        next(
                            row["interactionId"]
                            for row in doc["responses"]
                            if row["id"] == match.group(1)
                        )
                    ],
                },
            )
            last = match.end()
        _append_text(prompt, stem[last:])
    else:
        prompt.text = stem
    for part in doc["body"][1:]:
        asset_id = part["assetId"]
        href = (asset_paths or {})[asset_id]
        if (
            not isinstance(href, str)
            or not href
            or href.startswith(("/", "\\"))
            or "\\" in href
            or ":" in href
        ):
            result["diagnostics"].append(
                diagnostic("PROMPT_ASSET_PATH_INVALID", "Unsafe prompt image href")
            )
            result["content"] = result["bankAdmission"] = "blocked"
            return result
        image = _node(
            _node(body, "p"),
            "img",
            src=href,
            alt="题目图片" if doc["language"].startswith("zh") else "Question image",
        )
        result["assetReferences"].append(image.get("src"))
    kind = doc["questionType"]
    if kind in {"single_choice", "multi_choice", "true_false"}:
        response_id = identity["responses"][doc["responses"][0]["id"]]
        choices = _node(
            body,
            "qti-choice-interaction",
            **{
                "response-identifier": response_id,
                "id": identity["interactions"][doc["interactions"][0]["id"]],
                "shuffle": "false",
                "max-choices": "0" if kind == "multi_choice" else "1",
            },
        )
        options = doc["interactions"][0]["options"] or [
            {"id": "T", "text": "True"},
            {"id": "F", "text": "False"},
        ]
        for option in options:
            _node(
                choices,
                "qti-simple-choice",
                option["text"],
                identifier=identity["options"].get(option["id"], option["id"]),
            )
    elif kind in {"short_answer", "written"}:
        _node(
            body,
            "qti-extended-text-interaction",
            **{
                "response-identifier": identity["responses"][doc["responses"][0]["id"]],
                "id": identity["interactions"][doc["interactions"][0]["id"]],
            },
        )
    # This is private scorer material, not candidate-visible content. It keeps
    # the complete fill policy/guidance across a clean author re-import.
    guidance = {
        "profile": PROFILE_VERSION,
        "subject": doc["subject"],
        "author": doc["author"],
        "questionType": kind,
        "identifierMap": identity,
        "canonicalIds": {
            "item": doc["itemId"],
            "responses": list(identity["responses"]),
            "interactions": list(identity["interactions"]),
            "options": list(identity["options"]),
        },
    }
    rubric = _node(body, "qti-rubric-block", view="scorer", use="scoring")
    content = _node(rubric, "qti-content-body")
    if doc["author"]["correctAnswer"]:
        _node(content, "p", "Reference answer: " + doc["author"]["correctAnswer"])
    if doc["author"]["fillSpec"] is not None:
        for blank in doc["author"]["fillSpec"]["blanks"]:
            _node(
                content,
                "p",
                "Blank "
                + blank["id"]
                + ": "
                + ", ".join(
                    answer["value"] + " = " + answer["score"] + "/" + blank["max_score"]
                    for answer in blank["accepted_answers"]
                )
                + " ("
                + blank["comparison_policy"]
                + ")"
                + (" — " + blank["rubric"] if blank["rubric"] else ""),
            )
    if doc["author"]["explanation"]:
        _node(content, "p", "Scoring guidance: " + doc["author"]["explanation"])
    _node(
        content,
        "p",
        _GUIDANCE_PREFIX
        + json.dumps(guidance, ensure_ascii=False, sort_keys=True, separators=(",", ":")),
    )
    if literal_program:
        append_program(root, fill_spec, list(identity["responses"].values()))
    elif report["scoring"] == "equivalent" and kind in {
        "single_choice",
        "multi_choice",
        "true_false",
    }:
        _node(
            root,
            "qti-response-processing",
            template="https://purl.imsglobal.org/spec/qti/v3p0/rptemplates/match_correct.xml",
        )
    # No other automatic response-processing is emitted. In particular the
    # host's trim and semantic grading policies are not portable by assertion.
    xml = etree.tostring(root, encoding="UTF-8", xml_declaration=True)
    xsd = validate_xml(xml, "item")
    if xsd:
        result["diagnostics"].extend(xsd)
        result["content"] = result["bankAdmission"] = "blocked"
        return result
    result["xml"] = xml
    return result


def parse_item(
    data: bytes,
    *,
    member_path: str = "item.xml",
    asset_map: Mapping[str, dict] | None = None,
    trusted_export: bool = False,
) -> dict:
    result: dict = {
        "document": None,
        "content": "blocked",
        "scoring": "unavailable",
        "bankAdmission": "blocked",
        "diagnostics": [],
        "identifierMap": {"item": {}, "responses": {}, "interactions": {}, "options": {}},
        "assetReferences": [],
    }
    xsd = validate_xml(data, "item")
    if xsd:
        result["diagnostics"].extend(xsd)
        return result
    try:
        root = safe_root(data, kind="item")
        qti_item_id = root.get("identifier")
        if not qti_item_id:
            raise ValueError("Missing item identifier")
        if root.get("adaptive") not in {None, "false"} or root.get("time-dependent") not in {
            None,
            "false",
        }:
            raise ValueError("Adaptive/time-dependent item is unsupported")
        body = root.find(_Q + "qti-item-body")
        if body is None:
            raise ValueError("Missing item body")
        declarations = root.findall(_Q + "qti-response-declaration")
        if not 1 <= len(declarations) <= 20:
            raise ValueError("Unsupported response declaration count")
        if root.find(_Q + "qti-template-processing") is not None:
            raise ValueError("Template processing is unsupported")
        response_processing = root.find(_Q + "qti-response-processing")
        exact_choice_template = bool(
            response_processing is not None
            and response_processing.get("template")
            == "https://purl.imsglobal.org/spec/qti/v3p0/rptemplates/match_correct.xml"
            and not len(response_processing)
            and set(response_processing.attrib) == {"template"}
        )
        map_response_template = bool(
            response_processing is not None
            and not len(response_processing)
            and set(response_processing.attrib) == {"template"}
            and response_processing.get("template")
            == "https://purl.imsglobal.org/spec/qti/v3p0/rptemplates/map_response.xml"
            and len(declarations) == 1
            and declarations[0].get("identifier") == "RESPONSE"
        )
        point_spec = read_spec(declarations)
        finite_program = recognize(root, declarations, point_spec)
        if response_processing is not None and not (
            exact_choice_template or map_response_template or finite_program
        ):
            # No arbitrary response-processing interpreter. Candidate may keep
            # content but only if the rest of the structure can map faithfully.
            result["diagnostics"].append(
                diagnostic(
                    "SCORING_PROGRAM_UNSUPPORTED",
                    "Uploaded response-processing is not executed",
                    severity="warning",
                )
            )
        scorer_blocks = [
            node
            for node in body.findall(_Q + "qti-rubric-block")
            if node.get("view") == "scorer" and node.get("use") == "scoring"
        ]
        other_blocks = [
            node for node in body.findall(_Q + "qti-rubric-block") if node not in scorer_blocks
        ]
        guidance = None
        source_guidance = []
        explanation = ""
        for block in scorer_blocks:
            for paragraph in block.iter(_Q + "p"):
                text = "".join(paragraph.itertext()).strip()
                if text.startswith(_GUIDANCE_PREFIX) and not trusted_export:
                    # A third party may copy our rubric marker. It is source
                    # text, never a key, policy, identity, or grading witness.
                    result["diagnostics"].append(
                        diagnostic(
                            "SOURCE_GUIDANCE_UNTRUSTED",
                            "Embedded scorer metadata is not an authorized export receipt",
                            severity="warning",
                        )
                    )
                    try:
                        source_guidance.append(json.loads(text[len(_GUIDANCE_PREFIX) :]))
                    except (ValueError, TypeError):
                        source_guidance.append(None)
                    continue
                if text.startswith(_GUIDANCE_PREFIX):
                    try:
                        candidate = json.loads(text[len(_GUIDANCE_PREFIX) :])
                    except json.JSONDecodeError as exc:
                        raise ValueError("Invalid scorer guidance") from exc
                    if (
                        not isinstance(candidate, dict)
                        or candidate.get("profile") != PROFILE_VERSION
                    ):
                        raise ValueError("Unsupported scorer guidance profile")
                    if guidance is not None:
                        raise ValueError("Duplicate trusted scorer guidance")
                    guidance = candidate
                else:
                    explanation += ("\n" if explanation else "") + text
        instructions = []
        for block in other_blocks:
            if block.get("view") != "candidate" or block.get("use") != "instructions":
                raise ValueError("Unsupported rubric block")
            text = "".join(block.itertext()).strip()
            if text and (
                not trusted_export
                or text
                not in {"AI 生成", "内容由 AI 辅助生成", "AI generated", "AI-assisted content"}
            ):
                instructions.append(text)
        children = [child for child in body if child.tag != _Q + "qti-rubric-block"]
        shared_text = ""
        if (
            children
            and children[0].tag == _Q + "div"
            and children[0].get("class") == "reactutor-shared-context"
        ):
            shared_node = children.pop(0)
            if len(shared_node) != 1 or shared_node[0].tag != _Q + "p" or len(shared_node[0]):
                raise ValueError("Shared material is not representable")
            shared_text = shared_node[0].text or ""
        prompt_parts: list[str] = []
        text_entry_nodes: list[etree._Element] = []
        while children and children[0].tag in {_Q + "p", _Q + "div", _Q + "blockquote"}:
            # Image paragraphs are handled below with their verified assets.
            if (
                children[0].tag == _Q + "p"
                and len(children[0]) == 1
                and children[0][0].tag == _Q + "img"
            ):
                break
            block = children.pop(0)
            rendered, entries = _render_body_block(block)
            prompt_parts.append(rendered)
            text_entry_nodes.extend(entries)
        prompt_text = "\n\n".join(part for part in prompt_parts if part)
        images = []
        while (
            children
            and children[0].tag == _Q + "p"
            and len(children[0]) == 1
            and children[0][0].tag == _Q + "img"
        ):
            image_paragraph = children.pop(0)
            if (image_paragraph.text or "").strip() or (image_paragraph[0].tail or "").strip():
                raise ValueError("Image paragraph has unsupported text")
            image = image_paragraph[0]
            if image.get("alt") not in {"Question image", "题目图片"} or set(image.attrib) - {
                "src",
                "alt",
            }:
                raise ValueError("Image description/styling is unsupported")
            href = image.get("src")
            if href is None:
                raise ValueError("Image has no href")
            resolved = _safe_href(href, member_path)
            result["assetReferences"].append(href)
            asset = (asset_map or {}).get(resolved)
            if not asset or asset.get("kind") != "image" or asset.get("role") != "prompt":
                raise ValueError("Missing verified prompt image")
            images.append(asset)
        if (
            len(images) > 100
            or children
            and children[0].tag
            not in {_Q + "qti-choice-interaction", _Q + "qti-extended-text-interaction"}
        ):
            raise ValueError("Unsupported item body structure")
        choice = (
            children.pop(0)
            if children and children[0].tag == _Q + "qti-choice-interaction"
            else None
        )
        extended = (
            children.pop(0)
            if children and children[0].tag == _Q + "qti-extended-text-interaction"
            else None
        )
        if children:
            raise ValueError("Unsupported trailing item content")
        if choice is not None and (extended is not None or text_entry_nodes):
            raise ValueError("Mixed interactions are unsupported")
        if extended is not None and text_entry_nodes:
            raise ValueError("Mixed interactions are unsupported")
        if choice is None and extended is None and not text_entry_nodes:
            raise ValueError("No supported interaction")
        if choice is not None:
            if len(declarations) != 1 or choice.get("shuffle") not in {None, "false"}:
                raise ValueError("Choice shuffle or cardinality is unsupported")
            options: list[dict] = []
            saw_choice_prompt = False
            for option in choice:
                if option.tag == _Q + "qti-prompt" and not saw_choice_prompt and not options:
                    if len(option):
                        raise ValueError("Rich choice prompt is unsupported")
                    prompt_text += ("\n" if prompt_text else "") + (option.text or "")
                    saw_choice_prompt = True
                    continue
                if (
                    option.tag != _Q + "qti-simple-choice"
                    or len(option)
                    or option.get("identifier") is None
                ):
                    raise ValueError("Rich or unknown choice is unsupported")
                options.append({"id": option.get("identifier"), "text": option.text or ""})
            if len(options) < 2 or len(options) > 10:
                raise ValueError("Choice count is unsupported")
            if [o["id"] for o in options] == ["T", "F"]:
                kind = "true_false"
            else:
                kind = (
                    "multi_choice"
                    if declarations[0].get("cardinality") == "multiple"
                    else "single_choice"
                )
            if choice.get("max-choices") not in (
                {"0", None} if kind == "multi_choice" else {"1", None}
            ):
                raise ValueError("Choice max-choices is unsupported")
        elif extended is not None:
            kind = "written"
            options = []
            if len(extended) > 1 or any(
                child.tag != _Q + "qti-prompt" or len(child) for child in extended
            ):
                raise ValueError("Rich extended-text prompt is unsupported")
            if len(extended):
                prompt_text += ("\n" if prompt_text else "") + (extended[0].text or "")
        else:
            kind = "fill_blank"
            options = []
            if len(text_entry_nodes) != len(declarations):
                raise ValueError("Blank/response count mismatch")
        response_ids = [node.get("identifier") for node in declarations]
        if any(not rid for rid in response_ids) or len(set(response_ids)) != len(response_ids):
            raise ValueError("Duplicate/missing response identifier")
        actual_refs = (
            [choice.get("response-identifier")]
            if choice is not None
            else [extended.get("response-identifier")]
            if extended is not None
            else [node.get("response-identifier") for node in text_entry_nodes]
        )
        if actual_refs != response_ids:
            raise ValueError("Interaction/response order mismatch")
        if any(
            node.get("base-type") != ("identifier" if choice is not None else "string")
            or node.get("cardinality") != ("multiple" if kind == "multi_choice" else "single")
            for node in declarations
        ):
            raise ValueError("Unsupported response declaration type")
        correct_values = []
        unsupported_mapping = False
        for node in declarations:
            correct = node.find(_Q + "qti-correct-response")
            correct_values.append(
                [value.text or "" for value in correct.findall(_Q + "qti-value")]
                if correct is not None
                else []
            )
            if node.get("cardinality") == "single" and len(correct_values[-1]) > 1:
                raise ValueError(
                    "Single-cardinality response must not declare multiple correct values"
                )
        if kind == "fill_blank" and point_spec is None:
            unsupported_mapping = True
            result["diagnostics"].append(
                diagnostic(
                    "FILL_MAPPING_CONFLICT",
                    "Fill mapping is missing, unsupported or conflicts with its full-credit reference",
                    severity="warning",
                )
            )
        if kind != "fill_blank" and any(
            node.find(_Q + "qti-mapping") is not None for node in declarations
        ):
            unsupported_mapping = True
        if kind == "true_false":
            correct_answer = correct_values[0][0] if correct_values[0] else ""
        elif choice is not None:
            correct_answer = (
                ",".join(sorted(correct_values[0]))
                if kind == "multi_choice"
                else (correct_values[0][0] if correct_values[0] else "")
            )
        else:
            correct_answer = (
                correct_values[0][0] if extended is not None and correct_values[0] else ""
            )
        external_option_ids = [option["id"] for option in options]
        xml_response_ids = list(response_ids)
        xml_interactions = (
            [choice]
            if choice is not None
            else [extended]
            if extended is not None
            else text_entry_nodes
        )
        restored = (
            _trusted_identifiers(
                guidance, qti_item_id, response_ids, xml_interactions, external_option_ids
            )
            if guidance
            else None
        )
        if restored:
            response_ids = [restored["responses"][rid] for rid in xml_response_ids]
            prompt_text = _MARKER.sub(
                lambda match: "{{blank:" + restored["responses"][match.group(1)] + "}}", prompt_text
            )
        if restored and kind == "true_false" and not restored["options"]:
            # QTI materializes T/F choices even when the owned canonical source
            # intentionally used the empty implicit-choice representation.
            options = []
        if choice is not None and kind != "true_false":
            # Bank option keys are A-J. QTI identifiers are opaque; retain the
            # actual QTI identifiers in the reverse map rather than dropping a
            # valid external choice item solely for its identifier spelling.
            option_ids = (
                restored["options"]
                if restored
                else dict(zip(external_option_ids, "ABCDEFGHIJ", strict=False))
            )
            if len(option_ids) != len(options):
                raise ValueError("Duplicate choice identifier")
            if any(key not in option_ids for key in correct_values[0]):
                raise ValueError("Correct response references an unknown choice")
            correct_answer = ",".join(sorted(option_ids[key] for key in correct_values[0]))
            options = [{**option, "id": option_ids[option["id"]]} for option in options]
        subject = {"topic": "", "difficulty": "", "tags": []}
        if guidance:
            subject = guidance.get("subject", subject)
            author = guidance.get("author", {})
            declared = correct_values[0] if choice is not None else []
            if choice is not None and declared:
                guided = author.get("correctAnswer", "")
                if kind == "true_false":
                    expected = (
                        "T"
                        if str(guided).casefold()
                        in {"t", "true", "对", "正确", "是", "yes", "y", "1", "√", "✓"}
                        else "F"
                    )
                    if expected != declared[0]:
                        raise ValueError("Trusted scorer key conflicts with QTI declaration")
                elif set(str(guided).split(",")) != set(correct_answer.split(",")):
                    raise ValueError("Trusted scorer key conflicts with QTI declaration")
            if kind == "fill_blank":
                guided = normalize_fill_spec(author.get("fillSpec"))
                if point_spec is None or len(guided["blanks"]) != len(response_ids):
                    raise ValueError("Trusted fill policy conflicts with QTI declarations")
                for blank, mapped, rid, values in zip(
                    guided["blanks"],
                    point_spec["blanks"],
                    response_ids,
                    correct_values,
                    strict=True,
                ):
                    primary = next(
                        answer["value"]
                        for answer in blank["accepted_answers"]
                        if answer["score"] == blank["max_score"]
                    )
                    if (
                        blank["id"] != rid
                        or blank["max_score"] != mapped["max_score"]
                        or blank["accepted_answers"] != mapped["accepted_answers"]
                        or values != [primary]
                    ):
                        raise ValueError("Trusted fill policy conflicts with QTI declarations")
                if portable(guided) and not finite_program:
                    raise ValueError("Trusted literal scoring program changed")
            if extended is not None:
                authored_kind = guidance.get("questionType")
                if authored_kind not in {"short_answer", "written"}:
                    raise ValueError(
                        "Trusted extended-text question type conflicts with QTI interaction"
                    )
                kind = authored_kind
            if (
                extended is not None
                and correct_answer
                and author.get("correctAnswer", correct_answer) != correct_answer
            ):
                raise ValueError("Trusted reference answer conflicts with QTI declaration")
            if unsupported_mapping:
                raise ValueError(
                    "Trusted fill mapping conflicts with supported declaration profile"
                )
            correct_answer = author.get("correctAnswer", correct_answer)
            explanation = author.get("explanation", explanation)
            fill_spec = author.get("fillSpec")
            if guidance.get("questionType") in {"single_choice", "true_false"} and kind in {
                "single_choice",
                "true_false",
            }:
                kind = guidance["questionType"]
        else:
            fill_spec = None
        unsupported_program = response_processing is not None and not (
            (choice is not None and exact_choice_template)
            or (kind == "fill_blank" and finite_program)
        )
        if unsupported_mapping or unsupported_program:
            result["diagnostics"].append(
                diagnostic(
                    "SCORING_PROGRAM_UNSUPPORTED",
                    "Scoring rules are retained as inert references and require review",
                    severity="warning",
                )
            )
            # Preserve unsupported QTI rules for an author/scorer without
            # interpreting or installing them as host grading behavior.
            rules = [response_processing, *(node.find(_Q + "qti-mapping") for node in declarations)]
            source_rules = "\n".join(
                etree.tostring(node, encoding="unicode", with_tail=False)
                for node in rules
                if node is not None
            )
            if len(source_rules.encode("utf-8")) > 100_000:
                raise ValueError("Unsupported scoring rules exceed author-guidance limit")
            explanation += (
                ("\n" if explanation else "")
                + "Source QTI scoring rules (inert XML):\n"
                + source_rules
            )
        if kind == "fill_blank" and fill_spec is None:
            if point_spec is None:
                result["diagnostics"].append(
                    diagnostic(
                        "ANSWERLESS_FILL_REVIEW",
                        "No bounded point specification can be reconstructed without guessing",
                        severity="warning",
                    )
                )
                return result
            fill_spec = {
                **point_spec,
                "blanks": [
                    {**blank, "id": rid}
                    for blank, rid in zip(point_spec["blanks"], response_ids, strict=True)
                ],
            }
        if fill_spec is not None:
            fill_spec = normalize_fill_spec(fill_spec)
        materials = []
        if shared_text:
            materials.append(
                {
                    "id": "material-1",
                    "role": "shared_context",
                    "body": [{"kind": "text", "text": shared_text}],
                }
            )
        for index, instruction in enumerate(instructions, 1):
            materials.append(
                {
                    "id": f"instruction-{index}",
                    "role": "instruction",
                    "body": [{"kind": "text", "text": instruction}],
                }
            )
        image_assets = []
        image_parts = []
        for asset in images:
            image_assets.append(
                {key: asset[key] for key in ("id", "kind", "role", "mimeType", "sha256")}
            )
            image_parts.append({"kind": "image", "assetId": asset["id"]})
        interactions = []
        responses = []
        for index, rid in enumerate(response_ids, 1):
            iid = (
                list(restored["interactions"].values())[index - 1]
                if restored
                else f"interaction-{index}"
            )
            interactions.append(
                {
                    "id": iid,
                    "kind": "choice"
                    if choice is not None
                    else "extended_text"
                    if extended is not None
                    else "text_entry",
                    "cardinality": "multiple" if kind == "multi_choice" else "single",
                    "options": options if index == 1 and choice is not None else [],
                    "responseIds": [rid],
                }
            )
            responses.append(
                {
                    "id": rid,
                    "interactionId": iid,
                    "baseType": "identifier" if choice is not None else "string",
                    "cardinality": "multiple" if kind == "multi_choice" else "single",
                }
            )
        if not trusted_export:
            from deeptutor.services.practice.qti_text import readable_explanation

            explanation = readable_explanation(explanation)
        doc = {
            "schemaVersion": 1,
            "itemId": restored["item"][qti_item_id] if restored else qti_item_id,
            "questionType": kind,
            "language": root.get(_XML + "lang", "und"),
            "subject": subject,
            "body": [{"kind": "text", "text": prompt_text}, *image_parts],
            "materials": materials,
            "assets": image_assets,
            "interactions": interactions,
            "responses": responses,
            "author": {
                "correctAnswer": correct_answer,
                "explanation": explanation,
                "fillSpec": fill_spec,
            },
            "provenance": None,
        }
        doc = normalize_question_document(doc, source_format="content-v1")
        report = preflight(doc, asset_paths={a["id"]: "verified" for a in images})
        report["diagnostics"] = [*result["diagnostics"], *report["diagnostics"]]
        result.update(report)
        result["document"] = doc
        # The template proves a QTI rule shape, not equivalence to an accepted
        # host standard. Imported items have no owner-bound authority snapshot.
        if (kind == "fill_blank" and not finite_program) or (
            response_processing is not None and not finite_program
        ):
            result["scoring"] = "external"
            result["responseScoring"] = {rid: "external" for rid in response_ids}
        result["identifierMap"]["item"][qti_item_id] = doc["itemId"]
        result["identifierMap"]["responses"] = dict(
            zip(xml_response_ids, response_ids, strict=True)
        )
        result["identifierMap"]["interactions"] = {
            node.get("id") or f"interaction-{index}": inter["id"]
            for index, (node, inter) in enumerate(
                zip(xml_interactions, interactions, strict=True), 1
            )
        }
        metadata_conflict = False
        if finite_program and not trusted_export:
            for source in source_guidance:
                try:
                    authored = normalize_fill_spec(source["author"]["fillSpec"])
                    if (
                        not portable(authored)
                        or len(authored["blanks"]) != len(point_spec["blanks"])
                        or any(
                            a["max_score"] != b["max_score"]
                            or a["accepted_answers"] != b["accepted_answers"]
                            for a, b in zip(authored["blanks"], point_spec["blanks"], strict=True)
                        )
                    ):
                        metadata_conflict = True
                except (ValueError, TypeError, KeyError):
                    metadata_conflict = True
        policy_unproven = (
            not trusted_export
            and kind == "fill_blank"
            and (not finite_program or metadata_conflict)
        )
        if finite_program and not trusted_export:
            result["scoring"] = "equivalent"
            result["responseScoring"] = {rid: "equivalent" for rid in response_ids}
        if policy_unproven:
            result["diagnostics"].append(
                diagnostic(
                    "FILL_POLICY_UNPROVEN",
                    "Reference alternatives are preserved; external or application-specific fill policy needs review",
                    severity="warning",
                )
            )
        if unsupported_mapping or unsupported_program or policy_unproven:
            result["bankAdmission"] = "review"
        result["identifierMap"]["options"] = (
            {external: option_ids[external] for external in external_option_ids}
            if choice is not None and kind != "true_false"
            else {o["id"]: o["id"] for o in options}
        )
        return result
    except (ValueError, KeyError, TypeError) as exc:
        result["diagnostics"].append(
            diagnostic("ITEM_MAPPING_BLOCKED", str(exc), location=member_path)
        )
        return result
