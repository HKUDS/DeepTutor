"""LiteParse engine adapter implementing the ``Parser`` protocol.

LiteParse (run-llama/liteparse) is a Rust-backed PDF/Office/image parser: no
model weights, no CUDA, in-process. Like the PyMuPDF4LLM engine it can extract
embedded images, so it follows the same workdir contract — one
``<stem>.md`` plus an ``images/`` dir with portable ``images/<name>`` links
(the MinerU/Docling asset convention the cache loader expects).

Two of LiteParse's own defaults are overridden here rather than exposed:
``output_format`` is pinned to Markdown (the workdir contract is a ``.md``
file, so JSON or plain text would produce a mislabelled document), and
``image_output_dir`` is pinned to the workdir's ``images/`` (anywhere else is
invisible to the cache loader).
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
import re
from typing import Any, Callable, Optional

from ...base import ReadinessReport
from ...signature import ParserSignature
from ...types import ParserError
from .._versions import package_version
from .config import LiteParseConfig, resolve_liteparse_config

# Document and image types LiteParse decodes natively. Office formats and bare
# images are converted internally before parsing.
_SUPPORTED = frozenset(
    {".pdf", ".docx", ".pptx", ".xlsx", ".png", ".jpg", ".jpeg", ".gif", ".webp"}
)

# LiteParse references extracted images by bare file name — ``![](img_p1_1.png)``
# — so links are rewritten to ``images/<name>`` to match the asset convention.
_IMAGE_LINK_RE = re.compile(r"!\[([^\]]*)\]\(([^)]+)\)")


class LiteParseParser:
    """PDF/Office/image → Markdown via liteparse (no models, optional images)."""

    name = "liteparse"
    needs_local_models = False

    @classmethod
    def is_available(cls) -> bool:
        return importlib.util.find_spec("liteparse") is not None

    def resolve_config(self) -> LiteParseConfig:
        return resolve_liteparse_config()

    def supported_formats(self) -> frozenset[str]:
        return _SUPPORTED

    def signature(self, config: LiteParseConfig) -> ParserSignature:
        return ParserSignature.build(
            "liteparse",
            package_version("liteparse"),
            {
                "image_mode": config.image_mode,
                "extract_links": config.extract_links,
                "extract_images": config.extract_images,
                "max_pages": config.max_pages,
            },
        )

    def is_ready(self, config: LiteParseConfig) -> ReadinessReport:
        if not self.is_available():
            return ReadinessReport(
                ready=False,
                reason="not_configured",
                message="liteparse isn't installed (pip install deeptutor[parse-liteparse]).",
            )
        return ReadinessReport(ready=True)

    def parse(
        self,
        source_path: Path,
        workdir: Path,
        *,
        config: LiteParseConfig,
        on_output: Optional[Callable[[str], None]] = None,
    ) -> None:
        from liteparse import LiteParse

        source_path = Path(source_path)
        workdir = Path(workdir)
        if on_output:
            on_output(f"Converting {source_path.name} via LiteParse…")

        images_dir = workdir / "images"
        kwargs: dict[str, Any] = {
            "output_format": "markdown",
            "image_mode": config.image_mode,
            "extract_links": config.extract_links,
            "quiet": True,
            # A systemic OCR failure aborts the whole parse by default. Prefer
            # the natively recovered text over losing the document outright —
            # the ingestion pipeline treats a ParserError as "no content".
            "ocr_failure_fatal": False,
        }
        if config.extract_images:
            images_dir.mkdir(parents=True, exist_ok=True)
            kwargs["extract_images"] = True
            kwargs["image_output_dir"] = str(images_dir)
        if config.max_pages > 0:
            kwargs["max_pages"] = config.max_pages

        try:
            result = LiteParse(**kwargs).parse(str(source_path))
        except Exception as exc:  # noqa: BLE001 - surface as a parser error
            raise ParserError(f"LiteParse failed to convert {source_path.name}: {exc}") from exc

        markdown = str(getattr(result, "text", "") or "")
        if config.extract_images:
            markdown = self._portable_image_links(markdown, getattr(result, "images", None))
            # Drop the images dir if nothing was actually extracted, so the
            # cache loader doesn't report an empty asset_dir.
            if images_dir.is_dir() and not any(images_dir.iterdir()):
                images_dir.rmdir()

        (workdir / f"{source_path.stem}.md").write_text(markdown, encoding="utf-8")

    @staticmethod
    def _portable_image_links(markdown: str, images: Any) -> str:
        """Prefix links naming an extracted image with the ``images/`` dir.

        Only names LiteParse reports as extracted are rewritten, so a link the
        document itself carried to an unrelated URL is left alone.
        """
        names = {
            name for image in (images or []) if (name := str(getattr(image, "name", "") or ""))
        }
        if not names:
            return markdown

        def _repl(match: re.Match[str]) -> str:
            alt, target = match.group(1), match.group(2)
            return f"![{alt}](images/{target})" if target in names else match.group(0)

        return _IMAGE_LINK_RE.sub(_repl, markdown)


__all__ = ["LiteParseParser"]
