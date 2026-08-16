from __future__ import annotations

from pathlib import Path
import re
from typing import Any, Iterable

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEEPTUTOR_DIR = PROJECT_ROOT / "deeptutor"

# Template placeholders are expected to be like {topic}, {knowledge_title}, etc.
# Avoid false positives from LaTeX (\frac{1}{3}) and Mermaid (B{{Processing}}).
PLACEHOLDER_RE = re.compile(r"(?<!\{)\{[A-Za-z_][A-Za-z0-9_]*\}(?!\})")


def _load_yaml(path: Path) -> Any:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _iter_english_prompt_files() -> Iterable[Path]:
    nested = DEEPTUTOR_DIR.rglob("en/*.yaml")
    flat = DEEPTUTOR_DIR.rglob("en.yaml")
    return sorted(set(nested) | set(flat))


def _get_placeholders(value: Any) -> set[str]:
    found: set[str] = set()
    if isinstance(value, str):
        found |= set(PLACEHOLDER_RE.findall(value))
    elif isinstance(value, dict):
        for child in value.values():
            found |= _get_placeholders(child)
    elif isinstance(value, list):
        for child in value:
            found |= _get_placeholders(child)
    return found


def _collect_keys(value: Any, prefix: str = "") -> set[str]:
    keys: set[str] = set()
    if isinstance(value, dict):
        for key, child in value.items():
            path = f"{prefix}.{key}" if prefix else str(key)
            keys.add(path)
            keys |= _collect_keys(child, path)
    elif prefix:
        keys.add(prefix)
    return keys


def test_prompts_key_and_placeholder_parity():
    assert DEEPTUTOR_DIR.exists(), f"DeepTutor dir not found: {DEEPTUTOR_DIR}"

    failures: list[str] = []
    english_files = list(_iter_english_prompt_files())
    assert len(english_files) >= 61

    for en_file in english_files:
        zh_file = (
            en_file.parent.parent / "zh" / en_file.name
            if en_file.parent.name == "en"
            else en_file.parent / "zh.yaml"
        )
        display = en_file.relative_to(DEEPTUTOR_DIR).as_posix()
        if not zh_file.exists():
            failures.append(f"[MISSING zh] {display}")
            continue

        en_obj = _load_yaml(en_file)
        zh_obj = _load_yaml(zh_file)
        en_keys = _collect_keys(en_obj)
        zh_keys = _collect_keys(zh_obj)
        en_placeholders = _get_placeholders(en_obj)
        zh_placeholders = _get_placeholders(zh_obj)

        missing_keys = sorted(en_keys - zh_keys)
        extra_keys = sorted(zh_keys - en_keys)
        missing_placeholders = sorted(en_placeholders - zh_placeholders)
        extra_placeholders = sorted(zh_placeholders - en_placeholders)

        if missing_keys or extra_keys or missing_placeholders or extra_placeholders:
            message = [f"[DIFF zh] {display}"]
            if missing_keys:
                message.append("  missing keys: " + ", ".join(missing_keys[:50]))
            if extra_keys:
                message.append("  extra keys: " + ", ".join(extra_keys[:50]))
            if missing_placeholders:
                message.append("  missing placeholders: " + ", ".join(missing_placeholders))
            if extra_placeholders:
                message.append("  extra placeholders: " + ", ".join(extra_placeholders))
            failures.append("\n".join(message))

    assert not failures, "Prompt parity failures:\n" + "\n\n".join(failures)
