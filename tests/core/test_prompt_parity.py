from __future__ import annotations

from pathlib import Path
import re
from typing import Any, Iterable

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[2]
AGENTS_DIR = PROJECT_ROOT / "src" / "agents"

# Template placeholders are expected to be like {topic}, {knowledge_title}, etc.
# Avoid false positives from LaTeX (\frac{1}{3}) and Mermaid (B{{Processing}}).
PLACEHOLDER_RE = re.compile(r"(?<!\{)\{[A-Za-z_][A-Za-z0-9_]*\}(?!\})")


def _load_yaml(path: Path) -> Any:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f) or {}


def _iter_yaml_files(root: Path) -> Iterable[Path]:
    if not root.exists():
        return []
    return sorted([p for p in root.rglob("*.yaml") if p.is_file()])


def _get_placeholders(value: Any) -> set[str]:
    found: set[str] = set()
    if isinstance(value, str):
        found |= set(PLACEHOLDER_RE.findall(value))
    elif isinstance(value, dict):
        for v in value.values():
            found |= _get_placeholders(v)
    elif isinstance(value, list):
        for v in value:
            found |= _get_placeholders(v)
    return found


def _collect_keys(value: Any, prefix: str = "") -> set[str]:
    keys: set[str] = set()
    if isinstance(value, dict):
        for k, v in value.items():
            path = f"{prefix}.{k}" if prefix else str(k)
            keys.add(path)
            keys |= _collect_keys(v, path)
    elif isinstance(value, list):
        if prefix:
            keys.add(prefix)
    else:
        if prefix:
            keys.add(prefix)
    return keys


def test_prompts_key_and_placeholder_parity():
    assert AGENTS_DIR.exists(), f"Agents dir not found: {AGENTS_DIR}"

    failures: list[str] = []

    for module_dir in sorted([p for p in AGENTS_DIR.iterdir() if p.is_dir()]):
        prompts_dir = module_dir / "prompts"
        en_dir = prompts_dir / "en"
        if not en_dir.exists():
            continue

        zh_dir = prompts_dir / "zh"
        cn_dir = prompts_dir / "cn"

        for en_file in _iter_yaml_files(en_dir):
            rel = en_file.relative_to(en_dir)
            en_obj = _load_yaml(en_file)

            candidates: list[tuple[str, Path]] = []
            if zh_dir.exists():
                candidates.append(("zh", zh_dir / rel))
            if cn_dir.exists():
                candidates.append(("cn", cn_dir / rel))

            if not candidates:
                continue

            for lang_name, target_file in candidates:
                if not target_file.exists():
                    failures.append(f"[MISSING {lang_name}] {module_dir.name}: {rel.as_posix()}")
                    continue

                target_obj = _load_yaml(target_file)
                en_keys = _collect_keys(en_obj)
                target_keys = _collect_keys(target_obj)

                missing = sorted(en_keys - target_keys)
                extra = sorted(target_keys - en_keys)

                en_ph = _get_placeholders(en_obj)
                target_ph = _get_placeholders(target_obj)
                ph_missing = sorted(en_ph - target_ph)
                ph_extra = sorted(target_ph - en_ph)

                if missing or extra or ph_missing or ph_extra:
                    msg = [f"[DIFF {lang_name}] {module_dir.name}: {rel.as_posix()}"]
                    if missing:
                        msg.append("  missing keys: " + ", ".join(missing[:50]))
                    if extra:
                        msg.append("  extra keys: " + ", ".join(extra[:50]))
                    if ph_missing:
                        msg.append("  missing placeholders: " + ", ".join(ph_missing))
                    if ph_extra:
                        msg.append("  extra placeholders: " + ", ".join(ph_extra))
                    failures.append("\n".join(msg))

    assert not failures, "Prompt parity failures:\n" + "\n\n".join(failures)
