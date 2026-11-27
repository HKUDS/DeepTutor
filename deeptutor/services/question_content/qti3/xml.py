"""Hostile-input screening and offline QTI schema validation."""

from __future__ import annotations

from collections.abc import Mapping
from functools import lru_cache
from hashlib import sha256
import json
from pathlib import Path
import re

from defusedxml.common import DTDForbidden, EntitiesForbidden, ExternalReferenceForbidden
from defusedxml.lxml import fromstring as defused_fromstring

# Tree construction/types and XSD validation only; parsing uses defusedxml.
from lxml import etree  # nosec B410

from .profile import (
    ITEM_SCHEMA_NAME,
    MAX_XML_BYTES,
    MAX_XML_DEPTH,
    MAX_XML_ELEMENTS,
    PACKAGE_NS,
    PACKAGE_SCHEMA_NAME,
    QTI_NS,
    diagnostic,
)

_SCHEMA_DIR = Path(__file__).with_name("schemas")


class _DenyResolver(etree.Resolver):
    def __init__(self, verified: Mapping[str, bytes] | None = None):
        super().__init__()
        self.verified = verified or {}

    def resolve(self, url: str, pubid: str | None, context: object) -> object:
        path = Path(url)
        if (
            not path.is_absolute()
            or path.parent != _SCHEMA_DIR.resolve()
            or path.name not in self.verified
        ):
            raise ValueError(f"External XML resource is forbidden: {url}")
        return self.resolve_string(self.verified[path.name], context, base_url=str(path))


def _verified_bundle() -> dict[str, bytes]:
    inventory_path = _SCHEMA_DIR / "SOURCE.json"
    if not inventory_path.is_file() or inventory_path.is_symlink():
        raise FileNotFoundError("Offline QTI 3 schema inventory is unavailable")
    if inventory_path.stat().st_size > 100_000:
        raise ValueError("Offline QTI 3 schema inventory exceeds limit")
    inventory = json.loads(inventory_path.read_text("utf-8"))
    rows = inventory.get("files") if isinstance(inventory, dict) else None
    if not isinstance(rows, list) or not 1 <= len(rows) <= 100:
        raise ValueError("Offline QTI 3 schema inventory is invalid")
    verified: dict[str, bytes] = {}
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("Offline QTI 3 schema inventory entry is invalid")
        name, digest = row.get("file"), row.get("sha256")
        if (
            not isinstance(name, str)
            or not name.endswith(".xsd")
            or Path(name).name != name
            or "\\" in name
            or not isinstance(digest, str)
            or not re.fullmatch(r"[0-9a-f]{64}", digest)
            or name in verified
        ):
            raise ValueError("Offline QTI 3 schema inventory entry is invalid")
        path = _SCHEMA_DIR / name
        if not path.is_file() or path.is_symlink():
            raise FileNotFoundError(f"Offline schema {name} is unavailable")
        data = path.read_bytes()
        if sha256(data).hexdigest() != digest:
            raise ValueError(f"Offline schema {name} digest mismatch")
        verified[name] = data
    if ITEM_SCHEMA_NAME not in verified or PACKAGE_SCHEMA_NAME not in verified:
        raise ValueError("Offline QTI 3 root schemas are not inventoried")
    return verified


def safe_root(data: bytes, *, kind: str) -> etree._Element:
    if not isinstance(data, bytes) or len(data) > MAX_XML_BYTES:
        raise ValueError("XML byte limit exceeded")
    # A lexical gate avoids parser-version-dependent treatment of DTD, entities,
    # and processing instructions before the defused parse.
    lower = data.lower()
    if any(
        token in lower for token in (b"<!doctype", b"<!entity", b"<?xml-stylesheet", b"<xi:include")
    ):
        raise ValueError("DTD, entities, stylesheet and XInclude are forbidden")
    if re.search(rb"<\?(?!xml(?:\s|\?>))", lower):
        raise ValueError("Processing instructions are forbidden")
    parser = etree.XMLParser(
        resolve_entities=False,
        load_dtd=False,
        no_network=True,
        huge_tree=False,
        remove_comments=False,
    )
    parser.resolvers.add(_DenyResolver())
    try:
        # Reject declarations while retaining bounded parsing and the deny resolver.
        root = defused_fromstring(data, parser=parser, forbid_dtd=True, forbid_entities=True)
    except (
        etree.XMLSyntaxError,
        DTDForbidden,
        EntitiesForbidden,
        ExternalReferenceForbidden,
    ) as exc:
        raise ValueError(f"Unsafe or malformed XML: {exc}") from exc
    expected = (
        f"{{{QTI_NS}}}qti-assessment-item"
        if kind == "item"
        else f"{{{PACKAGE_NS}}}manifest"
        if kind == "manifest"
        else None
    )
    if expected is None or root.tag != expected:
        raise ValueError("Unexpected XML namespace or root")
    count = 0
    stack = [(root, 1)]
    while stack:
        node, depth = stack.pop()
        count += 1
        if count > MAX_XML_ELEMENTS or depth > MAX_XML_DEPTH:
            raise ValueError("XML structural limit exceeded")
        if isinstance(node, etree._ProcessingInstruction):
            raise ValueError("Processing instructions are forbidden")
        if isinstance(node.tag, str) and node.tag.startswith("{http://www.w3.org/2001/XInclude}"):
            raise ValueError("XInclude is forbidden")
        for key in node.attrib:
            if key.lower().startswith("on"):
                raise ValueError("Event-handler attributes are forbidden")
        stack.extend((child, depth + 1) for child in node)
    return root


@lru_cache(maxsize=2)
def _schema_for_kind(kind: str) -> etree.XMLSchema:
    schema_name = ITEM_SCHEMA_NAME if kind == "item" else PACKAGE_SCHEMA_NAME
    path = _SCHEMA_DIR / schema_name
    verified = _verified_bundle()
    parser = etree.XMLParser(resolve_entities=False, load_dtd=False, no_network=True)
    parser.resolvers.add(_DenyResolver(verified))
    root = defused_fromstring(
        verified[schema_name],
        parser=parser,
        base_url=str(path.resolve()),
        forbid_dtd=True,
        forbid_entities=True,
    )
    return etree.XMLSchema(root)


def validate_xml(data: bytes, kind: str) -> list[dict]:
    try:
        root = safe_root(data, kind=kind)
    except (ValueError, TypeError) as exc:
        return [diagnostic("XML_UNSAFE_OR_INVALID", str(exc))]
    try:
        schema = _schema_for_kind(kind)
        if schema.validate(root):
            return []
        return [
            diagnostic("XSD_INVALID", entry.message, location=str(entry.line))
            for entry in list(schema.error_log)[:20]
        ]
    except FileNotFoundError as exc:
        return [diagnostic("XSD_BUNDLE_UNAVAILABLE", str(exc))]
    except (
        etree.XMLSchemaError,
        etree.XMLSyntaxError,
        OSError,
        ValueError,
        json.JSONDecodeError,
    ) as exc:
        return [diagnostic("XSD_BUNDLE_INVALID", str(exc))]
