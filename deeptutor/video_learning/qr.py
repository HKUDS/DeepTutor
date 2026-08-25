"""QR code payload generator and parser for video-learning pairing."""

from __future__ import annotations

import io
import re
from urllib.parse import parse_qs, quote, urlparse
import xml.etree.ElementTree as ET

import qrcode
import qrcode.image.svg

PAIRING_URI_SCHEME = "deeptutor-video-learning"
PAIRING_URI_VERSION = "1"
_CODE_RE = re.compile(r"^[A-Za-z0-9_-]{4,16}$")


class InvalidPairingQRError(ValueError):
    """Raised when a QR payload does not match the strict pairing URI format."""


def build_pairing_uri(code: str) -> str:
    cleaned = (code or "").strip()
    if not _CODE_RE.fullmatch(cleaned):
        raise ValueError(f"Invalid pairing code format: {code!r}")
    return f"{PAIRING_URI_SCHEME}://pair?v={PAIRING_URI_VERSION}&code={cleaned}"


def parse_pairing_uri(uri: str) -> str:
    raw = (uri or "").strip()
    if not raw.startswith(f"{PAIRING_URI_SCHEME}:"):
        raise InvalidPairingQRError("Invalid scheme for video learning pairing.")
    parsed = urlparse(raw)
    if parsed.scheme != PAIRING_URI_SCHEME:
        raise InvalidPairingQRError("Invalid scheme for video learning pairing.")
    target = (parsed.netloc or parsed.path or "").strip("/")
    if target != "pair":
        raise InvalidPairingQRError(f"Invalid pairing action: {target!r}")
    query = parse_qs(parsed.query, keep_blank_values=False)
    version = query.get("v", [""])[0]
    if version != PAIRING_URI_VERSION:
        raise InvalidPairingQRError(f"Unsupported pairing version: {version!r}")
    code = query.get("code", [""])[0].strip()
    if not _CODE_RE.fullmatch(code):
        raise InvalidPairingQRError(f"Invalid pairing code in payload: {code!r}")
    return code


def generate_pairing_qr_svg(code: str) -> str:
    payload = build_pairing_uri(code)
    qr = qrcode.QRCode(
        version=1,
        error_correction=qrcode.constants.ERROR_CORRECT_M,
        box_size=8,
        border=2,
        image_factory=qrcode.image.svg.SvgPathImage,
    )
    qr.add_data(payload)
    qr.make(fit=True)
    img = qr.make_image()
    buf = io.BytesIO()
    img.save(buf)
    svg_str = buf.getvalue().decode("utf-8")
    # Verify the generated SVG is well-formed XML
    ET.fromstring(svg_str)
    return svg_str


def generate_pairing_qr_data_url(code: str) -> tuple[str, str]:
    payload = build_pairing_uri(code)
    svg_str = generate_pairing_qr_svg(code)
    data_url = f"data:image/svg+xml;utf8,{quote(svg_str)}"
    return payload, data_url


def generate_qr_data_url(payload: str) -> str:
    """Generate a controlled SVG data URL for a non-pairing bootstrap link."""
    qr = qrcode.QRCode(version=None, error_correction=qrcode.constants.ERROR_CORRECT_M, box_size=8, border=2, image_factory=qrcode.image.svg.SvgPathImage)
    qr.add_data(payload)
    qr.make(fit=True)
    image = qr.make_image()
    buf = io.BytesIO()
    image.save(buf)
    svg = buf.getvalue().decode("utf-8")
    ET.fromstring(svg)
    return f"data:image/svg+xml;utf8,{quote(svg)}"
