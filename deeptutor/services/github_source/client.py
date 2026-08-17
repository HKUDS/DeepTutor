"""Minimal async GitHub REST API client used by the KB source-sync engine.

Self-contained, depends only on ``httpx`` (already a project dependency).
No ``gh`` or ``git`` CLI required.  A ``GITHUB_TOKEN`` environment variable
is optional but recommended — it lifts the unauthenticated rate limit from
60 to 5 000 requests/hour and enables private-repo access.
"""

from __future__ import annotations

from dataclasses import dataclass
import logging
import os
from typing import Any

import httpx

logger = logging.getLogger(__name__)

GITHUB_API_BASE = "https://api.github.com"
DEFAULT_TIMEOUT_S = 30.0
MAX_FILE_BYTES = 2 * 1024 * 1024  # 2 MB cap per individual file download


@dataclass(frozen=True)
class TreeEntry:
    """One entry from a GitHub tree listing."""

    path: str
    sha: str
    type: str  # "blob" | "tree"


@dataclass(frozen=True)
class FileChange:
    """One file changed between two commits."""

    path: str
    status: str  # "added" | "removed" | "modified" | "renamed" | ...
    sha: str


@dataclass(frozen=True)
class GitHubAPIError(Exception):
    """Raised when the GitHub API returns a non-2xx response."""

    status_code: int
    message: str

    def __str__(self) -> str:
        return f"GitHub API {self.status_code}: {self.message}"


def _token() -> str | None:
    return os.environ.get("GITHUB_TOKEN") or None


def _headers() -> dict[str, str]:
    h: dict[str, str] = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "DeepTutor/1.0 (+https://hkuds.dev/deeptutor)",
    }
    token = _token()
    if token:
        h["Authorization"] = f"Bearer {token}"
    return h


class GitHubClient:
    """Thin async wrapper around the handful of REST endpoints we need."""

    def __init__(
        self,
        *,
        timeout_s: float = DEFAULT_TIMEOUT_S,
        client_factory: Any = None,
    ) -> None:
        self._timeout_s = timeout_s
        self._client_factory = client_factory

    async def _request_json(self, method: str, url: str, **kw: Any) -> Any:
        factory = self._client_factory or (lambda: httpx.AsyncClient(timeout=self._timeout_s))
        async with factory() as client:
            resp = await client.request(method, url, headers=_headers(), **kw)
        if resp.status_code >= 400:
            try:
                body = resp.json()
                msg = body.get("message", resp.text[:500])
            except Exception:
                msg = resp.text[:500]
            raise GitHubAPIError(resp.status_code, str(msg))
        return resp.json()

    async def _request_bytes(self, url: str, **kw: Any) -> bytes:
        factory = self._client_factory or (lambda: httpx.AsyncClient(timeout=self._timeout_s))
        async with factory() as client:
            resp = await client.get(url, headers=_headers(), **kw)
        if resp.status_code >= 400:
            raise GitHubAPIError(resp.status_code, resp.text[:500])
        return resp.content

    async def get_default_branch(self, repo: str) -> str:
        data = await self._request_json("GET", f"{GITHUB_API_BASE}/repos/{repo}")
        return data.get("default_branch", "main")

    async def get_latest_commit_sha(self, repo: str, branch: str) -> str:
        data = await self._request_json("GET", f"{GITHUB_API_BASE}/repos/{repo}/commits/{branch}")
        return data["sha"]

    async def get_tree(
        self,
        repo: str,
        branch: str,
        *,
        path_prefix: str = "",
        glob: str = "*.md",
    ) -> list[TreeEntry]:
        data = await self._request_json(
            "GET",
            f"{GITHUB_API_BASE}/repos/{repo}/git/trees/{branch}",
            params={"recursive": "1"},
        )
        entries: list[TreeEntry] = []
        prefix = path_prefix.strip("/")
        for item in data.get("tree", []):
            if item.get("type") != "blob":
                continue
            p = item.get("path", "")
            if prefix and not p.startswith(prefix + "/") and p != prefix:
                continue
            if not _match_glob(p, glob):
                continue
            entries.append(TreeEntry(path=p, sha=item.get("sha", ""), type="blob"))
        return entries

    async def compare_commits(self, repo: str, base: str, head: str) -> list[FileChange]:
        data = await self._request_json(
            "GET",
            f"{GITHUB_API_BASE}/repos/{repo}/compare/{base}...{head}",
        )
        changes: list[FileChange] = []
        for item in data.get("files", []):
            changes.append(
                FileChange(
                    path=item.get("filename", ""),
                    status=item.get("status", "modified"),
                    sha=item.get("sha", ""),
                )
            )
        return changes

    async def download_file(self, repo: str, path: str, ref: str) -> bytes:
        url = f"https://raw.githubusercontent.com/{repo}/{ref}/{path}"
        content = await self._request_bytes(url)
        if len(content) > MAX_FILE_BYTES:
            content = content[:MAX_FILE_BYTES]
        return content


def _match_glob(path: str, glob: str) -> bool:
    import fnmatch

    return fnmatch.fnmatch(path, glob) or fnmatch.fnmatch(path.rsplit("/", 1)[-1], glob)
