from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
import importlib
import json
import os
from pathlib import Path
import sys
import threading
from typing import Any

from .models import ImageCandidate, PageIndexPage, SectionTreeNode, TextBlock, TitleCandidate

VECTIFY_PAGEINDEX_RAW_FILENAME = "vectify_pageindex.json"

_REPO_ROOT = Path(__file__).resolve().parents[3]
_VECTIFY_PAGEINDEX_ROOT = _REPO_ROOT / "third_party" / "PageIndex"
_PAGEINDEX_LOCK = threading.Lock()
_PageIndexRunner = Callable[..., dict[str, Any]]


@dataclass(frozen=True)
class PageIndexBuildResult:
    pages: list[PageIndexPage]
    section_tree: list[SectionTreeNode]
    raw: dict[str, Any]


def _bbox_list(bbox: tuple[float, float, float, float] | list[float]) -> list[float]:
    return [float(value) for value in bbox]


def _coerce_int(value: object, default: int) -> int:
    if isinstance(value, str):
        value = value.strip()
        if value.startswith("<physical_index_"):
            value = value.removeprefix("<physical_index_").removesuffix(">")
        elif value.startswith("physical_index_"):
            value = value.removeprefix("physical_index_")
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default


def _bounded_page(value: object, *, default: int, total_pages: int) -> int:
    if total_pages <= 0:
        return default
    page = _coerce_int(value, default)
    return max(1, min(total_pages, page))


def _normalize_raw_result(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        structure = raw.get("structure")
        if isinstance(structure, list):
            return raw
        if raw.get("title") and raw.get("start_index"):
            return {"structure": [raw]}
    if isinstance(raw, list):
        return {"structure": raw}
    raise RuntimeError("VectifyAI PageIndex returned an unsupported result shape.")


def _load_vectify_pageindex_module() -> Any:
    if not (_VECTIFY_PAGEINDEX_ROOT / "pageindex").exists():
        raise RuntimeError(
            "VectifyAI PageIndex submodule is missing. "
            "Run `git submodule update --init --recursive third_party/PageIndex`."
        )
    root = str(_VECTIFY_PAGEINDEX_ROOT)
    if root not in sys.path:
        sys.path.insert(0, root)
    try:
        return importlib.import_module("pageindex.page_index")
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "VectifyAI PageIndex dependencies are not installed. "
            "Install the Structure Note dependencies including litellm, PyPDF2, "
            "PyMuPDF, python-dotenv, and pyyaml."
        ) from exc


def _resolve_pageindex_model(model: str | None) -> str | None:
    if model:
        return model
    env_model = os.getenv("DEEPTUTOR_PAGEINDEX_MODEL")
    if env_model:
        return env_model

    try:
        from deeptutor.services.llm import get_llm_client, get_llm_config

        config = get_llm_config()
        get_llm_client(config)
        api_key = getattr(config, "api_key", None)
        base_url = getattr(config, "base_url", None)
        if api_key and not os.getenv("OPENAI_API_KEY"):
            os.environ["OPENAI_API_KEY"] = str(api_key)
        if base_url and not os.getenv("OPENAI_BASE_URL"):
            os.environ["OPENAI_BASE_URL"] = str(base_url)
        return str(config.model) if config.model else None
    except Exception:
        return None


def _safe_stem(value: object) -> str:
    stem = Path(str(value)).name or "pageindex"
    return "".join(char if char.isalnum() or char in ".-_" else "-" for char in stem)


def _logger_class(log_dir: Path) -> type:
    class PageIndexJsonLogger:
        def __init__(self, file_path: object) -> None:
            log_dir.mkdir(parents=True, exist_ok=True)
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            self._path = log_dir / f"{_safe_stem(file_path)}_{timestamp}.json"
            self._items: list[object] = []

        def log(self, _level: str, message: object, **_kwargs: object) -> None:
            self._items.append(message if isinstance(message, dict) else {"message": str(message)})
            self._path.write_text(
                json.dumps(self._items, indent=2, ensure_ascii=False, default=str),
                encoding="utf-8",
            )

        def info(self, message: object, **kwargs: object) -> None:
            self.log("INFO", message, **kwargs)

        def error(self, message: object, **kwargs: object) -> None:
            self.log("ERROR", message, **kwargs)

        def debug(self, message: object, **kwargs: object) -> None:
            self.log("DEBUG", message, **kwargs)

        def exception(self, message: object, **kwargs: object) -> None:
            self.log("ERROR", message, **kwargs)

    return PageIndexJsonLogger


@contextmanager
def _patched_pageindex_logger(module: Any, log_dir: Path | None) -> Iterator[None]:
    original = getattr(module, "JsonLogger", None)
    if original is None or log_dir is None:
        yield
        return
    module.JsonLogger = _logger_class(log_dir)
    try:
        yield
    finally:
        module.JsonLogger = original


def _run_vectify_pageindex(
    pdf_path: Path,
    *,
    model: str | None = None,
    work_dir: Path | None = None,
    pageindex_runner: _PageIndexRunner | None = None,
) -> dict[str, Any]:
    resolved_model = _resolve_pageindex_model(model)
    kwargs: dict[str, object] = {
        "model": resolved_model,
        "if_add_node_id": "yes",
        "if_add_node_summary": "yes",
        "if_add_doc_description": "yes",
        "if_add_node_text": "no",
    }

    if pageindex_runner is not None:
        return _normalize_raw_result(pageindex_runner(str(pdf_path), **kwargs))

    module = _load_vectify_pageindex_module()
    log_dir = (work_dir or pdf_path.parent) / "pageindex_logs"
    with _PAGEINDEX_LOCK:
        with _patched_pageindex_logger(module, log_dir):
            raw = module.page_index(str(pdf_path), **kwargs)
    return _normalize_raw_result(raw)


def _extract_page_artifacts(pdf_path: Path) -> list[PageIndexPage]:
    try:
        import fitz
    except ImportError as exc:  # pragma: no cover - dependency is runtime-required
        raise RuntimeError("PyMuPDF is required for Structure Note page evidence.") from exc

    pages: list[PageIndexPage] = []
    document = fitz.open(pdf_path)
    try:
        for page_index, page in enumerate(document, start=1):
            raw = page.get_text("dict")
            blocks: list[TextBlock] = []
            image_candidates: list[ImageCandidate] = []

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

                for line in block.get("lines", []):
                    spans = line.get("spans", [])
                    text = "".join(str(span.get("text", "")) for span in spans).strip()
                    if not text:
                        continue
                    span_sizes = [float(span.get("size", 0.0) or 0.0) for span in spans]
                    blocks.append(
                        TextBlock(
                            text=text,
                            bbox=_bbox_list(line.get("bbox", bbox)),
                            font_size=max(span_sizes) if span_sizes else None,
                        )
                    )

            pages.append(
                PageIndexPage(
                    page_number=page_index,
                    width=float(page.rect.width),
                    height=float(page.rect.height),
                    text="\n".join(block.text for block in blocks).strip(),
                    text_blocks=blocks,
                    title_candidates=[],
                    image_candidates=image_candidates,
                )
            )
    finally:
        document.close()

    return pages


def _iter_structure_nodes(structure: object, level: int = 2) -> Iterator[tuple[dict[str, Any], int]]:
    if isinstance(structure, dict):
        yield structure, level
        children = structure.get("nodes") or []
        yield from _iter_structure_nodes(children, level + 1)
    elif isinstance(structure, list):
        for item in structure:
            yield from _iter_structure_nodes(item, level)


def _attach_pageindex_title_candidates(
    pages: list[PageIndexPage],
    structure: object,
) -> None:
    page_lookup = {page.page_number: page for page in pages}
    seen: set[tuple[int, str]] = set()
    for raw_node, level in _iter_structure_nodes(structure):
        title = str(raw_node.get("title") or "").strip()
        if not title:
            continue
        page_number = _coerce_int(raw_node.get("start_index"), 0)
        page = page_lookup.get(page_number)
        if page is None:
            continue
        key = (page_number, title)
        if key in seen:
            continue
        seen.add(key)
        page.title_candidates.append(
            TitleCandidate(
                text=title,
                page_number=page_number,
                bbox=[],
                font_size=None,
                score=max(1.0, 100.0 - float(level)),
            )
        )


def pages_from_pageindex_raw(pdf_path: Path, raw: dict[str, Any]) -> list[PageIndexPage]:
    normalized = _normalize_raw_result(raw)
    pages = _extract_page_artifacts(pdf_path)
    _attach_pageindex_title_candidates(pages, normalized.get("structure") or [])
    return pages


def sections_from_pageindex_raw(
    raw: dict[str, Any],
    *,
    total_pages: int,
) -> list[SectionTreeNode]:
    normalized = _normalize_raw_result(raw)
    return sections_from_pageindex_structure(normalized.get("structure") or [], total_pages)


def sections_from_pageindex_structure(
    structure: object,
    total_pages: int,
) -> list[SectionTreeNode]:
    if total_pages <= 0:
        return []

    nodes: list[SectionTreeNode] = []
    counter = 0

    def visit(
        raw_items: object,
        *,
        parent_id: str | None,
        level: int,
        path: list[str],
    ) -> list[str]:
        nonlocal counter
        child_ids: list[str] = []
        items = raw_items if isinstance(raw_items, list) else [raw_items]
        for raw in items:
            if not isinstance(raw, dict):
                continue
            title = str(raw.get("title") or "").strip()
            if not title:
                continue

            page_start = _bounded_page(raw.get("start_index"), default=1, total_pages=total_pages)
            page_end = _bounded_page(raw.get("end_index"), default=page_start, total_pages=total_pages)
            if page_end < page_start:
                page_end = page_start

            counter += 1
            section_id = f"section-{counter:03d}"
            section_path = [*path, title]
            node = SectionTreeNode(
                section_id=section_id,
                title=title,
                level=max(2, min(level, 5)),
                page_start=page_start,
                page_end=page_end,
                summary=str(raw.get("summary") or "").strip(),
                parent_id=parent_id,
                child_ids=[],
                path=section_path,
            )
            nodes.append(node)
            child_ids.append(section_id)
            node.child_ids = visit(
                raw.get("nodes") or [],
                parent_id=section_id,
                level=level + 1,
                path=section_path,
            )
        return child_ids

    visit(structure, parent_id=None, level=2, path=[])
    if nodes:
        return nodes
    return [
        SectionTreeNode(
            section_id="section-001",
            title="Document",
            level=2,
            page_start=1,
            page_end=total_pages,
            path=["Document"],
        )
    ]


def build_page_index_bundle(
    pdf_path: Path,
    *,
    model: str | None = None,
    work_dir: Path | None = None,
    pageindex_runner: _PageIndexRunner | None = None,
) -> PageIndexBuildResult:
    raw = _run_vectify_pageindex(
        Path(pdf_path),
        model=model,
        work_dir=work_dir,
        pageindex_runner=pageindex_runner,
    )
    pages = pages_from_pageindex_raw(Path(pdf_path), raw)
    section_tree = sections_from_pageindex_raw(raw, total_pages=len(pages))
    return PageIndexBuildResult(pages=pages, section_tree=section_tree, raw=raw)


def build_page_index(pdf_path: Path) -> list[PageIndexPage]:
    return build_page_index_bundle(Path(pdf_path)).pages


__all__ = [
    "PageIndexBuildResult",
    "VECTIFY_PAGEINDEX_RAW_FILENAME",
    "build_page_index",
    "build_page_index_bundle",
    "pages_from_pageindex_raw",
    "sections_from_pageindex_raw",
    "sections_from_pageindex_structure",
]
