"""Bounded QTI 3 item-bank content packages.

This module handles bytes and package-relative identities only. Authentication,
staging, and bank admission remain application-service responsibilities.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from hashlib import sha256
from io import BytesIO
import posixpath
import re
import stat
import unicodedata
from urllib.parse import urlsplit

# ElementTree only constructs/serializes output; input is parsed by SafeET.
import xml.etree.ElementTree as ET  # nosec B405
import zipfile

from defusedxml import ElementTree as SafeET

from .profile import PACKAGE_NS, QTI_NS

MAX_ARCHIVE_BYTES = 100 * 1024 * 1024
MAX_TOTAL_BYTES = 512 * 1024 * 1024
MAX_MEMBER_BYTES = 50 * 1024 * 1024
MAX_XML_BYTES = 10 * 1024 * 1024
MAX_MEMBERS = 2_000
MAX_ITEMS = 2_000
MAX_RATIO = 200
_IMAGE_MIME = {"image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp"}
_ITEM_TYPE = "imsqti_item_xmlv3p0"
_MEDIA_TYPE = "webcontent"


def _diag(code: str, location: str, message: str, *, member: str | None = None) -> dict:
    result = {"code": code, "severity": "error", "message": message, "location": location}
    if member is not None:
        result["memberPath"] = member
    return result


def _empty(data: bytes, diagnostics: list[dict]) -> dict:
    return {
        "packageValidation": "invalid",
        "diagnostics": diagnostics,
        "items": [],
        "assets": {},
        "counts": {
            key: None
            for key in (
                "discovered",
                "ready",
                "review",
                "blocked",
                "scoringEquivalent",
                "scoringExternal",
                "scoringUnavailable",
            )
        },
        "sourceSha256": sha256(data).hexdigest(),
    }


def _safe_member(name: str) -> str:
    if not isinstance(name, str) or not name or "\x00" in name or "\\" in name:
        raise ValueError("invalid member name")
    if name.startswith(("/", "//")) or re.match(r"^[A-Za-z]:", name):
        raise ValueError("absolute member name")
    if any(part in ("", ".", "..") for part in name.rstrip("/").split("/")):
        raise ValueError("noncanonical member path")
    if unicodedata.normalize("NFC", name) != name:
        raise ValueError("noncanonical Unicode member path")
    if len(name.encode("utf-8")) > 1024:
        raise ValueError("member path too long")
    return name.rstrip("/")


def _resolve(href: str, owner: str) -> str:
    if not isinstance(href, str) or not href or "\x00" in href or "\\" in href or "%" in href:
        raise ValueError("unsafe resource reference")
    parsed = urlsplit(href)
    if parsed.scheme or parsed.netloc or parsed.query or parsed.fragment or href.startswith("/"):
        raise ValueError("external or ambiguous resource reference")
    if any(part in ("", ".") for part in href.split("/")):
        raise ValueError("noncanonical resource reference")
    if unicodedata.normalize("NFC", href) != href:
        raise ValueError("noncanonical Unicode reference")
    parts = owner.split("/")[:-1]
    for part in href.split("/"):
        if part == "..":
            if not parts:
                raise ValueError("resource reference escapes package")
            parts.pop()
        else:
            parts.append(part)
    return _safe_member("/".join(parts))


def _index_archive(data: bytes) -> tuple[zipfile.ZipFile, dict[str, zipfile.ZipInfo]]:
    if len(data) > MAX_ARCHIVE_BYTES:
        raise ValueError("QTI archive exceeds compressed byte limit")
    archive = zipfile.ZipFile(BytesIO(data))
    infos = archive.infolist()
    if len(infos) > MAX_MEMBERS:
        raise ValueError("QTI archive has too many members")
    index: dict[str, zipfile.ZipInfo] = {}
    folded: set[str] = set()
    declared_total = 0
    for info in infos:
        name = _safe_member(info.filename)
        mode = (info.external_attr >> 16) & 0xFFFF
        file_type = stat.S_IFMT(mode)
        if info.flag_bits & 1 or info.compress_type not in (
            zipfile.ZIP_STORED,
            zipfile.ZIP_DEFLATED,
        ):
            raise ValueError("encrypted or unsupported ZIP member")
        if file_type not in (0, stat.S_IFREG, stat.S_IFDIR):
            raise ValueError("ZIP member is a link or special file")
        if info.is_dir():
            if file_type not in (0, stat.S_IFDIR):
                raise ValueError("ZIP directory has conflicting file mode")
            continue
        if file_type == stat.S_IFDIR:
            raise ValueError("ZIP file has directory mode")
        folded_name = name.casefold()
        if name in index or folded_name in folded:
            raise ValueError("duplicate or case-colliding ZIP member")
        if info.file_size > MAX_MEMBER_BYTES or (
            name.lower().endswith((".xml", ".xsd")) and info.file_size > MAX_XML_BYTES
        ):
            raise ValueError("ZIP member exceeds byte limit")
        if info.file_size and (
            not info.compress_size or info.file_size > MAX_RATIO * info.compress_size
        ):
            raise ValueError("ZIP member exceeds compression ratio limit")
        declared_total += info.file_size
        if declared_total > MAX_TOTAL_BYTES:
            raise ValueError("ZIP expanded bytes exceed limit")
        index[name] = info
        folded.add(folded_name)
    # Even without extraction, a file that shadows a directory creates
    # ambiguous package identities for manifest and href resolution.
    for name in index:
        prefix = name
        while "/" in prefix:
            prefix = prefix.rsplit("/", 1)[0]
            if prefix in index:
                raise ValueError("ZIP file shadows a directory")
    if "imsmanifest.xml" not in index:
        raise ValueError("root imsmanifest.xml is missing")
    return archive, index


class _Reader:
    def __init__(self, archive: zipfile.ZipFile, index: Mapping[str, zipfile.ZipInfo]):
        self.archive = archive
        self.index = index
        self.cache: dict[str, bytes] = {}
        self.total = 0

    def read(self, path: str) -> bytes:
        if path in self.cache:
            return self.cache[path]
        info = self.index[path]
        chunks = []
        size = 0
        with self.archive.open(info) as source:
            while chunk := source.read(64 * 1024):
                size += len(chunk)
                self.total += len(chunk)
                if size > info.file_size or size > MAX_MEMBER_BYTES or self.total > MAX_TOTAL_BYTES:
                    raise ValueError("ZIP actual expanded bytes exceed limit")
                chunks.append(chunk)
        if size != info.file_size:
            raise ValueError("ZIP member byte count differs from directory")
        result = b"".join(chunks)
        self.cache[path] = result
        return result


def _manifest(data: bytes) -> tuple[list[dict], dict[str, dict]]:
    from . import validate_xml

    issues = validate_xml(data, kind="manifest")
    if issues:
        raise ValueError("root manifest failed offline XML/XSD validation")
    root = SafeET.fromstring(data)
    if root.tag != f"{{{PACKAGE_NS}}}manifest":
        raise ValueError("root manifest namespace is not QTI 3")
    metadata = root.find(f"{{{PACKAGE_NS}}}metadata")
    schema = metadata.find(f"{{{PACKAGE_NS}}}schema") if metadata is not None else None
    version = metadata.find(f"{{{PACKAGE_NS}}}schemaversion") if metadata is not None else None
    if (
        schema is None
        or (schema.text or "").strip() != "QTI Package"
        or version is None
        or (version.text or "").strip() != "3.0.0"
    ):
        raise ValueError("manifest QTI package metadata is unsupported")
    resources_node = root.find(f"{{{PACKAGE_NS}}}resources")
    if resources_node is None:
        raise ValueError("root manifest has no resources")
    resources: dict[str, dict] = {}
    ordered_items: list[dict] = []
    files_seen: dict[str, str] = {}
    folded_files: dict[str, str] = {}
    for element in resources_node:
        if element.tag != f"{{{PACKAGE_NS}}}resource":
            raise ValueError("unknown manifest resource element")
        rid = element.get("identifier") or ""
        kind = element.get("type") or ""
        href = element.get("href")
        if not rid or rid in resources or kind not in (_ITEM_TYPE, _MEDIA_TYPE):
            raise ValueError("duplicate or unsupported manifest resource identity")
        if len(resources) >= MAX_MEMBERS:
            raise ValueError("manifest has too many resources")
        paths = []
        dependencies = []
        for child in element:
            if child.tag == f"{{{PACKAGE_NS}}}file":
                path = _resolve(child.get("href") or "", "imsmanifest.xml")
                if path.casefold() in folded_files and folded_files[path.casefold()] != path:
                    raise ValueError("manifest file paths collide by case")
                folded_files[path.casefold()] = path
                if path in files_seen and files_seen[path] != rid:
                    raise ValueError("manifest file has ambiguous resource ownership")
                files_seen[path] = rid
                if path in paths:
                    raise ValueError("duplicate manifest file declaration")
                paths.append(path)
            elif child.tag == f"{{{PACKAGE_NS}}}dependency":
                dep = child.get("identifierref") or ""
                if not dep or dep in dependencies:
                    raise ValueError("invalid manifest dependency")
                dependencies.append(dep)
            else:
                raise ValueError("unknown manifest resource child")
        main = _resolve(href, "imsmanifest.xml") if href is not None else None
        if kind == _ITEM_TYPE:
            if main is None or main not in paths:
                raise ValueError("item resource needs its declared XML href")
            ordered_items.append({"resourceId": rid, "memberPath": main})
        elif main is not None and main not in paths:
            raise ValueError("resource href is not declared as file")
        if kind == _MEDIA_TYPE and any(
            not path.lower().endswith((".png", ".jpg", ".jpeg", ".webp")) for path in paths
        ):
            raise ValueError("unsupported active or non-image webcontent resource")
        resources[rid] = {"kind": kind, "files": paths, "dependencies": dependencies}
    if len(ordered_items) > MAX_ITEMS:
        raise ValueError("QTI package has too many items")
    if not ordered_items:
        raise ValueError("QTI item-bank package has no items")
    for rid, resource in resources.items():
        if any(dep not in resources or dep == rid for dep in resource["dependencies"]):
            raise ValueError("manifest dependency is missing or self-referential")
    visiting: set[str] = set()
    visited: set[str] = set()

    def visit(rid: str, depth: int = 0) -> set[str]:
        if depth > 128:
            raise ValueError("manifest dependency depth exceeds limit")
        if rid in visiting:
            raise ValueError("manifest dependency cycle")
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
    return ordered_items, resources


def _sniff_image(data: bytes) -> str | None:
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        return "image/webp"
    return None


def _verify_image(data: bytes, expected: str | None = None) -> str:
    mime = _sniff_image(data)
    if mime is None or (expected is not None and mime != expected):
        raise ValueError("unsupported image MIME or magic")
    try:
        from PIL import Image

        with Image.open(BytesIO(data)) as image:
            width, height = image.size
            if width < 1 or height < 1 or width * height > 40_000_000:
                raise ValueError("image dimensions exceed limit")
            image.verify()
    except (ImportError, OSError) as exc:
        raise ValueError("image failed decode verification") from exc
    return mime


def _image_identity(digest: str, asset_id: str, primary_ids: dict[str, str]) -> str:
    """Keep distinct same-item figures addressable when their bytes are equal.

    Import resolves an asset identity from its package path and digest. Reusing
    one path twice inside an item would therefore collapse two canonical assets.
    The primary digest path still deduplicates ordinary sharing across items.
    """
    if not isinstance(asset_id, str) or not asset_id:
        raise ValueError("Missing canonical prompt image identity")
    primary_id = primary_ids.setdefault(digest, asset_id)
    if primary_id == asset_id:
        return digest
    return digest + "-" + sha256(asset_id.encode("utf-8")).hexdigest()


def _item_references(data: bytes) -> list[str]:
    from .xml import safe_root

    root = safe_root(data, kind="item")
    refs: list[str] = []
    body = root.find(f"{{{QTI_NS}}}qti-item-body")
    if body is None:
        return refs

    def visit(element, *, scorer: bool = False) -> None:
        local = element.tag.rsplit("}", 1)[-1].lower()
        scorer = scorer or (local == "qti-rubric-block" and element.get("view") == "scorer")
        if local in ("qti-img", "img"):
            source = element.get("src")
            if source:
                if scorer:
                    raise ValueError("scorer-only media is outside prompt-image profile")
                refs.append(source)
        elif local in ("qti-object", "object"):
            source = element.get("data")
            if source:
                if scorer:
                    raise ValueError("scorer-only media is outside prompt-image profile")
                refs.append(source)
        for child in element:
            visit(child, scorer=scorer)

    visit(body)
    return list(dict.fromkeys(refs))


def _counts(items: Sequence[dict]) -> dict:
    return {
        "discovered": len(items),
        "ready": sum(item["bankAdmission"] == "ready" for item in items),
        "review": sum(item["bankAdmission"] == "review" for item in items),
        "blocked": sum(item["bankAdmission"] == "blocked" for item in items),
        "scoringEquivalent": sum(item["scoring"] == "equivalent" for item in items),
        "scoringExternal": sum(item["scoring"] == "external" for item in items),
        "scoringUnavailable": sum(item["scoring"] == "unavailable" for item in items),
    }


def _blocked_item(member: str, rid: str, diagnostics: list[dict]) -> dict:
    return {
        "memberPath": member,
        "resourceId": rid,
        "document": None,
        "content": "blocked",
        "scoring": "unavailable",
        "bankAdmission": "blocked",
        "diagnostics": diagnostics,
        "identifierMap": {},
        "assetReferences": [],
        "assetPaths": [],
    }


def load_package(data: bytes, *, filename: str, trusted_export: bool = False) -> dict:
    """Read standalone item XML or a bounded QTI 3 item-bank ZIP in memory."""
    from . import parse_item

    if type(data) is not bytes or type(filename) is not str:
        return _empty(
            b"", [_diag("PACKAGE_INPUT_INVALID", "input", "Expected file bytes and filename")]
        )
    digest = sha256(data).hexdigest()
    if filename.lower().endswith(".xml"):
        if len(data) > MAX_XML_BYTES:
            return _empty(data, [_diag("XML_SIZE_LIMIT", filename, "Item XML exceeds byte limit")])
        result = parse_item(data, member_path="item.xml", trusted_export=trusted_export)
        refs = result.get("assetReferences") or []
        if refs:
            result = dict(result)
            result["content"] = "blocked"
            result["bankAdmission"] = "blocked"
            result["diagnostics"] = list(result.get("diagnostics") or []) + [
                _diag(
                    "STANDALONE_ASSET_REQUIRES_ZIP",
                    "item.xml",
                    "Referenced assets require a package",
                )
            ]
        item = {"memberPath": "item.xml", "resourceId": None, "assetPaths": [], **result}
        return {
            "packageValidation": "valid",
            "diagnostics": [],
            "items": [item],
            "assets": {},
            "counts": _counts([item]),
            "sourceSha256": digest,
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
        if len(manifest) > MAX_XML_BYTES:
            raise ValueError("root manifest exceeds XML byte limit")
        item_refs, resources = _manifest(manifest)
        declared = {path for resource in resources.values() for path in resource["files"]}
        if set(index) - {"imsmanifest.xml"} - declared:
            raise ValueError("ZIP contains files absent from the manifest")
        item_members = {ref["memberPath"] for ref in item_refs}
        if any(
            not path.lower().endswith((".png", ".jpg", ".jpeg", ".webp"))
            for path in declared - item_members
        ):
            raise ValueError("unsupported active or non-image package resource")
    except (ValueError, KeyError, zipfile.BadZipFile, RuntimeError, ET.ParseError) as exc:
        if archive is not None:
            archive.close()
        return _empty(data, [_diag("PACKAGE_STRUCTURE_INVALID", "imsmanifest.xml", str(exc))])
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
                            "Unsafe XML construct in package",
                            member=member,
                        )
                    )
                    break
                identity_root = SafeET.fromstring(xml)
                if identity_root.tag == f"{{{QTI_NS}}}qti-assessment-item":
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
                refs = _item_references(xml)
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
                        failures.append(_diag("ASSET_INVALID", path, str(exc), member=member))
                        continue
                    asset_id = (
                        "asset_"
                        + sha256((path + "\0" + sha256(image).hexdigest()).encode()).hexdigest()[
                            :32
                        ]
                    )
                    descriptor = {
                        "id": asset_id,
                        "kind": "image",
                        "role": "prompt",
                        "mimeType": mime,
                        "sha256": sha256(image).hexdigest(),
                    }
                    asset_map[path] = descriptor
                    assets[path] = {"descriptor": descriptor, "bytes": image}
                parsed = parse_item(
                    xml, member_path=member, asset_map=asset_map, trusted_export=trusted_export
                )
                item = {
                    "memberPath": member,
                    "resourceId": rid,
                    "assetPaths": asset_paths,
                    **parsed,
                }
                if failures:
                    fatal.extend(
                        problem
                        for problem in failures
                        if problem["code"] == "ASSET_REFERENCE_UNSAFE"
                    )
                    item["content"] = "blocked"
                    item["bankAdmission"] = "blocked"
                    item["diagnostics"] = list(item.get("diagnostics") or []) + failures
                items.append(item)
            except (ValueError, zipfile.BadZipFile, RuntimeError, ET.ParseError) as exc:
                items.append(
                    _blocked_item(
                        member, rid, [_diag("ITEM_INVALID", member, str(exc), member=member)]
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
        "sourceSha256": digest,
    }


def _xml_bytes(element: ET.Element) -> bytes:
    return ET.tostring(element, encoding="utf-8", xml_declaration=True)


def _zip_bytes(files: Mapping[str, bytes]) -> bytes:
    output = BytesIO()
    with zipfile.ZipFile(output, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as archive:
        for path in sorted(files):
            info = zipfile.ZipInfo(path, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = (stat.S_IFREG | 0o644) << 16
            archive.writestr(info, files[path], compress_type=zipfile.ZIP_DEFLATED, compresslevel=6)
    return output.getvalue()


def build_package(
    items: Sequence[dict],
    *,
    asset_bytes: Mapping[object, bytes],
    origin_labels: Mapping[str, str] | None = None,
) -> dict:
    """Write a deterministic all-or-nothing QTI 3 item-bank ZIP."""
    from . import serialize_item

    if len(items) > MAX_ITEMS:
        return {
            "packageValidation": "invalid",
            "diagnostics": [
                _diag("EXPORT_ITEM_LIMIT", "items", "Too many items for one QTI package")
            ],
            "items": [],
            "zip": None,
            "sourceSha256": None,
        }
    origin_labels = origin_labels or {}
    results: list[dict] = []
    diagnostics: list[dict] = []
    files: dict[str, bytes] = {}
    manifest_resources: list[tuple[str, str, str | None, list[str], list[str]]] = []
    media_by_path: dict[str, str] = {}
    seen_item_paths: set[str] = set()
    for row in items:
        document = row.get("document") if isinstance(row, dict) else None
        if not isinstance(document, dict):
            diagnostics.append(
                _diag("EXPORT_DOCUMENT_INVALID", "items", "Expected canonical item document")
            )
            continue
        item_id = document.get("itemId")
        if not isinstance(item_id, str) or not item_id:
            diagnostics.append(_diag("EXPORT_ITEM_ID_INVALID", "items", "Item identity is missing"))
            continue
        path = "items/" + sha256(item_id.encode("utf-8")).hexdigest()[:32] + ".xml"
        if path in seen_item_paths:
            diagnostics.append(
                _diag("EXPORT_ITEM_ID_DUPLICATE", item_id, "Duplicate item identity")
            )
            continue
        seen_item_paths.add(path)
        paths: dict[str, str] = {}
        dependencies: list[str] = []
        primary_image_ids: dict[str, str] = {}
        for asset in document.get("assets", []):
            if asset.get("role") != "prompt":
                continue
            asset_id = asset.get("id")
            image = asset_bytes.get((item_id, asset_id), asset_bytes.get(asset_id))
            try:
                if not isinstance(image, bytes) or len(image) > MAX_MEMBER_BYTES:
                    raise ValueError("authorized image bytes are unavailable")
                mime = _verify_image(image, asset.get("mimeType"))
                digest = sha256(image).hexdigest()
                if digest != asset.get("sha256"):
                    raise ValueError("authorized image digest differs from canonical descriptor")
                image_identity = _image_identity(digest, asset_id, primary_image_ids)
                image_path = "assets/" + image_identity + _IMAGE_MIME[mime]
                if image_path in files and files[image_path] != image:
                    raise ValueError("content-addressed image collision")
                files[image_path] = image
                paths[asset_id] = posixpath.relpath(image_path, posixpath.dirname(path))
                media_id = "media_" + image_identity
                media_by_path[image_path] = media_id
                if media_id not in dependencies:
                    dependencies.append(media_id)
            except ValueError as exc:
                diagnostics.append(_diag("EXPORT_ASSET_INVALID", str(asset_id), str(exc)))
        serialized = serialize_item(
            document,
            asset_paths=paths,
            score_snapshot=row.get("score_snapshot"),
            origin_label=origin_labels.get(item_id),
        )
        result = {
            "memberPath": path,
            "resourceId": "item_" + sha256(item_id.encode()).hexdigest(),
            **{key: value for key, value in serialized.items() if key != "xml"},
        }
        results.append(result)
        if serialized.get("xml") is None:
            diagnostics.extend(result.get("diagnostics") or [])
            if not result.get("diagnostics"):
                diagnostics.append(
                    _diag(
                        "EXPORT_ITEM_BLOCKED",
                        path,
                        "Selected item could not be serialized",
                        member=path,
                    )
                )
            continue
        files[path] = serialized["xml"]
        manifest_resources.append((result["resourceId"], _ITEM_TYPE, path, [path], dependencies))
    if diagnostics or len(results) != len(items) or not results:
        return {
            "packageValidation": "invalid",
            "diagnostics": diagnostics or [_diag("EXPORT_EMPTY", "items", "No exportable items")],
            "items": results,
            "zip": None,
            "sourceSha256": None,
        }
    for path, rid in sorted(media_by_path.items()):
        manifest_resources.append((rid, _MEDIA_TYPE, path, [path], []))
    ET.register_namespace("", PACKAGE_NS)
    identity = sha256()
    for path in sorted(files):
        identity.update(path.encode("utf-8"))
        identity.update(b"\0")
        identity.update(sha256(files[path]).digest())
    root = ET.Element(
        f"{{{PACKAGE_NS}}}manifest", {"identifier": "qti-bank-" + identity.hexdigest()[:32]}
    )
    metadata = ET.SubElement(root, f"{{{PACKAGE_NS}}}metadata")
    # QTI 3.0.1 is the ASI maintenance XSD baseline. Official QTI 3 content
    # packages identify their package metadata separately as QTI Package 3.0.0.
    ET.SubElement(metadata, f"{{{PACKAGE_NS}}}schema").text = "QTI Package"
    ET.SubElement(metadata, f"{{{PACKAGE_NS}}}schemaversion").text = "3.0.0"
    ET.SubElement(root, f"{{{PACKAGE_NS}}}organizations")
    resources = ET.SubElement(root, f"{{{PACKAGE_NS}}}resources")
    for rid, kind, href, resource_paths, dependencies in manifest_resources:
        resource = ET.SubElement(
            resources,
            f"{{{PACKAGE_NS}}}resource",
            {"identifier": rid, "type": kind, "href": href or ""},
        )
        for child_path in resource_paths:
            ET.SubElement(resource, f"{{{PACKAGE_NS}}}file", {"href": child_path})
        for dependency in sorted(dependencies):
            ET.SubElement(resource, f"{{{PACKAGE_NS}}}dependency", {"identifierref": dependency})
    files["imsmanifest.xml"] = _xml_bytes(root)
    archive_bytes = _zip_bytes(files)
    if len(archive_bytes) > MAX_ARCHIVE_BYTES:
        return {
            "packageValidation": "invalid",
            "diagnostics": [
                _diag(
                    "EXPORT_ARCHIVE_TOO_LARGE", "archive", "Output exceeds QTI archive byte limit"
                )
            ],
            "items": results,
            "zip": None,
            "sourceSha256": None,
        }
    checked = load_package(archive_bytes, filename="questions.zip", trusted_export=True)
    if checked["packageValidation"] != "valid" or any(
        item["content"] == "blocked" for item in checked["items"]
    ):
        return {
            "packageValidation": "invalid",
            "diagnostics": checked["diagnostics"]
            + [problem for item in checked["items"] for problem in item["diagnostics"]],
            "items": results,
            "zip": None,
            "sourceSha256": None,
        }
    return {
        "packageValidation": "valid",
        "diagnostics": [],
        "items": results,
        "zip": archive_bytes,
        "sourceSha256": sha256(archive_bytes).hexdigest(),
    }


__all__ = ["load_package", "build_package"]
