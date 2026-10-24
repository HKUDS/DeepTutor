"""QTI 2.1/2.2 item-bank packages over shared bounded archive primitives."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from hashlib import sha256
import posixpath
import re

# ElementTree only constructs/serializes output; input is parsed by SafeET.
import xml.etree.ElementTree as ET  # nosec B405
import zipfile

from defusedxml import ElementTree as SafeET

from deeptutor.services.question_content.qti3.package import (
    MAX_ARCHIVE_BYTES,
    MAX_ITEMS,
    MAX_MEMBERS,
    MAX_XML_BYTES,
    _counts,
    _diag,
    _empty,
    _image_identity,
    _index_archive,
    _Reader,
    _resolve,
    _verify_image,
    _zip_bytes,
)

from .item import parse_item, serialize_item
from .profile import DIALECTS, PACKAGE_NS
from .xml import safe_root, validate_xml

_IMAGE_EXT = {"image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp"}


def _manifest(data: bytes, version: str) -> tuple[list[dict], dict[str, dict]]:
    issues = validate_xml(data, kind="manifest", version=version)
    if issues:
        raise ValueError("QTI 2 root manifest failed offline XSD validation")
    root = SafeET.fromstring(data, forbid_dtd=True, forbid_entities=True, forbid_external=True)
    q = f"{{{PACKAGE_NS}}}"
    if root.tag != q + "manifest":
        raise ValueError("Unexpected content-package namespace")
    metadata = root.find(q + "metadata")
    schema = metadata.find(q + "schema") if metadata is not None else None
    schema_version = metadata.find(q + "schemaversion") if metadata is not None else None
    label = (schema.text or "").strip() if schema is not None else ""
    if not label or schema_version is None or not (schema_version.text or "").strip():
        raise ValueError("QTI 2 item-bank metadata is incomplete")
    stated = re.search(r"(?i)qti[\s-]*v?\s*(2\.[12])\b", label)
    if stated and stated.group(1) != version:
        raise ValueError("QTI metadata version contradicts item resource type")
    resources_node = root.find(q + "resources")
    if resources_node is None:
        raise ValueError("QTI 2 manifest has no resources")
    resources: dict[str, dict] = {}
    items: list[dict] = []
    files_seen: dict[str, str] = {}
    folded: dict[str, str] = {}
    for element in resources_node:
        if element.tag != q + "resource":
            raise ValueError("Unknown QTI 2 manifest resource element")
        rid, kind = element.get("identifier") or "", element.get("type") or ""
        href = element.get("href")
        if not rid or rid in resources or kind not in {DIALECTS[version].item_type, "webcontent"}:
            raise ValueError("Duplicate or unsupported QTI 2 resource identity")
        if len(resources) >= MAX_MEMBERS:
            raise ValueError("QTI 2 manifest has too many resources")
        if "{http://www.w3.org/XML/1998/namespace}base" in element.attrib:
            raise ValueError("Resource xml:base is outside item-bank profile")
        paths: list[str] = []
        dependencies: list[str] = []
        for child in element:
            if child.tag == q + "file":
                if "{http://www.w3.org/XML/1998/namespace}base" in child.attrib:
                    raise ValueError("File xml:base is outside item-bank profile")
                path = _resolve(child.get("href") or "", "imsmanifest.xml")
                if path.casefold() in folded and folded[path.casefold()] != path:
                    raise ValueError("QTI 2 manifest file paths collide by case")
                folded[path.casefold()] = path
                if path in paths or path in files_seen and files_seen[path] != rid:
                    raise ValueError("QTI 2 manifest file ownership is ambiguous")
                files_seen[path] = rid
                paths.append(path)
            elif child.tag == q + "dependency":
                dep = child.get("identifierref") or ""
                if not dep or dep in dependencies:
                    raise ValueError("Invalid QTI 2 resource dependency")
                dependencies.append(dep)
            else:
                raise ValueError("Unsupported QTI 2 resource metadata")
        main = _resolve(href, "imsmanifest.xml") if href is not None else None
        if kind == DIALECTS[version].item_type:
            if main is None or main not in paths:
                raise ValueError("QTI 2 item resource needs its declared XML href")
            items.append({"resourceId": rid, "memberPath": main})
        elif main is not None and main not in paths:
            raise ValueError("QTI 2 media href is not declared")
        if kind == "webcontent" and any(
            not path.lower().endswith((".png", ".jpg", ".jpeg", ".webp")) for path in paths
        ):
            raise ValueError("Unsupported active QTI 2 webcontent resource")
        resources[rid] = {"kind": kind, "files": paths, "dependencies": dependencies}
    if not items or len(items) > MAX_ITEMS:
        raise ValueError("QTI 2 item-bank package has no items or exceeds item limit")
    for rid, resource in resources.items():
        if any(dep not in resources or dep == rid for dep in resource["dependencies"]):
            raise ValueError("QTI 2 dependency identity is missing or self-referential")
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(rid: str, depth: int = 0) -> set[str]:
        if depth > 128:
            raise ValueError("QTI 2 dependency depth exceeds limit")
        if rid in visiting:
            raise ValueError("QTI 2 dependency cycle")
        if rid in visited:
            return set(resources[rid]["closure"])
        visiting.add(rid)
        paths = set(resources[rid]["files"])
        for dep in resources[rid]["dependencies"]:
            paths.update(visit(dep, depth + 1))
        visiting.remove(rid)
        visited.add(rid)
        resources[rid]["closure"] = sorted(paths)
        return paths

    for rid in resources:
        visit(rid)
    return items, resources


def _item_references(data: bytes, version: str) -> list[str]:
    root = safe_root(data, kind="item", version=version)
    body = root.find(f"{{{DIALECTS[version].item_ns}}}itemBody")
    if body is None:
        return []
    refs: list[str] = []

    def visit(element, scorer: bool = False) -> None:
        local = element.tag.rsplit("}", 1)[-1].lower()
        scorer = scorer or (local == "rubricblock" and element.get("view") == "scorer")
        if local in {"img", "object"}:
            value = element.get("src") if local == "img" else element.get("data")
            if value:
                if scorer:
                    raise ValueError("Scorer-only media is outside prompt-image profile")
                refs.append(value)
        for child in element:
            visit(child, scorer)

    visit(body)
    return list(dict.fromkeys(refs))


def _blocked_item(member: str, rid: str, issues: list[dict]) -> dict:
    return {
        "memberPath": member,
        "resourceId": rid,
        "document": None,
        "content": "blocked",
        "scoring": "unavailable",
        "bankAdmission": "blocked",
        "diagnostics": issues,
        "identifierMap": {},
        "assetReferences": [],
        "assetPaths": [],
        "responseScoring": {},
    }


def load_package(data: bytes, *, filename: str, version: str, trusted_export: bool = False) -> dict:
    if version not in DIALECTS:
        return _empty(
            data, [_diag("QTI_VERSION_UNSUPPORTED", "version", "Unsupported QTI 2 version")]
        )
    if type(data) is not bytes or type(filename) is not str:
        return _empty(
            b"", [_diag("PACKAGE_INPUT_INVALID", "input", "Expected file bytes and filename")]
        )
    if filename.lower().endswith(".xml"):
        if len(data) > MAX_XML_BYTES:
            return _empty(data, [_diag("XML_SIZE_LIMIT", filename, "Item XML exceeds byte limit")])
        parsed = parse_item(data, version=version, trusted_export=trusted_export)
        if parsed.get("assetReferences"):
            parsed = {
                **parsed,
                "content": "blocked",
                "bankAdmission": "blocked",
                "diagnostics": [
                    *parsed.get("diagnostics", []),
                    _diag(
                        "STANDALONE_ASSET_REQUIRES_ZIP",
                        "item.xml",
                        "Referenced assets require a package",
                    ),
                ],
            }
        item = {"memberPath": "item.xml", "resourceId": None, "assetPaths": [], **parsed}
        return {
            "packageValidation": "valid",
            "diagnostics": [],
            "items": [item],
            "assets": {},
            "counts": _counts([item]),
            "sourceSha256": sha256(data).hexdigest(),
        }
    if not filename.lower().endswith(".zip"):
        return _empty(
            data, [_diag("PACKAGE_FORMAT_UNSUPPORTED", filename, "Expected QTI XML or ZIP")]
        )
    archive: zipfile.ZipFile | None = None
    try:
        archive, index = _index_archive(data)
        reader = _Reader(archive, index)
        manifest = reader.read("imsmanifest.xml")
        item_refs, resources = _manifest(manifest, version)
        declared = {path for resource in resources.values() for path in resource["files"]}
        if set(index) - {"imsmanifest.xml"} - declared:
            raise ValueError("QTI 2 ZIP has files absent from the manifest")
        item_members = {ref["memberPath"] for ref in item_refs}
        if any(
            not path.lower().endswith((".png", ".jpg", ".jpeg", ".webp"))
            for path in declared - item_members
        ):
            raise ValueError("Unsupported active QTI 2 package resource")
    except (ValueError, KeyError, zipfile.BadZipFile, RuntimeError, ET.ParseError) as exc:
        if archive is not None:
            archive.close()
        return _empty(data, [_diag("PACKAGE_STRUCTURE_INVALID", "imsmanifest.xml", str(exc)[:200])])
    items: list[dict] = []
    assets: dict[str, dict] = {}
    fatal: list[dict] = []
    identifiers: set[str] = set()
    try:
        for ref in item_refs:
            member, rid = ref["memberPath"], ref["resourceId"]
            if member not in index:
                items.append(
                    _blocked_item(
                        member,
                        rid,
                        [
                            _diag(
                                "ITEM_FILE_MISSING",
                                member,
                                "Declared item XML is missing",
                                member=member,
                            )
                        ],
                    )
                )
                continue
            try:
                xml = reader.read(member)
                if any(
                    token in xml.lower()
                    for token in (b"<!doctype", b"<!entity", b"<?xml-stylesheet", b"<xi:include")
                ):
                    fatal.append(
                        _diag(
                            "PACKAGE_XML_UNSAFE",
                            member,
                            "Unsafe item XML in package",
                            member=member,
                        )
                    )
                    break
                identity_root = safe_root(xml, kind="item", version=version)
                item_id = identity_root.get("identifier")
                if item_id and item_id in identifiers:
                    fatal.append(
                        _diag(
                            "DUPLICATE_ITEM_IDENTIFIER",
                            member,
                            "Multiple XML items share an assessment item identifier",
                            member=member,
                        )
                    )
                    break
                if item_id:
                    identifiers.add(item_id)
                refs = _item_references(xml, version)
                closure = set(resources[rid]["closure"])
                asset_map: dict[str, dict] = {}
                asset_paths: list[str] = []
                failures: list[dict] = []
                for href in refs:
                    try:
                        path = _resolve(href, member)
                    except ValueError as exc:
                        failures.append(
                            _diag("ASSET_REFERENCE_UNSAFE", member, str(exc), member=member)
                        )
                        continue
                    asset_paths.append(path)
                    if path not in closure:
                        failures.append(
                            _diag(
                                "ASSET_UNDECLARED",
                                path,
                                "Image is outside item resource closure",
                                member=member,
                            )
                        )
                        continue
                    if path not in index:
                        failures.append(
                            _diag("ASSET_MISSING", path, "Required image is missing", member=member)
                        )
                        continue
                    try:
                        image = reader.read(path)
                        mime = _verify_image(image)
                    except (ValueError, zipfile.BadZipFile, RuntimeError) as exc:
                        failures.append(_diag("ASSET_INVALID", path, str(exc)[:200], member=member))
                        continue
                    digest = sha256(image).hexdigest()
                    asset_id = "asset_" + sha256((path + "\0" + digest).encode()).hexdigest()[:32]
                    descriptor = {
                        "id": asset_id,
                        "kind": "image",
                        "role": "prompt",
                        "mimeType": mime,
                        "sha256": digest,
                    }
                    asset_map[path] = descriptor
                    assets[path] = {"descriptor": descriptor, "bytes": image}
                parsed = parse_item(
                    xml,
                    version=version,
                    member_path=member,
                    asset_map=asset_map,
                    trusted_export=trusted_export,
                )
                item = {
                    "memberPath": member,
                    "resourceId": rid,
                    "assetPaths": asset_paths,
                    **parsed,
                }
                if failures:
                    fatal.extend(
                        issue for issue in failures if issue["code"] == "ASSET_REFERENCE_UNSAFE"
                    )
                    item["content"] = item["bankAdmission"] = "blocked"
                    item["diagnostics"] = [*item.get("diagnostics", []), *failures]
                items.append(item)
            except (ValueError, KeyError, zipfile.BadZipFile, RuntimeError, ET.ParseError) as exc:
                items.append(
                    _blocked_item(
                        member, rid, [_diag("ITEM_INVALID", member, str(exc)[:200], member=member)]
                    )
                )
    finally:
        archive.close()
    if fatal:
        return _empty(data, fatal)
    return {
        "packageValidation": "valid",
        "diagnostics": [],
        "items": items,
        "assets": assets,
        "counts": _counts(items),
        "sourceSha256": sha256(data).hexdigest(),
    }


def build_package(
    items: Sequence[dict],
    *,
    asset_bytes: Mapping[object, bytes],
    version: str,
    origin_labels: Mapping[str, str] | None = None,
) -> dict:
    if version not in DIALECTS or not 1 <= len(items) <= MAX_ITEMS:
        return {
            "packageValidation": "invalid",
            "diagnostics": [
                _diag("EXPORT_INPUT_INVALID", "items", "Invalid QTI 2 dialect or item count")
            ],
            "items": [],
            "zip": None,
            "sourceSha256": None,
        }
    origin_labels = origin_labels or {}
    reports: list[dict] = []
    diagnostics: list[dict] = []
    files: dict[str, bytes] = {}
    resources: list[tuple[str, str, str, list[str], list[str]]] = []
    media: dict[str, str] = {}
    seen_ids: set[str] = set()
    for row in items:
        doc = row.get("document") if isinstance(row, dict) else None
        item_id = doc.get("itemId") if isinstance(doc, dict) else None
        if not isinstance(item_id, str) or not item_id or item_id in seen_ids:
            diagnostics.append(
                _diag(
                    "EXPORT_ITEM_ID_INVALID",
                    "items",
                    "Missing or duplicate canonical item identity",
                )
            )
            continue
        seen_ids.add(item_id)
        member = "items/" + sha256(item_id.encode()).hexdigest()[:32] + ".xml"
        paths: dict[str, str] = {}
        dependencies: list[str] = []
        primary_image_ids: dict[str, str] = {}
        for asset in doc.get("assets", []):
            if asset.get("role") != "prompt":
                continue
            asset_id = asset.get("id")
            raw = asset_bytes.get((item_id, asset_id), asset_bytes.get(asset_id))
            try:
                if not isinstance(raw, bytes) or len(raw) > 50 * 1024 * 1024:
                    raise ValueError("Authorized image bytes are unavailable")
                mime = _verify_image(raw, asset.get("mimeType"))
                digest = sha256(raw).hexdigest()
                if digest != asset.get("sha256"):
                    raise ValueError("Authorized image digest differs from canonical descriptor")
                image_identity = _image_identity(digest, asset_id, primary_image_ids)
                path = "assets/" + image_identity + _IMAGE_EXT[mime]
                if path in files and files[path] != raw:
                    raise ValueError("Content-addressed image collision")
                files[path] = raw
                paths[asset_id] = posixpath.relpath(path, posixpath.dirname(member))
                media_id = "media_" + image_identity
                media[path] = media_id
                if media_id not in dependencies:
                    dependencies.append(media_id)
            except ValueError as exc:
                diagnostics.append(_diag("EXPORT_ASSET_INVALID", str(asset_id), str(exc)))
        serialized = serialize_item(
            doc,
            version=version,
            asset_paths=paths,
            score_snapshot=row.get("score_snapshot"),
            origin_label=origin_labels.get(item_id),
        )
        report = {
            "memberPath": member,
            "resourceId": "item_" + sha256(item_id.encode()).hexdigest(),
            **{key: value for key, value in serialized.items() if key != "xml"},
        }
        reports.append(report)
        if serialized.get("xml") is None:
            diagnostics.extend(
                report.get("diagnostics")
                or [_diag("EXPORT_ITEM_BLOCKED", member, "Selected item could not be serialized")]
            )
            continue
        files[member] = serialized["xml"]
        resources.append(
            (report["resourceId"], DIALECTS[version].item_type, member, [member], dependencies)
        )
    if diagnostics or len(reports) != len(items):
        return {
            "packageValidation": "invalid",
            "diagnostics": diagnostics,
            "items": reports,
            "zip": None,
            "sourceSha256": None,
        }
    for path, rid in sorted(media.items()):
        resources.append((rid, "webcontent", path, [path], []))
    identity = sha256()
    for path in sorted(files):
        identity.update(path.encode("utf-8") + b"\0" + sha256(files[path]).digest())
    q = f"{{{PACKAGE_NS}}}"
    ET.register_namespace("", PACKAGE_NS)
    root = ET.Element(q + "manifest", {"identifier": "qti-bank-" + identity.hexdigest()[:32]})
    metadata = ET.SubElement(root, q + "metadata")
    ET.SubElement(metadata, q + "schema").text = DIALECTS[version].metadata_schema
    ET.SubElement(metadata, q + "schemaversion").text = "1.0.0"
    ET.SubElement(root, q + "organizations")
    parent = ET.SubElement(root, q + "resources")
    for rid, kind, href, resource_paths, dependencies in resources:
        resource = ET.SubElement(
            parent, q + "resource", {"identifier": rid, "type": kind, "href": href}
        )
        for path in resource_paths:
            ET.SubElement(resource, q + "file", {"href": path})
        for dep in sorted(dependencies):
            ET.SubElement(resource, q + "dependency", {"identifierref": dep})
    files["imsmanifest.xml"] = ET.tostring(root, encoding="utf-8", xml_declaration=True)
    archive = _zip_bytes(files)
    if len(archive) > MAX_ARCHIVE_BYTES:
        return {
            "packageValidation": "invalid",
            "diagnostics": [
                _diag("EXPORT_ARCHIVE_TOO_LARGE", "archive", "QTI 2 output exceeds byte limit")
            ],
            "items": reports,
            "zip": None,
            "sourceSha256": None,
        }
    checked = load_package(archive, filename="questions.zip", version=version, trusted_export=True)
    if checked["packageValidation"] != "valid" or any(
        item["content"] == "blocked" for item in checked["items"]
    ):
        return {
            "packageValidation": "invalid",
            "diagnostics": [
                *checked["diagnostics"],
                *[issue for item in checked["items"] for issue in item.get("diagnostics", [])],
            ],
            "items": reports,
            "zip": None,
            "sourceSha256": None,
        }
    return {
        "packageValidation": "valid",
        "diagnostics": [],
        "items": reports,
        "zip": archive,
        "sourceSha256": sha256(archive).hexdigest(),
    }


__all__ = ["load_package", "build_package"]
