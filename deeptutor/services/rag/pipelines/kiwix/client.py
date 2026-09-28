"""Bounded client for kiwix-serve's public search and raw-content APIs.

One connected KB points to one ZIM name on one server.  Search uses the ZIM's
existing full-text index; only matched articles are read, so no archive is
uploaded, unpacked, or indexed again by DeepTutor.
"""

from __future__ import annotations

from dataclasses import dataclass
from html import unescape
from html.parser import HTMLParser
import re
from urllib.parse import quote, unquote, urlsplit

from defusedxml import ElementTree
import httpx

MAX_SEARCH_BYTES = 512_000
MAX_CATALOG_BYTES = 1_000_000
MAX_ARTICLE_BYTES = 2_000_000
MAX_ARTICLE_CHARS = 12_000
MAX_TITLE_BYTES = 32_000
_ZIM_NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,127}$")
_BLOCKS = frozenset(
    {"article", "br", "div", "h1", "h2", "h3", "h4", "h5", "h6", "li", "p", "section", "tr"}
)
_SKIP = frozenset({"script", "style", "nav", "footer", "header", "noscript"})


class KiwixError(ValueError):
    """The configured server or selected archive cannot satisfy a request."""


def normalize_base_url(value: str) -> str:
    raw = str(value or "").strip()
    if len(raw) > 2048 or any(ord(char) < 32 for char in raw):
        raise KiwixError("Enter a valid kiwix-serve base URL.")
    parsed = urlsplit(raw)
    try:
        port = parsed.port
    except ValueError as exc:
        raise KiwixError("Enter a valid kiwix-serve host and port.") from exc
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or (port is not None and not 1 <= port <= 65535)
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or any(part in {".", ".."} for part in unquote(parsed.path).split("/"))
    ):
        raise KiwixError(
            "Enter a kiwix-serve HTTP(S) base URL without credentials or query parameters."
        )
    return parsed.geturl().rstrip("/")


def validate_zim_name(value: str) -> str:
    name = str(value or "").strip()
    if not _ZIM_NAME.fullmatch(name):
        raise KiwixError("Enter one ZIM name from the Kiwix library (letters, numbers, _, - or .).")
    return name


def validate_article_path(value: str) -> str:
    path = unquote(str(value or "").strip()).lstrip("/")
    if (
        not path
        or len(path) > 2048
        or any(part in {"", ".", ".."} for part in path.split("/"))
        or any(ord(char) < 32 for char in path)
        or "\\" in path
    ):
        raise KiwixError("Invalid ZIM article path.")
    return path


class _PlainText(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self.skip_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in _SKIP:
            self.skip_depth += 1
        elif not self.skip_depth and tag in _BLOCKS:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag in _SKIP and self.skip_depth:
            self.skip_depth -= 1
        elif not self.skip_depth and tag in _BLOCKS:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if not self.skip_depth:
            self.parts.append(data)


def html_to_text(raw: str, *, max_chars: int = MAX_ARTICLE_CHARS) -> str:
    parser = _PlainText()
    parser.feed(raw)
    text = unescape("".join(parser.parts))
    return re.sub(
        r"\n{3,}", "\n\n", "\n".join(" ".join(line.split()) for line in text.splitlines())
    ).strip()[:max_chars]


@dataclass(frozen=True)
class KiwixHit:
    title: str
    article_path: str
    snippet: str


@dataclass(frozen=True)
class KiwixArchive:
    zim_name: str
    title: str


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def parse_catalog_xml(data: bytes, *, base_url: str) -> list[KiwixArchive]:
    """Read exact ZIM identifiers from a bounded legacy OPDS acquisition feed."""
    try:
        root = ElementTree.fromstring(data)
    except Exception as exc:
        raise KiwixError("kiwix-serve returned invalid OPDS catalog XML.") from exc
    if _local_name(root.tag) != "feed":
        raise KiwixError("kiwix-serve returned an unexpected OPDS catalog format.")
    base = urlsplit(base_url)
    prefix = f"{base.path.rstrip('/')}/content/"
    archives: list[KiwixArchive] = []
    seen: set[str] = set()
    for entry in root:
        if _local_name(entry.tag) != "entry":
            continue
        fields = {_local_name(child.tag): child for child in entry}
        name = ""
        # OPDS <name> may be a date-free alias. The same-server content link
        # identifies the exact loaded archive/version selected by the user.
        for link in entry:
            if (
                _local_name(link.tag) != "link"
                or link.attrib.get("type", "").split(";", 1)[0].lower() != "text/html"
            ):
                continue
            url = urlsplit(link.attrib.get("href") or "")
            if url.scheme and (url.scheme, url.netloc) != (base.scheme, base.netloc):
                continue
            if url.netloc and not url.scheme:
                continue
            if url.query or not url.path.startswith(prefix):
                continue
            name = unquote(url.path[len(prefix) :].split("/", 1)[0])
            break
        if not name:
            name = (fields.get("name").text or "").strip() if fields.get("name") is not None else ""
        try:
            name = validate_zim_name(name)
        except KiwixError:
            continue
        if name in seen:
            continue
        seen.add(name)
        title = (
            " ".join((fields.get("title").text or "").split())
            if fields.get("title") is not None
            else ""
        )
        archives.append(KiwixArchive(zim_name=name, title=title[:300] or name))
        if len(archives) >= 50:
            break
    return archives


def parse_search_xml(data: bytes, *, base_url: str, zim_name: str) -> list[KiwixHit]:
    """Accept only RSS items linked to the selected archive on this server."""
    try:
        root = ElementTree.fromstring(data)
    except Exception as exc:
        raise KiwixError("kiwix-serve returned invalid search XML.") from exc
    if root.tag != "rss":
        raise KiwixError("kiwix-serve returned an unexpected search format.")
    base = urlsplit(base_url)
    prefix = f"{base.path.rstrip('/')}/content/{quote(zim_name, safe='')}/"
    hits: list[KiwixHit] = []
    for item in root.findall("./channel/item"):
        link = (item.findtext("link") or "").strip()
        parsed = urlsplit(link)
        if parsed.scheme and (parsed.scheme, parsed.netloc) != (base.scheme, base.netloc):
            continue
        if parsed.query or not parsed.path.startswith(prefix):
            continue
        try:
            article_path = validate_article_path(parsed.path[len(prefix) :])
        except KiwixError:
            continue
        title = " ".join((item.findtext("title") or "").split())[:300]
        description = item.find("description")
        snippet = (
            " ".join("".join(description.itertext()).split())[:1000]
            if description is not None
            else ""
        )
        hits.append(
            KiwixHit(title=title or article_path, article_path=article_path, snippet=snippet)
        )
    return hits


class KiwixClient:
    def __init__(
        self, base_url: str, zim_name: str, *, transport: httpx.AsyncBaseTransport | None = None
    ) -> None:
        self.base_url = normalize_base_url(base_url)
        self.zim_name = validate_zim_name(zim_name)
        self.transport = transport

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            transport=self.transport,
            timeout=httpx.Timeout(10.0),
            follow_redirects=False,
            trust_env=False,
        )

    @classmethod
    async def list_archives(
        cls, base_url: str, query: str = "", *, transport: httpx.AsyncBaseTransport | None = None
    ) -> list[KiwixArchive]:
        """Browse a server's loaded books via legacy OPDS, whose v2 feed can omit them."""
        client = cls(base_url, "catalog", transport=transport)
        params: dict[str, str | int] = {"count": 50, "start": 0}
        if query.strip():
            params["q"] = query.strip()[:100]
        async with client._client() as http:
            raw, _ = await client._get(
                http, "catalog/search", params=params, limit=MAX_CATALOG_BYTES
            )
        return parse_catalog_xml(raw, base_url=client.base_url)

    async def _get(
        self,
        client: httpx.AsyncClient,
        path: str,
        *,
        params: dict[str, str | int] | None = None,
        limit: int,
    ) -> tuple[bytes, str]:
        url = f"{self.base_url}/{path.lstrip('/')}"
        try:
            async with client.stream("GET", url, params=params) as response:
                if response.status_code != 200:
                    raise KiwixError(f"kiwix-serve returned HTTP {response.status_code}.")
                content_type = response.headers.get("content-type", "").split(";", 1)[0].lower()
                body = bytearray()
                async for chunk in response.aiter_bytes():
                    body.extend(chunk)
                    if len(body) > limit:
                        raise KiwixError("kiwix-serve response exceeded the article size limit.")
                return bytes(body), content_type
        except httpx.HTTPError as exc:
            raise KiwixError("Could not reach kiwix-serve.") from exc

    async def probe(self) -> str:
        """Check metadata and a real one-result search without scanning the ZIM."""
        async with self._client() as client:
            raw, _ = await self._get(
                client,
                f"raw/{quote(self.zim_name, safe='')}/meta/Title",
                limit=MAX_TITLE_BYTES,
            )
            try:
                xml, _ = await self._get(
                    client,
                    "search",
                    params={
                        "books.name": self.zim_name,
                        "pattern": "a",
                        "format": "xml",
                        "pageLength": 1,
                    },
                    limit=MAX_SEARCH_BYTES,
                )
                parse_search_xml(xml, base_url=self.base_url, zim_name=self.zim_name)
            except KiwixError as exc:
                raise KiwixError(
                    "The archive is readable, but kiwix-serve full-text search is unavailable. "
                    "Book and Guided Learning need a searchable ZIM."
                ) from exc
        title = raw.decode("utf-8", errors="replace").strip()
        if not title:
            raise KiwixError("The selected ZIM archive has no readable title metadata.")
        return title[:300]

    async def search(self, query: str, *, top_k: int = 5) -> list[tuple[KiwixHit, str]]:
        count = max(1, min(int(top_k), 10))
        async with self._client() as client:
            xml, _ = await self._get(
                client,
                "search",
                params={
                    "books.name": self.zim_name,
                    "pattern": query[:500],
                    "format": "xml",
                    "pageLength": count,
                },
                limit=MAX_SEARCH_BYTES,
            )
            hits = parse_search_xml(xml, base_url=self.base_url, zim_name=self.zim_name)[:count]
            # Hydrate only a few hits.  The Kiwix search snippet remains useful
            # evidence for the rest, and an unreadable title alone is never cited.
            result: list[tuple[KiwixHit, str]] = []
            for hit in hits:
                text = ""
                if len(result) < 4:
                    try:
                        text = await self._read_article(client, hit.article_path)
                    except KiwixError:
                        pass
                if text or hit.snippet:
                    # The first article characters can be unrelated to a hit
                    # thousands of words later. Book clips source text to 1200
                    # chars, so lead with Kiwix's matched search passage.
                    context = (
                        f"Search match: {hit.snippet}\n\nArticle opening: {text}"
                        if hit.snippet and text
                        else f"Search match: {hit.snippet}"
                        if hit.snippet
                        else text
                    )
                    result.append((hit, context))
            return result

    async def _read_article(
        self,
        client: httpx.AsyncClient,
        article_path: str,
        *,
        max_chars: int = MAX_ARTICLE_CHARS,
    ) -> str:
        path = validate_article_path(article_path)
        raw, mime = await self._get(
            client,
            f"raw/{quote(self.zim_name, safe='')}/content/{quote(path, safe='/')}",
            limit=MAX_ARTICLE_BYTES,
        )
        if mime not in {"text/html", "application/xhtml+xml", "text/plain"}:
            raise KiwixError("The selected ZIM entry is not a readable article.")
        decoded = raw.decode("utf-8", errors="replace")
        return (
            html_to_text(decoded, max_chars=max_chars)
            if mime != "text/plain"
            else decoded.strip()[:max_chars]
        )

    async def read_article(self, article_path: str) -> str:
        async with self._client() as client:
            text = await self._read_article(client, article_path, max_chars=500_000)
        if not text:
            raise KiwixError("The selected ZIM article has no readable text.")
        return text
