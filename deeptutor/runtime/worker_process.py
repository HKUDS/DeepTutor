"""Private ``python -m`` entry point for isolated worker calls."""

from __future__ import annotations

import importlib
import os
from pathlib import Path
import pickle
import sys
import traceback
from typing import Any


def _resolve(callable_path: str):
    module_name, separator, attribute = callable_path.rpartition(":")
    if not separator or not module_name or not attribute:
        raise ValueError("callable_path must use 'package.module:callable' syntax")
    target = getattr(importlib.import_module(module_name), attribute)
    if not callable(target):
        raise TypeError(f"{callable_path!r} does not resolve to a callable")
    return target


def _execute(request: dict[str, Any]) -> dict[str, Any]:
    try:
        result = _resolve(str(request["callable_path"]))(
            *tuple(request.get("args") or ()),
            **dict(request.get("kwargs") or {}),
        )
        return {"ok": True, "result": result}
    except BaseException as exc:  # noqa: BLE001 - this is a process boundary
        attrs = {}
        filename = getattr(exc, "filename", None)
        if filename is not None:
            attrs["filename"] = str(filename)
        return {
            "ok": False,
            "message": str(exc),
            "module": type(exc).__module__,
            "type": type(exc).__name__,
            "traceback": traceback.format_exc(),
            "attrs": attrs,
        }


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    if len(args) != 2:
        return 2
    request_path = Path(args[0])
    result_path = Path(args[1])
    try:
        request = pickle.loads(request_path.read_bytes())  # noqa: S301 - parent-owned file
        envelope = _execute(request)
        staged = result_path.with_suffix(".tmp")
        staged.write_bytes(pickle.dumps(envelope, protocol=pickle.HIGHEST_PROTOCOL))
        os.replace(staged, result_path)
        return 0
    except BaseException:
        traceback.print_exc()
        return 1


if __name__ == "__main__":  # pragma: no cover - exercised through subprocess
    raise SystemExit(main())
