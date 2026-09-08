"""Admin-facing data models and persistence for the DeepTutor commerce layer.

The learner-facing payment engine (:mod:`deeptutor.payment.service`,
:mod:`deeptutor.payment.gateways`) *reads* configuration; this module owns the
*write* side that the admin console drives (RIC-546):

* **Gateway configuration** — WeChat Pay APIv3, EPay universal gateway, and
  the CDK channel.  Stored at ``data/system/payment/gateways.json``.
* **Pricing plans** — price/validity plus the permission bundle (books,
  knowledge bases, LLM model whitelist) a purchase unlocks.  Stored at
  ``data/system/payment/plans.json``.

The order *ledger* is persisted by :mod:`deeptutor.payment.orders`; this
module additionally exposes the admin read/refund views over that store.

Everything here is kept intentionally free of FastAPI imports so it stays
unit-testable in isolation and importable from scripts — the HTTP surface
lives in :mod:`deeptutor.api.routers.payment_admin`.

Path reuse
----------
``gateways_path`` / ``plans_path`` are re-exported from the sibling modules
that already own them (:mod:`deeptutor.payment.gateways` and
:mod:`deeptutor.payment.service`), so a config written here is read by the
cashier from the exact same file.  Tests that monkeypatch ``SYSTEM_ROOT`` on
those modules keep working because the path helpers resolve through the
patched module attribute.

Secrets
-------
Gateway credentials must never round-trip to the browser.  Follow the same
convention as the model catalog (``CATALOG_SECRET_MASK`` in
``deeptutor.services.config.model_catalog``): reads redact secret-shaped
keys to ``"***"`` and writes treat a ``"***"`` value as "keep the stored
value".  This file exports ``GATEWAY_SECRET_MASK`` and the
``redact_gateways`` / ``restore_gateway_secrets`` helpers so the router can
stay thin.
"""

from __future__ import annotations

import json
import logging
import re
from typing import Any

from deeptutor.payment.gateways import gateways_path
from deeptutor.payment.orders import (
    ORDER_STATUS_REFUNDED,
    TRANSITION_EXTRA_REFUND,
    OrderNotFoundError,
    get_order,
    list_order_records,
    transition_order,
)
from deeptutor.payment.service import plans_path
from deeptutor.services.file_io import atomic_write_json

logger = logging.getLogger(__name__)

#: Re-exported for callers that want the channel constants from one place.
GATEWAY_WECHAT = "wechat"
GATEWAY_EPAY = "epay"
GATEWAY_CDK = "cdk"

GATEWAYS_FILE_NAME = "gateways.json"
PLANS_FILE_NAME = "plans.json"

#: Placeholder returned to settings clients in place of stored credentials.
#: Accepted on write as "keep the existing value".  Mirrors the model-catalog
#: convention (``CATALOG_SECRET_MASK``) so a load/edit/save round trip never
#: sends a real secret to the browser.
GATEWAY_SECRET_MASK = "***"

#: Keys whose value is a credential and must be redacted on read.
_GATEWAY_SECRET_HINTS = ("key", "secret", "token", "password")

#: WeChat configuration keys that may hold a PEM block or a filesystem path.
_WECHAT_CREDENTIAL_KEYS = frozenset(
    {
        "merchant_private_key_path",
        "platform_cert_pem",
        "platform_certs_dir",
    }
)

#: EPay configuration keys that hold credentials.
_EPAY_CREDENTIAL_KEYS = frozenset({"merchant_key"})

#: Known gateway channel names accepted by the config write path.
GATEWAY_NAMES = frozenset({GATEWAY_WECHAT, GATEWAY_EPAY, GATEWAY_CDK})


def _is_secret_key(key: str) -> bool:
    normalized = str(key or "").lower()
    if normalized in _WECHAT_CREDENTIAL_KEYS or normalized in _EPAY_CREDENTIAL_KEYS:
        return True
    return any(hint in normalized for hint in _GATEWAY_SECRET_HINTS)


def load_gateway_config() -> dict[str, Any]:
    """Read the *full* stored gateway document (all channels, unfiltered).

    ``deeptutor.payment.gateways.load_gateways`` filters to the two online
    channels it understands (wechat/epay) and is the right reader for the
    cashier; this is the admin/round-trip view that also carries the CDK
    channel flag, so a GET/PUT round trip preserves every channel.
    """
    path = gateways_path()
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning("Failed to read gateway config at %s: %s", path, exc)
        return {}
    return payload if isinstance(payload, dict) else {}


def redact_gateways(gateways: dict[str, Any]) -> dict[str, Any]:
    """Return a wire-safe deep copy of the gateway config (no mutation)."""
    out: dict[str, Any] = {}
    for name, cfg in gateways.items():
        if isinstance(cfg, dict):
            cfg = dict(cfg)
            for key, value in list(cfg.items()):
                if _is_secret_key(key) and value not in (None, "", False):
                    cfg[key] = GATEWAY_SECRET_MASK
            out[name] = cfg
        else:
            out[name] = cfg
    return out


def _restore_secret(proposed: Any, current: Any) -> Any:
    if proposed == GATEWAY_SECRET_MASK:
        return current
    return proposed


def restore_gateway_secrets(
    proposed: dict[str, Any], current: dict[str, Any] | None = None
) -> dict[str, Any]:
    """Replace ``GATEWAY_SECRET_MASK`` placeholders with stored values.

    ``current`` defaults to the full stored document when omitted.
    """
    current = load_gateway_config() if current is None else current
    stored = current if isinstance(current, dict) else {}
    out: dict[str, Any] = {}
    for name, cfg in proposed.items():
        if not isinstance(cfg, dict):
            out[name] = cfg
            continue
        stored_cfg = stored.get(name) if isinstance(stored.get(name), dict) else {}
        cfg = dict(cfg)
        for key, value in list(cfg.items()):
            if _is_secret_key(key):
                cfg[key] = _restore_secret(value, stored_cfg.get(key))
        out[name] = cfg
    return out


def validate_gateways(gateways: dict[str, Any]) -> None:
    """Fail-closed validation of the gateway configuration shape.

    Unknown channels are rejected so a typo cannot silently disable a payment
    path the deployment relies on.  Channel-level validation is deliberately
    lenient (a storefront can be pre-configured before real credentials are
    dropped in); the runtime gateways module re-checks at call time.
    """
    if not isinstance(gateways, dict):
        raise ValueError("gateways must be an object")
    for name, cfg in gateways.items():
        if name not in GATEWAY_NAMES:
            raise ValueError(f"unsupported gateway: {name}")
        if not isinstance(cfg, dict):
            raise ValueError(f"gateway {name} configuration must be an object")
        if not isinstance(cfg.get("enabled", False), bool):
            raise ValueError(f"gateway {name} 'enabled' must be a boolean")


def save_gateways(gateways: dict[str, Any]) -> dict[str, Any]:
    """Validate and atomically persist the gateway configuration.

    Accepts any subset of the known gateway channels.  Credentials are
    restored from the stored value when a ``GATEWAY_SECRET_MASK`` placeholder
    is submitted, so a load/edit/save round trip preserves them.
    """
    proposed = restore_gateway_secrets(gateways)
    validate_gateways(proposed)
    atomic_write_json(gateways_path(), proposed)
    logger.info("gateway configuration saved: %s", ", ".join(sorted(proposed)))
    return proposed


def public_gateways() -> dict[str, Any]:
    """Wire-safe gateway view for the admin console (credentials redacted)."""
    return redact_gateways(load_gateway_config())


# ---------------------------------------------------------------------------
# Pricing plans
# ---------------------------------------------------------------------------


PLAN_ID_RE = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")

#: Billing cadence buckets the learner UI groups by.
VALID_PERIODS = frozenset({"monthly", "quarterly", "yearly", "lifetime"})


class PlanValidationError(ValueError):
    """A pricing-plan document failed validation with a stable reason."""


def _normalize_string_list(value: Any, plan_key: str, field: str) -> list[str]:
    if value in (None, ""):
        return []
    if not isinstance(value, list):
        raise PlanValidationError(f"{plan_key}.{field} must be an array")
    out: list[str] = []
    for item in value:
        text = str(item or "").strip()
        if text and text not in out:
            out.append(text)
    return out


def _normalize_knowledge_bases(value: Any, plan_key: str) -> list[dict[str, Any]]:
    """Normalise KB references to the ``[{"name": "admin:kb:..."}]`` shape
    the provisioning engine and the multi-user grant layer both consume."""
    if value in (None, ""):
        return []
    raw = value if isinstance(value, list) else [value]
    out: list[dict[str, Any]] = []
    for item in raw:
        if isinstance(item, dict):
            name = str(
                item.get("resource_id")
                or item.get("id")
                or item.get("name")
                or item.get("kb_name")
                or ""
            ).strip()
            record = dict(item)
            record["name"] = name
            record.pop("resource_id", None)
            record.pop("id", None)
            record.pop("kb_name", None)
        else:
            name = str(item or "").strip()
            if not name:
                continue
            record = {"name": name}
        if not name:
            continue
        if name not in (existing.get("name") for existing in out):
            out.append(record)
    return out


def _normalize_models(value: Any, plan_key: str) -> dict[str, Any]:
    """Normalise the model whitelist to ``{"llm": [{"profile_id":...,
    "model_ids": [...]}]}`` — the exact shape the grant layer resolves."""
    if value in (None, ""):
        return {"llm": []}
    models = value if isinstance(value, dict) else {"llm": value}
    llm = models.get("llm")
    if not isinstance(llm, list):
        llm = []
    out: list[dict[str, Any]] = []
    for item in llm:
        if not isinstance(item, dict):
            continue
        profile_id = str(
            item.get("profile_id") or item.get("profile") or item.get("id") or ""
        ).strip()
        if not profile_id:
            continue
        model_ids = item.get("model_ids")
        if not isinstance(model_ids, list) or not model_ids:
            continue
        cleaned: list[str] = []
        for mid in model_ids:
            text = str(mid or "").strip()
            if text and text not in cleaned:
                cleaned.append(text)
        record = dict(item)
        record["profile_id"] = profile_id
        record.pop("profile", None)
        record.pop("id", None)
        record["model_ids"] = cleaned
        out.append(record)
    return {"llm": out}


def normalize_plan(raw: Any, *, plan_key: str = "plan") -> dict[str, Any]:
    """Coerce a stored/submitted plan into the canonical shape.

    Never raises on unknown keys — the permission bundle is forward-compatible
    (the provisioning engine reads ``models``/``knowledge_bases``/``skills``/
    ``books``) — but *does* raise :class:`PlanValidationError` for malformed
    core fields so an admin console edit cannot persist a plan the learner UI
    or the cashier would misread.
    """
    if not isinstance(raw, dict):
        raise PlanValidationError(f"{plan_key} must be an object")
    plan: dict[str, Any] = dict(raw)

    plan_id = str(plan.get("id") or plan.get("plan_id") or "").strip()
    if not plan_id:
        raise PlanValidationError(f"{plan_key}.id is required")
    if not PLAN_ID_RE.fullmatch(plan_id):
        raise PlanValidationError(f"{plan_key}.id must be 1-64 characters of [A-Za-z0-9_-]")
    plan["id"] = plan_id
    plan.pop("plan_id", None)

    name = str(plan.get("name") or "").strip()
    if not name:
        raise PlanValidationError(f"{plan_key}.name is required")
    plan["name"] = name

    price_fen = plan.get("price_fen")
    if price_fen is None:
        raise PlanValidationError(f"{plan_key}.price_fen is required")
    try:
        price_fen = int(price_fen)
    except (TypeError, ValueError) as exc:
        raise PlanValidationError(f"{plan_key}.price_fen must be an integer fee in fen") from exc
    if price_fen < 0:
        raise PlanValidationError(f"{plan_key}.price_fen cannot be negative")
    plan["price_fen"] = price_fen

    period = str(plan.get("period") or "").strip().lower() or "monthly"
    if period not in VALID_PERIODS:
        raise PlanValidationError(
            f"{plan_key}.period must be one of: {', '.join(sorted(VALID_PERIODS))}"
        )
    plan["period"] = period

    duration_days = plan.get("duration_days")
    if duration_days is not None:
        try:
            duration_days = int(duration_days)
        except (TypeError, ValueError) as exc:
            raise PlanValidationError(f"{plan_key}.duration_days must be an integer") from exc
        if duration_days <= 0:
            raise PlanValidationError(
                f"{plan_key}.duration_days must be positive (or omit for lifetime)"
            )
    plan["duration_days"] = duration_days

    # Permission bundle — each key validated independently, dropped if invalid
    # rather than failing the whole plan so a partially-unsupported bundle
    # degrades gracefully instead of blocking the catalogue.
    plan["books"] = _normalize_string_list(
        plan.get("books") or plan.get("book_ids"), plan_key, "books"
    )
    plan.pop("book_ids", None)
    plan["knowledge_bases"] = _normalize_knowledge_bases(
        plan.get("knowledge_bases") or plan.get("kb"), plan_key
    )
    plan.pop("kb", None)
    plan["skills"] = _normalize_string_list(plan.get("skills"), plan_key, "skills")
    plan["models"] = _normalize_models(plan.get("models"), plan_key)
    plan["perks"] = _normalize_string_list(plan.get("perks"), plan_key, "perks")
    plan["tag"] = str(plan.get("tag") or "").strip() or None
    plan["recommended"] = bool(plan.get("recommended", False))
    plan["published"] = bool(plan.get("published", True))
    return plan


def load_plans() -> list[dict[str, Any]]:
    """Return the stored plan catalogue (all plans, published or not)."""
    path = plans_path()
    if not path.exists():
        return []
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        logger.warning("Failed to read plans at %s: %s", path, exc)
        return []
    raw = payload.get("plans") if isinstance(payload, dict) else payload
    if not isinstance(raw, list):
        return []
    plans: list[dict[str, Any]] = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        try:
            plans.append(normalize_plan(item))
        except PlanValidationError as exc:
            logger.warning("Skipping invalid plan: %s", exc)
    return plans


def find_plan(plan_id: str) -> dict[str, Any] | None:
    """Resolve a plan by id, or None when it does not exist (or is invalid)."""
    for plan in load_plans():
        if str(plan.get("id") or "") == plan_id:
            return plan
    return None


def save_plans(plans: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Validate every plan and atomically persist the catalogue."""
    normalized = [normalize_plan(plan) for plan in plans]
    ids = [plan["id"] for plan in normalized]
    if len(ids) != len(set(ids)):
        raise PlanValidationError("plan ids must be unique")
    atomic_write_json(plans_path(), {"plans": normalized})
    return normalized


def upsert_plan(plan: dict[str, Any]) -> dict[str, Any]:
    """Insert or replace one plan in the catalogue and persist the result."""
    normalized = normalize_plan(plan)
    plans = load_plans()
    replaced = False
    for index, existing in enumerate(plans):
        if existing.get("id") == normalized["id"]:
            plans[index] = normalized
            replaced = True
            break
    if not replaced:
        plans.append(normalized)
    save_plans(plans)
    return normalized


def delete_plan(plan_id: str) -> bool:
    """Remove a plan from the catalogue; returns True when it was removed.

    A soft-archive flag is intentionally not used — referential safety for
    historical orders is preserved because every order snapshots its plan
    (see ``orders.create_order``), so deleting a plan never corrupts the
    ledger.
    """
    plans = load_plans()
    remaining = [p for p in plans if p.get("id") != plan_id]
    if len(remaining) == len(plans):
        return False
    save_plans(remaining)
    return True


def public_plan(plan: dict[str, Any]) -> dict[str, Any]:
    """The learner-facing projection of a plan (no permission internals)."""
    return {
        "id": plan.get("id"),
        "name": plan.get("name"),
        "period": plan.get("period", "monthly"),
        "price_fen": plan.get("price_fen"),
        "duration_days": plan.get("duration_days"),
        "perks": list(plan.get("perks") or []),
        "tag": plan.get("tag"),
        "recommended": bool(plan.get("recommended")),
    }


# ---------------------------------------------------------------------------
# Order ledger — admin views
# ---------------------------------------------------------------------------

_ORDER_ADMIN_FIELDS = (
    "order_id",
    "order_no",
    "user_id",
    "username",
    "gateway",
    "amount_fen",
    "currency",
    "status",
    "expires_at",
    "created_at",
    "paid_at",
    "granted_at",
    "refunded_at",
    "refund_reason",
    "notify_count",
    "last_error",
)


def admin_order_view(order: dict[str, Any]) -> dict[str, Any]:
    """Full admin view of one order (no redaction needed — the order store
    never persists credentials).

    The ledger stores the merchant-facing trade number under ``out_trade_no``
    (the learner-facing projection calls it ``order_no``) and the plan details
    inside a ``plan`` snapshot; this view normalises both so the admin console
    reads ``order_no`` / ``plan_id`` / ``plan_name`` directly.
    """
    view: dict[str, Any] = {}
    for key in _ORDER_ADMIN_FIELDS:
        if key in order:
            view[key] = order.get(key)
    if "order_no" not in view and order.get("out_trade_no"):
        view["order_no"] = order.get("out_trade_no")
    plan = order.get("plan")
    if isinstance(plan, dict):
        view["plan_snapshot"] = plan
        if "plan_id" not in view and plan.get("id"):
            view["plan_id"] = plan.get("id")
        if "plan_name" not in view and plan.get("name"):
            view["plan_name"] = plan.get("name")
    return view


def admin_list_orders(
    *,
    user_id: str | None = None,
    status: str | None = None,
    gateway: str | None = None,
    limit: int = 200,
    offset: int = 0,
) -> list[dict[str, Any]]:
    """Admin listing over the full order ledger (every user, not just self).

    Reads the full store rows (not the learner-facing projection), applies the
    caller's filters, then paginates.  ``limit`` is the page size, ``offset``
    the skip.
    """
    records = list_order_records()
    out: list[dict[str, Any]] = []
    for row in records:
        if user_id is not None and str(row.get("user_id") or "") != user_id:
            continue
        if status is not None and str(row.get("status") or "") != status:
            continue
        if gateway is not None and str(row.get("gateway") or "") != gateway:
            continue
        out.append(admin_order_view(row))
    return out[offset : offset + limit]


def admin_get_order(order_id: str) -> dict[str, Any]:
    """Return one order's admin view, or raise :class:`OrderNotFoundError`."""
    order = get_order(order_id)
    if order is None:
        raise OrderNotFoundError(f"order not found: {order_id}")
    return admin_order_view(order)


def admin_refund_order(order_id: str, *, reason: str = "") -> dict[str, Any]:
    """Mark an order refunded (admin-driven refund flag on the ledger).

    Uses the same status machine as the notify engine so an already-terminal
    order (refunded/failed) is a no-op rather than a corrupt transition.
    """
    try:
        order = transition_order(
            order_id, ORDER_STATUS_REFUNDED, extra=TRANSITION_EXTRA_REFUND(reason)
        )
    except (OrderNotFoundError, ValueError) as exc:
        raise OrderNotFoundError(f"refund failed for {order_id}: {exc}") from exc
    return admin_order_view(order)


__all__ = [
    "GATEWAY_CDK",
    "GATEWAY_EPAY",
    "GATEWAY_NAMES",
    "GATEWAY_SECRET_MASK",
    "GATEWAY_WECHAT",
    "PLAN_ID_RE",
    "PlanValidationError",
    "VALID_PERIODS",
    "admin_get_order",
    "admin_list_orders",
    "admin_order_view",
    "admin_refund_order",
    "delete_plan",
    "find_plan",
    "load_gateway_config",
    "load_plans",
    "normalize_plan",
    "plans_path",
    "public_gateways",
    "public_plan",
    "redact_gateways",
    "restore_gateway_secrets",
    "save_gateways",
    "save_plans",
    "upsert_plan",
    "validate_gateways",
]
