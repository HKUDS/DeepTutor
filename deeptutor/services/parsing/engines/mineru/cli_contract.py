"""Versioned local MinerU commands and the 4.x stateless result bundle."""

from __future__ import annotations

import json
import math
import os
from pathlib import Path, PurePosixPath, PureWindowsPath
import re
import tempfile
import time
from typing import Any
from urllib.parse import unquote
import zipfile

from ._process import cli_process


def read_cli_version(command: str, *, timeout: float = 10.0) -> str:
    """Read a bounded version probe using the existing owned process-tree scope."""
    with tempfile.TemporaryDirectory(prefix="deeptutor-mineru-version-") as directory:
        log = Path(directory) / "version.log"
        with cli_process([command, "--version"], log, dict(os.environ)) as process:
            deadline = time.monotonic() + timeout
            while process.poll() is None:
                if time.monotonic() >= deadline:
                    raise TimeoutError("MinerU CLI version probe timed out")
                time.sleep(0.05)
            if process.poll() != 0:
                raise ValueError("MinerU CLI version probe failed")
        with log.open(encoding="utf-8", errors="replace") as stream:
            output = stream.read(4096)
    output = re.sub(r"\x1b\[[0-9;]*m", "", output)
    match = re.search(
        r"(?im)(?:mineru(?:-kit)?[^\d\n]*|magic-pdf[^\d\n]*|^v?)(\d+\.\d+\.\d+)\b", output
    )
    if match is None:
        raise ValueError("Could not identify the configured MinerU CLI version")
    return match.group(1)


def build_parse_command(command: str, version: str, source: Path, output: Path) -> list[str]:
    """Select the whole-file CLI contract without changing the chosen executable."""
    major = int(version.split(".", 1)[0])
    if major in {1, 2, 3}:
        return [command, "-p", str(source), "-o", str(output)]
    if major != 4:
        raise ValueError(
            f"Unsupported MinerU CLI version {version}; supported major versions are 1–4"
        )
    if Path(command).stem.casefold() != "mineru-kit":
        raise ValueError(
            "MinerU 4 local parsing requires its stateless mineru-kit executable. "
            "Set that exact path in Document Parsing; the configured executable was not replaced."
        )
    return [
        command,
        "parse",
        str(source),
        "--pages",
        "all",
        "--format",
        "zip",
        "-o",
        str(output / "result.zip"),
    ]


def _relative_asset(value: str, root: Path) -> str:
    """Require a materialized local asset inside this parse attempt."""
    name = unquote(value)
    path = PurePosixPath(name)
    if path.is_absolute() or PureWindowsPath(name).drive or "\\" in name or ".." in path.parts:
        raise ValueError("MinerU bundle contains an unsafe asset reference")
    target = root.joinpath(*path.parts).resolve()
    if not target.is_relative_to(root.resolve()) or not target.is_file():
        raise ValueError(f"MinerU bundle asset is missing: {name}")
    return path.as_posix()


def _annotations(value: Any) -> list[str]:
    if not isinstance(value, list) or any(
        not isinstance(row, dict) or not isinstance(row.get("content"), str) for row in value
    ):
        raise ValueError("Invalid MinerU structured annotations")
    return [row["content"] for row in value]


def _legacy_bbox(value: Any) -> list[float] | None:
    """Convert DocVortex unit coordinates to the existing 0–1000 IR scale."""
    if value is None:
        return None
    if (
        not isinstance(value, list)
        or len(value) != 4
        or any(
            type(coordinate) not in {int, float}
            or not math.isfinite(coordinate)
            or not 0 <= coordinate <= 1
            for coordinate in value
        )
    ):
        raise ValueError("Invalid MinerU normalized bounding box")
    if value[0] > value[2] or value[1] > value[3]:
        raise ValueError("Inverted MinerU bounding box")
    return [coordinate * 1000 for coordinate in value]


def import_v4_bundle(archive_path: Path, output: Path) -> None:
    """Validate consumed 4.x fields and publish the established DeepTutor IR files.

    MinerU 4.1.3 exports markdown.md, middle_json.json, structured_content.json
    and materialized assets. This reader never treats an invalid new bundle as
    a legacy content list, and retains the original versioned JSON files.
    """
    with zipfile.ZipFile(archive_path) as archive:
        seen = set()
        total_size = 0
        for entry in archive.infolist():
            path = PurePosixPath(entry.filename)
            if (
                path.is_absolute()
                or ".." in path.parts
                or "\\" in entry.filename
                or any(":" in part for part in path.parts)
                or PureWindowsPath(entry.filename).drive
            ):
                raise ValueError("Unsafe MinerU bundle member")
            if (entry.external_attr >> 16) & 0o170000 == 0o120000:
                raise ValueError("MinerU bundle symlinks are not supported")
            identity = path.as_posix().casefold()
            if identity == archive_path.name.casefold():
                raise ValueError("MinerU bundle cannot replace its own archive")
            if identity in seen:
                raise ValueError("Duplicate MinerU bundle member")
            seen.add(identity)
            total_size += entry.file_size
            if total_size > 1024 * 1024 * 1024:
                raise ValueError("MinerU bundle exceeds the 1 GiB extraction limit")
        for entry in archive.infolist():
            destination = output.joinpath(*PurePosixPath(entry.filename).parts)
            if entry.is_dir():
                destination.mkdir(parents=True, exist_ok=True)
            else:
                destination.parent.mkdir(parents=True, exist_ok=True)
                with archive.open(entry) as source, destination.open("wb") as target:
                    while chunk := source.read(1024 * 1024):
                        target.write(chunk)
    middle = json.loads((output / "middle_json.json").read_text(encoding="utf-8"))
    structured = json.loads((output / "structured_content.json").read_text(encoding="utf-8"))
    if (
        not isinstance(middle, dict)
        or middle.get("schema") != "docvortex.middle"
        or middle.get("schema_version") != "2.0"
        or middle.get("is_full_document") is not True
    ):
        raise ValueError("Expected a complete MinerU 4 docvortex.middle 2.0 result")
    pages = middle.get("pages")
    rendered = structured.get("pages") if isinstance(structured, dict) else None
    if not isinstance(structured, dict) or structured.get("is_full_document") is not True:
        raise ValueError("Expected a complete MinerU structured result")
    if (
        not isinstance(pages, list)
        or not pages
        or not isinstance(rendered, list)
        or len(pages) != len(rendered)
    ):
        raise ValueError("MinerU page coverage does not match its structured result")
    metadata = middle.get("metadata", {})
    document = metadata.get("document", {}) if isinstance(metadata, dict) else {}
    page_count = document.get("page_count") if isinstance(document, dict) else None
    if page_count is not None and (type(page_count) is not int or page_count != len(pages)):
        raise ValueError("MinerU result does not cover the reported document page count")
    blocks: list[dict[str, Any]] = []
    previous_page = -1
    for raw, page in zip(pages, rendered):
        if not isinstance(raw, dict) or not isinstance(page, dict):
            raise ValueError("Invalid MinerU page")
        index = page.get("page_idx")
        if type(index) is not int or index != previous_page + 1 or index != raw.get("page_idx"):
            raise ValueError("MinerU page indices must match and be strictly increasing")
        previous_page = index
        items = page.get("blocks")
        raw_items = raw.get("blocks")
        if (
            not isinstance(items, list)
            or not isinstance(raw_items, list)
            or len(items) != len(raw_items)
        ):
            raise ValueError("MinerU structured block coverage is incomplete")
        for original, item in zip(raw_items, items):
            if not isinstance(item, dict) or not isinstance(original, dict):
                raise ValueError("Invalid MinerU content block")
            kind, content = item.get("type"), item.get("content")
            if (
                not isinstance(kind, str)
                or not isinstance(content, str)
                or original.get("type") != kind
            ):
                raise ValueError("Invalid MinerU structured content")
            block: dict[str, Any] = {
                "type": kind,
                "page_idx": index,
                "bbox": _legacy_bbox(item.get("bbox")),
            }
            if item.get("image_source"):
                block["img_path"] = _relative_asset(item["image_source"], output)
            if kind == "table":
                block.update(
                    table_body=content,
                    table_caption=_annotations(item.get("captions", [])),
                    table_footnote=_annotations(item.get("footnotes", [])),
                )
            elif kind in {"image", "chart"}:
                block.update(
                    type="image",
                    image_caption=_annotations(item.get("captions", [])),
                    image_footnote=_annotations(item.get("footnotes", [])),
                )
                if content:
                    block["image_caption"].append(content)
            else:
                block["text"] = content
                if kind == "equation":
                    block["text_format"] = "latex"
                elif kind not in {
                    "ref_text",
                    "header",
                    "footer",
                    "page_number",
                    "aside_text",
                    "page_footnote",
                }:
                    block["type"] = "text"
            blocks.append(block)
    if not (output / "markdown.md").is_file():
        raise ValueError("MinerU bundle has no Markdown output")
    (output / "mineru4_content_list.json").write_text(
        json.dumps(blocks, ensure_ascii=False) + "\n", encoding="utf-8"
    )
