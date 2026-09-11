"""Core sync logic: pull Markdown from a GitHub repo into a KB's raw/ dir."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import logging
from pathlib import Path
import re
from urllib.parse import urlsplit, urlunsplit

from deeptutor.knowledge.add_documents import DEFAULT_BASE_DIR
from deeptutor.services.github_source.client import (
    GitHubAPIError,
    GitHubClient,
)

logger = logging.getLogger(__name__)

SYNC_INTERVAL_HOURS = 24
MARKDOWN_EXTENSIONS = (".md", ".markdown")


@dataclass
class SyncResult:
    ok: bool
    skipped: bool = False
    files_added: int = 0
    files_updated: int = 0
    files_removed: int = 0
    error: str = ""


def _utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def redact_sync_error(exc: Exception) -> str:
    """Return a bounded sync error without credential-shaped values."""
    message = str(exc).strip() or type(exc).__name__

    def redact_url(match: re.Match[str]) -> str:
        try:
            parsed = urlsplit(match.group(0))
            host = parsed.hostname or ""
            if parsed.port is not None:
                host = f"{host}:{parsed.port}"
            return urlunsplit((parsed.scheme, host, parsed.path, "", ""))
        except ValueError:
            # Error strings are untrusted input too. A malformed bracket or port
            # must not make credential redaction mask the original sync failure.
            return "[redacted-url]"

    message = re.sub(r"https?://[^\s,;]+", redact_url, message)
    message = re.sub(r"\bsk-[A-Za-z0-9_-]{4,}\b", "[redacted]", message)
    message = re.sub(
        r"(?i)((?:api[_-]?key|authorization|token|password)\s*[:=]\s*)[^\s,;]+",
        r"\1[redacted]",
        message,
    )
    return message[:1000]


def _record_sync_failure(kb_name: str, source: dict, base_dir: str, error: str) -> None:
    try:
        from deeptutor.knowledge.manager import KnowledgeBaseManager

        KnowledgeBaseManager(base_dir=base_dir).update_github_source_state(
            kb_name=kb_name,
            source_id=source["id"],
            last_sync_status="error",
            last_sync_error=error,
        )
    except Exception:
        logger.warning("Could not persist GitHub sync failure status for '%s'", kb_name)


def _is_markdown(path: str) -> bool:
    return path.lower().endswith(MARKDOWN_EXTENSIONS)


def _raw_rel_path(github_path: str, path_prefix: str) -> str:
    prefix = path_prefix.strip("/")
    if prefix and github_path.startswith(prefix + "/"):
        return github_path[len(prefix) + 1 :]
    return github_path


def _contained_dest(raw_dir: Path, rel: str) -> Path | None:
    """Resolve *rel* under *raw_dir*, or ``None`` if it escapes.

    ``rel`` comes from the GitHub API's tree/compare response, so it is remote
    input. Two shapes would otherwise write outside the KB: a ``..`` segment,
    and — more quietly — an absolute path, because ``Path("/kb") / "/etc/x"``
    is ``/etc/x``, silently discarding the base. git rejects both in tree
    entries today, but a downloader must not depend on the remote to enforce
    where it writes.
    """
    candidate = (raw_dir / rel).resolve()
    root = raw_dir.resolve()
    if candidate != root and root not in candidate.parents:
        logger.warning("GitHub sync: refusing path outside the KB raw dir: %s", rel)
        return None
    return candidate


def _filter_markdown_changes(changes, path_prefix, glob):
    from fnmatch import fnmatch

    prefix = path_prefix.strip("/")
    result = []
    for ch in changes:
        p = ch.path
        if prefix and not p.startswith(prefix + "/") and p != prefix:
            continue
        if not (_is_markdown(p) and (fnmatch(p, glob) or fnmatch(p.rsplit("/", 1)[-1], glob))):
            continue
        result.append(ch)
    return result


def _filter_markdown_entries(entries, path_prefix, glob):
    from fnmatch import fnmatch

    prefix = path_prefix.strip("/")
    result = []
    for e in entries:
        p = e.path
        if prefix and not p.startswith(prefix + "/") and p != prefix:
            continue
        if not (_is_markdown(p) and (fnmatch(p, glob) or fnmatch(p.rsplit("/", 1)[-1], glob))):
            continue
        result.append(e)
    return result


async def sync_source(kb_name, source, *, base_dir=DEFAULT_BASE_DIR, client=None):
    client = client or GitHubClient()
    kb_dir = Path(base_dir) / kb_name
    raw_dir = kb_dir / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)

    repo = source["repo"]
    branch = source.get("branch") or "main"
    path_prefix = source.get("path") or ""
    glob = source.get("glob") or "*.md"
    old_sha = source.get("last_synced_sha") or ""

    try:
        latest_sha = await client.get_latest_commit_sha(repo, branch)
    except GitHubAPIError as exc:
        error = redact_sync_error(exc)
        _record_sync_failure(kb_name, source, base_dir, error)
        return SyncResult(ok=False, error=error)
    except Exception as exc:
        error = f"Failed to fetch latest SHA: {redact_sync_error(exc)}"
        _record_sync_failure(kb_name, source, base_dir, error)
        return SyncResult(ok=False, error=error)

    if old_sha and old_sha == latest_sha:
        return SyncResult(ok=True, skipped=True)

    try:
        if not old_sha:
            result = await _full_sync(
                client, kb_name, raw_dir, repo, branch, path_prefix, glob, latest_sha, base_dir
            )
        else:
            result = await _incremental_sync(
                client,
                kb_name,
                raw_dir,
                repo,
                branch,
                path_prefix,
                glob,
                old_sha,
                latest_sha,
                base_dir,
            )
    except GitHubAPIError as exc:
        error = redact_sync_error(exc)
        _record_sync_failure(kb_name, source, base_dir, error)
        return SyncResult(ok=False, error=error)
    except Exception as exc:
        error = redact_sync_error(exc)
        _record_sync_failure(kb_name, source, base_dir, error)
        return SyncResult(ok=False, error=error)

    if not result.ok:
        _record_sync_failure(kb_name, source, base_dir, result.error)
        return result

    from deeptutor.knowledge.manager import KnowledgeBaseManager

    manager = KnowledgeBaseManager(base_dir=base_dir)
    manager.update_github_source_state(
        kb_name=kb_name,
        source_id=source["id"],
        last_synced_sha=latest_sha,
        last_synced_at=_utcnow_iso(),
        last_sync_status="success",
        last_sync_error=None,
        files_synced=result.files_added + result.files_updated,
    )
    return result


async def _full_sync(
    client, kb_name, raw_dir, repo, branch, path_prefix, glob, latest_sha, base_dir
):
    tree = await client.get_tree(repo, branch, path_prefix=path_prefix, glob=glob)
    entries = _filter_markdown_entries(tree, path_prefix, glob)
    downloaded = []
    for entry in entries:
        rel = _raw_rel_path(entry.path, path_prefix)
        dest = _contained_dest(raw_dir, rel)
        if dest is None:
            continue
        dest.parent.mkdir(parents=True, exist_ok=True)
        content = await client.download_file(repo, entry.path, latest_sha)
        dest.write_bytes(content)
        downloaded.append(str(dest))
    if downloaded:
        await _index_files(kb_name, downloaded, base_dir)
    return SyncResult(ok=True, files_added=len(downloaded))


async def _incremental_sync(
    client, kb_name, raw_dir, repo, branch, path_prefix, glob, old_sha, new_sha, base_dir
):
    all_changes = await client.compare_commits(repo, old_sha, new_sha)
    changes = _filter_markdown_changes(all_changes, path_prefix, glob)
    added_or_modified = []
    removed = []
    for ch in changes:
        rel = _raw_rel_path(ch.path, path_prefix)
        if ch.status == "removed":
            removed.append(rel)
        else:
            added_or_modified.append(ch.path)
    downloaded = []
    for gh_path in added_or_modified:
        rel = _raw_rel_path(gh_path, path_prefix)
        dest = _contained_dest(raw_dir, rel)
        if dest is None:
            continue
        content = await client.download_file(repo, gh_path, new_sha)
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(content)
        downloaded.append(str(dest))
    if downloaded:
        await _index_files(kb_name, downloaded, base_dir)
    removed_count = 0
    for rel in removed:
        target = _contained_dest(raw_dir, rel)
        if target is not None and target.exists():
            try:
                from deeptutor.knowledge.add_documents import remove_raw_document

                kb_dir = Path(base_dir) / kb_name
                remove_raw_document(kb_dir, target)
                removed_count += 1
            except Exception as exc:
                logger.warning("Failed to remove %s: %s", rel, exc)
    return SyncResult(ok=True, files_added=len(downloaded), files_removed=removed_count)


async def _index_files(kb_name, file_paths, base_dir):
    if not file_paths:
        return 0
    from deeptutor.knowledge.add_documents import add_documents

    count = await add_documents(
        kb_name=kb_name, source_files=file_paths, base_dir=base_dir, allow_duplicates=False
    )
    return count or 0
