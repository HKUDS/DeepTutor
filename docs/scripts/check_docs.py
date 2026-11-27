"""Locale parity, screenshot hashes, channel-schema drift, and built-site link checks."""

from __future__ import annotations

import ast
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]
CONTENT = ROOT / "docs" / "src" / "content" / "docs"
PUBLIC = ROOT / "docs" / "public" / "screenshots" / "dev"
GIFS = ROOT / "docs" / "public" / "gifs"
MANIFEST = ROOT / "assets" / "figs" / "web-dev" / "manifest.json"
DIST = ROOT / "docs" / "dist"
CHANNELS = ROOT / "deeptutor" / "partners" / "channels"
CHANNEL_SCHEMA = ROOT / "deeptutor" / "partners" / "config" / "schema.py"
HREF = re.compile(r"""(?:href|src)=["']([^"']+)["']""")
SKIP_CHANNEL_MODULES = {"base", "manager", "registry", "weixin_qr", "lark_http"}
SHARED_SWITCHES = {"enabled", "send_progress", "send_tool_hints", "streaming", "allow_from"}


def check_locale_paths(paths: set[str]) -> list[str]:
    if not paths:
        return ["no pages found in docs/src/content/docs"]
    errors = []
    en = {path for path in paths if not path.startswith("zh-cn/")}
    zh = {path.removeprefix("zh-cn/") for path in paths - en}
    if en - zh:
        errors.append("only English: " + ", ".join(sorted(en - zh)))
    if zh - en:
        errors.append("only Chinese: " + ", ".join(sorted(zh - en)))
    return errors


def check_staged_parity() -> list[str]:
    # An untracked translation will not land in the commit.
    content = CONTENT.relative_to(ROOT).as_posix()
    indexed = subprocess.check_output(
        ["git", "ls-files", "-z", "--", content], cwd=ROOT, encoding="utf-8"
    )
    paths = {
        path.removeprefix(f"{content}/")
        for path in indexed.split("\0")
        if path.endswith((".md", ".mdx"))
    }
    return check_locale_paths(paths)


def check_parity() -> list[str]:
    paths = list(CONTENT.rglob("*.md")) + list(CONTENT.rglob("*.mdx"))
    errors = check_locale_paths({path.relative_to(CONTENT).as_posix() for path in paths})
    for path in paths:
        rel = path.relative_to(CONTENT).as_posix()
        if rel in {"index.mdx", "zh-cn/index.mdx"}:
            continue
        text = path.read_text(encoding="utf-8")
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


def check_gifs() -> list[str]:
    errors = []
    by_page: dict[str, set[str]] = {}
    missing = set()
    for path in list(CONTENT.rglob("*.md")) + list(CONTENT.rglob("*.mdx")):
        text = re.sub(r"<!--.*?-->", "", path.read_text(), flags=re.DOTALL)
        names = set(re.findall(r"/gifs/([A-Za-z0-9_.-]+)", text))
        rel = path.relative_to(CONTENT).as_posix()
        by_page[rel] = names
        for name in names:
            if not (GIFS / name).exists():
                missing.add(name)
    for name in sorted(missing):
        errors.append(f"missing gif {name}")
    for rel, names in sorted(by_page.items()):
        if rel.startswith("zh-cn/"):
            continue
        zh_rel = f"zh-cn/{rel}"
        zh_names = by_page.get(zh_rel, set())
        if names != zh_names:
            errors.append(f"{rel} gif refs {sorted(names)} != {zh_rel} {sorted(zh_names)}")
    return errors


def _normalized_base() -> str:
    raw = os.environ.get("DOCS_BASE", "/").strip()
    if raw in {"", "/"}:
        return ""
    return "/" + raw.strip("/")


def dest_exists(url: str, base: str = "") -> bool:
    path = url.split("#", 1)[0].split("?", 1)[0]
    if base:
        if path == base:
            path = "/"
        elif path.startswith(f"{base}/"):
            path = path[len(base) :]
        else:
            return False
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


def _resolved_fields(
    index: dict[str, tuple[list[str], list[str]]], name: str, seen: set[str] | None = None
) -> list[str]:
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
                    and any(
                        isinstance(target, ast.Name) and target.id == "name"
                        for target in stmt.targets
                    )
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
    match = re.search(
        r"## (?:Shared delivery switches|共享投递开关)(.*?)(?:\n## |\Z)", parts[0], re.S
    )
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


def check_generated_reference() -> list[str]:
    """Ensure generated capabilities and HTTP route index pages match source manifests."""
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "generate_reference", Path(__file__).resolve().with_name("generate_reference.py")
    )
    if spec is None or spec.loader is None:
        return ["unable to load generate_reference.py"]
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    errors = []
    for locale, folder in (("en", CONTENT), ("zh", CONTENT / "zh-cn")):
        cap_path = folder / "developers" / "reference" / "capabilities.md"
        expected_cap = mod.capabilities(locale)
        if not cap_path.exists() or cap_path.read_text() != expected_cap:
            errors.append(
                f"{cap_path.relative_to(ROOT)} drifted; run python3 docs/scripts/generate_reference.py"
            )
        http_path = folder / "developers" / "reference" / "http-api.md"
        if not http_path.exists():
            errors.append(f"{http_path.relative_to(ROOT)} is missing")
            continue
        actual_http = http_path.read_text()
        head = (
            actual_http.split(mod.MARKER, 1)[0].rstrip() + "\n\n"
            if mod.MARKER in actual_http
            else actual_http.rstrip() + "\n\n"
        )
        expected_http = head + mod.route_index(locale)
        if actual_http != expected_http:
            errors.append(
                f"{http_path.relative_to(ROOT)} route index drifted; run python3 docs/scripts/generate_reference.py"
            )
    return errors


def check_links() -> list[str]:
    if not DIST.exists():
        return ["docs/dist is missing; run the docs build first"]
    base = _normalized_base()
    errors = []
    for page in DIST.rglob("*.html"):
        for match in HREF.findall(page.read_text(errors="ignore")):
            if match.startswith(
                ("http://", "https://", "mailto:", "data:", "#", "javascript:", "//")
            ):
                continue
            if not match.startswith("/"):
                continue
            if not dest_exists(match, base):
                errors.append(f"{page.relative_to(DIST)} -> {match}")
    return errors


def main() -> int:
    mode = sys.argv[1] if len(sys.argv) > 1 else "source"
    if mode == "staged-parity":
        errors = check_staged_parity()
    else:
        errors = (
            check_parity()
            + check_screenshots()
            + check_gifs()
            + check_channel_schema()
            + check_generated_reference()
        )
        if mode == "dist":
            errors.extend(check_links())
    if errors:
        print("\n".join(errors))
        return 1
    print("docs checks passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
