#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Parse PDF files using MinerU and save results to reference_papers directory
"""

import argparse
from datetime import datetime
from pathlib import Path
import shutil
import subprocess
import sys


def check_mineru_installed():
    """Check if MinerU is installed"""
    try:
        # Security: Using partial path is intentional here - we need to find
        # the command in user's PATH. These are trusted CLI tools, not user input.
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

    try:
        # Security: Same as above - intentionally using PATH lookup for CLI tool.
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

    return None


def parse_pdf_with_mineru(pdf_path: str, output_base_dir: str = None):
    """
    Parse PDF file using MinerU

    Args:
        pdf_path: Path to PDF file
        output_base_dir: Base path for output directory, defaults to reference_papers

    Returns:
        bool: Whether parsing was successful
    """
    mineru_cmd = check_mineru_installed()
    if not mineru_cmd:
        print("✗ Error: MinerU installation not detected")
        print("Please install MinerU first:")
        print("  pip install magic-pdf[full]")
        print("or")
        print("  pip install mineru")
        print("or visit: https://github.com/opendatalab/MinerU")
        return False

    print(f"✓ Detected MinerU command: {mineru_cmd}")

    pdf_path = Path(pdf_path).resolve()
    if not pdf_path.exists():
        print(f"✗ Error: PDF file does not exist: {pdf_path}")
        return False

    if not pdf_path.suffix.lower() == ".pdf":
        print(f"✗ Error: File is not PDF format: {pdf_path}")
        return False

    # Project root is 3 levels up from src/tools/question/
    project_root = Path(__file__).parent.parent.parent.parent
    if output_base_dir is None:
        output_base_dir = project_root / "reference_papers"
    else:
        output_base_dir = Path(output_base_dir)

    output_base_dir.mkdir(parents=True, exist_ok=True)

    pdf_name = pdf_path.stem
    output_dir = output_base_dir / pdf_name

    if output_dir.exists():
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        backup_dir = output_base_dir / f"{pdf_name}_backup_{timestamp}"
        print(f"⚠️ Directory already exists, backing up to: {backup_dir.name}")
        shutil.move(str(output_dir), str(backup_dir))

    print(f"📄 PDF file: {pdf_path}")
    print(f"📁 Output directory: {output_dir}")
    print("→ Starting parsing...")

    try:
        temp_output = output_base_dir / "temp_mineru_output"
        temp_output.mkdir(parents=True, exist_ok=True)

        cmd = [mineru_cmd, "-p", str(pdf_path), "-o", str(temp_output)]

        print(f"🔧 Executing command: {' '.join(cmd)}")

        result = subprocess.run(cmd, capture_output=True, text=True, check=False, shell=False)

        if result.returncode != 0:
            print("✗ MinerU parsing failed:")
            print(f"Stdout: {result.stdout}")
            print(f"Stderr: {result.stderr}")
            if temp_output.exists():
                shutil.rmtree(temp_output)
            return False

        print("✓ MinerU parsing completed!")

        generated_folders = list(temp_output.iterdir())

        if not generated_folders:
            print("⚠️ Warning: No generated files found in temp directory")
            if temp_output.exists():
                shutil.rmtree(temp_output)
            return False

        source_folder = generated_folders[0] if generated_folders[0].is_dir() else temp_output

        # Create target directory and move content
        output_dir.mkdir(parents=True, exist_ok=True)

        # Move MinerU-generated content to target directory
        if source_folder.exists() and source_folder.is_dir():
            # If source_folder is the PDF-named directory, move its contents
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

        return True

    except Exception as e:
        print(f"✗ Error occurred during parsing: {e!s}")
        import traceback

        traceback.print_exc()
        return False


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
