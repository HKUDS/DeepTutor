"""教材全自动化管线（P7）—— upload→parse→canonicalize→import 事件链.

老师把教材 PDF 丢进一个开了 ``auto_pipeline`` 开关的 KB，upload 处理任务
成功的尾部自动接力剩下的全部环节::

    raw（upload 已落 raw/）
      → parsed      ParseService.parse（内容寻址缓存，命中即复用）
      → canonicalized  /books/canonicalize（页脚法+页眉法 layout_json 优先；
                       mode="auto" 时 0 章降级走 enrich 树转 toc，返回标注
                       mode="legacy_toc"；mode="faithful" 强制保真、0 章
                       fail-loud —— 附录降级表）
      → figures     figure_backfill 编程入口（plan + apply，--apply 语义）
      → latex       latex_delimit.fix_book（裸 LaTeX 补定界）
      → imported    import-from-book（canonical KP 树优先 → 目级模块）
      → tree        canonical_kp_tree 落书 manifest（确认在保真路径也生效）
      → share       （可选）授权用户列表 share read；KB grants 经 canonicalize
                    的 knowledge_bases=[KB] 关联自带
      → qb          learning/ingest_pipeline.start_pipeline 四段一体（书锚定）

全程无人工接力。每段状态落在 KB manifest（kb_config.json 里该 KB 条目的
``metadata`` 字典）的 ``pipeline`` 键下，按文件名各存一份；状态端点
``GET /knowledge-bases/{kb}/pipeline`` 直接读它，不做二次推断。

两个契约：

* **显式开关**：只有 ``manifest.metadata.auto_pipeline`` 为真才触发。存量
  KB 缺省为假，上传行为与现状逐字节一致（回归红线）。
* **失败隔离**：任一段失败只把该文件的状态置 ``error`` + 原因，不中断同批
  其他文件，也绝不把 upload 任务本身拖成失败。
"""

from __future__ import annotations

import asyncio
from datetime import datetime
import json
import logging
from pathlib import Path
from typing import Any, Callable

from deeptutor.knowledge.manager import KnowledgeBaseManager

logger = logging.getLogger(__name__)

#: KB manifest（kb_config.json 条目）里打开事件链的开关键。
AUTO_PIPELINE_FLAG = "auto_pipeline"
#: KB manifest.metadata 里挂每文件管线状态的键。
PIPELINE_KEY = "pipeline"

#: 状态端点按此顺序返回各段；前两段由 upload/parse 写入，其余由本模块写入。
#: figures/latex 是增强段（失败记入段内 error 但不拦后续段），qb 是核心段。
STAGE_KEYS = ("raw", "parsed", "canonicalized", "imported", "figures", "latex", "qb")

LogFn = Callable[..., None]


# ─────────────────────────────────────────────────────────────────────────────
# KB manifest（kb_config.json 条目）读写
# ─────────────────────────────────────────────────────────────────────────────


def _manager_for(base_dir: str | Path | None) -> KnowledgeBaseManager:
    """Resolve the KB manager for ``base_dir``.

    The upload task passes its own ``base_dir`` through; tests inject a temp
    dir the same way. ``None`` falls back to the current workspace's KB root
    (multi-user aware, like every other consumer of the manager).
    """
    if base_dir is not None:
        return KnowledgeBaseManager(base_dir=str(base_dir))
    from deeptutor.multi_user.knowledge_access import current_kb_manager

    return current_kb_manager()


def read_kb_metadata(kb_name: str, *, base_dir: str | Path | None = None) -> dict[str, Any]:
    """The KB manifest's ``metadata`` dict — ``{}`` when absent/unreadable."""
    try:
        manager = _manager_for(base_dir)
        manager.config = manager._load_config()
        entry = manager.config.get("knowledge_bases", {}).get(kb_name) or {}
        metadata = entry.get("metadata")
        return dict(metadata) if isinstance(metadata, dict) else {}
    except Exception:  # noqa: BLE001 — a broken manifest reads as "no state"
        logger.warning("auto pipeline: unreadable manifest for KB %s", kb_name, exc_info=True)
        return {}


def auto_pipeline_enabled(kb_name: str, *, base_dir: str | Path | None = None) -> bool:
    """True only when the KB manifest explicitly turns the chain on.

    Missing flag, ``false``, or a truthy-looking string like ``"false"`` all
    read as off — the default must stay off so existing KBs keep their exact
    current upload behaviour. A non-empty options dict (per
    :func:`read_chain_options`) also turns the chain on.
    """
    flag = read_kb_metadata(kb_name, base_dir=base_dir).get(AUTO_PIPELINE_FLAG)
    return flag is True or (isinstance(flag, dict) and bool(flag))


def read_chain_options(kb_name: str, *, base_dir: str | Path | None = None) -> dict[str, Any]:
    """The chain's tunables, read from the KB manifest's ``auto_pipeline`` flag.

    ``True`` keeps the defaults (mode auto / 题库 on / 不共享)；a dict may carry
    ``mode``（"auto"|"faithful"）、``enable_qb``、``share_read_users``. Unknown
    values fall back to the defaults instead of erroring — the manifest is a
    config surface, not a failure point.
    """
    flag = read_kb_metadata(kb_name, base_dir=base_dir).get(AUTO_PIPELINE_FLAG)
    opts = flag if isinstance(flag, dict) else {}
    mode = str(opts.get("mode") or "").strip().lower()
    users = opts.get("share_read_users")
    return {
        "mode": mode if mode in ("auto", "faithful") else "auto",
        "enable_qb": bool(opts.get("enable_qb", True)),
        "share_read_users": [str(u).strip() for u in users or [] if str(u).strip()],
    }


def read_pipeline_state(
    kb_name: str, *, base_dir: str | Path | None = None
) -> dict[str, dict[str, Any]]:
    """Every file's pipeline record written so far, keyed by file name."""
    pipeline = read_kb_metadata(kb_name, base_dir=base_dir).get(PIPELINE_KEY)
    return dict(pipeline) if isinstance(pipeline, dict) else {}


def record_stage(
    kb_name: str,
    filename: str,
    stage: str,
    *,
    payload: dict[str, Any] | None = None,
    error: str | None = None,
    base_dir: str | Path | None = None,
) -> dict[str, Any]:
    """Persist one stage's outcome for ``filename`` into the KB manifest.

    On success the stage slot carries a timestamp plus whatever the caller
    produced (book id, parse workdir, module count…). On failure the whole
    file's record flips to ``status: error`` with the reason, leaving the
    stages that already succeeded intact for the status endpoint to show.
    """
    manager = _manager_for(base_dir)
    manager.config = manager._load_config()
    entry = manager.config.setdefault("knowledge_bases", {}).setdefault(kb_name, {"path": kb_name})
    pipeline = entry.setdefault("metadata", {}).setdefault(PIPELINE_KEY, {})
    record = pipeline.get(filename) if isinstance(pipeline.get(filename), dict) else {}
    record = {"file": filename, **record}
    now = datetime.now().isoformat()
    record["updated_at"] = now
    if error is not None:
        record["status"] = "error"
        record["error"] = str(error)[:500]
        record[f"{stage}_error"] = str(error)[:500]
    else:
        record["status"] = "ok"
        record.pop("error", None)
        record[stage] = {"at": now, **(payload or {})}
    pipeline[filename] = record
    manager._save_config()
    return record


# ─────────────────────────────────────────────────────────────────────────────
# canonicalize 输入构建（wave2-batch / tier-rebuild-all 补丁脚本的产品化）
# ─────────────────────────────────────────────────────────────────────────────


class AutoPipelineError(RuntimeError):
    """One stage of the chain failed — the message lands in the file's state."""


def _clean_title(stem: str) -> str:
    """The book title from the PDF stem: ``人教A版2019-必修第一册`` → spaces.

    Mirrors the batch drivers: hyphens were name-mangling, not prose.
    """
    title = stem.strip()
    if "人教A版2019-" in title:
        title = title.replace("人教A版2019-", "").replace("-", " ")
    return title.replace("-", " ").strip() or stem


def _book_dir_of(workdir: str | Path) -> Path:
    """The parse product dir: ``sig/<stem>/`` layer, else the workdir itself."""
    workdir = Path(workdir)
    subdirs = [d for d in workdir.iterdir() if d.is_dir()] if workdir.is_dir() else []
    candidate = subdirs[0] if len(subdirs) == 1 and any(subdirs[0].glob("*.md")) else workdir
    if not any(candidate.glob("*.md")):
        raise AutoPipelineError(f"parse 产物目录无 md: {candidate}")
    return candidate


def _layout_from(book_dir: Path) -> dict[str, Any] | None:
    """The MinerU layout dict: whole-book ``layout.json``, or part files merged.

    Part splits (大部头) each carry their own ``pdf_info`` — renumber the
    pages into one sequence so the 页脚法 sees a whole book.
    """
    whole = book_dir / "layout.json"
    if whole.is_file():
        try:
            layout = json.loads(whole.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        return layout if isinstance(layout, dict) else None

    parts = sorted(book_dir.glob("part*_layout.json"))
    if not parts:
        return None
    first: dict[str, Any] | None = None
    pages: list[dict[str, Any]] = []
    for part in parts:
        try:
            payload = json.loads(part.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        if first is None and isinstance(payload, dict):
            first = {k: v for k, v in payload.items() if k != "pdf_info"}
        for page in payload.get("pdf_info") or []:
            page["page_idx"] = len(pages)
            pages.append(page)
    if first is None or not pages:
        return None
    first["pdf_info"] = pages
    return first


def _tree_to_toc(children: list[dict[str, Any]] | None) -> list[dict[str, Any]]:
    """Convert a doc_intel tree into the canonicalize endpoint's TOC shape.

    The 附录降级表's fallback: 页脚法 0 章（教师用书/异版式）时把 enrich 树转
    toc 建书 —— 可能无页内容，status 如实。
    """

    def convert(node: dict[str, Any]) -> dict[str, Any] | None:
        title = str(node.get("title") or "").strip()
        if not title:
            return None
        item: dict[str, Any] = {"title": title}
        kids = [
            converted
            for child in node.get("children") or []
            if isinstance(child, dict) and (converted := convert(child)) is not None
        ]
        if kids:
            item["children"] = kids
        return item

    roots = [
        converted
        for unit in children or []
        if isinstance(unit, dict) and (converted := convert(unit)) is not None
    ]
    return roots


def _page_specs_from_layout(
    layout: dict[str, Any], chapters: list[Any], title: str
) -> list[dict[str, Any]]:
    """Verbatim per-page reading blocks under each 页脚法 chapter.

    Same shape the batch drivers posted: one spec per rebuilt chapter, one
    page per ``页N``, body = the page's own text joined by blank lines.
    """
    from deeptutor.textbook_struct.chapter_rebuild import block_text

    pages = layout.get("pdf_info") or []

    def page_text(page: dict[str, Any]) -> str:
        parts = []
        for block in page.get("para_blocks") or []:
            if not isinstance(block, dict) or block.get("type") == "image":
                continue
            text = block_text(block)
            if text:
                parts.append(text)
        return "\n\n".join(parts)

    specs: list[dict[str, Any]] = []
    for index, chapter in enumerate(chapters):
        specs_pages: list[dict[str, Any]] = []
        for pno in range(chapter.page_idx + 1, (chapter.end_page_idx or 0) + 1):
            if pno >= len(pages):
                break
            text = page_text(pages[pno])
            if not text.strip():
                continue
            specs_pages.append(
                {
                    "title": f"页{pno + 1}",
                    "blocks": [
                        {
                            "block_type": "reading",
                            "params": {
                                "body": text,
                                "variant": "prose",
                                "source_label": f"{title} p{pno + 1}",
                            },
                        }
                    ],
                }
            )
        if specs_pages:
            specs.append({"chapter_index": index, "pages": specs_pages})
    return specs


def _enrich_tree(book_dir: Path, filename: str) -> dict[str, Any] | None:
    """The doc_intel tree rebuilt from the parse product's content_list."""
    blocks: list[dict[str, Any]] = []
    for cl in sorted(book_dir.glob("*_content_list.json")):
        if cl.name.endswith("_v2.json"):
            continue
        try:
            payload = json.loads(cl.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if isinstance(payload, list):
            blocks.extend(item for item in payload if isinstance(item, dict))
    if not blocks:
        return None
    from deeptutor.knowledge.doc_intel.enrich import enrich

    markdown = ""
    md = next(iter(book_dir.glob("*.md")), None)
    if md is not None:
        markdown = md.read_text(encoding="utf-8")[:5000]
    try:
        result = enrich(blocks, markdown=markdown, filename=filename, doc_id="")
    except Exception:  # noqa: BLE001 — the tree is an optimization, never required
        logger.warning("auto pipeline: enrich failed for %s", filename, exc_info=True)
        return None
    tree = result.get("tree")
    return tree if isinstance(tree, dict) and tree.get("children") else None


# ─────────────────────────────────────────────────────────────────────────────
# 事件链本体
# ─────────────────────────────────────────────────────────────────────────────


FAITHFUL_FAIL_GUIDANCE = (
    "页眉/页脚法识别 0 章：该 PDF 无法识别章节结构"
    "（缺『第N章/第N课』式页眉页脚，或非教材版式）。"
    "faithful 模式拒绝降级为 AI 生成路径；"
    "请改用 mode='auto' 走 legacy_toc 兜底，或补齐 PDF 页眉页脚后重跑"
)


async def _canonicalize_stage(
    kb_name: str, path: Path, parsed: Any, *, book_storage: Any, canonicalize: Any, mode: str
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    """canonicalize one parsed textbook: 保真法优先，0 章按 mode 分流.

    ``mode="faithful"``（教材场景）0 章/0 页直接 fail-loud，绝不静默落 AI
    生成路径；``mode="auto"``（缺省）降级 enrich 树转 toc 建书并在返回里标注
    ``mode="legacy_toc"``。``canonicalize`` is the ``/books/canonicalize``
    endpoint callable (plus its ``CanonicalizeRequest`` model), injected by
    the adapter that kicks the chain off — domain code here never imports the
    API layer. Returns ``(summary, layout)``; layout is threaded out so the
    post-import tree-cache step can inline-rebuild from it.
    """
    from deeptutor.book.canonical_tree import canonical_tree_from_doc_trees

    canonicalize_book, CanonicalizeRequest = canonicalize
    book_dir = _book_dir_of(parsed.workdir)
    title = _clean_title(path.stem)
    layout = _layout_from(book_dir)

    specs: list[dict[str, Any]] = []
    toc: list[dict[str, Any]] = []
    if layout is not None:
        # 页脚法+页眉法: chapters from the running headers, pages from ranges.
        # 0 章 → 概述锚定法兜底（仅 en/英语书启用，见 chapter_rebuild.rebuild_with_fallback）。
        from deeptutor.textbook_struct.chapter_rebuild import rebuild_with_fallback

        chapters = await asyncio.to_thread(rebuild_with_fallback, layout, title=title)
        specs = await asyncio.to_thread(_page_specs_from_layout, layout, chapters, title)

    if specs:
        request = CanonicalizeRequest(
            title=title,
            source="layout_json",
            layout=layout,
            language="zh",
            knowledge_bases=[kb_name],
            metadata={"origin": "auto_pipeline", "parse_dir": str(book_dir)},
            chapters=specs,
        )
        source = "layout_json"
        chain_mode = "faithful"
    else:
        if mode == "faithful":
            raise AutoPipelineError(FAITHFUL_FAIL_GUIDANCE)
        # 降级表: 保真法 0 章（或无 layout）→ enrich 树转 toc 建书。
        tree = await asyncio.to_thread(_enrich_tree, book_dir, path.name)
        toc = _tree_to_toc((tree or {}).get("children"))
        if not toc:
            raise AutoPipelineError("页眉/页脚法 0 章且 enrich 树转 toc 为空")
        request = CanonicalizeRequest(
            title=title,
            source="toc_json",
            toc=toc,
            language="zh",
            knowledge_bases=[kb_name],
            metadata={"origin": "auto_pipeline", "parse_dir": str(book_dir)},
            chapters=[],
        )
        source = "toc_json"
        chain_mode = "legacy_toc"

    result = await canonicalize_book(request)
    book = result.get("book") or {}

    # canonical 树兜底落缓: the P0 hook inside canonicalize reads the KB
    # docstore's doc_tree; a KB whose ingest never stamped it (or a toc-only
    # import) gets the tree rebuilt here from the parse product instead.
    tree = None
    if source == "toc_json":
        tree = await asyncio.to_thread(_enrich_tree, book_dir, path.name)
    if tree is not None:
        slim = canonical_tree_from_doc_trees([tree])
        if slim is not None and not book_storage.load_canonical_kp_tree(book.get("id") or ""):
            book_storage.save_canonical_kp_tree(book.get("id") or "", slim)

    return {
        "book_id": book.get("id"),
        "title": book.get("title"),
        "source": source,
        "mode": chain_mode,
        "chapters": book.get("chapter_count", 0),
        "pages": book.get("page_count", 0),
        "book_status": str(getattr(book.get("status"), "value", book.get("status") or "")),
    }, layout


async def _figure_stage(
    book_id: str, parse_workdir: str | Path, *, book_storage: Any
) -> dict[str, Any]:
    """figure_backfill 的编程入口串联：plan_from_parse_dir + apply_plan（--apply 语义）.

    模块级 CLI 调用不等价编程复刻，这里直接用 :func:`plan_from_parse_dir`
    （内部走 ``load_content_lists``）拿计划，再 :func:`apply_plan` 落图入块
    —— 与 figure_backfill 既有测试同一用法。无书页或无插图素材时是合法的
    零产出，不是失败。
    """
    from deeptutor.book.engine import BookEngine
    from deeptutor.book.figure_backfill import apply_plan, load_content_lists, plan_from_parse_dir

    empty = {"pages": 0, "blocks_inserted": 0, "images_copied": 0}
    book_dir = _book_dir_of(parse_workdir)
    engine = BookEngine(storage=book_storage)
    pages = await asyncio.to_thread(engine.list_pages, book_id)
    if not pages:
        return empty
    items, content_dir = await asyncio.to_thread(load_content_lists, book_dir)
    if not items:
        return empty
    plan = await asyncio.to_thread(plan_from_parse_dir, book_id, pages, book_dir)
    if not plan.entries:
        return empty
    return await apply_plan(engine, book_id, plan, content_dir=content_dir, storage=book_storage)


async def _ensure_tree_cached(
    kb_name: str,
    book_id: str,
    layout: dict[str, Any] | None,
    filename: str,
    *,
    book_storage: Any,
) -> bool:
    """树落缓：确认书 manifest 里挂上 canonical KP 树（best-effort）.

    canonicalize 的 P0 钩子可能已缓存；未缓存时优先读 KB docstore 的
    canonical 树（import 之后才有），保真路径再拿 layout 内联重建兜底。
    """
    if await asyncio.to_thread(book_storage.load_canonical_kp_tree, book_id):
        return True
    from deeptutor.book.canonical_tree import cache_canonical_tree_for_book

    if await asyncio.to_thread(
        cache_canonical_tree_for_book, book_id, [kb_name], storage=book_storage
    ):
        return True
    if layout is None:
        return False
    from deeptutor.book.canonical_tree import rebuild_canonical_tree_from_layout

    return await asyncio.to_thread(
        rebuild_canonical_tree_from_layout,
        book_id,
        layout,
        filename=filename,
        storage=book_storage,
    )


def _share_read_grants(book_id: str, usernames: list[str]) -> dict[str, list[str]]:
    """共享授权：给授权用户列表逐个 share read（缺省不共享）.

    KB grants 不在这里落——canonicalize 已把书关联 ``knowledge_bases=[KB]``，
    有该 KB 授权的账号经 KB 链接即可见。未知用户名 fail-soft 记
    ``share_skipped``，绝不因一个手误中止整条链。
    """
    granted: list[str] = []
    skipped: list[str] = []
    for raw in usernames:
        username = str(raw or "").strip()
        if not username:
            continue
        from deeptutor.multi_user.identity import set_book_grant

        if set_book_grant(username, book_id, "read"):
            granted.append(username)
        else:
            skipped.append(username)
    return {"shared_read": granted, "share_skipped": skipped}


async def run_auto_pipeline(
    kb_name: str,
    file_paths: list[str | Path],
    *,
    base_dir: str | Path | None = None,
    task_id: str | None = None,
    log: LogFn | None = None,
    canonicalize: Any | None = None,
    import_from_book: Any | None = None,
    import_request_model: Any | None = None,
    mode: str | None = None,
    enable_qb: bool | None = None,
    share_read_users: list[str] | None = None,
) -> dict[str, dict[str, Any]]:
    """Run the full chain for each uploaded file, one failure at a time.

    Called at the tail of a successful upload task; every stage outcome is
    persisted via :func:`record_stage` before the next file starts, so the
    status endpoint reflects reality even mid-run or after a crash. Re-running
    it against an already-ingested KB works the same way（parse 缓存命中、
    各段状态覆写）；重跑会 canonicalize 出一本新书。

    ``canonicalize`` / ``import_from_book`` / ``import_request_model`` are the
    adapter endpoints this chain composes (canonicalize endpoint + request
    model, import-from-book endpoint + request model); they are injected by
    the caller in the API layer so this module stays free of adapter imports.

    New-in-faithful-chain knobs (caller args win; otherwise
    :func:`read_chain_options` reads them off the KB manifest):

    * ``mode`` — "auto"（缺省，保真 0 章回落 toc 并标注 legacy_toc）或
      "faithful"（教材场景强制保真，0 章 fail-loud 带指引）。
    * ``enable_qb`` — 链尾自动触发题库 ingest-pipeline（缺省开）。
    * ``share_read_users`` — 建书后给这些账号 share read（缺省不共享）。

    Core stages（parsed/canonicalized/imported/qb）失败按既有约定整文件置
    error 并停链；增强段（figures/latex/树落缓/共享）失败记入各自段位但
    不拦后续——书已建成，缺插图/补定界不该拖死题库。
    """
    from deeptutor.book.storage import get_book_storage
    from deeptutor.services.parsing.service import ParseService

    if canonicalize is None or import_from_book is None or import_request_model is None:
        raise AutoPipelineError(
            "run_auto_pipeline requires the canonicalize/import-from-book "
            "endpoint callables (inject them from the API layer)"
        )

    def say(message: str, level: str = "info") -> None:
        if log is not None:
            log(message, level=level)
        elif level in ("error", "warning"):
            getattr(logger, "warning" if level == "warning" else "error")(message)
        else:
            logger.info(message)

    options = read_chain_options(kb_name, base_dir=base_dir)
    chain_mode = str(mode or options["mode"]).strip().lower()
    if chain_mode not in ("auto", "faithful"):
        chain_mode = "auto"
    run_qb = enable_qb if enable_qb is not None else options["enable_qb"]
    share_users = (
        [str(u).strip() for u in share_read_users or [] if str(u).strip()]
        if share_read_users is not None
        else options["share_read_users"]
    )

    parse_service = ParseService()
    book_storage = get_book_storage()
    results: dict[str, dict[str, Any]] = {}

    for raw_path in file_paths:
        path = Path(raw_path)
        name = path.name
        record_stage(kb_name, name, "raw", payload={"path": str(path)}, base_dir=base_dir)
        results[name] = {"status": "ok"}

        # ── parsed: ParseService 复用缓存，产物缺失才真正解析 ──
        try:
            parsed = await asyncio.to_thread(parse_service.parse, path)
        except Exception as exc:  # noqa: BLE001
            record_stage(kb_name, name, "parsed", error=str(exc), base_dir=base_dir)
            results[name] = {"status": "error", "stage": "parsed", "error": str(exc)}
            say(f"{name}: parse failed — {exc}", level="error")
            continue
        record_stage(
            kb_name,
            name,
            "parsed",
            payload={"workdir": str(parsed.workdir), "engine": parsed.engine},
            base_dir=base_dir,
        )

        # ── canonicalized: 保真法 layout_json → 降级 toc_json（按 mode 分流）──
        layout: dict[str, Any] | None = None
        try:
            canonicalized, layout = await _canonicalize_stage(
                kb_name,
                path,
                parsed,
                book_storage=book_storage,
                canonicalize=canonicalize,
                mode=chain_mode,
            )
        except Exception as exc:  # noqa: BLE001
            record_stage(kb_name, name, "canonicalized", error=str(exc), base_dir=base_dir)
            results[name] = {"status": "error", "stage": "canonicalized", "error": str(exc)}
            say(f"{name}: canonicalize failed — {exc}", level="error")
            continue
        record_stage(kb_name, name, "canonicalized", payload=canonicalized, base_dir=base_dir)
        say(
            f"{name}: canonicalized → {canonicalized['book_id']} "
            f"(mode={canonicalized['mode']} chapters={canonicalized['chapters']} "
            f"pages={canonicalized['pages']})"
        )

        book_id = str(canonicalized.get("book_id") or "")

        # ── figures: figure_backfill plan + apply（增强段，失败不拦后续）──
        figures: dict[str, Any] = {"pages": 0, "blocks_inserted": 0, "images_copied": 0}
        try:
            figures = await _figure_stage(book_id, parsed.workdir, book_storage=book_storage)
            record_stage(kb_name, name, "figures", payload=figures, base_dir=base_dir)
            say(f"{name}: figure backfill inserted {figures.get('blocks_inserted', 0)} block(s)")
        except Exception as exc:  # noqa: BLE001
            figures = {"error": str(exc)[:500]}
            record_stage(kb_name, name, "figures", payload=figures, base_dir=base_dir)
            say(f"{name}: figure backfill failed — {exc}", level="warning")

        # ── latex: latex_delimit.fix_book（增强段，失败不拦后续）──
        latex_summary: dict[str, Any] = {}
        try:
            from deeptutor.book.latex_delimit import fix_book

            latex_summary = await asyncio.to_thread(fix_book, book_id, storage=book_storage)
            record_stage(kb_name, name, "latex", payload=latex_summary, base_dir=base_dir)
            say(f"{name}: latex delimit fixed {latex_summary.get('blocks_fixed', 0)} block(s)")
        except Exception as exc:  # noqa: BLE001
            latex_summary = {"error": str(exc)[:500]}
            record_stage(kb_name, name, "latex", payload=latex_summary, base_dir=base_dir)
            say(f"{name}: latex delimit failed — {exc}", level="warning")

        # ── imported: canonical 树优先的 import-from-book ──
        try:
            imported = await import_from_book(book_id, import_request_model(chapters=[]))
        except Exception as exc:  # noqa: BLE001
            record_stage(kb_name, name, "imported", error=str(exc), base_dir=base_dir)
            results[name] = {"status": "error", "stage": "imported", "error": str(exc)}
            say(f"{name}: import-from-book failed — {exc}", level="error")
            continue

        # ── tree: 树落缓确认（增强段）+ share: 共享授权（增强段）──
        try:
            tree_cached = await _ensure_tree_cached(
                kb_name, book_id, layout, path.name, book_storage=book_storage
            )
        except Exception as exc:  # noqa: BLE001
            tree_cached = False
            say(f"{name}: tree cache check failed — {exc}", level="warning")
        try:
            share_info = _share_read_grants(book_id, share_users)
            if share_info["share_skipped"]:
                say(
                    f"{name}: share read skipped for unknown user(s): "
                    f"{', '.join(share_info['share_skipped'])}",
                    level="warning",
                )
        except Exception as exc:  # noqa: BLE001
            share_info = {"shared_read": [], "share_skipped": [], "error": str(exc)[:500]}
            say(f"{name}: share grants failed — {exc}", level="warning")

        record_stage(
            kb_name,
            name,
            "imported",
            payload={
                "book_id": book_id,
                "module_count": imported.get("module_count", 0),
                "tree_cached": tree_cached,
                **share_info,
            },
            base_dir=base_dir,
        )
        say(f"{name}: imported {imported.get('module_count', 0)} module(s) into {book_id}")

        # ── qb: 题库 ingest-pipeline 四段一体（核心段，失败整文件置 error）──
        qb_run_id = ""
        if run_qb:
            try:
                from deeptutor.learning.ingest_pipeline import start_pipeline

                run = await asyncio.to_thread(start_pipeline, kb_name, book_id)
                qb_run_id = str(run.get("run_id") or "")
                record_stage(
                    kb_name,
                    name,
                    "qb",
                    payload={"run_id": qb_run_id, "status": run.get("status")},
                    base_dir=base_dir,
                )
                say(f"{name}: question-bank pipeline {qb_run_id} ({run.get('status')})")
            except Exception as exc:  # noqa: BLE001
                record_stage(kb_name, name, "qb", error=str(exc), base_dir=base_dir)
                results[name] = {"status": "error", "stage": "qb", "error": str(exc)}
                say(f"{name}: qb pipeline failed to start — {exc}", level="error")
                continue

        results[name] = {
            "status": "ok",
            "book_id": book_id,
            "mode": canonicalized.get("mode"),
            "chapters": canonicalized.get("chapters", 0),
            "pages": canonicalized.get("pages", 0),
            "figures": figures,
            "tree_cached": tree_cached,
            "qb_pipeline_run_id": qb_run_id,
        }

    return results
