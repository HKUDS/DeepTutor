from __future__ import annotations

from pathlib import Path
import re

from .models import CitationEntry, GenerationChunk, ImagePlaceholder, PageIndexPage

_PLACEHOLDER_RE = re.compile(
    r"\[\[IMAGE_PLACEHOLDER:(?P<placeholder_id>[^:\]]+):(?P<page_hint>\d+):(?P<purpose>[^\]]+)\]\]"
)


def _pages_map(pages: list[PageIndexPage]) -> dict[int, PageIndexPage]:
    return {page.page_number: page for page in pages}


def _figure_caption(chunk: GenerationChunk, page_number: int | None, language: str) -> str:
    topic = (chunk.section_summary or chunk.section_title).strip()
    if len(topic) > 120:
        topic = f"{topic[:120].rstrip()}..."
    if language == "zh":
        source = f"第 {page_number} 页" if page_number else "对应页"
        return (
            f"图示来源：{source}。该图对应本节“{chunk.section_title}”的核心内容："
            f"{topic or '结构、过程或关键例子'}"
        )
    source = f"page {page_number}" if page_number else "the source page"
    return (
        f"Figure from {source}. It supports the explanation of {chunk.section_title} by showing "
        f"{topic or 'the structure, process, or key example'} discussed in the section."
    )


def _render_page_crop(
    pdf_path: Path, page_number: int, output_path: Path, clip: list[float] | None = None
) -> None:
    import fitz

    document = fitz.open(pdf_path)
    try:
        page = document[page_number - 1]
        rect = fitz.Rect(clip) if clip else page.rect
        pix = page.get_pixmap(matrix=fitz.Matrix(2, 2), clip=rect, alpha=False)
        pix.save(output_path)
    finally:
        document.close()


def process_images(
    chunks: list[GenerationChunk],
    pages: list[PageIndexPage],
    pdf_path: Path,
    images_dir: Path,
    source_file: str,
    language: str = "en",
) -> tuple[list[GenerationChunk], list[ImagePlaceholder], list[CitationEntry]]:
    images_dir.mkdir(parents=True, exist_ok=True)
    page_lookup = _pages_map(pages)
    placeholders: list[ImagePlaceholder] = []
    citations: list[CitationEntry] = []

    for chunk in chunks:
        if not chunk.placeholder_ids:
            continue

        def replace(match: re.Match[str]) -> str:
            placeholder_id = match.group("placeholder_id")
            page_hint = int(match.group("page_hint"))
            purpose = match.group("purpose")
            candidates = []
            for page_number in chunk.page_numbers:
                page = page_lookup.get(page_number)
                if not page:
                    continue
                candidates.extend(page.image_candidates)

            placeholder = ImagePlaceholder(
                placeholder_id=placeholder_id,
                chunk_id=chunk.chunk_id,
                page_hint=page_hint,
                purpose=purpose,
            )

            image_name = f"{placeholder_id}.png"
            image_path = images_dir / image_name
            markdown_image_path = f"images/{image_name}"

            try:
                if len(candidates) == 1:
                    candidate = candidates[0]
                    _render_page_crop(pdf_path, candidate.page_number, image_path, candidate.bbox)
                    placeholder.status = "filled"
                    placeholder.image_path = markdown_image_path
                    placeholder.resolved_page = candidate.page_number
                    placeholder.resolved_region = candidate.bbox
                else:
                    fallback_page = page_hint if page_hint in page_lookup else chunk.page_start
                    _render_page_crop(pdf_path, fallback_page, image_path, None)
                    placeholder.status = "fallback_page"
                    placeholder.image_path = markdown_image_path
                    placeholder.resolved_page = fallback_page
                    placeholder.resolved_region = None

                placeholders.append(placeholder)
                citations.append(
                    CitationEntry(
                        citation_id=f"cite-{placeholder_id}",
                        section_path=chunk.section_path,
                        page_start=chunk.page_start,
                        page_end=chunk.page_end,
                        source_file=source_file,
                        source_kind="image",
                        image_page=placeholder.resolved_page,
                        image_region=placeholder.resolved_region,
                        excerpt=purpose,
                    )
                )
                caption = _figure_caption(chunk, placeholder.resolved_page, language)
                return f"![{purpose}]({markdown_image_path})\n\n*{caption}*"
            except Exception as exc:
                placeholder.status = "fallback_text"
                placeholder.error = str(exc)
                placeholders.append(placeholder)
                return (
                    "> Figure reference unavailable for this page range."
                    if language != "zh"
                    else "> 当前页范围的图片引用暂不可用。"
                )

        chunk.markdown = _PLACEHOLDER_RE.sub(replace, chunk.markdown)

    return chunks, placeholders, citations
