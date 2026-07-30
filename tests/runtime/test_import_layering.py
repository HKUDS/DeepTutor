"""The provider/registry layering must not become mutually dependent.

``deferred_tools`` (registry layer) sanitises provider text through
``providers.text``, so the provider *primitives* sit below the registry.
``providers.view`` composes the registry, so it sits above. Re-exporting
``view`` from ``providers/__init__`` puts the registry back into the package's
own import path: the cycle then resolves only when something else happens to
import ``providers`` first, which makes the suite pass or fail on test order
rather than on correctness.

A fresh interpreter is the only way to assert this — within one process the
first import wins and caches, hiding the cycle.
"""

from __future__ import annotations

import subprocess
import sys

# Importing this module first is the worst case: it pulls in providers.text,
# which triggers the provider package's own initialisation.
_CANARY = "deeptutor.runtime.registry.deferred_tools"


def test_registry_imports_without_a_provider_cycle() -> None:
    proc = subprocess.run(
        [sys.executable, "-c", f"import {_CANARY}"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, (
        f"{_CANARY} cannot be imported on its own — the provider layering has a "
        f"cycle:\n{proc.stderr}"
    )
