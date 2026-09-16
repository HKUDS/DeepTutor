"""Scoped compatibility for stale Pandas/Arrow extension registrations."""

from __future__ import annotations

import importlib
import threading
from typing import Any

_PANDAS_ARROW_EXTENSION_MODULE = "pandas.core.arrays.arrow.extension_types"
_PANDAS_ARROW_EXTENSION_NAMES = ("pandas.period", "pandas.interval")
_extension_registration_lock = threading.Lock()


def _is_duplicate_registration_error(error: BaseException) -> bool:
    message = str(error)
    return (
        "A type extension with name" in message
        and "already defined" in message
        and any(name in message for name in _PANDAS_ARROW_EXTENSION_NAMES)
    )


def _unregister_stale_extension_types(
    pyarrow: Any,
    arrow_key_error: type[BaseException],
) -> None:
    for name in _PANDAS_ARROW_EXTENSION_NAMES:
        try:
            pyarrow.unregister_extension_type(name)
        except arrow_key_error:
            # The extension may not have been registered yet.
            continue


def prepare_pandas_arrow_extensions() -> None:
    """Import Pandas Arrow extensions, repairing stale registry entries.

    Pandas registers ``pandas.period`` and ``pandas.interval`` as a module import
    side effect. If a test runner, plugin, or reload hook removes that module from
    ``sys.modules`` without unregistering the pyarrow types, importing it again
    raises ``pyarrow.lib.ArrowKeyError``. GraphRAG runs in isolated worker threads,
    so this repair is performed immediately inside each worker before GraphRAG
    imports its pandas users.

    The helper is a no-op when pyarrow is not installed. Other import or registry
    errors are allowed to propagate so a real dependency failure is not hidden.
    """
    try:
        import pyarrow
        from pyarrow.lib import ArrowKeyError
    except ImportError:
        return

    with _extension_registration_lock:
        try:
            importlib.import_module(_PANDAS_ARROW_EXTENSION_MODULE)
        except ModuleNotFoundError as error:
            if error.name == "pandas":
                return
            raise
        except ArrowKeyError as error:
            if not _is_duplicate_registration_error(error):
                raise
            _unregister_stale_extension_types(pyarrow, ArrowKeyError)
            importlib.import_module(_PANDAS_ARROW_EXTENSION_MODULE)


__all__ = ["prepare_pandas_arrow_extensions"]
