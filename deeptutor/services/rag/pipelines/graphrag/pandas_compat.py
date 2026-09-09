"""Pandas type extension compatibility guard for GraphRAG indexing.

This module provides a protection mechanism against the "pandas.period already defined"
error that occurs in Windows multiprocessing environments when GraphRAG's concurrent
workflows attempt to register pandas extension types multiple times.

The issue primarily affects Windows systems where multiprocessing uses 'spawn' mode
(each subprocess re-imports all modules) rather than 'fork' mode on Unix systems.
"""

from __future__ import annotations

import os
import sys
import threading
import warnings
from typing import Any

# Global lock to prevent concurrent pandas extension registration
_pandas_init_lock = threading.Lock()
_pandas_initialized = False


def suppress_pandas_extension_warnings() -> None:
    """Suppress pandas extension type registration warnings.

    This prevents duplicate extension type warnings from appearing in logs when
    GraphRAG's concurrent workflows import pandas multiple times in different
    processes or threads.
    """
    warnings.filterwarnings(
        "ignore",
        message=".*already defined.*",
        category=UserWarning,
        module="pandas",
    )
    warnings.filterwarnings(
        "ignore",
        message=".*type extension.*already.*",
        category=RuntimeWarning,
    )


def configure_pandas_for_graphrag() -> None:
    """Configure pandas environment to prevent extension type conflicts in GraphRAG.

    This function should be called before any GraphRAG indexing operation that
    involves pandas DataFrame operations. It:

    1. Suppresses extension type registration warnings
    2. Sets environment variables to limit parallelism that can trigger conflicts
    3. Ensures pandas is imported in a controlled manner

    Thread-safe: multiple concurrent calls are protected by a lock.
    """
    global _pandas_initialized

    with _pandas_init_lock:
        if _pandas_initialized:
            return

        # Suppress warnings first
        suppress_pandas_extension_warnings()

        # Limit threading in numeric libraries to reduce concurrent pandas operations
        # that can trigger extension type conflicts
        os.environ.setdefault("NUMEXPR_MAX_THREADS", "1")
        os.environ.setdefault("OMP_NUM_THREADS", "1")
        os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")
        os.environ.setdefault("MKL_NUM_THREADS", "1")

        # Pre-import pandas in the main thread to ensure extension types are
        # registered before any subprocess spawning
        try:
            import pandas as pd

            # Force pandas to register its extension types early
            _ = pd.DataFrame({"_init": [1]})

            # Pre-import common pandas extension modules that GraphRAG uses
            from pandas.core.arrays import PeriodArray  # noqa: F401

        except ImportError:
            # pandas not installed - GraphRAG checks will handle this
            pass
        except Exception:
            # Silently ignore registration errors - they're often benign
            # The actual GraphRAG operation will surface real problems
            pass

        _pandas_initialized = True


def wrap_graphrag_operation(func: Any) -> Any:
    """Decorator to wrap GraphRAG operations with pandas compatibility guards.

    Usage:
        @wrap_graphrag_operation
        async def build_index(...):
            ...
    """
    import functools

    @functools.wraps(func)
    async def wrapper(*args: Any, **kwargs: Any) -> Any:
        configure_pandas_for_graphrag()
        return await func(*args, **kwargs)

    return wrapper


__all__ = [
    "configure_pandas_for_graphrag",
    "suppress_pandas_extension_warnings",
    "wrap_graphrag_operation",
]
