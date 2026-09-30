#!/usr/bin/env python
"""Run MinerU's local CLI for supported documents and images."""

import argparse
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
import os
from pathlib import Path
import shutil
import subprocess
import sys
import time

from .formats import MINERU_SUPPORTED_FORMATS

# Minimum seconds between on_output callbacks. MinerU's CLI emits tqdm-style
# progress that universal-newline decoding turns into many lines per second;
# without a floor the trace panel gets flooded during model downloads.
_ON_OUTPUT_MIN_INTERVAL = 0.5

#: Upper bound on the failure excerpt carried back to callers: long enough for
#: a useful stderr tail, short enough to fit inside an error message.
_FAILURE_DETAIL_MAX_CHARS = 400


def _bounded_detail(text: str) -> str:
    """One failure excerpt, trimmed to ``_FAILURE_DETAIL_MAX_CHARS``."""
    clean = str(text or "").strip()
    if len(clean) <= _FAILURE_DETAIL_MAX_CHARS:
        return clean
    return clean[:_FAILURE_DETAIL_MAX_CHARS].rstrip() + "…"


class LocalParseReason(StrEnum):
    """Why a local MinerU parse failed.

    The values mirror ``readiness.py``'s pre-flight reasons (``cli_missing``,
    ``models_missing``) so the two failure vocabularies stay aligned.
    """

    CLI_MISSING = "cli_missing"
    INPUT_MISSING = "input_missing"
    UNSUPPORTED_INPUT = "unsupported_input"
    LEGACY_CLI_INPUT = "legacy_cli_input"
    NONZERO_EXIT = "nonzero_exit"
    NO_ARTIFACTS = "no_artifacts"
    EXCEPTION = "exception"


@dataclass(frozen=True, slots=True)
class LocalParseResult:
    """Outcome of one local MinerU parse.

    ``detail`` is a bounded, user-safe excerpt (stderr tail or exception
    text), never the whole process log.
    """

    ok: bool
    reason: LocalParseReason | None = None
    detail: str = ""

    @classmethod
    def success(cls) -> "LocalParseResult":
        """A parse that wrote its artifacts."""
        return cls(ok=True)

    @classmethod
    def failure(cls, reason: LocalParseReason, detail: str = "") -> "LocalParseResult":
        """A failed parse, with the reason and its bounded excerpt."""
        return cls(ok=False, reason=reason, detail=_bounded_detail(detail))


def check_mineru_installed():
    """Check if MinerU is installed"""
    try:
        # Security: Using partial path is intentional here - we need to find
        # the command in user's PATH. These are trusted CLI tools, not user input.
        result = subprocess.run(
            ["mineru", "--version"],  # nosec B607
            check=False,
            capture_output=True,
            text=True,
            shell=False,
        )
        if result.returncode == 0:
            return "mineru"
    except FileNotFoundError:
        pass

    try:
        # Security: Same as above - intentionally using PATH lookup for CLI tool.
        result = subprocess.run(
            ["magic-pdf", "--version"],  # nosec B607
            check=False,
            capture_output=True,
            text=True,
            shell=False,
        )
        if result.returncode == 0:
            return "magic-pdf"
    except FileNotFoundError:
        pass

    return None


def parse_document_with_mineru_result(
    source_path: str,
    output_base_dir: str | None = None,
    on_output: Callable[[str], None] | None = None,
    cli_command: str | None = None,
    extra_env: dict[str, str] | None = None,
) -> LocalParseResult:
    """Parse with MinerU and report *why* a failure happened.

    Same inputs as :func:`parse_document_with_mineru`, but the outcome carries
    a :class:`LocalParseReason` and a bounded ``detail`` (stderr tail or
    exception text) instead of a bare ``False``.

    Args:
        source_path: Path to a PDF, image, DOCX, PPTX, or XLSX file
        output_base_dir: Base path for output directory, defaults to reference_papers
        on_output: Optional callback invoked (rate-limited) with each line of
            the CLI's combined stdout/stderr, so callers can surface live
            progress (model downloads, per-page parsing) instead of a silent
            multi-minute subprocess. Called from this thread.
        cli_command: Explicit MinerU executable to run (the validated
            ``local_cli_path`` setting). None = auto-detect from PATH.
        extra_env: Env vars merged over os.environ for the subprocess (e.g.
            MINERU_MODEL_SOURCE / HF_ENDPOINT so a lazy first-parse model
            download honors the configured source and mirror).

    Returns:
        LocalParseResult: Whether parsing succeeded, and why it failed.
    """
    if cli_command:
        mineru_cmd = cli_command
        print(f"✓ Using configured MinerU command: {mineru_cmd}")
    else:
        mineru_cmd = check_mineru_installed()
        if not mineru_cmd:
            print("✗ Error: MinerU installation not detected")
            print("Please install MinerU first:")
            print("  pip install magic-pdf[full]")
            print("or")
            print("  pip install mineru")
            print("or visit: https://github.com/opendatalab/MinerU")
            return LocalParseResult.failure(
                LocalParseReason.CLI_MISSING,
                "neither `mineru` nor `magic-pdf` was found on PATH",
            )
        print(f"✓ Detected MinerU command: {mineru_cmd}")

    source_file = Path(source_path).resolve()
    if not source_file.exists():
        print(f"✗ Error: Input file does not exist: {source_file}")
        return LocalParseResult.failure(LocalParseReason.INPUT_MISSING, str(source_file))

    suffix = source_file.suffix.lower()
    if suffix not in MINERU_SUPPORTED_FORMATS:
        print(f"✗ Error: Unsupported MinerU input format: {source_file}")
        return LocalParseResult.failure(
            LocalParseReason.UNSUPPORTED_INPUT,
            suffix or "(no file extension)",
        )

    if Path(mineru_cmd).name == "magic-pdf" and suffix != ".pdf":
        print("✗ Error: The legacy magic-pdf CLI only accepts PDF files.")
        print("Install the current CLI with `pip install mineru` for images and Office files.")
        return LocalParseResult.failure(
            LocalParseReason.LEGACY_CLI_INPUT,
            f"magic-pdf cannot parse {suffix or '(no file extension)'}",
        )

    # Project root is 3 levels up from deeptutor/tools/question/
    project_root = Path(__file__).parent.parent.parent.parent
    if output_base_dir is None:
        base_dir = project_root / "reference_papers"
    else:
        base_dir = Path(output_base_dir)

    base_dir.mkdir(parents=True, exist_ok=True)

    source_name = source_file.stem
    output_dir = base_dir / source_name

    if output_dir.exists():
        print(f"⚠️ Directory already exists, replacing: {output_dir.name}")
        shutil.rmtree(output_dir)

    print(f"📄 Input file: {source_file}")
    print(f"📁 Output directory: {output_dir}")
    print("→ Starting parsing...")

    try:
        temp_output = base_dir / "temp_mineru_output"
        if temp_output.exists():
            shutil.rmtree(temp_output)
        temp_output.mkdir(parents=True, exist_ok=True)

        cmd = [mineru_cmd, "-p", str(source_file), "-o", str(temp_output)]

        print(f"🔧 Executing command: {' '.join(cmd)}")

        # Stream combined stdout/stderr line by line. text=True enables
        # universal newlines, so tqdm's \r-rewritten progress bars arrive as
        # individual lines rather than one giant buffered blob at exit.
        process = subprocess.Popen(  # nosec B603 — fixed argv, shell=False
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            shell=False,
            env={**os.environ, **extra_env} if extra_env else None,
        )
        tail: deque[str] = deque(maxlen=40)
        last_emit = 0.0
        assert process.stdout is not None
        for raw_line in process.stdout:
            line = raw_line.strip()
            if not line:
                continue
            tail.append(line)
            if on_output is not None:
                now = time.monotonic()
                if now - last_emit >= _ON_OUTPUT_MIN_INTERVAL:
                    last_emit = now
                    try:
                        on_output(line[:300])
                    except Exception:
                        # A broken callback must not kill the parse; stop
                        # reporting and keep going.
                        on_output = None
        returncode = process.wait()

        if returncode != 0:
            print("✗ MinerU parsing failed:")
            print("\n".join(tail))
            if temp_output.exists():
                shutil.rmtree(temp_output)
            return LocalParseResult.failure(
                LocalParseReason.NONZERO_EXIT,
                f"exit code {returncode}\n" + "\n".join(tail),
            )

        print("✓ MinerU parsing completed!")

        generated_folders = list(temp_output.iterdir())

        if not generated_folders:
            print("⚠️ Warning: No generated files found in temp directory")
            if temp_output.exists():
                shutil.rmtree(temp_output)
            return LocalParseResult.failure(
                LocalParseReason.NO_ARTIFACTS,
                f"no files were produced in {temp_output}",
            )

        source_folder = generated_folders[0] if generated_folders[0].is_dir() else temp_output

        # Create target directory and move content
        output_dir.mkdir(parents=True, exist_ok=True)

        # Move MinerU-generated content to target directory
        if source_folder.exists() and source_folder.is_dir():
            # If source_folder is the source-named directory, move its contents
            for item in source_folder.iterdir():
                dest_item = output_dir / item.name
                if dest_item.exists():
                    if dest_item.is_dir():
                        shutil.rmtree(dest_item)
                    else:
                        dest_item.unlink()
                shutil.move(str(item), str(dest_item))
            print(f"📦 Files saved to: {output_dir}")
        else:
            if output_dir.exists():
                shutil.rmtree(output_dir)
            shutil.move(str(source_folder), str(output_dir))
            print(f"📦 Files saved to: {output_dir}")

        if temp_output.exists():
            shutil.rmtree(temp_output)

        print("\n📋 Generated files:")
        for item in output_dir.rglob("*"):
            if item.is_file():
                rel_path = item.relative_to(output_dir)
                print(f"  - {rel_path}")

        return LocalParseResult.success()

    except Exception as e:
        print(f"✗ Error occurred during parsing: {e!s}")
        import traceback

        traceback.print_exc()
        return LocalParseResult.failure(
            LocalParseReason.EXCEPTION,
            f"{type(e).__name__}: {e}",
        )


def parse_document_with_mineru(
    source_path: str,
    output_base_dir: str | None = None,
    on_output: Callable[[str], None] | None = None,
    cli_command: str | None = None,
    extra_env: dict[str, str] | None = None,
) -> bool:
    """Parse a supported document or image using MinerU.

    Retained bool contract for existing callers; see
    :func:`parse_document_with_mineru_result` when the failure reason and its
    bounded diagnostic excerpt matter.

    Returns:
        bool: Whether parsing was successful
    """
    return parse_document_with_mineru_result(
        source_path,
        output_base_dir,
        on_output=on_output,
        cli_command=cli_command,
        extra_env=extra_env,
    ).ok


def parse_pdf_with_mineru(
    pdf_path: str,
    output_base_dir: str | None = None,
    on_output: Callable[[str], None] | None = None,
    cli_command: str | None = None,
    extra_env: dict[str, str] | None = None,
):
    """Backward-compatible PDF-only wrapper around the generic CLI adapter."""
    pdf_file = Path(pdf_path)
    if pdf_file.suffix.lower() != ".pdf":
        print(f"✗ Error: File is not PDF format: {pdf_file.resolve()}")
        return False
    return parse_document_with_mineru(
        pdf_path,
        output_base_dir,
        on_output=on_output,
        cli_command=cli_command,
        extra_env=extra_env,
    )


def main():
    """Main function"""
    parser = argparse.ArgumentParser(
        description="Parse PDF files using MinerU and save results to reference_papers directory",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Parse a single PDF file
  python pdf_parser.py /path/to/paper.pdf

  # Parse PDF and specify output directory
  python pdf_parser.py /path/to/paper.pdf -o /custom/output/dir
        """,
    )

    parser.add_argument("pdf_path", type=str, help="Path to PDF file")

    parser.add_argument(
        "-o",
        "--output",
        type=str,
        default=None,
        help="Base path for output directory (default: reference_papers)",
    )

    args = parser.parse_args()

    success = parse_pdf_with_mineru(args.pdf_path, args.output)

    if success:
        print("\n✓ Parsing completed!")
        sys.exit(0)
    else:
        print("\n✗ Parsing failed!")
        sys.exit(1)


if __name__ == "__main__":
    main()
