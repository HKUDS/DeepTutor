"""
Notebook API Router
Provides notebook creation, querying, updating, deletion, and record management functions
"""

import hashlib
import json
from pathlib import Path
import re
import sys
import time
from typing import Literal
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from fastapi import APIRouter, BackgroundTasks, HTTPException, UploadFile
from pydantic import BaseModel

# Ensure module can be imported
project_root = Path(__file__).parent.parent.parent.parent
if str(project_root) not in sys.path:
    sys.path.insert(0, str(project_root))

from src.api.routers.knowledge import _kb_base_dir, run_upload_processing_task
from src.api.utils.notebook_manager import notebook_manager
from src.knowledge.manager import KnowledgeBaseManager
from src.logging import get_logger
from src.services.config import load_config_with_main
from src.services.llm import get_llm_config
from src.tools.web_crawler import fetch_urls

router = APIRouter()

# Initialize logger
config = load_config_with_main("solve_config.yaml", project_root)
log_dir = config.get("paths", {}).get("user_log_dir") or config.get("logging", {}).get("log_dir")
logger = get_logger("Notebook", level="INFO", log_dir=log_dir)


# === Helper Functions ===
def _strip_research_banner(content: str) -> str:
    lines = content.splitlines()
    if not lines:
        return content

    first_line = re.sub(r"^[#>*\\s]+", "", lines[0]).strip()
    first_line = first_line.replace("*", "").strip()
    if "深度研究完成" in first_line:
        return "\n".join(lines[1:]).lstrip()
    return content


def _extract_markdown_title(content: str) -> str:
    lines = content.splitlines()
    # Prefer first H1 after banner
    for line in lines:
        if re.match(r"^#\\s+\\S", line):
            return re.sub(r"^#\\s+", "", line).strip()
    # Fallback to any heading
    for line in lines:
        if re.match(r"^#{2,6}\\s+\\S", line):
            return re.sub(r"^#{2,6}\\s+", "", line).strip()
    # Final fallback to first non-empty text line
    for line in lines:
        cleaned = re.sub(r"^[#>*\\s]+", "", line).strip()
        cleaned = cleaned.replace("*", "").strip()
        if cleaned:
            return cleaned
    return ""


MAX_SOURCE_CONTENT_CHARS = 8000
REPORT_SOURCE_CONTENT_CHARS = 50000  # 增加到 50000 字符（约 25000 中文字）
SOURCES_KB_DESCRIPTION = "Notebook selected sources"
SOURCES_SIGNATURE_VERSION = "3"
MIN_FETCHED_CONTENT_CHARS = 200
MIN_INDEXABLE_WEB_CONTENT_CHARS = 300
RETRYABLE_FETCH_RESYNC_COOLDOWN_SECONDS = 600
_SOURCES_OWNER_TYPE = "notebook_sources"
_LEGACY_SOURCES_KB_RE = re.compile(r"^notebook_(?P<notebook_id>[^/]+)_sources$")
_SUCCESS_FETCH_STATUS_PREFIX = "success_"
_SOURCE_META_FIELDS = (
    "requested_url",
    "canonical_url",
    "final_url",
    "fetch_method",
    "fetch_status",
    "fetch_error",
    "content_type",
    "content_chars",
    "file_size",
    "fetched_at",
    "is_pdf",
    "file_path",
)
_TRACKING_QUERY_PREFIXES = ("utm_",)
_TRACKING_QUERY_KEYS = {
    "source",
    "from",
    "from_source",
    "wid",
    "spm",
    "spm_id_from",
    "upstream_biz",
    "utm_source",
    "utm_medium",
    "utm_campaign",
    "utm_term",
    "utm_content",
    "gclid",
    "fbclid",
}
_TOUTIAO_DOMAINS = {"toutiao.com", "www.toutiao.com", "m.toutiao.com"}
_TOUTIAO_ARTICLE_RE = re.compile(r"/(?:group|article)/(\d+)")
_LOW_QUALITY_CONTENT_MARKERS = (
    "您需要允许该网站执行 JavaScript",
    "you need to enable javascript",
    "你的浏览器版本过低，可能导致网站不能正常访问",
    "visit the bitauto international website",
)


def _safe_upload_filename(filename: str) -> str:
    normalized = (filename or "").replace("\\", "/").strip()
    if not normalized:
        raise ValueError("filename is empty")

    parts = [part for part in normalized.split("/") if part not in ("", ".")]
    if not parts or any(part == ".." for part in parts):
        raise ValueError("invalid filename")

    safe_name = parts[-1].strip()
    if not safe_name or safe_name in {".", ".."} or "\x00" in safe_name:
        raise ValueError("invalid filename")

    return safe_name


def _get_notebook_sources_kb_name(notebook_id: str) -> str:
    return f"notebook_{notebook_id}_sources"


def _normalize_notebook_name(name: str) -> str:
    cleaned = " ".join((name or "").split()).strip()
    return cleaned or "未命名笔记本"


def _build_sources_kb_display_name(notebook_name: str) -> str:
    return f"{_normalize_notebook_name(notebook_name)} · 来源库"


def _build_source_display_name(notebook_name: str, source_title: str) -> str:
    title = (source_title or "").strip() or "来源"
    return f"{_normalize_notebook_name(notebook_name)} · {title}"


def _get_notebook_name(notebook_id: str) -> str:
    notebook = notebook_manager.get_notebook(notebook_id) or {}
    return _normalize_notebook_name(notebook.get("name", ""))


def _load_kb_metadata(kb_dir: Path) -> dict:
    metadata_path = kb_dir / "metadata.json"
    if not metadata_path.exists():
        return {}
    try:
        with open(metadata_path, encoding="utf-8") as f:
            data = json.load(f)
            return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _write_kb_metadata(kb_dir: Path, metadata: dict) -> None:
    metadata_path = kb_dir / "metadata.json"
    with open(metadata_path, "w", encoding="utf-8") as f:
        json.dump(metadata, f, ensure_ascii=False, indent=2)


def _ensure_sources_kb_alias_metadata(
    kb_dir: Path, kb_name: str, notebook_id: str, notebook_name: str
) -> None:
    metadata = _load_kb_metadata(kb_dir)
    metadata.setdefault("name", kb_name)
    metadata.setdefault("created_at", time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()))
    metadata["description"] = SOURCES_KB_DESCRIPTION
    metadata["display_name"] = _build_sources_kb_display_name(notebook_name)
    metadata["system_managed"] = True
    metadata["owner"] = {
        "type": _SOURCES_OWNER_TYPE,
        "notebook_id": notebook_id,
        "notebook_name": notebook_name,
    }
    _write_kb_metadata(kb_dir, metadata)


def _extract_legacy_notebook_id(kb_name: str) -> str:
    match = _LEGACY_SOURCES_KB_RE.match((kb_name or "").strip())
    return match.group("notebook_id") if match else ""


def _find_notebook_sources_kb_names(
    kb_manager: KnowledgeBaseManager, notebook_id: str
) -> list[str]:
    notebook_id = (notebook_id or "").strip()
    if not notebook_id:
        return []

    legacy_name = _get_notebook_sources_kb_name(notebook_id)
    found = set()

    for kb_name in kb_manager.list_knowledge_bases():
        if kb_name == legacy_name:
            found.add(kb_name)
            continue
        try:
            metadata = kb_manager.get_metadata(kb_name)
        except Exception:
            continue
        owner = metadata.get("owner") if isinstance(metadata, dict) else None
        if (
            isinstance(owner, dict)
            and owner.get("type") == _SOURCES_OWNER_TYPE
            and str(owner.get("notebook_id") or "").strip() == notebook_id
        ):
            found.add(kb_name)
            continue
        if _extract_legacy_notebook_id(kb_name) == notebook_id:
            found.add(kb_name)

    if legacy_name in found:
        ordered = [legacy_name]
        ordered.extend(sorted(name for name in found if name != legacy_name))
        return ordered
    return sorted(found)


def _resolve_notebook_sources_kb_name(kb_manager: KnowledgeBaseManager, notebook_id: str) -> str:
    matches = _find_notebook_sources_kb_names(kb_manager, notebook_id)
    if matches:
        return matches[0]
    return _get_notebook_sources_kb_name(notebook_id)


def _canonicalize_source_url(url: str) -> str:
    raw = (url or "").strip()
    if not raw:
        return ""

    parsed = urlparse(raw)
    if not parsed.netloc:
        return raw

    scheme = (parsed.scheme or "https").lower()
    netloc = parsed.netloc.lower()
    path = re.sub(r"/{2,}", "/", parsed.path or "/")

    if netloc in _TOUTIAO_DOMAINS:
        match = _TOUTIAO_ARTICLE_RE.search(path)
        if match:
            article_id = match.group(1)
            return urlunparse(("https", "m.toutiao.com", f"/article/{article_id}/", "", "", ""))

    query_pairs = parse_qsl(parsed.query, keep_blank_values=False)
    filtered_pairs = []
    for key, value in query_pairs:
        lowered = key.lower()
        if lowered in _TRACKING_QUERY_KEYS:
            continue
        if any(lowered.startswith(prefix) for prefix in _TRACKING_QUERY_PREFIXES):
            continue
        filtered_pairs.append((key, value))
    filtered_pairs.sort()
    query = urlencode(filtered_pairs, doseq=True)

    return urlunparse((scheme, netloc, path, "", query, ""))


def _is_low_quality_content(text: str) -> bool:
    content = (text or "").strip()
    if not content:
        return True
    lowered = content.lower()
    if any(marker.lower() in lowered for marker in _LOW_QUALITY_CONTENT_MARKERS):
        return True
    if "probe.js" in lowered:
        return True
    return False


def _should_replace_source_content(existing: str, fetched: str) -> tuple[bool, str]:
    existing_text = (existing or "").strip()
    fetched_text = (fetched or "").strip()

    if not fetched_text:
        return False, "empty fetched content"
    if _is_low_quality_content(fetched_text):
        return False, "low-quality fetched content"
    if not existing_text:
        return True, "existing content empty"
    if _is_low_quality_content(existing_text):
        return True, "existing content low quality"
    if len(fetched_text) >= len(existing_text):
        return True, "fetched content longer"
    if len(existing_text) < 500 and len(fetched_text) >= MIN_FETCHED_CONTENT_CHARS:
        return True, "fetched content reaches minimum quality threshold"
    if len(fetched_text) >= max(MIN_FETCHED_CONTENT_CHARS, int(len(existing_text) * 0.7)):
        return True, "fetched content close to existing length"

    return False, "fetched content significantly shorter than existing"


def _is_success_fetch_status(status: str) -> bool:
    return bool(status) and status.startswith(_SUCCESS_FETCH_STATUS_PREFIX)


def _attach_source_metadata(base: dict, source: dict, canonical_url: str) -> dict:
    normalized = base.copy()
    if canonical_url:
        normalized["canonical_url"] = canonical_url
    for field in _SOURCE_META_FIELDS:
        if field in source and source.get(field) is not None:
            normalized[field] = source.get(field)
    return normalized


def _is_indexable_source(source: dict) -> bool:
    source_type = source.get("type") or ""
    fetch_status = (source.get("fetch_status") or "").strip()

    if source.get("is_pdf") and source.get("file_path"):
        return not fetch_status or _is_success_fetch_status(fetch_status)

    if source_type == "web":
        content = (source.get("content") or "").strip()
        if not content or _is_low_quality_content(content):
            return False

        if fetch_status and not _is_success_fetch_status(fetch_status):
            return False
        if len(content) < MIN_INDEXABLE_WEB_CONTENT_CHARS:
            return False
        return True

    # Non-web sources keep legacy behavior.
    return bool((source.get("content") or "").strip())


def _normalize_source_payload(source: dict) -> dict:
    content = (source.get("content") or "").strip()
    canonical_url = _canonicalize_source_url(source.get("url") or "")
    max_chars = (
        REPORT_SOURCE_CONTENT_CHARS if source.get("type") == "report" else MAX_SOURCE_CONTENT_CHARS
    )
    if len(content) > max_chars:
        content = content[:max_chars] + "\n\n[truncated]"
    normalized = {
        "id": source.get("id") or "",
        "type": source.get("type") or "web",
        "title": source.get("title") or canonical_url or source.get("url") or "Source",
        "url": canonical_url or source.get("url") or "",
        "content": content,
    }
    if source.get("type") == "web":
        normalized["content_chars"] = len(content)
    return _attach_source_metadata(normalized, source, canonical_url)


def _source_key(source: dict) -> str:
    canonical_url = _canonicalize_source_url(source.get("url") or "")
    key = canonical_url or source.get("url") or source.get("id") or source.get("title") or ""
    return f"{source.get('type', '')}-{key}"


def _dedupe_sources(sources: list[dict]) -> list[dict]:
    seen = set()
    deduped = []
    for source in sources:
        key = _source_key(source)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(source)
    return deduped


def _collect_selected_sources(sessions: list[dict]) -> list[dict]:
    selected = []
    for session in sessions:
        for source in session.get("sources", []) or []:
            if not source:
                continue
            if source.get("selected", True):
                selected.append(_normalize_source_payload(source))
    return _dedupe_sources(selected)


def _collect_selected_sources_raw(sessions: list[dict]) -> list[dict]:
    """Collect selected sources without normalization (for enrichment first)."""
    selected = []
    for session in sessions:
        for source in session.get("sources", []) or []:
            if not source:
                continue
            if source.get("selected", True):
                selected.append(source)
    return _dedupe_sources(selected)


def _source_digest(source: dict) -> dict:
    content = source.get("content") or ""
    canonical_url = _canonicalize_source_url(source.get("url") or "")
    content_hash = hashlib.sha1(content.encode("utf-8")).hexdigest()
    return {
        "id": source.get("id") or "",
        "type": source.get("type") or "",
        "title": source.get("title") or "",
        "url": canonical_url or source.get("url") or "",
        "content_hash": content_hash,
    }


def _sources_signature(sources: list[dict]) -> str:
    payload = [_source_digest(source) for source in sources]
    payload.sort(key=lambda item: (item["type"], item["url"], item["id"], item["title"]))
    raw = json.dumps(
        {"version": SOURCES_SIGNATURE_VERSION, "sources": payload},
        sort_keys=True,
        ensure_ascii=True,
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _selected_sources_signature(selected_sources: list[dict]) -> str | None:
    if not selected_sources:
        return None
    normalized_for_signature = [_normalize_source_payload(source) for source in selected_sources]
    return _sources_signature(normalized_for_signature)


def _load_sources_manifest(kb_dir: Path) -> dict:
    manifest_path = kb_dir / "sources_manifest.json"
    if not manifest_path.exists():
        return {}
    try:
        with open(manifest_path, encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return {}


def _manifest_has_retryable_fetch_failures(manifest: dict) -> bool:
    sources = manifest.get("sources")
    if not isinstance(sources, list):
        return False

    for source in sources:
        if not isinstance(source, dict):
            continue
        if (source.get("type") or "").lower() != "web":
            continue
        status = str(source.get("fetch_status") or "").strip().lower()
        if status.startswith("failed_") or status.startswith("blocked_"):
            return True

    return False


def _retryable_failure_cooldown_remaining(manifest: dict) -> float:
    if not _manifest_has_retryable_fetch_failures(manifest):
        return 0.0
    try:
        updated_at = float(manifest.get("updated_at") or 0.0)
    except (TypeError, ValueError):
        return 0.0
    if updated_at <= 0:
        return 0.0
    elapsed = time.time() - updated_at
    return max(0.0, RETRYABLE_FETCH_RESYNC_COOLDOWN_SECONDS - elapsed)


def _should_sync_sources_kb(notebook_id: str, signature: str | None) -> bool:
    if not signature:
        return False

    kb_manager = KnowledgeBaseManager(base_dir=str(_kb_base_dir))
    kb_names = kb_manager.list_knowledge_bases()
    matched_kb_names = _find_notebook_sources_kb_names(kb_manager, notebook_id)
    kb_name = (
        matched_kb_names[0] if matched_kb_names else _get_notebook_sources_kb_name(notebook_id)
    )

    if kb_name not in kb_names:
        return True

    try:
        kb_dir = kb_manager.get_knowledge_base_path(kb_name)
    except Exception:
        return True

    manifest = _load_sources_manifest(kb_dir)
    if manifest.get("signature") != signature:
        return True

    if not _manifest_has_retryable_fetch_failures(manifest):
        return False

    return _retryable_failure_cooldown_remaining(manifest) <= 0


def _write_sources_manifest(
    kb_dir: Path, signature: str, sources: list[dict], notebook_name: str
) -> None:
    indexable_count = 0
    source_entries = []
    for source in sources:
        if _is_indexable_source(source):
            indexable_count += 1

        entry = {
            "id": source.get("id") or "",
            "type": source.get("type") or "",
            "title": source.get("title") or "",
            "url": source.get("url") or "",
            "canonical_url": source.get("canonical_url") or "",
            "requested_url": source.get("requested_url") or "",
            "final_url": source.get("final_url") or source.get("url") or "",
            "fetch_status": source.get("fetch_status") or "",
            "fetch_method": source.get("fetch_method") or "",
            "content_chars": int(source.get("content_chars") or len(source.get("content") or "")),
            "is_pdf": bool(source.get("is_pdf")),
            "file_path": source.get("file_path") or "",
            "raw_filename": source.get("raw_filename") or "",
            "source_display_name": _build_source_display_name(
                notebook_name,
                source.get("title") or source.get("url") or "来源",
            ),
            "indexable": _is_indexable_source(source),
        }
        if source.get("fetch_error"):
            entry["fetch_error"] = source["fetch_error"]
        source_entries.append(entry)

    manifest = {
        "signature": signature,
        "signature_version": SOURCES_SIGNATURE_VERSION,
        "count": len(sources),
        "indexable_count": indexable_count,
        "updated_at": time.time(),
        "notebook_name": _normalize_notebook_name(notebook_name),
        "display_name": _build_sources_kb_display_name(notebook_name),
        "sources": source_entries,
    }
    manifest_path = kb_dir / "sources_manifest.json"
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest, f, ensure_ascii=True, indent=2)


def _refresh_sources_manifest_display_names(kb_dir: Path, notebook_name: str) -> None:
    manifest_path = kb_dir / "sources_manifest.json"
    if not manifest_path.exists():
        return
    try:
        with open(manifest_path, encoding="utf-8") as f:
            manifest = json.load(f)
    except Exception:
        return

    if not isinstance(manifest, dict):
        return

    changed = False
    target_display_name = _build_sources_kb_display_name(notebook_name)
    target_notebook_name = _normalize_notebook_name(notebook_name)
    if manifest.get("display_name") != target_display_name:
        manifest["display_name"] = target_display_name
        changed = True
    if manifest.get("notebook_name") != target_notebook_name:
        manifest["notebook_name"] = target_notebook_name
        changed = True

    sources = manifest.get("sources", [])
    if isinstance(sources, list):
        for source in sources:
            if not isinstance(source, dict):
                continue
            title = source.get("title") or source.get("url") or "来源"
            target_source_display_name = _build_source_display_name(notebook_name, title)
            if source.get("source_display_name") != target_source_display_name:
                source["source_display_name"] = target_source_display_name
                changed = True
            raw_filename = source.get("raw_filename") or Path(source.get("file_path") or "").name
            if raw_filename and source.get("raw_filename") != raw_filename:
                source["raw_filename"] = raw_filename
                changed = True

    if changed:
        with open(manifest_path, "w", encoding="utf-8") as f:
            json.dump(manifest, f, ensure_ascii=True, indent=2)


def _format_source_markdown(source: dict) -> str:
    title = source.get("title") or source.get("url") or "Source"
    lines = [f"# {title}"]
    if source.get("type"):
        lines.append(f"\nType: {source['type']}")
    if source.get("url"):
        lines.append(f"\nSource: {source['url']}")
    if source.get("fetch_status"):
        lines.append(f"\nFetch-Status: {source['fetch_status']}")
    if source.get("fetch_method"):
        lines.append(f"\nFetch-Method: {source['fetch_method']}")
    if source.get("fetch_error"):
        lines.append(f"\nFetch-Error: {source['fetch_error']}")
    if source.get("content"):
        lines.append(f"\n\n{source['content']}")
    return "\n".join(lines).strip() + "\n"


async def _enrich_sources_with_content(sources: list[dict], raw_dir: Path) -> list[dict]:
    """
    Enrich sources by fetching web content for URLs that don't have content yet.
    Supports both HTML pages and PDF files.

    Args:
        sources: List of source dicts
        raw_dir: Directory to save downloaded PDF files

    Returns:
        New list with enriched sources.
    """
    # Find web sources that should be refreshed from original URLs.
    urls_to_fetch = []
    url_to_source_idx = {}

    for idx, source in enumerate(sources):
        if (
            source.get("type") == "web"
            and source.get("url")
            and not source.get("file_path")  # Skip PDFs already downloaded
        ):
            source_url = source["url"]
            canonical_url = _canonicalize_source_url(source_url)
            fetch_url = canonical_url or source_url
            urls_to_fetch.append(fetch_url)
            url_to_source_idx[source_url] = idx
            url_to_source_idx[fetch_url] = idx

    if not urls_to_fetch:
        return sources  # Nothing to fetch

    logger.info(f"Fetching content for {len(urls_to_fetch)} source URLs")

    # Fetch all URLs concurrently (with PDF support)
    fetch_results = await fetch_urls(urls_to_fetch, concurrency=5, pdf_save_dir=raw_dir)

    # Create enriched sources list
    enriched = [s.copy() for s in sources]

    for result in fetch_results:
        lookup_candidates = [
            result.get("requested_url"),
            result.get("url"),
            _canonicalize_source_url(result.get("requested_url") or ""),
            _canonicalize_source_url(result.get("url") or ""),
        ]
        idx = None
        for candidate in lookup_candidates:
            if not candidate:
                continue
            idx = url_to_source_idx.get(candidate)
            if idx is not None:
                break
        if idx is None:
            logger.warning(
                "Skip fetched result because source index was not found: "
                f"requested={result.get('requested_url')} final={result.get('url')}"
            )
            continue
        url = result.get("url") or result.get("requested_url") or ""
        fetched_at = result.get("fetched_at") or time.time()

        # Persist fetch metadata for observability/debugging.
        enriched[idx]["requested_url"] = (
            result.get("requested_url") or enriched[idx].get("url") or ""
        )
        enriched[idx]["final_url"] = result.get("final_url") or result.get("url") or ""
        enriched[idx]["fetch_method"] = result.get("fetch_method") or "http"
        enriched[idx]["fetch_status"] = result.get("fetch_status") or ""
        enriched[idx]["content_type"] = result.get("content_type") or ""
        enriched[idx]["file_size"] = int(result.get("file_size") or 0)
        enriched[idx]["fetched_at"] = fetched_at
        canonical_url = _canonicalize_source_url(
            enriched[idx].get("final_url") or enriched[idx].get("url") or ""
        )
        if canonical_url:
            enriched[idx]["canonical_url"] = canonical_url

        if result.get("error"):
            logger.warning(f"Failed to fetch {url}: {result['error']}")
            # Add error info to source
            enriched[idx]["fetch_error"] = result["error"]
            if (enriched[idx].get("content") or "").strip():
                enriched[idx]["content_chars"] = len((enriched[idx].get("content") or "").strip())
        else:
            # Successfully fetched
            if "fetch_error" in enriched[idx]:
                enriched[idx].pop("fetch_error", None)

            if result.get("is_pdf"):
                # PDF file downloaded
                enriched[idx]["file_path"] = result["file_path"]
                enriched[idx]["is_pdf"] = True
                if result.get("url"):
                    enriched[idx]["url"] = result["url"]
                enriched[idx]["content_chars"] = 0
                if result.get("title") and not enriched[idx].get("title"):
                    enriched[idx]["title"] = result["title"]
                logger.info(f"Downloaded PDF from {url} to {result['file_path']}")
            else:
                # HTML content extracted
                existing_content = enriched[idx].get("content") or ""
                fetched_content = result.get("content") or ""
                should_replace, reason = _should_replace_source_content(
                    existing_content, fetched_content
                )
                if not should_replace:
                    enriched[idx]["fetch_error"] = f"Skipped fetched content: {reason}"
                    enriched[idx]["content_chars"] = len((existing_content or "").strip())
                    logger.warning(
                        f"Skipped replacing content for {url} "
                        f"(existing={len(existing_content)}, fetched={len(fetched_content)}): {reason}"
                    )
                    continue

                enriched[idx]["content"] = fetched_content
                enriched[idx]["content_chars"] = len(fetched_content)
                if result.get("url"):
                    enriched[idx]["url"] = result["url"]
                if result.get("title") and not enriched[idx].get("title"):
                    enriched[idx]["title"] = result["title"]
                logger.info(
                    f"Fetched {len(fetched_content)} chars from {url} "
                    f"(existing was {len(existing_content)} chars)"
                )

    return enriched


def _write_source_files(raw_dir: Path, sources: list[dict]) -> tuple[list[str], list[str]]:
    """
    Write source files to the raw directory.
    For HTML sources: creates markdown files with content.
    For PDF sources: the PDF file is already downloaded, just return its path.

    Returns:
        (all_file_paths, indexable_file_paths)
    """
    raw_dir.mkdir(parents=True, exist_ok=True)
    file_paths: list[str] = []
    indexable_paths: list[str] = []

    for source in sources:
        source_indexable = _is_indexable_source(source)
        # If it's a PDF that was already downloaded, just add its path
        if source.get("is_pdf") and source.get("file_path"):
            file_path = source["file_path"]
            # Verify the file exists and is in the raw_dir
            if Path(file_path).exists() and Path(file_path).parent == raw_dir:
                file_paths.append(file_path)
                source["raw_filename"] = Path(file_path).name
                if source_indexable:
                    indexable_paths.append(file_path)
                logger.info(f"Using existing PDF: {file_path}")
            else:
                logger.warning(f"PDF file not found or not in raw_dir: {file_path}")
            continue

        # For HTML/text sources, create markdown file
        key = _source_key(source) or f"source-{len(file_paths)}"
        digest = hashlib.sha1(key.encode("utf-8")).hexdigest()[:12]
        filename = f"source_{digest}.md"
        file_path = raw_dir / filename

        with open(file_path, "w", encoding="utf-8") as f:
            f.write(_format_source_markdown(source))
        source["raw_filename"] = filename
        output_path = str(file_path)
        file_paths.append(output_path)
        if source_indexable:
            indexable_paths.append(output_path)

    return file_paths, indexable_paths


async def _sync_sources_kb(notebook_id: str, background_tasks: BackgroundTasks) -> str | None:
    notebook_name = _get_notebook_name(notebook_id)
    sessions = notebook_manager.list_sessions(notebook_id)
    # Collect sources WITHOUT normalization first (to preserve full content for enrichment)
    selected_sources = _collect_selected_sources_raw(sessions)
    if not selected_sources:
        return None

    # Calculate signature before enrichment (for consistency)
    # Note: We normalize for signature calculation, but keep raw sources for enrichment.
    signature = _selected_sources_signature(selected_sources)
    if not signature:
        return None

    kb_manager = KnowledgeBaseManager(base_dir=str(_kb_base_dir))
    matched_kb_names = _find_notebook_sources_kb_names(kb_manager, notebook_id)
    kb_name = (
        matched_kb_names[0] if matched_kb_names else _get_notebook_sources_kb_name(notebook_id)
    )

    # Keep only one active sources KB per notebook.
    for stale_kb_name in matched_kb_names[1:]:
        try:
            kb_manager.delete_knowledge_base(stale_kb_name, confirm=True)
        except Exception:
            logger.warning(f"Failed to delete stale sources KB '{stale_kb_name}'")

    if kb_name in kb_manager.list_knowledge_bases():
        kb_dir = kb_manager.get_knowledge_base_path(kb_name)
        _ensure_sources_kb_alias_metadata(kb_dir, kb_name, notebook_id, notebook_name)
        _refresh_sources_manifest_display_names(kb_dir, notebook_name)
        manifest = _load_sources_manifest(kb_dir)
        if manifest.get("signature") == signature:
            if not _manifest_has_retryable_fetch_failures(manifest):
                return kb_name
            cooldown_remaining = _retryable_failure_cooldown_remaining(manifest)
            if cooldown_remaining > 0:
                logger.info(
                    "Sources signature unchanged and retryable fetch failures still cooling down for "
                    f"{cooldown_remaining:.0f}s, skipping sync for '{kb_name}'"
                )
                return kb_name
            logger.info(
                "Sources signature unchanged but previous fetch failures detected, "
                f"retrying sync for '{kb_name}'"
            )
        kb_manager.delete_knowledge_base(kb_name, confirm=True)

    kb_dir = Path(kb_manager.create_knowledge_base(kb_name, description=SOURCES_KB_DESCRIPTION))
    raw_dir = kb_dir / "raw"
    _ensure_sources_kb_alias_metadata(kb_dir, kb_name, notebook_id, notebook_name)

    # Enrich sources by fetching web content (including PDFs) - BEFORE normalization
    selected_sources = await _enrich_sources_with_content(selected_sources, raw_dir)

    # NOW normalize content after enrichment (truncate if needed)
    selected_sources = [_normalize_source_payload(s) for s in selected_sources]

    file_paths, indexable_file_paths = _write_source_files(raw_dir, selected_sources)
    _write_sources_manifest(kb_dir, signature, selected_sources, notebook_name)

    if indexable_file_paths:
        llm_cfg = get_llm_config()
        background_tasks.add_task(
            run_upload_processing_task,
            kb_name=kb_name,
            base_dir=str(_kb_base_dir),
            api_key=llm_cfg.api_key,
            base_url=llm_cfg.base_url,
            uploaded_file_paths=indexable_file_paths,
        )
    elif file_paths:
        logger.info(f"No indexable source files for {kb_name}; raw files kept for inspection")

    return kb_name


def _sync_notebook_sources_aliases(notebook_id: str) -> None:
    kb_manager = KnowledgeBaseManager(base_dir=str(_kb_base_dir))
    notebook_name = _get_notebook_name(notebook_id)
    for kb_name in _find_notebook_sources_kb_names(kb_manager, notebook_id):
        try:
            kb_dir = kb_manager.get_knowledge_base_path(kb_name)
            _ensure_sources_kb_alias_metadata(kb_dir, kb_name, notebook_id, notebook_name)
            _refresh_sources_manifest_display_names(kb_dir, notebook_name)
        except Exception:
            logger.warning(f"Failed to sync aliases for sources KB '{kb_name}'")


async def _trigger_kb_indexing(kb_sync_info: dict, background_tasks: BackgroundTasks):
    """Trigger KB indexing for a synced note"""
    try:
        if not kb_sync_info:
            return

        kb_name = kb_sync_info.get("kb_name")
        file_path = kb_sync_info.get("file_path")

        if not kb_name or not file_path:
            return

        llm_cfg = get_llm_config()

        background_tasks.add_task(
            run_upload_processing_task,
            kb_name=kb_name,
            base_dir=str(_kb_base_dir),
            api_key=llm_cfg.api_key,
            base_url=llm_cfg.base_url,
            uploaded_file_paths=[file_path],
        )
    except Exception as e:
        # Just log error, don't fail the request
        print(f"Failed to trigger KB indexing: {e}")


# === Request/Response Models ===


class CreateNotebookRequest(BaseModel):
    """Create notebook request"""

    name: str
    description: str = ""
    color: str = "#3B82F6"
    icon: str = "book"


class UpdateNotebookRequest(BaseModel):
    """Update notebook request"""

    name: str | None = None
    description: str | None = None
    color: str | None = None
    icon: str | None = None


class AddRecordRequest(BaseModel):
    """Add record request"""

    notebook_ids: list[str]
    record_type: Literal["solve", "question", "research", "co_writer", "chat", "note"]
    title: str
    user_query: str
    output: str
    metadata: dict = {}
    kb_name: str | None = None


class RemoveRecordRequest(BaseModel):
    """Remove record request"""

    record_id: str


class GenerateTitleRequest(BaseModel):
    """Generate title request"""

    content: str


class SessionMessage(BaseModel):
    id: str
    role: Literal["user", "assistant"]
    content: str
    isStreaming: bool | None = None
    sources: dict | None = None
    source_catalog: list[dict] | None = None


class SessionSource(BaseModel):
    id: str
    type: Literal["web", "file", "kb", "report"]
    title: str
    url: str | None = None
    selected: bool = True
    content: str | None = None
    source_key: str | None = None
    ref_number: int | None = None


class SessionSnapshot(BaseModel):
    session_id: str | None = None
    title: str | None = None
    messages: list[SessionMessage] = []
    sources: list[SessionSource] = []
    research_report: str | None = None
    research_state: dict | None = None
    studio_state: dict | None = None
    created_at: float | None = None
    updated_at: float | None = None


# === API Endpoints ===


@router.get("/list")
async def list_notebooks():
    """
    Get all notebook list

    Returns:
        Notebook list (includes summary information)
    """
    try:
        notebooks = notebook_manager.list_notebooks()
        return {"notebooks": notebooks, "total": len(notebooks)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/statistics")
async def get_statistics():
    """
    Get notebook statistics

    Returns:
        Statistics information
    """
    try:
        stats = notebook_manager.get_statistics()
        return stats
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/create")
async def create_notebook(request: CreateNotebookRequest):
    """
    Create new notebook

    Args:
        request: Create request

    Returns:
        Created notebook information
    """
    try:
        notebook = notebook_manager.create_notebook(
            name=request.name,
            description=request.description,
            color=request.color,
            icon=request.icon,
        )
        return {"success": True, "notebook": notebook}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{notebook_id}")
async def get_notebook(notebook_id: str):
    """
    Get notebook details

    Args:
        notebook_id: Notebook ID

    Returns:
        Notebook details (includes all records)
    """
    try:
        notebook = notebook_manager.get_notebook(notebook_id)
        if not notebook:
            raise HTTPException(status_code=404, detail="Notebook not found")
        return notebook
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.put("/{notebook_id}")
async def update_notebook(notebook_id: str, request: UpdateNotebookRequest):
    """
    Update notebook information

    Args:
        notebook_id: Notebook ID
        request: Update request

    Returns:
        Updated notebook information
    """
    try:
        notebook = notebook_manager.update_notebook(
            notebook_id=notebook_id,
            name=request.name,
            description=request.description,
            color=request.color,
            icon=request.icon,
        )
        if not notebook:
            raise HTTPException(status_code=404, detail="Notebook not found")
        if request.name is not None:
            try:
                _sync_notebook_sources_aliases(notebook_id)
            except Exception as e:
                logger.warning(f"Failed to sync notebook sources aliases: {e}")
        return {"success": True, "notebook": notebook}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/{notebook_id}")
async def delete_notebook(notebook_id: str):
    """
    Delete notebook

    Args:
        notebook_id: Notebook ID

    Returns:
        Deletion result
    """
    try:
        success = notebook_manager.delete_notebook(notebook_id)
        if not success:
            raise HTTPException(status_code=404, detail="Notebook not found")
        return {"success": True, "message": "Notebook deleted successfully"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/add_record")
async def add_record(request: AddRecordRequest, background_tasks: BackgroundTasks):
    """
    Add record to notebook

    Args:
        request: Add record request
        background_tasks: Background tasks handler

    Returns:
        Addition result
    """
    try:
        result = notebook_manager.add_record(
            notebook_ids=request.notebook_ids,
            record_type=request.record_type,
            title=request.title,
            user_query=request.user_query,
            output=request.output,
            metadata=request.metadata,
            kb_name=request.kb_name,
        )

        # Trigger KB indexing if sync info is present
        if "kb_sync_info" in result and result["kb_sync_info"]:
            await _trigger_kb_indexing(result["kb_sync_info"], background_tasks)

        return {
            "success": True,
            "record": result["record"],
            "added_to_notebooks": result["added_to_notebooks"],
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/{notebook_id}/records/{record_id}")
async def remove_record(notebook_id: str, record_id: str):
    """
    Remove record from notebook
    """
    try:
        success = notebook_manager.remove_record(notebook_id, record_id)
        if not success:
            raise HTTPException(status_code=404, detail="Record not found")
        return {"success": True, "message": "Record removed successfully"}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


class SingleRecordRequest(BaseModel):
    """Add single record to a specific notebook"""

    type: Literal["solve", "question", "research", "co_writer", "chat", "note"]
    title: str
    user_query: str = ""
    output: str
    metadata: dict = {}
    kb_name: str | None = None


@router.post("/{notebook_id}/records")
async def add_single_record(
    notebook_id: str, request: SingleRecordRequest, background_tasks: BackgroundTasks
):
    """
    Add a record directly to a specific notebook

    Args:
        notebook_id: Notebook ID
        request: Record data
        background_tasks: Background tasks handler

    Returns:
        Addition result
    """
    try:
        result = notebook_manager.add_record(
            notebook_ids=[notebook_id],
            record_type=request.type,
            title=request.title,
            user_query=request.user_query or request.title,
            output=request.output,
            metadata=request.metadata,
            kb_name=request.kb_name,
        )

        # Trigger KB indexing if sync info is present
        if "kb_sync_info" in result and result["kb_sync_info"]:
            await _trigger_kb_indexing(result["kb_sync_info"], background_tasks)

        return {
            "success": True,
            "record": result["record"],
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/{notebook_id}/sessions")
async def list_sessions(notebook_id: str):
    """List all chat sessions for a notebook"""
    if not notebook_manager.get_notebook(notebook_id):
        raise HTTPException(status_code=404, detail="Notebook not found")
    sessions = notebook_manager.list_sessions(notebook_id)
    return {"sessions": sessions}


@router.get("/{notebook_id}/sessions/latest")
async def latest_session(notebook_id: str):
    """Get latest chat session for a notebook"""
    if not notebook_manager.get_notebook(notebook_id):
        raise HTTPException(status_code=404, detail="Notebook not found")
    session = notebook_manager.get_latest_session(notebook_id)
    return {"session": session}


@router.post("/{notebook_id}/sessions")
async def upsert_session(
    notebook_id: str, request: SessionSnapshot, background_tasks: BackgroundTasks
):
    """Create or update a chat session snapshot"""
    if not notebook_manager.get_notebook(notebook_id):
        raise HTTPException(status_code=404, detail="Notebook not found")
    payload = request.dict(exclude_none=True)
    session = notebook_manager.upsert_session(notebook_id, payload)
    try:
        sessions = notebook_manager.list_sessions(notebook_id)
        selected_sources = _collect_selected_sources_raw(sessions)
        signature = _selected_sources_signature(selected_sources)
        if _should_sync_sources_kb(notebook_id, signature):
            await _sync_sources_kb(notebook_id, background_tasks)
    except Exception as e:
        print(f"Failed to sync session sources to KB: {e}")
    return {"session": session}


@router.post("/{notebook_id}/upload_source_pdf")
async def upload_source_pdf(
    notebook_id: str,
    file: UploadFile,
    background_tasks: BackgroundTasks,
):
    """
    Upload a PDF file as a source for the notebook.
    The PDF will be saved to the sources KB and processed for vectorization.
    """
    if not notebook_manager.get_notebook(notebook_id):
        raise HTTPException(status_code=404, detail="Notebook not found")

    try:
        safe_filename = _safe_upload_filename(file.filename or "")
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid filename")

    # Validate file type
    if not safe_filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are supported")

    # Check file size (50MB max)
    content = await file.read()
    if len(content) > 50 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="PDF file too large (max 50MB)")

    # Create or get the sources KB
    kb_manager = KnowledgeBaseManager(base_dir=str(_kb_base_dir))
    notebook_name = _get_notebook_name(notebook_id)
    matched_kb_names = _find_notebook_sources_kb_names(kb_manager, notebook_id)
    kb_name = (
        matched_kb_names[0] if matched_kb_names else _get_notebook_sources_kb_name(notebook_id)
    )

    for stale_kb_name in matched_kb_names[1:]:
        try:
            kb_manager.delete_knowledge_base(stale_kb_name, confirm=True)
        except Exception:
            logger.warning(f"Failed to delete stale sources KB '{stale_kb_name}'")

    # Create KB if it doesn't exist
    if kb_name not in kb_manager.list_knowledge_bases():
        kb_dir = Path(kb_manager.create_knowledge_base(kb_name, description=SOURCES_KB_DESCRIPTION))
    else:
        kb_dir = kb_manager.get_knowledge_base_path(kb_name)
    _ensure_sources_kb_alias_metadata(kb_dir, kb_name, notebook_id, notebook_name)

    raw_dir = kb_dir / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)

    # Save the PDF file
    file_path = raw_dir / safe_filename
    file_path.write_bytes(content)

    logger.info(
        f"Uploaded PDF source: {safe_filename} ({len(content) / 1024:.1f}KB) to {file_path}"
    )

    # Trigger background processing
    llm_cfg = get_llm_config()
    background_tasks.add_task(
        run_upload_processing_task,
        kb_name=kb_name,
        base_dir=str(_kb_base_dir),
        api_key=llm_cfg.api_key,
        base_url=llm_cfg.base_url,
        uploaded_file_paths=[str(file_path)],
    )

    return {
        "success": True,
        "filename": safe_filename,
        "file_path": str(file_path),
        "kb_name": kb_name,
    }


@router.post("/generate_title")
async def generate_title(request: GenerateTitleRequest):
    """Generate a short title for a note content"""
    try:
        from lightrag.llm.openai import openai_complete_if_cache

        from src.services.llm import get_llm_config

        llm_cfg = get_llm_config()

        cleaned_content = _strip_research_banner(request.content).strip()
        if cleaned_content != request.content.strip():
            title = _extract_markdown_title(cleaned_content)
            if title:
                return {"title": title[:30] + "..." if len(title) > 30 else title}

        prompt = f"""
Please generate a concise and descriptive title for the following note content.
The title should be under 10 words.
Do not wrap in quotes.

Content:
{cleaned_content[:1000]}...
"""

        title = await openai_complete_if_cache(
            model=llm_cfg.model, prompt=prompt, api_key=llm_cfg.api_key, base_url=llm_cfg.base_url
        )

        title = title.strip().strip('"')
        if not title:
            title = _extract_markdown_title(cleaned_content)
        return {"title": title or "New Note"}
    except Exception as e:
        logger.error(f"Title generation failed: {e}")
        # Fallback
        return {"title": "New Note"}


@router.get("/health")
async def health_check():
    """Health check"""
    return {"status": "healthy", "service": "notebook"}


@router.get("/{notebook_id}/sources_kb_status")
async def get_sources_kb_status(notebook_id: str):
    """
    Check the indexing status of the temporary sources knowledge base.

    Args:
        notebook_id: Notebook ID

    Returns:
        Status information:
        - ready: bool - Whether KB is ready for querying
        - status: str - "not_created" | "indexing" | "ready" | "error"
        - progress: dict | None - Progress information if indexing
    """
    try:
        kb_manager = KnowledgeBaseManager(base_dir=str(_kb_base_dir))
        kb_name = _resolve_notebook_sources_kb_name(kb_manager, notebook_id)

        # Check if KB exists
        if kb_name not in kb_manager.list_knowledge_bases():
            return {"ready": False, "status": "not_created", "progress": None}

        # Check progress file
        kb_dir = kb_manager.get_knowledge_base_path(kb_name)
        progress_file = kb_dir / ".progress.json"

        if not progress_file.exists():
            # No progress file - either completed long ago or indexing hasn't started
            # Check if rag_storage exists as a sign of completion
            rag_storage = kb_dir / "rag_storage"
            if rag_storage.exists():
                return {"ready": True, "status": "ready", "progress": None}
            else:
                # KB exists but no storage yet - probably just started
                return {
                    "ready": False,
                    "status": "indexing",
                    "progress": {
                        "stage": "initializing",
                        "message": "准备中...",
                        "progress_percent": 0,
                    },
                }

        # Read progress file
        try:
            with open(progress_file, encoding="utf-8") as f:
                import json

                progress = json.load(f)

            stage = progress.get("stage", "")

            if stage == "completed":
                return {"ready": True, "status": "ready", "progress": None}
            elif stage == "error":
                return {"ready": False, "status": "error", "progress": progress}
            else:
                return {"ready": False, "status": "indexing", "progress": progress}
        except Exception as e:
            logger.error(f"Failed to read progress file: {e}")
            # Assume ready if we can't read progress
            return {"ready": True, "status": "ready", "progress": None}

    except Exception as e:
        logger.error(f"Failed to check sources KB status: {e}")
        raise HTTPException(status_code=500, detail=str(e))
