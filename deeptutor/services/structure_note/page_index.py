from __future__ import annotations

from pathlib import Path
import re
from statistics import median

from .models import ImageCandidate, PageIndexPage, TextBlock, TitleCandidate

_HEADING_PATTERN = re.compile(r"^(\d+([.\-]\d+)*|[IVXLC]+|[A-Z])[\).:\s-]")


def _bbox_list(bbox: tuple[float, float, float, float] | list[float]) -> list[float]:
    return [float(value) for value in bbox]


def build_page_index(pdf_path: Path) -> list[PageIndexPage]:
    try:
        import fitz
    except ImportError as exc:  # pragma: no cover - dependency is runtime-required
        raise RuntimeError("PyMuPDF is required for Structure Note indexing.") from exc

    pages: list[PageIndexPage] = []
    document = fitz.open(pdf_path)
    try:
        for page_index, page in enumerate(document, start=1):
            raw = page.get_text("dict")
            blocks: list[TextBlock] = []
            title_candidates: list[TitleCandidate] = []
            image_candidates: list[ImageCandidate] = []
            font_sizes: list[float] = []
            max_font_size = 0.0

            for block in raw.get("blocks", []):
                block_type = int(block.get("type", 0))
                bbox = _bbox_list(block.get("bbox", [0, 0, 0, 0]))
                if block_type == 1:
                    width = float(bbox[2] - bbox[0])
                    height = float(bbox[3] - bbox[1])
                    page_area = max(page.rect.width * page.rect.height, 1.0)
                    image_candidates.append(
                        ImageCandidate(
                            candidate_id=f"img-{page_index}-{len(image_candidates) + 1}",
                            page_number=page_index,
                            bbox=bbox,
                            width=width,
                            height=height,
                            area_ratio=(width * height) / page_area,
                        )
                    )
                    continue

                lines = block.get("lines", [])
                for line in lines:
                    spans = line.get("spans", [])
                    text = "".join(str(span.get("text", "")) for span in spans).strip()
                    if not text:
                        continue
                    span_sizes = [float(span.get("size", 0.0) or 0.0) for span in spans]
                    line_font_size = max(span_sizes) if span_sizes else None
                    if line_font_size:
                        font_sizes.extend(span_sizes)
                        max_font_size = max(max_font_size, line_font_size)
                    line_bbox = _bbox_list(line.get("bbox", bbox))
                    blocks.append(
                        TextBlock(
                            text=text,
                            bbox=line_bbox,
                            font_size=line_font_size,
                        )
                    )

            size_median = median(font_sizes) if font_sizes else 0.0
            top_threshold = page.rect.height * 0.45
            for block in blocks:
                font_size = block.font_size or 0.0
                heading_like = bool(_HEADING_PATTERN.match(block.text))
                large_enough = font_size >= max(size_median + 1.5, max_font_size * 0.82, 11.5)
                near_top = block.bbox[1] <= top_threshold
                if len(block.text) > 160:
                    continue
                if not (heading_like or (large_enough and near_top)):
                    continue
                title_candidates.append(
                    TitleCandidate(
                        text=block.text,
                        page_number=page_index,
                        bbox=block.bbox,
                        font_size=font_size or None,
                        score=round((font_size or 0.0) + (3 if heading_like else 0), 3),
                    )
                )

            page_text = "\n".join(block.text for block in blocks).strip()
            pages.append(
                PageIndexPage(
                    page_number=page_index,
                    width=float(page.rect.width),
                    height=float(page.rect.height),
                    text=page_text,
                    text_blocks=blocks,
                    title_candidates=title_candidates,
                    image_candidates=image_candidates,
                )
            )
    finally:
        document.close()

    return pages
