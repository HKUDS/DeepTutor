"""Hostile-input screening and pinned offline XSD validation for QTI 2.x."""

from __future__ import annotations

from functools import lru_cache
from hashlib import sha256
import json
from pathlib import Path

from defusedxml.common import DTDForbidden, EntitiesForbidden, ExternalReferenceForbidden
from defusedxml.lxml import fromstring as defused_fromstring

# Tree construction/types and XSD validation only; parsing uses defusedxml.
from lxml import etree  # nosec B410

from .profile import DIALECTS, PACKAGE_NS, diagnostic

_SCHEMAS = Path(__file__).with_name("schemas").resolve()
_ROOTS = {dialect.item_schema for dialect in DIALECTS.values()} | {
    dialect.package_schema for dialect in DIALECTS.values()
}


@lru_cache(maxsize=1)
def _inventory() -> dict:
    catalog = json.loads((_SCHEMAS / "inventory.json").read_text("utf-8"))
    if not isinstance(catalog, dict) or len(catalog) > 100:
        raise ValueError("QTI 2 offline schema catalog is invalid")
    return catalog


class _LocalResolver(etree.Resolver):
    def resolve(self, url: str, pubid: str | None, context: object) -> object:
        path = Path(url)
        if path.is_absolute() and path.parent == _SCHEMAS and path.name in _ROOTS:
            if path.is_symlink():
                raise ValueError("Schema symlink is forbidden")
            return self.resolve_filename(str(path), context)
        entry = _inventory().get(url)
        if not isinstance(entry, dict):
            raise ValueError("Unlisted QTI 2 schema dependency")
        name = entry.get("file")
        if not isinstance(name, str) or "/" in name or "\\" in name:
            raise ValueError("Invalid QTI 2 schema inventory")
        local = _SCHEMAS / name
        if local.is_symlink() or not local.is_file():
            raise ValueError("QTI 2 schema dependency is unavailable")
        data = local.read_bytes()
        if sha256(data).hexdigest() != entry.get("sha256") or len(data) != entry.get("bytes"):
            raise ValueError("QTI 2 schema dependency digest mismatch")
        return self.resolve_string(data, context, base_url=url)


@lru_cache(maxsize=4)
def _schema(version: str, kind: str) -> etree.XMLSchema:
    dialect = DIALECTS[version]
    name = dialect.item_schema if kind == "item" else dialect.package_schema
    path = _SCHEMAS / name
    if not path.is_file() or path.is_symlink():
        raise ValueError("QTI 2 root schema is unavailable")
    expected = next(
        (record["sha256"] for url, record in _inventory().items() if record["file"] == name), None
    )
    if sha256(path.read_bytes()).hexdigest() != expected:
        raise ValueError("QTI 2 root schema digest mismatch")
    parser = etree.XMLParser(resolve_entities=False, load_dtd=False, no_network=True)
    parser.resolvers.add(_LocalResolver())
    root = defused_fromstring(
        path.read_bytes(), parser=parser, base_url=str(path), forbid_dtd=True, forbid_entities=True
    )
    return etree.XMLSchema(root)


def safe_root(data: bytes, *, kind: str, version: str) -> etree._Element:
    if version not in DIALECTS or kind not in {"item", "manifest"}:
        raise ValueError("Unsupported QTI 2 dialect or XML kind")
    if type(data) is not bytes or len(data) > 10 * 1024 * 1024:
        raise ValueError("XML byte limit exceeded")
    lower = data.lower()
    if any(
        token in lower for token in (b"<!doctype", b"<!entity", b"<?xml-stylesheet", b"<xi:include")
    ):
        raise ValueError("DTD, entity, stylesheet or XInclude is forbidden")
    parser = etree.XMLParser(
        resolve_entities=False, load_dtd=False, no_network=True, huge_tree=False
    )
    parser.resolvers.add(_LocalResolver())
    try:
        root = defused_fromstring(data, parser=parser, forbid_dtd=True, forbid_entities=True)
    except (
        etree.XMLSyntaxError,
        DTDForbidden,
        EntitiesForbidden,
        ExternalReferenceForbidden,
    ) as exc:
        raise ValueError("Unsafe or malformed QTI XML") from exc
    namespace = DIALECTS[version].item_ns if kind == "item" else PACKAGE_NS
    name = "assessmentItem" if kind == "item" else "manifest"
    if root.tag != f"{{{namespace}}}{name}":
        raise ValueError("Unexpected QTI 2 namespace or root")
    count = 0
    stack = [(root, 1)]
    while stack:
        node, depth = stack.pop()
        count += 1
        if count > 200_000 or depth > 128:
            raise ValueError("XML structural limit exceeded")
        if isinstance(node, etree._ProcessingInstruction):
            raise ValueError("Processing instructions are forbidden")
        if any(key.lower().startswith("on") for key in node.attrib):
            raise ValueError("Event-handler attributes are forbidden")
        stack.extend((child, depth + 1) for child in node)
    return root


def validate_xml(data: bytes, *, kind: str, version: str) -> list[dict]:
    try:
        root = safe_root(data, kind=kind, version=version)
        schema = _schema(version, kind)
        if schema.validate(root):
            return []
        return [
            diagnostic("XSD_INVALID", issue.message, location=str(issue.line))
            for issue in list(schema.error_log)[:20]
        ]
    except (ValueError, KeyError, OSError, etree.XMLSchemaError, etree.XMLSyntaxError) as exc:
        return [diagnostic("XML_UNSAFE_OR_INVALID", str(exc)[:200])]


__all__ = ["safe_root", "validate_xml"]
