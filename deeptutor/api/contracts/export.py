"""Deterministically export backend-owned browser contracts."""

from __future__ import annotations

import argparse
from copy import deepcopy
import json
from pathlib import Path
from typing import Any

from pydantic import BaseModel

from deeptutor.app.contracts import TurnRequest

from .turn_protocol import (
    ErrorEnvelope,
    RuntimeStatus,
    SessionDetail,
    SessionSummary,
    TurnProtocolDocument,
)

PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_OUTPUT_DIR = PROJECT_ROOT / "web" / "contracts" / "schema"
HTTP_METHODS = {"delete", "get", "head", "options", "patch", "post", "put", "trace"}


def _json_text(payload: dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def _merge_model_schema(components: dict[str, Any], model: type[BaseModel]) -> None:
    schema = model.model_json_schema(ref_template="#/components/schemas/{model}")
    definitions = schema.pop("$defs", {})
    components.update(definitions)
    components[model.__name__] = schema


def _assert_unique_operation_ids(openapi: dict[str, Any]) -> None:
    """Reject router defects instead of hiding them in generated artifacts."""

    seen: dict[str, tuple[str, str]] = {}
    duplicates: list[str] = []
    for path, path_item in openapi.get("paths", {}).items():
        for method, operation in path_item.items():
            if method not in HTTP_METHODS or not isinstance(operation, dict):
                continue
            operation_id = operation.get("operationId")
            if not operation_id:
                continue
            previous = seen.get(operation_id)
            if previous is None:
                seen[operation_id] = (path, method)
                continue
            duplicates.append(
                f"{operation_id}: {previous[1].upper()} {previous[0]} and {method.upper()} {path}"
            )
    if duplicates:
        raise RuntimeError("Duplicate OpenAPI operation IDs:\n" + "\n".join(duplicates))


def render_contracts() -> dict[str, str]:
    from deeptutor.api.main import app

    openapi = deepcopy(app.openapi())
    _assert_unique_operation_ids(openapi)
    schemas = openapi.setdefault("components", {}).setdefault("schemas", {})
    for model in (TurnRequest, RuntimeStatus, SessionSummary, SessionDetail, ErrorEnvelope):
        _merge_model_schema(schemas, model)
    openapi["x-deeptutor-web-protocol-version"] = "2.0"

    protocol = TurnProtocolDocument.model_json_schema()
    return {
        "openapi.json": _json_text(openapi),
        "turn-protocol.json": _json_text(protocol),
    }


def write_contracts(output_dir: Path, *, check: bool = False) -> list[str]:
    rendered = render_contracts()
    changed: list[str] = []
    for filename, content in rendered.items():
        target = output_dir / filename
        current = target.read_text(encoding="utf-8") if target.exists() else None
        if current == content:
            continue
        changed.append(filename)
        if not check:
            output_dir.mkdir(parents=True, exist_ok=True)
            target.write_text(content, encoding="utf-8")
    return changed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="fail when artifacts drift")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    args = parser.parse_args(argv)

    changed = write_contracts(args.output_dir, check=args.check)
    if args.check and changed:
        print("Frontend contract drift: " + ", ".join(changed))
        return 1
    if changed:
        print("Updated frontend contracts: " + ", ".join(changed))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
