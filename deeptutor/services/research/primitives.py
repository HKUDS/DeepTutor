"""Bounded primary-source evidence for scientific research (#1629).

These primitives read papers and pinned repository snapshots. They never run a
repository, and do not infer experimental reproduction from static inspection.
"""

from __future__ import annotations

import asyncio
from decimal import Decimal, InvalidOperation
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import threading
import time
from typing import Any
from urllib.parse import quote, urljoin, urlsplit

from defusedxml import ElementTree as ET
from defusedxml.common import DefusedXmlException
import httpx

from deeptutor.services.mcp.network import validate_mcp_url_async

_ATOM = "{http://www.w3.org/2005/Atom}"
_ID = re.compile(r"(?:\d{4}\.\d{4,5}|[a-z][a-z.-]+/\d{7})(?:v[1-9]\d*)?")
_HOSTS = {"arxiv.org", "export.arxiv.org", "api.github.com", "raw.githubusercontent.com"}
_API_LOCK = threading.Lock()
_NEXT_API = 0.0
ARXIV_INTERVAL = 3.0


class ResearchError(ValueError):
    pass


def arxiv_id(value: str) -> str:
    value = re.sub(r"^arxiv:\s*", "", value.strip(), flags=re.I)
    if "://" in value:
        parsed = urlsplit(value)
        if (
            parsed.scheme not in {"http", "https"}
            or parsed.hostname
            not in {"arxiv.org", "www.arxiv.org", "alphaxiv.org", "www.alphaxiv.org"}
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
        ):
            raise ResearchError("Use an arXiv identifier or canonical arXiv/alphaXiv paper URL.")
        value = re.sub(r"^/(?:abs|pdf)/", "", parsed.path)
    value = value.removesuffix(".pdf")
    if not _ID.fullmatch(value):
        raise ResearchError(
            "Invalid arXiv identifier; versions and legacy archive IDs are supported."
        )
    return value


def repository(value: str) -> tuple[str, str]:
    parsed = urlsplit(value)
    parts = parsed.path.strip("/").split("/")
    if (
        parsed.scheme != "https"
        or parsed.hostname != "github.com"
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or len(parts) != 2
    ):
        raise ResearchError(
            "Native audit needs https://github.com/owner/repository; other providers can use a configured research MCP server."
        )
    owner, name = parts[0], parts[1].removesuffix(".git")
    if (
        not re.fullmatch(r"[A-Za-z0-9_-]{1,39}", owner)
        or not re.fullmatch(r"[A-Za-z0-9_.-]{1,100}", name)
        or name in {".", ".."}
    ):
        raise ResearchError("Invalid GitHub repository identity.")
    return owner, name


def source_path(value: str) -> str:
    path = PurePosixPath(value)
    if not value or path.is_absolute() or ".." in path.parts or "\\" in value or len(value) > 300:
        raise ResearchError("Repository paths must be bounded relative file paths.")
    return path.as_posix()


async def _pace_arxiv():
    global _NEXT_API
    with _API_LOCK:
        now = time.monotonic()
        delay = max(0, _NEXT_API - now)
        _NEXT_API = max(now, _NEXT_API) + ARXIV_INTERVAL
    if delay:
        await asyncio.sleep(delay)


class ResearchClient:
    def __init__(
        self,
        *,
        client_factory=None,
        cache_root: Path | None = None,
        github_token: str | None = None,
    ):
        self.client_factory = client_factory or (
            lambda: httpx.AsyncClient(timeout=httpx.Timeout(30, connect=10), follow_redirects=False)
        )
        self.cache_root = cache_root
        self.github_token = github_token

    async def fetch(self, url: str, *, limit: int, accept: str = "application/json") -> bytes:
        async with asyncio.timeout(45):
            async with self.client_factory() as client:
                for _ in range(4):
                    parsed = urlsplit(url)
                    if (
                        parsed.scheme != "https"
                        or parsed.hostname not in _HOSTS
                        or parsed.username
                        or parsed.password
                    ):
                        raise ResearchError(
                            "Research downloads are restricted to primary-source hosts."
                        )
                    ok, detail = await validate_mcp_url_async(url, strict=True)
                    if not ok:
                        raise ResearchError(detail)
                    headers = {"User-Agent": "DeepTutor-Research/1", "Accept": accept}
                    if parsed.hostname == "api.github.com" and self.github_token:
                        headers["Authorization"] = f"Bearer {self.github_token}"
                    async with client.stream("GET", url, headers=headers) as response:
                        if response.is_redirect:
                            url = urljoin(url, response.headers.get("location", ""))
                            continue
                        if response.status_code != 200:
                            raise ResearchError(
                                f"Primary source returned HTTP {response.status_code}; evidence was not retrieved."
                            )
                        data = bytearray()
                        async for chunk in response.aiter_bytes():
                            if len(data) + len(chunk) > limit:
                                raise ResearchError(
                                    "Primary source exceeded the configured byte budget."
                                )
                            data.extend(chunk)
                        return bytes(data)
                raise ResearchError("Primary source exceeded the redirect budget.")

    async def search(self, query: str, *, limit: int = 6) -> list[dict]:
        if not query.strip() or len(query) > 1000 or not 1 <= limit <= 8:
            raise ResearchError(
                "Use a nonempty query up to 1000 characters and at most eight papers."
            )
        await _pace_arxiv()
        raw = await self.fetch(
            "https://export.arxiv.org/api/query?search_query="
            + quote(query, safe="")
            + f"&max_results={limit}&sortBy=relevance",
            limit=2 * 1024 * 1024,
            accept="application/atom+xml",
        )
        return parse_feed(raw)

    async def paper(self, identifier: str) -> dict:
        identifier = arxiv_id(identifier)
        await _pace_arxiv()
        papers = parse_feed(
            await self.fetch(
                "https://export.arxiv.org/api/query?id_list=" + quote(identifier, safe=""),
                limit=2 * 1024 * 1024,
                accept="application/atom+xml",
            )
        )
        if len(papers) != 1 or re.sub(r"v\d+$", "", papers[0]["arxiv_id"]) != re.sub(
            r"v\d+$", "", identifier
        ):
            raise ResearchError("The requested preprint was not returned by the primary source.")
        if re.search(r"v\d+$", identifier) and papers[0]["arxiv_id"] != identifier:
            raise ResearchError("The primary source did not return the requested paper version.")
        return papers[0]

    async def read_paper(
        self, identifier: str, *, pages: list[int] | None = None, figures: bool = False
    ) -> tuple[dict, list[bytes]]:
        if pages is not None and (
            not isinstance(pages, list)
            or len(pages) > 20
            or any(
                isinstance(page, bool) or not isinstance(page, int) or page < 1 for page in pages
            )
        ):
            raise ResearchError("Choose at most 20 positive, one-based source pages.")
        paper = await self.paper(identifier)
        raw = await self.fetch(paper["pdf_url"], limit=32 * 1024 * 1024, accept="application/pdf")
        if not raw.startswith(b"%PDF-"):
            raise ResearchError("Primary source did not return a PDF.")
        digest = hashlib.sha256(raw).hexdigest()
        extracted, images = await asyncio.to_thread(read_pdf, raw, pages, figures)
        if self.cache_root is not None:
            self.cache_root.mkdir(parents=True, exist_ok=True)
            # Complete bytes only; failed downloads never become a reusable PDF.
            import tempfile

            with tempfile.NamedTemporaryFile(dir=self.cache_root, delete=False) as handle:
                handle.write(raw)
                temporary = Path(handle.name)
            temporary.replace(self.cache_root / f"{digest}.pdf")
        paper.update(
            extracted,
            source_sha256=digest,
            evidence_level="primary_pdf",
            experimental_reproduction="not_run",
        )
        return paper, images

    async def code(self, url: str, *, files: list[str] | None = None, ref: str = "HEAD") -> dict:
        owner, name = repository(url)
        api = f"https://api.github.com/repos/{owner}/{name}"
        if not re.fullmatch(r"[A-Za-z0-9_./-]{1,100}", ref):
            raise ResearchError("Invalid repository revision.")
        commit = json.loads(
            await self.fetch(api + "/commits/" + quote(ref, safe=""), limit=1024 * 1024)
        )
        sha = str(commit.get("sha", ""))
        if not re.fullmatch(r"[a-f0-9]{40}", sha):
            raise ResearchError("Repository did not return an immutable commit identity.")
        tree = json.loads(
            await self.fetch(api + f"/git/trees/{sha}?recursive=1", limit=2 * 1024 * 1024)
        )
        paths = [
            row["path"]
            for row in tree.get("tree", [])
            if row.get("type") == "blob" and row.get("mode") != "120000"
        ]
        selected = [source_path(value) for value in files] if files else choose_files(paths)
        if len(selected) > 8:
            raise ResearchError("Static audits read at most eight selected repository files.")
        results: list[dict[str, Any]] = []
        for path in selected:
            if path not in paths:
                results.append({"path": path, "status": "unavailable"})
                continue
            try:
                data = await self.fetch(
                    api + "/contents/" + quote(path, safe="/") + f"?ref={sha}",
                    limit=128 * 1024,
                    accept="application/vnd.github.raw+json",
                )
                text = data.decode("utf-8")
            except (ResearchError, UnicodeError) as exc:
                results.append({"path": path, "status": "unverified", "reason": str(exc)})
                continue
            results.append(
                {
                    "path": path,
                    "status": "read",
                    "text": text[:24000],
                    "truncated": len(text) > 24000,
                    "sha256": hashlib.sha256(data).hexdigest(),
                    "url": f"https://github.com/{owner}/{name}/blob/{sha}/{quote(path, safe='/')}",
                }
            )
        return {
            "repository": f"https://github.com/{owner}/{name}",
            "commit": sha,
            "requested_ref": ref,
            "files": results,
            "tree_truncated": bool(tree.get("truncated")),
            "execution": "not_run",
            "scope": "selected static files, not proof of experimental reproducibility",
        }


def parse_feed(raw: bytes) -> list[dict]:
    if b"<!DOCTYPE" in raw.upper() or b"<!ENTITY" in raw.upper():
        raise ResearchError("Unexpected XML declarations in primary-source response.")
    try:
        root = ET.fromstring(raw)
    except (ET.ParseError, DefusedXmlException) as exc:
        raise ResearchError("Primary-source metadata was not a usable Atom feed.") from exc
    if root.tag != _ATOM + "feed":
        raise ResearchError("Primary-source metadata was not an Atom feed.")
    rows = []
    for entry in root.findall(_ATOM + "entry")[:8]:
        identifier = arxiv_id(entry.findtext(_ATOM + "id", ""))
        rows.append(
            {
                "arxiv_id": identifier,
                "title": " ".join(entry.findtext(_ATOM + "title", "").split()),
                "authors": [
                    author.findtext(_ATOM + "name", "")
                    for author in entry.findall(_ATOM + "author")
                ],
                "abstract": " ".join(entry.findtext(_ATOM + "summary", "").split())[:12000],
                "published": entry.findtext(_ATOM + "published", ""),
                "updated": entry.findtext(_ATOM + "updated", ""),
                "url": f"https://arxiv.org/abs/{identifier}",
                "pdf_url": f"https://arxiv.org/pdf/{identifier}",
                "evidence_level": "primary_abstract",
            }
        )
    return rows


def read_pdf(raw: bytes, pages: list[int] | None, figures: bool) -> tuple[dict, list[bytes]]:
    import fitz

    images: list[bytes] = []
    rendered_pages = []
    try:
        opened = fitz.open(stream=raw, filetype="pdf")
    except (RuntimeError, ValueError) as exc:
        raise ResearchError(
            "Primary PDF is unreadable or damaged; no page evidence was extracted."
        ) from exc
    with opened as document:
        if not document.page_count:
            raise ResearchError("Primary PDF has no source pages.")
        if document.page_count > 500:
            raise ResearchError(
                "Research PDF exceeds 500 pages; use the knowledge-base long-document workflow."
            )
        caption_pages = (
            [
                index + 1
                for index in range(document.page_count)
                if re.search(
                    r"(?m)^\s*(?:Figure|Fig\.?|图)\s*\d+\s*[:：.]", document[index].get_text(), re.I
                )
            ]
            if figures and pages is None
            else []
        )
        selected = pages or (
            caption_pages[:20]
            if caption_pages
            else list(range(1, min(document.page_count, 20) + 1))
        )
        if len(selected) > 20 or any(
            isinstance(page, bool)
            or not isinstance(page, int)
            or not 1 <= page <= document.page_count
            for page in selected
        ):
            raise ResearchError("Choose at most 20 valid one-based source pages.")
        rows = []
        text_budget = 36000
        for number in dict.fromkeys(selected):
            page = document[number - 1]
            text = page.get_text()[: min(4000, text_budget)]
            text_budget -= len(text)
            rows.append(
                {"page": number, "text": text, "text_truncated": len(page.get_text()) > len(text)}
            )
            if figures and len(images) < 2:
                scale = min(2.0, 1800 / max(page.rect.width, page.rect.height))
                png = page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False).tobytes("png")
                if len(png) <= 5 * 1024 * 1024:
                    images.append(png)
                    rendered_pages.append(number)
        return {
            "pages": rows,
            "total_pages": document.page_count,
            "text_status": "extracted"
            if any(row["text"].strip() for row in rows)
            else "no_extractable_text",
            "figure_discovery": "caption_candidate_pages"
            if caption_pages
            else "explicit_pages_or_page_fallback",
            "partial": not any(row["text"].strip() for row in rows)
            or len(rows) != document.page_count
            or any(row["text_truncated"] for row in rows),
            "visual_scope": "faithful source-page renders; these are not automatically identified figure crops",
            "rendered_pages": rendered_pages,
        }, images


def choose_files(paths: list[str]) -> list[str]:
    preferred = sorted(
        paths,
        key=lambda path: (
            0
            if path.casefold().startswith("readme")
            else 1
            if re.search(r"(?:model|train|eval|config|requirements)", path, re.I)
            else 2,
            len(path),
            path,
        ),
    )
    return [
        path
        for path in preferred
        if Path(path).suffix.lower()
        in {".py", ".md", ".toml", ".yaml", ".yml", ".json", ".txt", ".cpp", ".h"}
    ][:6]


def normalize_quote(value: str) -> str:
    return " ".join(value.split())


def audit_checks(paper: dict, code: dict, checks: list[dict]) -> list[dict]:
    """Candidate numeric discrepancies require both exact source quotations."""
    if len(checks) > 12:
        raise ResearchError("An audit accepts at most twelve explicit checks.")
    pages = paper.get("pages", [])
    files = {row["path"]: row for row in code["files"] if row.get("status") == "read"}
    results = []
    for check in checks:
        row = {"claim": str(check.get("claim", ""))[:1000], "status": "unverified"}
        pq, cq = str(check.get("paper_quote", "")), str(check.get("code_quote", ""))
        source = files.get(str(check.get("file", "")))
        page = next(
            (page for page in pages if pq and normalize_quote(pq) in normalize_quote(page["text"])),
            None,
        )
        if source and cq and normalize_quote(cq) in normalize_quote(source["text"]) and page:
            row.update(
                paper_page=page["page"],
                paper_quote=pq[:1500],
                code_quote=cq[:1500],
                code_url=source["url"],
            )
            expected, implemented = (
                str(check.get("expected", "")),
                str(check.get("implemented", "")),
            )

            def matches(value, text):
                return bool(
                    value and re.search(r"(?<![\w.])" + re.escape(value) + r"(?![\w.])", text)
                )

            if matches(expected, pq) and matches(implemented, cq):
                try:
                    if not Decimal(expected).is_finite() or not Decimal(implemented).is_finite():
                        raise InvalidOperation
                    row["status"] = (
                        "candidate_discrepancy"
                        if Decimal(expected) != Decimal(implemented)
                        else "values_match"
                    )
                except InvalidOperation:
                    row["status"] = "requires_semantic_review"
            else:
                row["status"] = "requires_semantic_review"
        row["interpretation"] = (
            "Static quotation/value comparison. Check parameter mapping, units, defaults and active execution path before concluding."
        )
        results.append(row)
    return results


async def literature(client: ResearchClient, topic: str, followups: list[str]) -> dict:
    if len(followups) > 3:
        raise ResearchError("Use at most three recursive follow-up queries per literature pass.")
    papers, searches = {}, []
    for query in [topic, *followups]:
        rows = await client.search(query, limit=6)
        searches.append({"query": query, "count": len(rows)})
        for paper in rows:
            identity = re.sub(r"v\d+$", "", paper["arxiv_id"])
            papers[identity] = paper
    return {
        "searches": searches,
        "papers": list(papers.values()),
        "comparative_matrix": [
            {
                "source": paper["arxiv_id"],
                "authors": paper["authors"],
                "claim_evidence": paper["abstract"],
                "url": paper["url"],
                "evidence_level": "primary_abstract",
                "agreement": "requires_full_text_comparison",
                "contention": "requires_full_text_comparison",
            }
            for paper in papers.values()
        ],
        "coverage": "bounded arXiv discovery, not an exhaustive systematic review",
        "next_step": "Read full primary papers with preprint; compare claim, method, dataset, metric, result and limitations. Recurse with explicit follow-up queries; classify consensus/contention only with cited evidence.",
    }
