"""Run local Docling conversion outside the FAISS backend process.

Current macOS wheels for Docling's PyTorch dependency and FAISS bundle distinct
``libomp.dylib`` runtimes. Initializing both in one process aborts with OpenMP
Error #15 (and suppressing that guard can deadlock). The parent-side helper in
this module therefore launches the conversion through ``python -m``; only the
worker branch imports Docling and PyTorch.
"""

from __future__ import annotations

import argparse
from collections import deque
import os
from pathlib import Path
import subprocess  # nosec B404 - fixed module command, never a shell
import sys
from typing import Callable, Optional, Sequence

from ...types import ParserError
from .config import DoclingConfig

_WORKER_MODULE = "deeptutor.services.parsing.engines.docling.local_worker"
_ERROR_TAIL_LINES = 20


def parse_local(
    source_path: Path,
    workdir: Path,
    *,
    config: DoclingConfig,
    on_output: Optional[Callable[[str], None]] = None,
) -> None:
    """Convert one document in a fresh interpreter and stream worker output."""
    command = [
        sys.executable,
        "-m",
        _WORKER_MODULE,
        "--source",
        str(source_path.resolve()),
        "--workdir",
        str(workdir.resolve()),
    ]
    if config.do_ocr:
        command.append("--do-ocr")
    if config.do_table_structure:
        command.append("--do-table-structure")

    env = os.environ.copy()
    env["PYTHONUNBUFFERED"] = "1"
    try:
        process = subprocess.Popen(  # noqa: S603 - argv is fixed and shell=False
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            env=env,
        )
    except OSError as exc:
        raise ParserError(f"Could not start the isolated Docling worker: {exc}") from exc

    tail: deque[str] = deque(maxlen=_ERROR_TAIL_LINES)
    try:
        if process.stdout is not None:
            for raw_line in process.stdout:
                line = raw_line.strip()
                if not line:
                    continue
                tail.append(line)
                if on_output is not None:
                    on_output(line)
        return_code = process.wait()
    except BaseException:
        _stop_worker(process)
        raise

    if return_code != 0:
        detail = "\n".join(tail) or "no diagnostic output"
        raise ParserError(f"Docling worker exited with code {return_code}: {detail}")


def _stop_worker(process: subprocess.Popen) -> None:
    if process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()


def _build_converter(*, do_ocr: bool, do_table_structure: bool):
    """Import and configure Docling inside the isolated worker only."""
    from docling.document_converter import DocumentConverter

    try:
        from docling.datamodel.base_models import InputFormat
        from docling.datamodel.pipeline_options import PdfPipelineOptions
        from docling.document_converter import PdfFormatOption

        pipeline_options = PdfPipelineOptions()
        pipeline_options.do_ocr = do_ocr
        pipeline_options.do_table_structure = do_table_structure
        return DocumentConverter(
            format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=pipeline_options)}
        )
    except Exception:
        # Docling's option API varies between compatible releases. Preserve the
        # previous behavior: conversion still runs with upstream defaults.
        return DocumentConverter()


def _convert(
    source_path: Path,
    workdir: Path,
    *,
    do_ocr: bool,
    do_table_structure: bool,
) -> None:
    converter = _build_converter(
        do_ocr=do_ocr,
        do_table_structure=do_table_structure,
    )
    result = converter.convert(str(source_path))
    markdown = result.document.export_to_markdown()
    workdir.mkdir(parents=True, exist_ok=True)
    (workdir / f"{source_path.stem}.md").write_text(str(markdown), encoding="utf-8")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="DeepTutor isolated Docling converter")
    parser.add_argument("--source", required=True, type=Path)
    parser.add_argument("--workdir", required=True, type=Path)
    parser.add_argument("--do-ocr", action="store_true")
    parser.add_argument("--do-table-structure", action="store_true")
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = _parser().parse_args(argv)
    try:
        _convert(
            args.source,
            args.workdir,
            do_ocr=args.do_ocr,
            do_table_structure=args.do_table_structure,
        )
    except Exception as exc:  # noqa: BLE001 - forwarded to the parent process
        print(f"{type(exc).__name__}: {exc}", file=sys.stderr, flush=True)
        return 1
    print(f"Converted {args.source.name} with isolated Docling", flush=True)
    return 0


if __name__ == "__main__":  # pragma: no cover - exercised through subprocess
    raise SystemExit(main())


__all__ = ["main", "parse_local"]
