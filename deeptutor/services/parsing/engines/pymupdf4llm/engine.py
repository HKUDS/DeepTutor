"""PyMuPDF4LLM engine adapter implementing the ``Parser`` protocol.

A lightweight, pure-Python PDF/e-book → Markdown engine built on PyMuPDF (fitz):
no CUDA, no model weights, suited to low-end / GPU-less machines. Unlike the
text-only and markitdown engines it can also extract embedded images and
rendered vector graphics, writing them into the parse's ``images/`` dir and
rewriting the Markdown links to a portable ``images/<name>`` form (matching the
MinerU/Docling asset convention the cache loader expects).
"""

from __future__ import annotations

import importlib.util
import os
from pathlib import Path
import re
from typing import Callable, Optional

from ...base import ReadinessReport
from ...signature import ParserSignature
from ...types import ParserError
from .._versions import package_version
from .config import PyMuPDF4LLMConfig, resolve_pymupdf4llm_config
from .formats import (
    MIN_PYMUPDF4LLM_VERSION,
    PYMUPDF4LLM_1_28_2_FORMATS,
    installed_pymupdf4llm_version,
    pymupdf4llm_version_is_current,
)

# Markdown image links emitted by pymupdf4llm. We rewrite any link that points
# at a file we actually extracted to a relative ``images/<name>`` so the cached
# markdown stays valid no matter where the cache dir is moved to.
_IMAGE_LINK_RE = re.compile(r"!\[([^\]]*)\]\(([^)]+)\)")


class PyMuPDF4LLMParser:
    """PDF/e-book → Markdown via pymupdf4llm (no models, optional image extraction)."""

    name = "pymupdf4llm"
    needs_local_models = False

    @classmethod
    def is_available(cls) -> bool:
        return importlib.util.find_spec("pymupdf4llm") is not None

    def resolve_config(self) -> PyMuPDF4LLMConfig:
        return resolve_pymupdf4llm_config()

    def supported_formats(self) -> frozenset[str]:
        return PYMUPDF4LLM_1_28_2_FORMATS

    def signature(self, config: PyMuPDF4LLMConfig) -> ParserSignature:
        return ParserSignature.build(
            "pymupdf4llm",
            package_version("pymupdf4llm"),
            {
                "write_images": config.write_images,
                "image_format": config.image_format,
                "image_dpi": config.image_dpi,
            },
        )

    def is_ready(self, config: PyMuPDF4LLMConfig) -> ReadinessReport:
        if not self.is_available():
            return ReadinessReport(
                ready=False,
                reason="not_configured",
                message="pymupdf4llm isn't installed (pip install deeptutor[parse-pymupdf4llm]).",
            )
        version = installed_pymupdf4llm_version()
        if not pymupdf4llm_version_is_current(version):
            return ReadinessReport(
                ready=False,
                reason="update_required",
                message=(
                    f"Installed PyMuPDF4LLM {version or 'unknown'} is too old. DeepTutor needs "
                    f"PyMuPDF4LLM >= {MIN_PYMUPDF4LLM_VERSION} for current layout, OCR, image "
                    "and multi-format support. Update it under Settings → Document Parsing."
                ),
            )
        return ReadinessReport(ready=True)

    def parse(
        self,
        source_path: Path,
        workdir: Path,
        *,
        config: PyMuPDF4LLMConfig,
        on_output: Optional[Callable[[str], None]] = None,
    ) -> None:
        to_markdown = self._resolve_to_markdown()

        source_path = Path(source_path)
        workdir = Path(workdir)
        if on_output:
            on_output(f"Converting {source_path.name} via PyMuPDF4LLM…")

        images_dir = workdir / "images"
        kwargs: dict[str, object] = {"show_progress": False}
        if config.write_images:
            images_dir.mkdir(parents=True, exist_ok=True)
            kwargs.update(
                write_images=True,
                image_path=str(images_dir),
                image_format=config.image_format,
                dpi=config.image_dpi,
            )

        try:
            markdown = to_markdown(str(source_path), **kwargs)
        except Exception as exc:  # noqa: BLE001 - surface as a parser error
            raise ParserError(f"PyMuPDF4LLM failed to convert {source_path.name}: {exc}")

        if config.write_images:
            markdown = self._portable_image_links(str(markdown), images_dir)
            # Drop the images dir if nothing was actually extracted, so the
            # cache loader doesn't report an empty asset_dir.
            if images_dir.is_dir() and not any(images_dir.iterdir()):
                images_dir.rmdir()

        (workdir / f"{source_path.stem}.md").write_text(str(markdown), encoding="utf-8")

    @staticmethod
    def _resolve_to_markdown() -> Callable[..., object]:
        """Return the current public converter.

        PyMuPDF4LLM 1.28's layout path now supports OCR and image extraction,
        so DeepTutor should use it instead of pinning the legacy helper and
        silently bypassing upstream improvements.
        """
        import pymupdf4llm

        return pymupdf4llm.to_markdown

    @staticmethod
    def _portable_image_links(markdown: str, images_dir: Path) -> str:
        """Rewrite links pointing at extracted files to a relative ``images/<name>``.

        pymupdf4llm embeds the ``image_path`` prefix (often absolute) in each
        link; normalizing by basename is version-agnostic and keeps the cached
        markdown portable.
        """
        names = {p.name for p in images_dir.iterdir()} if images_dir.is_dir() else set()
        if not names:
            return markdown

        def _repl(match: re.Match[str]) -> str:
            alt, target = match.group(1), match.group(2)
            base = os.path.basename(target.replace("\\", "/"))
            if base in names:
                return f"![{alt}](images/{base})"
            return match.group(0)

        return _IMAGE_LINK_RE.sub(_repl, markdown)


__all__ = ["PyMuPDF4LLMParser"]
