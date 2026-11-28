"""Install the CoCo skills (coco/skills/*) into DeepTutor's account skill folder.

DeepTutor reads user skills from the current content workspace
(``data/user/workspaces/<id>/skills``); the id differs per installation, so
ask DeepTutor for the folder instead of hard-coding it.

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


def target_root() -> Path:
    os.environ.setdefault("DEEPTUTOR_HOME", str(REPO_ROOT))
    from deeptutor.services.skill import get_skill_service

    return Path(get_skill_service().root)


def install(source: Path, target: Path) -> list[str]:
    """Copy every ``<name>/SKILL.md`` package, replacing older copies."""
    installed = []
    for skill_dir in sorted(p for p in source.iterdir() if (p / "SKILL.md").is_file()):
        dest = target / skill_dir.name
        if dest.exists():
            shutil.rmtree(dest)
        shutil.copytree(skill_dir, dest)
        installed.append(skill_dir.name)
    return installed


def main() -> int:
    if not SOURCE.is_dir():
        print(f"找不到技能源目录：{SOURCE}", file=sys.stderr)
        return 2
    target = target_root()
    target.mkdir(parents=True, exist_ok=True)
    names = install(SOURCE, target)
    if not names:
        print(f"{SOURCE} 里没有技能（<名称>/SKILL.md）", file=sys.stderr)
        return 2
    print(f"已安装 {len(names)} 个技能到 {target}：{', '.join(names)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
