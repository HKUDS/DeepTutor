"""QTI 2.1/2.2 item-bank profile identifiers."""

from __future__ import annotations

from dataclasses import dataclass

PACKAGE_NS = "http://www.imsglobal.org/xsd/imscp_v1p1"


@dataclass(frozen=True)
class Dialect:
    version: str
    item_ns: str
    item_schema: str
    package_schema: str
    metadata_schema: str
    item_type: str
    external_scored: bool


DIALECTS = {
    "2.1": Dialect(
        "2.1",
        "http://www.imsglobal.org/xsd/imsqti_v2p1",
        "imsqti_v2p1p2.xsd",
        "qtiv2p1_imscpv1p2_v1p0.xsd",
        "QTIv2.1 Item Bank Package",
        "imsqti_item_xmlv2p1",
        False,
    ),
    "2.2": Dialect(
        "2.2",
        "http://www.imsglobal.org/xsd/imsqti_v2p2",
        "imsqti_v2p2p4.xsd",
        "qtiv2p2_imscpv1p2_v1p0.xsd",
        "QTIv2.2 Item Bank Package",
        "imsqti_item_xmlv2p2",
        True,
    ),
}


def diagnostic(code: str, message: str, *, location: str = "", severity: str = "error") -> dict:
    return {"code": code, "severity": severity, "message": message, "location": location}
