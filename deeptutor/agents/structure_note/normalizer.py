from __future__ import annotations

from pathlib import Path
import shutil
import subprocess


class NormalizationError(RuntimeError):
    pass


def normalize_to_pdf(source_path: Path, output_dir: Path) -> Path:
    output_dir.mkdir(parents=True, exist_ok=True)
    suffix = source_path.suffix.lower()
    target_pdf = output_dir / "normalized.pdf"

    if suffix == ".pdf":
        shutil.copy2(source_path, target_pdf)
        return target_pdf

    if suffix not in {".ppt", ".pptx"}:
        raise NormalizationError(f"Unsupported file type for Structure Note: {suffix}")

    soffice = shutil.which("soffice")
    if not soffice:
        raise NormalizationError(
            "LibreOffice is required for PPT/PPTX uploads. Install `soffice` and retry."
        )

    command = [
        soffice,
        "--headless",
        "--convert-to",
        "pdf",
        "--outdir",
        str(output_dir),
        str(source_path),
    ]
    result = subprocess.run(command, capture_output=True, text=True, check=False)
    if result.returncode != 0:
        stderr = result.stderr.strip() or result.stdout.strip() or "Unknown conversion error"
        raise NormalizationError(f"Failed to convert PPT/PPTX to PDF: {stderr}")

    converted_pdf = output_dir / f"{source_path.stem}.pdf"
    if not converted_pdf.exists():
        raise NormalizationError("LibreOffice reported success but did not produce a PDF output.")

    converted_pdf.replace(target_pdf)
    return target_pdf
