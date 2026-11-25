"""Locale parity, screenshot hashes, channel-schema drift, and built-site link checks."""

from __future__ import annotations

import ast
import hashlib
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CONTENT = ROOT / "docs" / "src" / "content" / "docs"
PUBLIC = ROOT / "docs" / "public" / "screenshots" / "dev"
MANIFEST = ROOT / "assets" / "figs" / "web-dev" / "manifest.json"
DIST = ROOT / "docs" / "dist"
CHANNELS = ROOT / "deeptutor" / "partners" / "channels"
CHANNEL_SCHEMA = ROOT / "deeptutor" / "partners" / "config" / "schema.py"
HREF = re.compile(r"""(?:href|src)=["']([^"']+)["']""")
SKIP_CHANNEL_MODULES = {"base", "manager", "registry", "weixin_qr", "lark_http"}
SHARED_SWITCHES = {"enabled", "send_progress", "send_tool_hints", "streaming", "allow_from"}


def pages(base: Path) -> set[str]:
    found = set()
    for pattern in ("*.md", "*.mdx"):
        for path in base.rglob(pattern):
            rel = path.relative_to(base).as_posix()
            if rel.startswith("zh-cn/"):
                continue
            found.add(rel)
    return found


def check_parity() -> list[str]:
    errors = []
    en = pages(CONTENT)
    zh = pages(CONTENT / "zh-cn")
    if en - zh:
        errors.append("only English: " + ", ".join(sorted(en - zh)))
    if zh - en:
        errors.append("only Chinese: " + ", ".join(sorted(zh - en)))
    for path in list(CONTENT.rglob("*.md")) + list(CONTENT.rglob("*.mdx")):
        rel = path.relative_to(CONTENT).as_posix()
        if rel in {"index.mdx", "zh-cn/index.mdx"}:
            continue
        text = path.read_text()
        if not text.startswith("---"):
            errors.append(f"{rel} is missing frontmatter")
            continue
        block = text.split("---", 2)[1]
        if "quadrant:" not in block and "template: splash" not in block:
            errors.append(f"{rel} is missing quadrant")
    return errors


def check_screenshots() -> list[str]:
    errors = []
    manifest = json.loads(MANIFEST.read_text())
    for row in manifest["files"]:
        name = row["file"]
        copy = PUBLIC / name
        if not copy.exists():
            continue
        digest = hashlib.sha256(copy.read_bytes()).hexdigest()
        if digest != row["sha256"]:
            errors.append(f"{name} sha256 {digest} != manifest {row['sha256']}")
    referenced = set()
    for path in CONTENT.rglob("*"):
        if path.suffix not in {".md", ".mdx"}:
            continue
        text = re.sub(r"<!--.*?-->", "", path.read_text(), flags=re.DOTALL)
        referenced.update(re.findall(r"/screenshots/dev/([A-Za-z0-9_.-]+)", text))
    for name in sorted(referenced):
        if not (PUBLIC / name).exists():
            errors.append(f"missing screenshot {name}")
    return errors


def dest_exists(url: str) -> bool:
    path = url.split("#", 1)[0].split("?", 1)[0]
    if path in {"", "/"}:
        return (DIST / "index.html").exists()
    relative = path.lstrip("/")
    candidates = [
        DIST / relative,
        DIST / relative / "index.html",
        DIST / f"{relative}.html",
    ]
    return any(item.exists() for item in candidates)


def _class_fields(node: ast.ClassDef) -> list[str]:
    fields = []
    for stmt in node.body:
        if isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name):
            name = stmt.target.id
            if not name.startswith("_"):
                fields.append(name)
    return fields


def _class_index(paths: list[Path]) -> dict[str, tuple[list[str], list[str]]]:
    index: dict[str, tuple[list[str], list[str]]] = {}
    for path in paths:
        tree = ast.parse(path.read_text())
        for node in tree.body:
            if not isinstance(node, ast.ClassDef):
                continue
            bases = []
            for base in node.bases:
                if isinstance(base, ast.Name):
                    bases.append(base.id)
                elif isinstance(base, ast.Attribute):
                    bases.append(base.attr)
            index[node.name] = (bases, _class_fields(node))
    return index


def _resolved_fields(index: dict[str, tuple[list[str], list[str]]], name: str, seen: set[str] | None = None) -> list[str]:
    seen = seen or set()
    if name in seen or name not in index:
        return []
    seen.add(name)
    bases, fields = index[name]
    resolved: list[str] = []
    for base in bases:
        resolved.extend(_resolved_fields(index, base, seen))
    resolved.extend(fields)
    return resolved


def _channel_configs() -> dict[str, list[str]]:
    index = _class_index([CHANNEL_SCHEMA, *sorted(CHANNELS.glob("*.py"))])
    configs: dict[str, list[str]] = {}
    for path in sorted(CHANNELS.glob("*.py")):
        if path.stem in SKIP_CHANNEL_MODULES:
            continue
        tree = ast.parse(path.read_text())
        for node in tree.body:
            if not isinstance(node, ast.ClassDef) or not node.name.endswith("Channel"):
                continue
            key = None
            for stmt in node.body:
                if (
                    isinstance(stmt, ast.Assign)
                    and any(isinstance(target, ast.Name) and target.id == "name" for target in stmt.targets)
                    and isinstance(stmt.value, ast.Constant)
                    and isinstance(stmt.value.value, str)
                ):
                    key = stmt.value.value
            if not key:
                continue
            config_name = node.name.replace("Channel", "Config")
            fields = _resolved_fields(index, config_name)
            if fields:
                configs[key] = list(dict.fromkeys(fields))
    return configs


def _mentioned_fields(text: str) -> set[str]:
    names = set(re.findall(r"`([a-z][a-z0-9_]*)`", text))
    for label in re.findall(r"\*\*([^*]+)\*\*", text):
        slug = re.sub(r"[^a-z0-9_]", "", label.strip().lower().replace(" ", "_").replace("-", "_"))
        if slug:
            names.add(slug)
    return names


def _schema_sections(text: str) -> tuple[str, dict[str, str]]:
    parts = re.split(r'<a id="([^"]+)"></a>', text)
    sections: dict[str, str] = {}
    iterator = iter(parts[1:])
    for key, body in zip(iterator, iterator):
        sections[key] = body
    shared = ""
    match = re.search(r"## (?:Shared delivery switches|共享投递开关)(.*?)(?:\n## |\Z)", parts[0], re.S)
    if match:
        shared = match.group(1)
    return shared, sections


def check_channel_schema() -> list[str]:
    """The hand-written channel pages must name every config field the source declares."""
    errors = []
    configs = _channel_configs()
    if not configs:
        return ["channel schema source produced no configs"]
    pages = {
        "en": CONTENT / "channels" / "schema.md",
        "zh": CONTENT / "zh-cn" / "channels" / "schema.md",
    }
    for locale, path in pages.items():
        text = path.read_text()
        shared, sections = _schema_sections(text)
        shared_names = _mentioned_fields(shared)
        for key, fields in sorted(configs.items()):
            if f"`{key}`" not in text:
                errors.append(f"{locale} channel matrix is missing `{key}`")
            section = sections.get(key, "")
            if not section:
                errors.append(f"{locale} channel schema is missing the {key} field section")
                continue
            mentioned = _mentioned_fields(section) | (shared_names & SHARED_SWITCHES)
            missing = [field for field in fields if field not in mentioned]
            if missing:
                errors.append(f"{locale} {key} docs omit {', '.join(missing)}")
    return errors


def check_links() -> list[str]:
    if not DIST.exists():
        return ["docs/dist is missing; run the docs build first"]
    errors = []
    for page in DIST.rglob("*.html"):
        for match in HREF.findall(page.read_text(errors="ignore")):
            if match.startswith(("http://", "https://", "mailto:", "data:", "#", "javascript:")):
                continue
            if not match.startswith("/"):
                continue
            if not dest_exists(match):
                errors.append(f"{page.relative_to(DIST)} -> {match}")
    return errors


def main() -> int:
    mode = sys.argv[1] if len(sys.argv) > 1 else "source"
    errors = check_parity() + check_screenshots() + check_channel_schema()
    if mode == "dist":
        errors.extend(check_links())
    if errors:
        print("\n".join(errors))
        return 1
    print("docs checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
