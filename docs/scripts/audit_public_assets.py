"""Report public files with no literal path reference in the docs source or build."""

from __future__ import annotations

import html
from pathlib import Path
import re
import sys
from urllib.parse import unquote

DOCS = Path(__file__).resolve().parents[1]
TEXT_SUFFIXES = {
    ".astro",
    ".css",
    ".html",
    ".js",
    ".json",
    ".md",
    ".mdx",
    ".mjs",
    ".svg",
    ".ts",
    ".tsx",
    ".txt",
    ".webmanifest",
    ".xml",
}
# Browsers and crawlers can request these without an in-site link.
WELL_KNOWN = {"apple-touch-icon.png", "favicon.ico", "robots.txt"}
SCREENSHOT_METADATA = {"screenshots/dev/README.md", "screenshots/dev/manifest.json"}


def main() -> int:
    public = DOCS / "public"
    dist = DOCS / "dist"
    if not (dist / "index.html").is_file():
        print("Build the docs with npm run build in docs/ before auditing assets.", file=sys.stderr)
        return 1

    assets = {
        path.relative_to(public).as_posix(): path for path in public.rglob("*") if path.is_file()
    }
    paths = {
        relative
        for relative in assets.keys() - WELL_KNOWN - SCREENSHOT_METADATA
        if not relative.startswith(".well-known/")
    }
    if not paths:
        print("No public files to audit.")
        return 0

    alternatives = "|".join(re.escape(relative) for relative in sorted(paths))
    reference = re.compile(rf"(?<![\w.%-])(?:{alternatives})(?![\w.%-])")
    referenced = set()
    inputs = [DOCS / "astro.config.mjs"]
    for folder in (DOCS / "src", dist):
        inputs.extend(path for path in folder.rglob("*") if path.suffix in TEXT_SUFFIXES)
    for path in inputs:
        if path.is_file():
            text = path.read_text(encoding="utf-8")
            normalized = unquote(html.unescape(text)).replace(r"\/", "/")
            referenced.update(reference.findall(normalized))

    total = 0
    unused = sorted(paths - referenced)
    for relative in unused:
        size = assets[relative].stat().st_size
        total += size
        print(f"{size:>10}  docs/public/{relative}")
    print(f"{len(unused)} candidates, {total:,} bytes ({total / 1024**2:.1f} MiB)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
