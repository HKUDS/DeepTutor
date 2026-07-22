"""Channel-schema introspection — bridges Pydantic channel configs to the Web UI.

Used by ``GET /api/v1/partners/channels/schema`` so the front-end can render
generic forms for ANY channel (built-in or plugin) without hard-coding fields.

Why live here vs inside ``deeptutor.partners.channels``?
  * This is an API-shaping concern (JSON Schema flattening, secret-field
    detection) — keeping it next to the route avoids polluting the runtime
    channel package with HTTP-specific helpers.
"""

from __future__ import annotations

import inspect
from typing import Any

from pydantic import BaseModel

from deeptutor.services.partners.manager import _is_secret_field


def resolve_config_model(channel_cls: type) -> type[BaseModel] | None:
    """Find the Pydantic config model paired with ``channel_cls``.

    Convention every built-in channel follows: ``XxxChannel`` lives in the
    same module as ``XxxConfig`` (e.g. ``TelegramChannel`` ↔ ``TelegramConfig``).
    Falls back to "any ``*Config`` BaseModel in the module".
    """
    module = inspect.getmodule(channel_cls)
    if module is None:
        return None

    expected = channel_cls.__name__.replace("Channel", "") + "Config"
    candidate = getattr(module, expected, None)
    if isinstance(candidate, type) and issubclass(candidate, BaseModel):
        return candidate

    for _, obj in inspect.getmembers(module):
        if (
            isinstance(obj, type)
            and obj is not BaseModel
            and issubclass(obj, BaseModel)
            and obj.__name__.endswith("Config")
        ):
            return obj
    return None


def inline_refs(schema: dict[str, Any]) -> dict[str, Any]:
    """Flatten Pydantic's ``$defs`` / ``$ref`` so the front-end doesn't need a resolver.

    Nested model fields (e.g. ``slack.dm: SlackDMConfig``) become inline
    ``type: object`` subtrees with their own ``properties``.
    """
    defs: dict[str, Any] = dict(schema.get("$defs", {}))

    def _walk(node: Any) -> Any:
        if isinstance(node, dict):
            ref = node.get("$ref")
            if isinstance(ref, str) and ref.startswith("#/$defs/"):
                ref_name = ref.rsplit("/", 1)[-1]
                resolved = defs.get(ref_name, {})
                merged = {**resolved}
                # Allow per-field overrides (description, default) from the ref site.
                for k, v in node.items():
                    if k != "$ref":
                        merged[k] = v
                return _walk(merged)
            return {k: _walk(v) for k, v in node.items()}
        if isinstance(node, list):
            return [_walk(item) for item in node]
        return node

    out = _walk(schema)
    if isinstance(out, dict):
        out.pop("$defs", None)
    return out


def _schema_accepts_string(prop_schema: dict[str, Any]) -> bool:
    """True iff the JSON-Schema fragment can hold a string value.

    Used to filter out booleans/integers/arrays whose name happens to contain
    a secret-looking substring (e.g. ``user_token_read_only: bool``).
    """
    t = prop_schema.get("type")
    if t == "string":
        return True
    if isinstance(t, list) and "string" in t:
        return True
    for variant in prop_schema.get("anyOf", []):
        if isinstance(variant, dict) and variant.get("type") == "string":
            return True
    return False


def collect_secret_fields(schema: dict[str, Any], prefix: str = "") -> list[str]:
    """Return dot-paths for every string-typed property whose name hints at a secret.

    e.g. ``["token"]`` for telegram, ``["imap_password", "smtp_password"]``
    for email, ``["bot_token", "app_token"]`` for slack. A field like
    ``user_token_read_only: bool`` is intentionally skipped.
    """
    paths: list[str] = []
    properties = schema.get("properties") if isinstance(schema, dict) else None
    if not isinstance(properties, dict):
        return paths

    for prop_name, prop_schema in properties.items():
        if not isinstance(prop_schema, dict):
            continue
        full = f"{prefix}{prop_name}" if not prefix else f"{prefix}.{prop_name}"
        if _is_secret_field(prop_name) and _schema_accepts_string(prop_schema):
            paths.append(full)
        if prop_schema.get("type") == "object":
            paths.extend(collect_secret_fields(prop_schema, prefix=full))
    return paths


def channel_schema_payload(channel_cls: type) -> dict[str, Any] | None:
    """Build the per-channel schema payload, or ``None`` if no config model found."""
    model = resolve_config_model(channel_cls)
    if model is None:
        return None

    # by_alias=False → property names match Python field names (snake_case),
    # which is exactly the shape we persist in ``config.yaml`` and what every
    # channel's ``__init__`` expects when ``model_validate(dict)`` is called.
    # The pydantic Base config has populate_by_name=True so the runtime still
    # accepts both forms; we standardise on snake_case for the wire schema.
    raw = model.model_json_schema(by_alias=False)
    flat = inline_refs(raw)
    secret_fields = collect_secret_fields(flat)

    try:
        default_config = model().model_dump(mode="json", by_alias=False)
    except Exception:
        default_config = {}

    return {
        "name": getattr(channel_cls, "name", channel_cls.__name__),
        "display_name": getattr(channel_cls, "display_name", channel_cls.__name__),
        "default_config": default_config,
        "secret_fields": secret_fields,
        "json_schema": flat,
    }


def all_channel_schemas() -> dict[str, dict[str, Any]]:
    """Build the schema dict for every discovered channel (built-in + plugins).

    Channels whose module failed to import (missing optional dependency)
    still appear, marked ``available: False`` with the import error — the UI
    shows them grayed out instead of silently dropping them.
    """
    from deeptutor.partners.channels.registry import discover_all_with_errors

    channels, errors = discover_all_with_errors()

    out: dict[str, dict[str, Any]] = {}
    for name, cls in channels.items():
        payload = channel_schema_payload(cls)
        if payload is not None:
            payload["available"] = True
            out[name] = payload
    for name, reason in errors.items():
        out[name] = {
            "name": name,
            "display_name": name.title(),
            "available": False,
            "unavailable_reason": reason,
            "default_config": {"enabled": False},
            "secret_fields": [],
            "json_schema": None,
        }
    return out
