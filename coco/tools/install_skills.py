"""Install CoCo skills and personas into DeepTutor's admin workspace.

- ``coco/skills/<name>/SKILL.md``: DeepTutor reads user skills from the current
  content workspace (``data/user/workspaces/<id>/skills``); the id differs per
  installation, so ask DeepTutor for the folder instead of hard-coding it.
- ``coco/personas/<name>/PERSONA.md``: copied into the admin personas root;
  admin personas are a read-only overlay visible to every account.

Usage (from the DeepTutor-CoCo root, deeptutor conda env)::

    python -X utf8 coco/tools/install_skills.py
"""

from __future__ import annotations

import os
from pathlib import Path
import shutil
import sys

REPO_ROOT = Path(__file__).resolve().parents[2]
SOURCE = REPO_ROOT / "coco" / "skills"
PERSONA_SOURCE = REPO_ROOT / "coco" / "personas"


def target_root() -> Path:
    os.environ.setdefault("DEEPTUTOR_HOME", str(REPO_ROOT))
    from deeptutor.services.skill import get_skill_service

    return Path(get_skill_service().root)


def persona_root() -> Path:
    os.environ.setdefault("DEEPTUTOR_HOME", str(REPO_ROOT))
    from deeptutor.multi_user.paths import get_admin_path_service

    return get_admin_path_service().get_workspace_dir() / "personas"


def install(source: Path, target: Path, marker: str = "SKILL.md") -> list[str]:
    """Copy every ``<name>/<marker>`` package, replacing older copies."""
    installed = []
    for package in sorted(p for p in source.iterdir() if (p / marker).is_file()):
        dest = target / package.name
        if dest.exists():
            shutil.rmtree(dest)
        shutil.copytree(package, dest)
        installed.append(package.name)
    return installed


def _install_kind(source: Path, target: Path, marker: str, label: str) -> bool:
    if not source.is_dir():
        print(f"找不到{label}源目录：{source}", file=sys.stderr)
        return False
    target.mkdir(parents=True, exist_ok=True)
    names = install(source, target, marker)
    if not names:
        print(f"{source} 里没有{label}（<名称>/{marker}）", file=sys.stderr)
        return False
    print(f"已安装 {len(names)} 个{label}到 {target}：{', '.join(names)}")
    return True


def main() -> int:
    ok = _install_kind(SOURCE, target_root(), "SKILL.md", "技能")
    ok = _install_kind(PERSONA_SOURCE, persona_root(), "PERSONA.md", "人设") and ok
    return 0 if ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
