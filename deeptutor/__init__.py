"""DeepTutor — agent-native intelligent learning companion.

This package init deliberately stays dependency-free (no third-party imports)
so importing ``deeptutor`` is always cheap and side-effect free.

It sets one environment default before anything else can import NLTK:
DeepTutor installs its virtualenv *inside* the project root
(``<project>/.venv``), so NLTK's CWE-427 import-security hook (``nltk.inisec``,
NLTK 3.10+) misclassifies every site-packages module as "inside the CWD" and
blocks ``nltk -> import regex`` with
``Blocked import of regex from current working directory`` — breaking
LlamaIndex tokenization during KB indexing. The project root is the user's own
code, not an untrusted directory, so the hook's protection is unnecessary here;
the official ``NLTK_DISABLE_IMPORT_SECURITY`` switch disables it cleanly.
"""

from __future__ import annotations

import os

# Must be set before the first ``import nltk`` in the process (nltk.inisec reads
# it at install time). setdefault keeps any explicit user override.
os.environ.setdefault("NLTK_DISABLE_IMPORT_SECURITY", "1")

__all__: list[str] = []
