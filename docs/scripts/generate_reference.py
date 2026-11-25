"""Regenerate public reference pages from module manifests and the router index.

Run from the repository root:

    python3 docs/scripts/generate_reference.py
"""

from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
MANIFESTS = ROOT / "deeptutor" / "modules" / "manifests"
ROUTER_INDEX = ROOT / "deeptutor" / "api" / "router_index.json"
DOCS = ROOT / "docs" / "src" / "content" / "docs"
MARKER = "<!-- generated-route-index -->"

EXTRA_MOUNTS = {
    "deeptutor.api.routers.modules:router": {
        "prefix": "/api/modules",
        "auth": "authenticated",
        "module": "server",
    }
}


def load_mounts() -> dict[str, dict]:
    mounts = dict(EXTRA_MOUNTS)
    for path in sorted(MANIFESTS.glob("*.json")):
        data = json.loads(path.read_text())
        for route in data.get("routes", []):
            options = route.get("options") or {}
            mounts[route["reference"]] = {
                "prefix": options.get("prefix") or "",
                "auth": route.get("auth") or "",
                "module": data["id"],
            }
    return mounts


def route_index(locale: str) -> str:
    index = json.loads(ROUTER_INDEX.read_text())
    mounts = load_mounts()
    groups: list[tuple[str, str, str, list[dict]]] = []
    missing = []
    for reference, patterns in index["routers"].items():
        mount = mounts.get(reference)
        if mount is None:
            missing.append(reference)
            continue
        groups.append((mount["module"], mount["prefix"], mount["auth"], reference, patterns))
    groups.sort(key=lambda row: (row[0], row[1], row[3]))

    if locale == "zh":
        intro = (
            "## 路由索引\n\n"
            "下面的表由 `deeptutor/modules/manifests/*.json` 与 "
            "`deeptutor/api/router_index.json` 生成。路径是挂载前缀加上路由模板。"
            "字段和请求体以运行中的 `GET /openapi.json` 为准。\n"
        )
        columns = "| 方法 | 路径 |\n| --- | --- |"
        missing_label = "索引里有、清单未挂载"
    else:
        intro = (
            "## Route index\n\n"
            "Generated from `deeptutor/modules/manifests/*.json` and "
            "`deeptutor/api/router_index.json`. Each path is the mount prefix plus the route template. "
            "Request and response fields stay in the live `GET /openapi.json`.\n"
        )
        columns = "| Method | Path |\n| --- | --- |"
        missing_label = "Indexed but not mounted by a manifest"

    lines = [MARKER, "", intro]
    current = None
    for module, prefix, auth, reference, patterns in groups:
        if module != current:
            current = module
            lines.append(f"### {module}\n")
        short = reference.rsplit(".", 1)[-1]
        lines.append(f"#### `{short}` — `{prefix or '/'}` · {auth}\n")
        lines.append(columns)
        for pattern in patterns:
            methods = ", ".join(pattern["methods"]) or "WS"
            path = f"{prefix}{pattern['path']}"
            lines.append(f"| `{methods}` | `{path}` |")
        lines.append("")
    if missing:
        lines.append(f"### {missing_label}\n")
        for reference in missing:
            lines.append(f"- `{reference}`")
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def capabilities(locale: str) -> str:
    rows = []
    for path in sorted(MANIFESTS.glob("*.json")):
        data = json.loads(path.read_text())
        for name, spec in (data.get("capabilities") or {}).items():
            manifest = spec.get("manifest") or {}
            stages = ", ".join(f"`{stage}`" for stage in manifest.get("stages") or [])
            aliases = ", ".join(f"`{alias}`" for alias in manifest.get("cli_aliases") or []) or "—"
            description = (manifest.get("description") or "").replace("|", "\\|")
            rows.append((spec.get("order", 0), data["id"], name, stages, aliases, description))
    rows.sort(key=lambda row: (row[1], row[0], row[2]))
    if locale == "zh":
        head = """---
title: 能力
description: 已注册能力的名称、阶段、所属模块和 CLI 别名。
quadrant: reference
---

名称、阶段和 CLI 别名来自 `deeptutor/modules/manifests/*.json` 里每个能力的 `manifest`。描述保持清单中的英文原文。

| 能力 | 模块 | 阶段 | CLI | 说明 |
| --- | --- | --- | --- | --- |
"""
    else:
        head = """---
title: Capabilities
description: Registered capability names, stages, owning modules, and CLI aliases.
quadrant: reference
---

Names, stages, and CLI aliases come from each capability `manifest` in `deeptutor/modules/manifests/*.json`.

| Capability | Module | Stages | CLI | Description |
| --- | --- | --- | --- | --- |
"""
    body = "\n".join(
        f"| `{name}` | `{module}` | {stages or '—'} | {aliases} | {description} |"
        for _, module, name, stages, aliases, description in rows
    )
    return head + body + "\n"


def write_capabilities() -> None:
    for locale, folder in (("en", DOCS), ("zh", DOCS / "zh-cn")):
        target = folder / "developers" / "reference" / "capabilities.md"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(capabilities(locale))


def append_routes() -> None:
    for locale, folder in (("en", DOCS), ("zh", DOCS / "zh-cn")):
        target = folder / "developers" / "reference" / "http-api.md"
        text = target.read_text()
        if MARKER in text:
            text = text.split(MARKER, 1)[0].rstrip() + "\n\n"
        else:
            text = text.rstrip() + "\n\n"
        target.write_text(text + route_index(locale))


def main() -> None:
    write_capabilities()
    append_routes()


if __name__ == "__main__":
    main()
