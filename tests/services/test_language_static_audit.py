from __future__ import annotations

from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[2]


def test_agent_language_normalization_does_not_collapse_to_binary_en_zh() -> None:
    patterns = [
        re.compile(r'self\.language\s*=\s*"zh"\s+if\b.*?else\s+"en"', re.DOTALL),
        re.compile(r'return\s+"zh"\s+if\b.*?else\s+"en"', re.DOTALL),
    ]
    offenders: list[str] = []

    for path in (ROOT / "deeptutor" / "agents").rglob("*.py"):
        text = path.read_text(encoding="utf-8")
        if any(pattern.search(text) for pattern in patterns):
            offenders.append(str(path.relative_to(ROOT)))

    assert offenders == []
