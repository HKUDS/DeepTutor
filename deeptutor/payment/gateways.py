"""Online payment gateway adapters for DeepTutor Enterprise.

Two gateways are supported, mirroring the RIC-546 gateway-config model:

``wechat``
    The official WeChat Pay **APIv3** protocol (Native for scan-to-pay QR,
    H5/JSAPI as a jump URL).  APIv3 authenticates requests with a merchant
    private key over a ``RSA-SHA256`` signature and verifies callbacks using
    the **WeChat Pay Platform certificate's** public key (SHA256withRSA) plus
    the ``Wechatpay-Timestamp``/``Wechatpay-Nonce``/``Wechatpay-Signature``
    headers.  The notify body carries a ``resource`` envelope that must be
    AEAD-AES-256-GCM decrypted with ``api_v3_key``.

``epay``
    The 易支付 (EPay) universal gateway protocol — an HTTP-parameter protocol
    with an MD5 signature over sorted ``k=v`` pairs salted with the merchant
    key.  Order creation posts form data to the gateway's ``/submit.php`` and
    the gateway redirects the buyer back to ``return_url`` and POSTs the same
    signed body to ``notify_url``.

Configuration is stored under ``data/system/payment/gateways.json`` (written
by the admin console, RIC-546/550).  This module only *reads* the active
gateway; it never edits configuration.
"""

from __future__ import annotations

import base64
import binascii
from datetime import datetime, timedelta, timezone
import hashlib
import json
import logging
from pathlib import Path
import secrets
from typing import Any

from deeptutor.multi_user.paths import SYSTEM_ROOT, ensure_system_dirs

logger = logging.getLogger(__name__)

GATEWAY_WECHAT = "wechat"
GATEWAY_EPAY = "epay"
GATEWAY_NAMES = frozenset({GATEWAY_WECHAT, GATEWAY_EPAY})

GATEWAYS_FILE_NAME = "gateways.json"

#: How long a native/H5 order is valid before the gateway expires it.
ORDER_EXPIRE_MINUTES = 30

#: WeChat APIv3 platform certificate rotation window; re-fetch before expiry.
_WECHAT_PLATFORM_CERT_REFRESH_HOURS = 24 * 180


class GatewayError(ValueError):
    """A gateway configuration or signature problem with a stable reason."""


class SignatureVerificationError(GatewayError):
    """Callback signature failed verification."""


# ---------------------------------------------------------------------------
# Persistence
# ---------------------------------------------------------------------------


def _payment_root() -> Path:
    ensure_system_dirs()
    root = SYSTEM_ROOT / "payment"
    root.mkdir(parents=True, exist_ok=True)
    return root


def gateways_path() -> Path:
    return _payment_root() / GATEWAYS_FILE_NAME


def load_gateways() -> dict[str, dict[str, Any]]:
    """Return the stored gateway configuration (never raises).

    Unknown/inactive gateways are excluded; a caller of ``active_gateway``
    re-checks the ``enabled`` flag.
    """
    path = gateways_path()
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning("Failed to read gateway config at %s: %s", path, exc)
        return {}
    if not isinstance(payload, dict):
        return {}
    out: dict[str, dict[str, Any]] = {}
    for name, cfg in payload.items():
        if name in GATEWAY_NAMES and isinstance(cfg, dict):
            out[name] = cfg
    return out


def active_gateway(name: str) -> dict[str, Any]:
    """Return an enabled gateway's config, or raise :class:`GatewayError`."""
    if name not in GATEWAY_NAMES:
        raise GatewayError(f"unsupported gateway: {name}")
    gateways = load_gateways()
    cfg = gateways.get(name)
    if cfg is None or not bool(cfg.get("enabled")):
        raise GatewayError(f"gateway {name} is not enabled")
    return cfg


def list_active_gateways() -> list[str]:
    return [name for name in sorted(GATEWAY_NAMES) if _is_enabled(name)]


def _is_enabled(name: str) -> bool:
    cfg = load_gateways().get(name)
    return bool(cfg and cfg.get("enabled"))


# ---------------------------------------------------------------------------
# WeChat Pay APIv3
# ---------------------------------------------------------------------------

_WECHAT_NOTIFY_TIMESTAMP_SKEW_SECONDS = 300


def _load_merchant_private_key(path: str | None) -> Any:
    """Load the merchant APIv3 RSA private key."""
    from cryptography.hazmat.primitives.serialization import load_pem_private_key

    if not path:
        raise GatewayError("wechat merchant_private_key_path is not configured")
    try:
        return load_pem_private_key(
            Path(path).read_bytes(),
            password=None,
        )
    except Exception as exc:
        raise GatewayError(f"failed to load wechat merchant private key: {exc}") from exc


def wechat_authorization_header(cfg: dict[str, Any], method: str, url_path: str, body: str) -> str:
    """Build the ``Authorization: WECHATPAY2-SHA256-RSA2048 ...`` header."""
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import padding

    mchid = str(cfg.get("mchid") or "")
    serial = str(cfg.get("merchant_serial_no") or "")
    if not mchid or not serial:
        raise GatewayError("wechat mchid/merchant_serial_no not configured")

    timestamp = str(int(datetime.now(timezone.utc).timestamp()))
    nonce = secrets.token_hex(16)
    message = f"{method}\n{url_path}\n{timestamp}\n{nonce}\n{body}\n"
    private_key = _load_merchant_private_key(cfg.get("merchant_private_key_path"))
    signature = private_key.sign(
        message.encode("utf-8"),
        padding.PKCS1v15(),
        hashes.SHA256(),
    )
    return (
        "WECHATPAY2-SHA256-RSA2048 "
        f'mchid="{mchid}",nonce_str="{nonce}",signature="{base64.b64encode(signature).decode()}'
        f'",timestamp="{timestamp}",serial_no="{serial}"'
    )


def wechat_native_payload(
    cfg: dict[str, Any],
    *,
    description: str,
    out_trade_no: str,
    total_fen: int,
    notify_url: str,
    expires_at: str,
) -> dict[str, Any]:
    """Build the request body for the Native ``/v3/pay/transactions/native`` API."""
    return {
        "appid": str(cfg.get("appid") or ""),
        "mchid": str(cfg.get("mchid") or ""),
        "description": description[:127],
        "out_trade_no": out_trade_no,
        "notify_url": notify_url,
        "time_expire": expires_at,
        "amount": {"total": int(total_fen), "currency": "CNY"},
    }


def wechat_h5_payload(
    cfg: dict[str, Any],
    *,
    description: str,
    out_trade_no: str,
    total_fen: int,
    notify_url: str,
    expires_at: str,
) -> dict[str, Any]:
    """Build the request body for the H5 ``/v3/pay/transactions/h5`` API."""
    return {
        **wechat_native_payload(
            cfg,
            description=description,
            out_trade_no=out_trade_no,
            total_fen=total_fen,
            notify_url=notify_url,
            expires_at=expires_at,
        ),
        "scene_info": {
            "payer_client_ip": "127.0.0.1",
            "h5_info": {"type": "Wap"},
        },
    }


def _verify_wechat_signature(cfg: dict[str, Any], headers: dict[str, str], body: bytes) -> None:
    """Verify an APIv3 callback signature against the WeChat platform cert."""
    from cryptography.exceptions import InvalidSignature
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.asymmetric import padding
    from cryptography.x509 import load_pem_x509_certificate

    timestamp = headers.get("wechatpay-timestamp") or headers.get("Wechatpay-Timestamp") or ""
    nonce = headers.get("wechatpay-nonce") or headers.get("Wechatpay-Nonce") or ""
    signature = headers.get("wechatpay-signature") or headers.get("Wechatpay-Signature") or ""
    serial = headers.get("wechatpay-serial") or headers.get("Wechatpay-Serial") or ""
    if not (timestamp and nonce and signature and serial):
        raise SignatureVerificationError("missing wechat signature headers")

    try:
        if (
            abs(int(timestamp) - int(datetime.now(timezone.utc).timestamp()))
            > _WECHAT_NOTIFY_TIMESTAMP_SKEW_SECONDS
        ):
            raise SignatureVerificationError("wechat notify timestamp too old")
    except (TypeError, ValueError) as exc:
        raise SignatureVerificationError("malformed wechat timestamp") from exc

    cert_pem = _load_platform_certificate(cfg, serial)
    try:
        public_key = load_pem_x509_certificate(cert_pem).public_key()
    except Exception as exc:
        raise SignatureVerificationError("unreadable wechat platform certificate") from exc

    message = f"{timestamp}\n{nonce}\n{body.decode('utf-8')}\n"
    try:
        public_key.verify(
            base64.b64decode(signature),
            message.encode("utf-8"),
            padding.PKCS1v15(),
            hashes.SHA256(),
        )
    except (InvalidSignature, binascii.Error, ValueError) as exc:
        raise SignatureVerificationError("wechat signature verification failed") from exc


def _load_platform_certificate(cfg: dict[str, Any], serial: str) -> bytes:
    """Resolve the WeChat platform certificate PEM for ``serial``.

    Accepts an inline ``platform_cert_pem`` or a ``platform_certs_dir``
    holding ``<serial>.pem`` files.  On first use it attempts a one-time
    download from the WeChat certificates API when credentials are present;
    the download is best-effort (an operator can drop the PEM by hand instead).
    """
    inline = cfg.get("platform_cert_pem")
    if inline:
        return str(inline).encode("utf-8")
    certs_dir = cfg.get("platform_certs_dir")
    if certs_dir:
        path = Path(certs_dir) / f"{serial}.pem"
        if path.exists():
            return path.read_bytes()
        path_alt = Path(certs_dir) / f"{serial}.crt"
        if path_alt.exists():
            return path_alt.read_bytes()
    try:
        downloaded = _download_platform_certificate(cfg, serial)
        if downloaded:
            return downloaded
    except Exception:
        logger.debug("Could not download wechat platform cert for serial %s", serial, exc_info=True)
    raise SignatureVerificationError(f"no wechat platform certificate for serial {serial}")


def _download_platform_certificate(cfg: dict[str, Any], serial: str) -> bytes | None:
    """One-time best-effort download of the WeChat Pay platform certificate."""
    try:
        import httpx
    except ImportError:
        return None
    if not (
        cfg.get("mchid") and cfg.get("merchant_private_key_path") and cfg.get("merchant_serial_no")
    ):
        return None
    url = "https://api.mch.weixin.qq.com/v3/certificates"
    body = json.dumps({"limit": 1, "offset": 0}, separators=(",", ":"))
    headers = {"Authorization": wechat_authorization_header(cfg, "GET", "/v3/certificates", body)}
    resp = httpx.get(url, headers=headers, timeout=10)
    resp.raise_for_status()
    data = resp.json()
    for item in data.get("data", []) or []:
        if str(item.get("serial_no") or "") != serial:
            continue
        encrypted = item.get("encrypt_certificate") or {}
        plain = _decrypt_wechat_resource(
            {
                "ciphertext": encrypted.get("ciphertext") or "",
                "nonce": encrypted.get("nonce") or "",
                "associated_data": encrypted.get("associated_data") or "",
            },
            api_v3_key=cfg.get("api_v3_key") or "",
        )
        certs_dir = cfg.get("platform_certs_dir")
        if certs_dir:
            Path(certs_dir).mkdir(parents=True, exist_ok=True)
            (Path(certs_dir) / f"{serial}.pem").write_bytes(plain)
        return plain
    return None


def decrypt_wechat_notify_body(cfg: dict[str, Any], resource: dict[str, Any]) -> dict[str, Any]:
    """AEAD-AES-256-GCM decrypt an APIv3 ``resource`` envelope."""
    api_v3_key = str(cfg.get("api_v3_key") or "")
    if not api_v3_key:
        raise SignatureVerificationError("wechat api_v3_key is not configured")
    plaintext = _decrypt_wechat_resource(resource, api_v3_key=api_v3_key)
    try:
        payload = json.loads(plaintext.decode("utf-8"))
    except Exception as exc:
        raise SignatureVerificationError("wechat notify resource is not valid JSON") from exc
    if not isinstance(payload, dict):
        raise SignatureVerificationError("wechat notify resource is not an object")
    return payload


def _decrypt_wechat_resource(resource: dict[str, Any], *, api_v3_key: str) -> bytes:
    from cryptography.hazmat.primitives.ciphers.aead import AESGCM

    ciphertext = base64.b64decode(str(resource.get("ciphertext") or ""))
    nonce = str(resource.get("nonce") or "").encode("utf-8")
    associated = str(resource.get("associated_data") or "").encode("utf-8")
    try:
        return AESGCM(api_v3_key.encode("utf-8")).decrypt(nonce, ciphertext, associated)
    except Exception as exc:
        raise SignatureVerificationError("failed to decrypt wechat notify resource") from exc


def wechat_notify_result(*, ok: bool, message: str = "") -> dict[str, Any]:
    """The status body WeChat Pay expects after a notify call."""
    if ok:
        return {"code": "SUCCESS", "message": "成功"}
    return {"code": "FAIL", "message": message or "处理失败"}


# ---------------------------------------------------------------------------
# EPay (易支付) — MD5 signed form protocol
# ---------------------------------------------------------------------------


def _epay_sign(params: dict[str, Any], key: str) -> str:
    """EPay MD5 signature over sorted ``k=v`` pairs joined with ``&``."""
    filtered = {k: str(v) for k, v in params.items() if v not in (None, "") and k != "sign"}
    encoded = "&".join(f"{k}={filtered[k]}" for k in sorted(filtered))
    return hashlib.md5(f"{encoded}{key}".encode("utf-8")).hexdigest()


def epay_sign_params(cfg: dict[str, Any], params: dict[str, Any]) -> dict[str, Any]:
    """Return ``params`` plus the computed ``sign``/``sign_type``."""
    key = str(cfg.get("merchant_key") or "")
    if not key:
        raise GatewayError("epay merchant_key is not configured")
    sign_type = str(cfg.get("sign_type") or "MD5").upper()
    if sign_type != "MD5":
        raise GatewayError(f"unsupported epay sign_type: {sign_type}")
    signed = dict(params)
    signed["sign_type"] = sign_type
    signed["sign"] = _epay_sign(signed, key)
    return signed


def verify_epay_signature(cfg: dict[str, Any], params: dict[str, Any]) -> None:
    """Verify an EPay callback's ``sign`` over its form params.

    Uses a constant-time comparison.  Raises :class:`SignatureVerificationError`
    on any mismatch so the notify handler returns the gateway's failure body.
    """
    key = str(cfg.get("merchant_key") or "")
    if not key:
        raise SignatureVerificationError("epay merchant_key is not configured")
    incoming = str(params.get("sign") or "")
    if not incoming:
        raise SignatureVerificationError("epay callback missing sign")
    expected = _epay_sign(params, key)
    if not secrets.compare_digest(incoming.lower(), expected.lower()):
        raise SignatureVerificationError("epay signature verification failed")


def epay_notify_body(cfg: dict[str, Any], params: dict[str, Any]) -> dict[str, Any]:
    """Assemble the order-creation form body for the EPay gateway."""
    gateway = str(cfg.get("gateway_url") or "").rstrip("/")
    if not gateway:
        raise GatewayError("epay gateway_url is not configured")
    pid = str(cfg.get("pid") or cfg.get("merchant_id") or "")
    if not pid:
        raise GatewayError("epay pid/merchant_id is not configured")
    body = {
        "pid": pid,
        "type": str(cfg.get("pay_type") or "alipay"),
        "out_trade_no": str(params.get("out_trade_no") or ""),
        "notify_url": str(params.get("notify_url") or ""),
        "return_url": str(params.get("return_url") or ""),
        "name": str(params.get("name") or "")[:127],
        "money": str(params.get("money") or ""),
    }
    return epay_sign_params(cfg, body)


def epay_result_ok() -> str:
    """The literal body an EPay notify handler must return on success."""
    return "success"


def epay_result_fail() -> str:
    """The literal body an EPay notify handler must return on failure."""
    return "fail"


# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------


def format_price_fen(fen: int) -> str:
    """Render a fen-denominated amount as ``¥xx.xx``."""
    try:
        total = max(0, int(fen))
    except (TypeError, ValueError):
        total = 0
    return f"¥{total / 100:.2f}"


def iso_after(minutes: int) -> str:
    return (datetime.now(timezone.utc) + timedelta(minutes=minutes)).isoformat()


__all__ = [
    "GATEWAY_EPAY",
    "GATEWAY_NAMES",
    "GATEWAY_WECHAT",
    "GATEWAYS_FILE_NAME",
    "GatewayError",
    "SignatureVerificationError",
    "active_gateway",
    "decrypt_wechat_notify_body",
    "epay_notify_body",
    "epay_result_fail",
    "epay_result_ok",
    "epay_sign_params",
    "format_price_fen",
    "gateways_path",
    "iso_after",
    "list_active_gateways",
    "load_gateways",
    "verify_epay_signature",
    "wechat_authorization_header",
    "wechat_h5_payload",
    "wechat_native_payload",
    "wechat_notify_result",
    "_verify_wechat_signature",
]
