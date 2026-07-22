"""Guards against StatusI18n status-message drift for the visualize capability.

A capability that calls ``i18n.t("some_key", "default", ...)`` must have
``some_key`` defined in ``agents/<module>/prompts/{en,zh}/<capability>.yaml``
under the ``status:`` section. If it isn't, ``StatusI18n.t`` silently falls back to the
English ``default`` — so non-English users see English status text while the
code looks fine. This drift actually happened during the visualize Stage-3
rewrite (the yaml lagged the code: missing keys + orphan keys); these tests keep
it from recurring.

Scoped to ``visualize`` for now; the three checks are written generically and
can be parametrized over more capabilities once their yamls use the same
``status:`` layout.
"""

from __future__ import annotations

from pathlib import Path
import re

import yaml

_REPO = Path(__file__).resolve().parents[2]
_PROMPTS = _REPO / "deeptutor" / "agents" / "visualize" / "prompts"
_CODE = _REPO / "deeptutor" / "agents" / "visualize" / "capability.py"


def _status_keys(lang: str) -> set[str]:
    data = yaml.safe_load((_PROMPTS / lang / "visualize.yaml").read_text()) or {}
    status = data.get("status") if isinstance(data, dict) else None
    return set((status or {}).keys())


def _code() -> str:
    return _CODE.read_text()


def test_en_zh_status_parity() -> None:
    """en and zh must define the exact same set of status keys."""
    en, zh = _status_keys("en"), _status_keys("zh")
    assert en == zh, f"en/zh status keys differ: en-only={en - zh} zh-only={zh - en}"


def test_code_i18n_keys_exist_in_yaml() -> None:
    """Every literal i18n.t("key", ...) used in code must exist in the yaml,
    otherwise zh users silently get the English default."""
    used = set(re.findall(r'i18n\.t\(\s*"([^"]+)"', _code()))
    yaml_keys = _status_keys("en")
    missing = used - yaml_keys
    assert not missing, (
        "i18n keys used in visualize.py but missing from visualize.yaml "
        f"(zh falls back to English): {sorted(missing)}"
    )


def test_no_orphan_yaml_keys() -> None:
    """Every yaml status key must be referenced as a string literal somewhere in
    the module. Tolerates dynamic dispatch (e.g.
    ``artifact_key = "manim_artifacts_one" if ... else "manim_artifacts_many"``)
    while still catching dead copy left behind by deleted code paths."""
    code = _code()
    orphans = {k for k in _status_keys("en") if f'"{k}"' not in code}
    assert not orphans, (
        f"yaml status keys never referenced in visualize.py (dead copy): {sorted(orphans)}"
    )
