"""
TeX Downloader - LaTeX source code download tool

Features:
1. Download LaTeX source from ArXiv
2. Extract and locate main tex file
3. Read tex content

Author: DeepTutor Team
Version: v1.0
Based on: TODO.md specification
"""

import logging
import os
from pathlib import Path
import re
import shutil
import tarfile
import tempfile
import zipfile

import requests

logger = logging.getLogger(__name__)


class TexDownloadResult:
    """LaTeX download result"""

    def __init__(
        self,
        success: bool,
        tex_path: str | None = None,
        tex_content: str | None = None,
        error: str | None = None,
    ):
        self.success = success
        self.tex_path = tex_path
        self.tex_content = tex_content
        self.error = error


class TexDownloader:
    """LaTeX source code download tool"""

    def __init__(self, workspace_dir: str):
        """
        Initialize downloader

        Args:
            workspace_dir: Workspace directory (for saving downloaded files)
        """
        self.workspace_dir = Path(workspace_dir)
        self.workspace_dir.mkdir(parents=True, exist_ok=True)

    def download_arxiv_source(
        self, arxiv_url: str, arxiv_id: str | None = None
    ) -> TexDownloadResult:
        """
        Download LaTeX source from ArXiv

        Args:
            arxiv_url: ArXiv paper URL
            arxiv_id: ArXiv ID (optional, if not in URL)

        Returns:
            TexDownloadResult object
        """
        # Extract ArXiv ID
        if not arxiv_id:
            arxiv_id = self._extract_arxiv_id(arxiv_url)

        if not arxiv_id:
            return TexDownloadResult(success=False, error="Unable to extract ArXiv ID")

        try:
            # Build source download URL
            source_url = f"https://arxiv.org/e-print/{arxiv_id}"

            # Download source package
            print(f"  Downloading source: {source_url}")
            response = requests.get(source_url, timeout=30)
            response.raise_for_status()

            # Create temporary directory
            temp_dir = tempfile.mkdtemp(dir=self.workspace_dir)

            # Save source package
            source_file = Path(temp_dir) / f"{arxiv_id}_source"
            with open(source_file, "wb") as f:
                f.write(response.content)

            # Extract source package
            extract_dir = Path(temp_dir) / "extracted"
            extract_dir.mkdir(exist_ok=True)

            if self._is_tar_file(source_file):
                self._extract_tar(source_file, extract_dir)
            elif self._is_zip_file(source_file):
                self._extract_zip(source_file, extract_dir)
            else:
                # Might be a single tex file
                shutil.copy(source_file, extract_dir / f"{arxiv_id}.tex")

            # Find main tex file
            main_tex = self._find_main_tex(extract_dir)

            if not main_tex:
                return TexDownloadResult(success=False, error="Main tex file not found")

            # Read tex content
            tex_content = self._read_tex_file(main_tex)

            # Move to permanent location
            paper_dir = self.workspace_dir / f"paper_{arxiv_id}"
            paper_dir.mkdir(exist_ok=True)

            final_tex_path = paper_dir / "main.tex"
            shutil.copy(main_tex, final_tex_path)

            # Clean up temporary directory
            shutil.rmtree(temp_dir, ignore_errors=True)

            return TexDownloadResult(
                success=True, tex_path=str(final_tex_path), tex_content=tex_content
            )

        except requests.exceptions.RequestException as e:
            return TexDownloadResult(success=False, error=f"Download failed: {e!s}")
        except Exception as e:
            return TexDownloadResult(success=False, error=f"Processing failed: {e!s}")

    def _extract_arxiv_id(self, url: str) -> str | None:
        """Extract ArXiv ID from URL"""
        match = re.search(r"arxiv\.org/(?:abs|pdf)/(\d+\.\d+)", url)
        if match:
            return match.group(1)
        return None

    def _is_tar_file(self, file_path: Path) -> bool:
        """Check if file is a tar file"""
        try:
            with tarfile.open(file_path, "r:*") as tar:
                return True
        except Exception:
            return False

    def _is_zip_file(self, file_path: Path) -> bool:
        """Check if file is a zip file"""
        try:
            with zipfile.ZipFile(file_path, "r") as zip_file:
                return True
        except Exception:
            return False

    def _extract_tar(self, tar_path: Path, extract_dir: Path):
        """Extract tar file safely (prevent ZipSlip/TarSlip)"""
        with tarfile.open(tar_path, "r:*") as tar:
            # Safe extraction filter
            def is_within_directory(directory, target):
                abs_directory = os.path.abspath(directory)
                abs_target = os.path.abspath(target)
                prefix = os.path.commonprefix([abs_directory, abs_target])
                return prefix == abs_directory

            def safe_members(members):
                for member in members:
                    member_path = os.path.join(extract_dir, member.name)
                    if not is_within_directory(extract_dir, member_path):
                        print(f"Suspicious file path in tar: {member.name}. Skipping.")
                        continue
                    yield member

            tar.extractall(extract_dir, members=safe_members(tar))

    def _extract_zip(self, zip_path: Path, extract_dir: Path):
        """Extract zip file"""
        with zipfile.ZipFile(zip_path, "r") as zip_file:
            zip_file.extractall(extract_dir)

    def _find_main_tex(self, directory: Path) -> Path | None:
        """
        Find main tex file

        Priority:
        1. main.tex
        2. paper.tex
        3. Tex file containing \\documentclass
        4. Largest tex file
        """
        tex_files = list(directory.rglob("*.tex"))

        if not tex_files:
            return None

        # 1. Find main.tex or paper.tex
        for name in ["main.tex", "paper.tex", "manuscript.tex"]:
            for tex_file in tex_files:
                if tex_file.name.lower() == name:
                    return tex_file

        # 2. Find file containing \documentclass
        for tex_file in tex_files:
            try:
                content = tex_file.read_text(encoding="utf-8", errors="ignore")
                if r"\documentclass" in content:
                    return tex_file
            except Exception:
                logger.warning("Failed to read tex file %s", tex_file)
                continue

        # 3. Return largest tex file
        largest_tex = max(tex_files, key=lambda f: f.stat().st_size)
        return largest_tex

    def _read_tex_file(self, tex_path: Path) -> str:
        """Read tex file content"""
        try:
            return tex_path.read_text(encoding="utf-8", errors="ignore")
        except Exception as e:
            raise Exception(f"Failed to read tex file: {e!s}")


def read_tex_file(tex_path: str) -> str:
    """
    Read tex file content (convenience function)

    Args:
        tex_path: tex file path

    Returns:
        tex content
    """
    return Path(tex_path).read_text(encoding="utf-8", errors="ignore")


# ========== Usage Example ==========

if __name__ == "__main__":
    # Test download
    downloader = TexDownloader(workspace_dir="./test_workspace")

    # Test an ArXiv paper
    result = downloader.download_arxiv_source(
        arxiv_url="https://arxiv.org/abs/1706.03762",  # Attention is All You Need
        arxiv_id="1706.03762",
    )

    if result.success:
        print("✓ Download successful!")
        print(f"  File path: {result.tex_path}")
        print(f"  Content length: {len(result.tex_content)} characters")
        print(f"  Content preview: {result.tex_content[:500]}...")
    else:
        print(f"✗ Download failed: {result.error}")
