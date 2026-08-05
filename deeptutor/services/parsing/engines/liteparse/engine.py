"""liteparse engine adapter implementing the `Parser` protocol.

LiteParse is a fast, lightweight PDF/document parser with spatial text
extraction. It outputs Markdown (default), JSON, or plain text, and can
extract embedded images. Developed by LlamaIndex (Logan Markewich).
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from typing import Callable, Optional

from ...base import ReadinessReport
from ...signature import ParserSignature
from ...types import ParserError
from .._versions import package_version
from .config import LiteParseConfig, resolve_liteparse_config

_SUPPORTED = frozenset({".pdf", ".docx", ".pptx", ".xlsx", ".png", ".jpg", ".jpeg", ".gif", ".webp"})


class LiteParseParser:
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
                "output_format": config.output_format,
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
            on_output(f"Converting {source_path.name} via liteparse...")

        kwargs: dict[str, object] = {
            "output_format": config.output_format,
            "image_mode": config.image_mode,
            "extract_links": config.extract_links,
        }
        if config.extract_images and config.image_output_dir:
            images_dir = workdir / config.image_output_dir
            images_dir.mkdir(parents=True, exist_ok=True)
            kwargs["extract_images"] = True
            kwargs["image_output_dir"] = str(images_dir)
        if config.max_pages > 0:
            kwargs["max_pages"] = config.max_pages

        try:
            parser = LiteParse(**kwargs)
            result = parser.parse(str(source_path))
            markdown = result.text if result.text else ""
        except Exception as exc:
            raise ParserError(f"liteparse failed to convert {source_path.name}: {exc}")

        (workdir / f"{source_path.stem}.md").write_text(str(markdown), encoding="utf-8")


__all__ = ["LiteParseParser"]
