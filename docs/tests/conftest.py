"""Make ``doc_facts`` importable and keep the checks dependency-free.

These tests parse the repository rather than importing DeepTutor, so they need
no runtime dependencies — only the standard library and pytest. Running from
``docs/`` keeps them outside ``tests/conftest.py``, whose autouse fixtures build
the application container and would require the full dependency set.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
