"""Explicit QTI item-bank dialect dispatch."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from hashlib import sha256
import re
import zipfile

from defusedxml import ElementTree as SafeET
from defusedxml.ElementTree import ParseError

from .qti3.profile import PACKAGE_NS as QTI3_PACKAGE_NS
from .qti3.profile import QTI_NS as QTI3_ITEM_NS

_QTI2_PACKAGE_NS = "http://www.imsglobal.org/xsd/imscp_v1p1"
_QTI2_ITEMS = {
    "http://www.imsglobal.org/xsd/imsqti_v2p1": "2.1",
    "http://www.imsglobal.org/xsd/imsqti_v2p2": "2.2",
}
_QTI2_TYPES = {"imsqti_item_xmlv2p1": "2.1", "imsqti_item_xmlv2p2": "2.2"}


def _qti2_zip_version(root, reader, index: dict) -> str:
    """Use declared item types and present item roots, never a custom schema label."""
    from .qti3.package import _resolve

    q = f"{{{_QTI2_PACKAGE_NS}}}"
    resources = root.find(q + "resources")
    if resources is None:
        raise ValueError("QTI 2 manifest has no resources")
    types: set[str] = set()
    roots: set[str] = set()
    for resource in resources:
        if resource.tag != q + "resource":
            raise ValueError("Unsupported manifest resource")
        kind = resource.get("type") or ""
        if kind not in _QTI2_TYPES:
            if kind.startswith("imsqti_item_xml"):
                raise ValueError("Unsupported or mixed QTI item resource version")
            continue
        types.add(_QTI2_TYPES[kind])
        href = resource.get("href")
        if href is None:
            continue  # Strict package validation reports a missing item href.
        path = _resolve(href, "imsmanifest.xml")
        if path not in index:
            continue  # Strict package validation reports a missing item file.
        try:
            item = _root(reader.read(path))
        except (ValueError, ParseError):
            continue  # Malformed/unsafe item is handled by the selected reader.
        item_version = next(
            (
                dialect
                for namespace, dialect in _QTI2_ITEMS.items()
                if item.tag == f"{{{namespace}}}assessmentItem"
            ),
            None,
        )
        if item_version is None:
            raise ValueError("QTI item root namespace contradicts manifest resource type")
        roots.add(item_version)
    if len(types) != 1 or roots - types:
        raise ValueError("Mixed or unidentified QTI 2 item versions")
    version = next(iter(types))
    metadata = root.find(q + "metadata")
    schema = metadata.find(q + "schema") if metadata is not None else None
    label = (schema.text or "").strip() if schema is not None else ""
    stated = re.search(r"(?i)qti[\s-]*v?\s*(2\.[12])\b", label)
    if stated and stated.group(1) != version:
        raise ValueError("QTI metadata version contradicts item resource type")
    return version


def _invalid(data: bytes, code: str, message: str) -> dict:
    return {
        "version": None,
        "packageValidation": "invalid",
        "diagnostics": [
            {"code": code, "severity": "error", "message": message, "location": "input"}
        ],
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


def _root(data: bytes):
    if len(data) > 10 * 1024 * 1024:
        raise ValueError("XML byte limit exceeded")
    lower = data.lower()
    if any(
        token in lower for token in (b"<!doctype", b"<!entity", b"<?xml-stylesheet", b"<xi:include")
    ):
        raise ValueError("Unsafe XML construct")
    return SafeET.fromstring(data, forbid_dtd=True, forbid_entities=True, forbid_external=True)


def load_package(data: bytes, *, filename: str, trusted_export: bool = False) -> dict:
    """Detect QTI 2.1, 2.2 or 3.0 from root content, then call its strict reader."""
    if type(data) is not bytes or type(filename) is not str:
        return _invalid(b"", "PACKAGE_INPUT_INVALID", "Expected file bytes and filename")
    lower = filename.lower()
    try:
        if lower.endswith(".xml"):
            root = _root(data)
            if root.tag == f"{{{QTI3_ITEM_NS}}}qti-assessment-item":
                version = "3.0"
            else:
                version = next(
                    (
                        value
                        for ns, value in _QTI2_ITEMS.items()
                        if root.tag == f"{{{ns}}}assessmentItem"
                    ),
                    None,
                )
        elif lower.endswith(".zip"):
            from .qti3.package import _index_archive, _Reader

            archive, index = _index_archive(data)
            try:
                reader = _Reader(archive, index)
                root = _root(reader.read("imsmanifest.xml"))
                if root.tag == f"{{{_QTI2_PACKAGE_NS}}}manifest":
                    version = _qti2_zip_version(root, reader, index)
            finally:
                archive.close()
            if root.tag == f"{{{QTI3_PACKAGE_NS}}}manifest":
                version = "3.0"
            elif root.tag != f"{{{_QTI2_PACKAGE_NS}}}manifest":
                version = None
        else:
            version = None
        if version is None:
            return _invalid(
                data,
                "QTI_VERSION_UNSUPPORTED",
                "Only QTI 2.1, 2.2 and 3.0 item-bank exchange is supported",
            )
        if version == "3.0":
            from .qti3.package import load_package as load_qti3

            result = load_qti3(data, filename=filename, trusted_export=trusted_export)
        else:
            from .qti2.package import load_package as load_qti2

            result = load_qti2(
                data, filename=filename, trusted_export=trusted_export, version=version
            )
        return {"version": version, **result}
    except (ValueError, KeyError, ParseError, zipfile.BadZipFile, RuntimeError) as exc:
        # A malformed root is an invalid package, not a legacy-format fallback.
        return _invalid(data, "QTI_PACKAGE_INVALID", str(exc)[:200])


def build_package(
    items: Sequence[dict],
    *,
    asset_bytes: Mapping[object, bytes],
    origin_labels: Mapping[str, str] | None = None,
    version: str,
) -> dict:
    """Build an explicitly selected QTI dialect; no default version."""
    if version == "3.0":
        from .qti3.package import build_package as build_qti3

        result = build_qti3(items, asset_bytes=asset_bytes, origin_labels=origin_labels)
    elif version in {"2.1", "2.2"}:
        from .qti2.package import build_package as build_qti2

        result = build_qti2(
            items, asset_bytes=asset_bytes, origin_labels=origin_labels, version=version
        )
    else:
        return {
            "version": None,
            "packageValidation": "invalid",
            "diagnostics": [
                {
                    "code": "QTI_VERSION_UNSUPPORTED",
                    "severity": "error",
                    "message": "Unsupported QTI export dialect",
                    "location": "version",
                }
            ],
            "items": [],
            "zip": None,
            "sourceSha256": None,
        }
    return {"version": version, **result}


__all__ = ["load_package", "build_package"]
