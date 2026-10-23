#!/usr/bin/env python
"""Run MinerU's local CLI for supported documents and images."""

import argparse
from collections import deque
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
import logging
import math
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import time
from uuid import uuid4

from deeptutor.services.file_io import atomic_write_json
from deeptutor.services.parsing.cache import load_ir

from ._process import cli_process
from .formats import MINERU_SUPPORTED_FORMATS

# Minimum seconds between on_output callbacks. MinerU's CLI emits tqdm-style
# progress that universal-newline decoding turns into many lines per second;
# without a floor the trace panel gets flooded during model downloads.
_ON_OUTPUT_MIN_INTERVAL = 0.5
_LOCAL_PARSE_IDLE_TIMEOUT_SECONDS = 600
_LOCAL_PARSE_TIMEOUT_SECONDS = 7200

#: Upper bound on the failure excerpt carried back to callers: long enough for
#: a useful stderr tail, short enough to fit inside an error message.
_FAILURE_DETAIL_MAX_CHARS = 400


def _bounded_detail(text: str) -> str:
    """One failure excerpt, trimmed to ``_FAILURE_DETAIL_MAX_CHARS``."""
    clean = str(text or "").strip()
    if len(clean) <= _FAILURE_DETAIL_MAX_CHARS:
        return clean
    # Keep the exception/exit-code prefix and the terminal cause. Progress
    # bars can otherwise consume the whole excerpt before the real error (#1982).
    head = clean[:80].rstrip()
    tail_size = _FAILURE_DETAIL_MAX_CHARS - len(head) - 3
    return head + "\n…\n" + clean[-tail_size:].lstrip()


class LocalParseReason(StrEnum):
    """Why a local MinerU parse failed.

    The values mirror ``readiness.py``'s pre-flight reasons (``cli_missing``,
    ``models_missing``) so the two failure vocabularies stay aligned.
    """

    CLI_MISSING = "cli_missing"
    INPUT_MISSING = "input_missing"
    UNSUPPORTED_INPUT = "unsupported_input"
    LEGACY_CLI_INPUT = "legacy_cli_input"
    TIMEOUT = "timeout"
    CANCELLED = "cancelled"
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

    print(f"📄 Input file: {source_file}")
    print(f"📁 Output directory: {output_dir}")
    print("→ Starting parsing...")

    # Each CLI owns its attempt. Failed/interrupted attempts stay available,
    # while a prior usable output survives until a validated replacement (#1612).
    attempt = Path(tempfile.mkdtemp(prefix=".mineru-attempt-", dir=base_dir))
    temp_output = attempt / "output"
    temp_output.mkdir()
    state_path = attempt / "state.json"
    atomic_write_json(state_path, {"source": source_file.name, "state": "running"})
    interrupted: list[LocalParseReason] = []
    interruption_detail = ""
    result = LocalParseResult.failure(LocalParseReason.EXCEPTION, "parse interrupted")
    try:
        cmd = [mineru_cmd, "-p", str(source_file), "-o", str(temp_output)]

        print(f"🔧 Executing command: {' '.join(cmd)}")

        tail: deque[str] = deque(maxlen=40)
        last_emit = 0.0
        from deeptutor.knowledge.indexing_run import IndexingCancelled, current_run

        run = current_run()
        started = activity = time.monotonic()
        quiet_reported = False
        total_timeout: float = _LOCAL_PARSE_TIMEOUT_SECONDS
        try:
            configured_timeout = float(
                (extra_env or {}).get(
                    "MINERU_TASK_RESULT_TIMEOUT_SECONDS",
                    os.environ.get("MINERU_TASK_RESULT_TIMEOUT_SECONDS", str(total_timeout)),
                )
            )
            if math.isfinite(configured_timeout) and configured_timeout >= 1:
                total_timeout = configured_timeout
        except (TypeError, ValueError):
            pass
        env = {
            **os.environ,
            **(extra_env or {}),
            "PYTHONUTF8": "1",
            # MinerU's nested API client otherwise times out at 3600 seconds,
            # before our default deadline. Both owners use the resolved value.
            "MINERU_TASK_RESULT_TIMEOUT_SECONDS": f"{total_timeout:g}",
        }
        log_path = attempt / "cli.log"
        # File reads do not block on a pipe inherited by a surviving worker.
        # Settle the owned process tree before validating/publishing artifacts.
        with cli_process(cmd, log_path, env) as process:
            with log_path.open("r", encoding="utf-8", errors="replace") as output:
                while True:
                    if run is not None:
                        try:
                            run.check()
                        except IndexingCancelled:
                            interrupted.append(LocalParseReason.CANCELLED)
                            interruption_detail = "Task cancellation requested."
                            break
                        except OSError as exc:
                            interrupted.append(LocalParseReason.EXCEPTION)
                            interruption_detail = f"Indexing state check failed: {exc}"
                            break
                    for _ in range(32):
                        raw_line = output.readline(4096)
                        if not raw_line:
                            break
                        line = raw_line.strip()
                        if not line:
                            continue
                        activity = time.monotonic()
                        quiet_reported = False
                        tail.append(line)
                        if (
                            on_output is not None
                            and activity - last_emit >= _ON_OUTPUT_MIN_INTERVAL
                        ):
                            last_emit = activity
                            try:
                                on_output(line[:300])
                            except Exception:
                                on_output = None
                    returncode = process.poll()
                    if returncode is not None:
                        break
                    now = time.monotonic()
                    if now - started >= total_timeout:
                        interrupted.append(LocalParseReason.TIMEOUT)
                        interruption_detail = (
                            f"Total parse runtime exceeded {total_timeout:g} seconds."
                        )
                        break
                    if now - activity >= _LOCAL_PARSE_IDLE_TIMEOUT_SECONDS and not quiet_reported:
                        logging.getLogger(__name__).warning(
                            "MinerU output is quiet; progress is unknown, not a proven stall. "
                            "The %s-second total deadline and task cancellation remain active.",
                            total_timeout,
                        )
                        quiet_reported = True
                    time.sleep(0.1)

        # Cleanup has settled the owned tree. Read only a bounded diagnostic
        # tail now; draining a still-writing descendant before cleanup could
        # otherwise postpone cancellation/exit indefinitely.
        with log_path.open("rb") as output:
            output.seek(0, os.SEEK_END)
            start = max(0, output.tell() - 16384)
            output.seek(start)
            lines = output.read(16384).decode("utf-8", errors="replace").splitlines()
            if start:
                lines = lines[1:]
            tail.extend(line.strip()[:4096] for line in lines if line.strip())

        if interrupted:
            result = LocalParseResult.failure(
                interrupted[0],
                interruption_detail + " Completed checkpoints remain reusable.",
            )
            return result
        if returncode != 0:
            print("✗ MinerU parsing failed:")
            print("\n".join(tail))
            result = LocalParseResult.failure(
                LocalParseReason.NONZERO_EXIT,
                f"exit code {returncode}\n" + "\n".join(tail),
            )
            return result

        print("✓ MinerU parsing completed!")

        generated_folders = sorted(temp_output.iterdir())

        if not generated_folders:
            print("⚠️ Warning: No generated files found in temp directory")
            result = LocalParseResult.failure(
                LocalParseReason.NO_ARTIFACTS,
                f"no files were produced in {temp_output}",
            )
            return result

        named_folder = temp_output / source_name
        source_folder = named_folder if named_folder.is_dir() else temp_output
        markdown, blocks, _assets = load_ir(source_folder)
        if not markdown.strip() and not blocks:
            result = LocalParseResult.failure(
                LocalParseReason.NO_ARTIFACTS,
                "MinerU produced no usable markdown or content blocks",
            )
            return result

        backup = base_dir / f".{source_name}.previous-{uuid4().hex}"
        had_previous = output_dir.exists()
        if had_previous:
            output_dir.rename(backup)
        try:
            source_folder.rename(output_dir)
        except BaseException:
            if had_previous:
                backup.rename(output_dir)
            raise
        if had_previous:
            shutil.rmtree(backup)
        print(f"📦 Files saved to: {output_dir}")

        print("\n📋 Generated files:")
        for item in output_dir.rglob("*"):
            if item.is_file():
                rel_path = item.relative_to(output_dir)
                print(f"  - {rel_path}")

        result = LocalParseResult.success()
        return result

    except Exception as e:
        print(f"✗ Error occurred during parsing: {e!s}")
        import traceback

        traceback.print_exc()
        result = LocalParseResult.failure(
            LocalParseReason.EXCEPTION,
            f"{type(e).__name__}: {e}",
        )
        return result
    finally:
        if result.ok:
            shutil.rmtree(attempt, ignore_errors=True)
        else:
            try:
                atomic_write_json(
                    state_path,
                    {
                        "source": source_file.name,
                        "state": "incomplete",
                        "reason": str(result.reason),
                    },
                )
            except OSError:
                # A diagnostic write must not hide the original failure.
                pass


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
