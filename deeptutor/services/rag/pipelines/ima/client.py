"""Client for Tencent IMA's knowledge-base OpenAPI (``/openapi/wiki/v1``).

A method table over the calls DeepTutor needs, with the wire mechanics delegated
to :class:`~deeptutor.services.rag.pipelines.ima.transport.ImaTransport`, the
payload decoding to :mod:`.models`, and file downloads to :mod:`.media`:

Reading
    * ``search_knowledge`` — retrieval inside one knowledge base; returns matched
      items with a ``highlight_content`` snippet, cursor-paginated.
    * ``get_knowledge_list`` — *browse* a knowledge base (or one of its folders)
      and see what it actually holds. This is the inventory call: retrieval can
      only report what a query matched, never what a library contains.
    * ``search_knowledge_base`` / ``get_knowledge_base`` — which libraries these
      credentials can reach, and one library's name / description (which doubles
      as the connect-time credential check).
    * ``get_media_info`` (+ the notes module's ``get_doc_content``) — full source
      text for one item.

Writing
    * ``import_urls`` — add web pages / WeChat articles to a library.
    * the notes module (see :class:`ImaNotesClient`) — create or append notes.

Uploading local *files* is deliberately still out of scope: IMA's upload is a
four-step transaction ending in a signed direct-to-COS PUT, which needs its own
credential handling and size/type preflight. Deleting anything in IMA is out of
scope permanently — a connected KB never destroys the user's own library.
"""

from __future__ import annotations

from typing import Any, Optional

import httpx

from . import media as media_ops
from .config import ImaConfig
from .envelope import ImaAPIError, ImaAuthError, ImaRateLimitError
from .media import MAX_MEDIA_BYTES, ImaMediaContent
from .models import (
    ImaImportedUrl,
    ImaKnowledgePage,
    parse_imported_urls,
    parse_knowledge_bases,
    parse_knowledge_page,
)
from .notes import ImaNotesClient
from .transport import API_BASE_URL, DEFAULT_TIMEOUT, ImaTransport

# IMA's documented page bounds for every ``limit``-taking knowledge-base call.
MAX_PAGE_LIMIT = 50

# ``get_knowledge_base`` takes ids in batches, capped by IMA at 20.
MAX_DETAIL_IDS = 20

# ``import_urls`` accepts 1-10 URLs per call.
MAX_IMPORT_URLS = 10

# ``search_knowledge`` is cursor-paginated. Retrieval feeds an LLM prompt, so a
# couple of pages is plenty — this bounds the calls a single search can make.
_MAX_SEARCH_PAGES = 3

# Media type IMA assigns to a note linked into a knowledge base. Its text comes
# from the notes module rather than a file download.
_NOTE_MEDIA_TYPE = 11


class ImaClient:
    """Stateless wrapper over the IMA knowledge-base OpenAPI."""

    def __init__(
        self,
        config: ImaConfig,
        *,
        timeout: float = DEFAULT_TIMEOUT,
        transport: Optional[httpx.AsyncBaseTransport] = None,
    ) -> None:
        self._config = config
        self._timeout = timeout
        self._transport = transport
        self._wire = ImaTransport(config, timeout=timeout, transport=transport)
        self._notes = ImaNotesClient(config, timeout=timeout, transport=transport)

    @property
    def notes(self) -> ImaNotesClient:
        """The notes-module client sharing this client's credentials."""
        return self._notes

    @property
    def knowledge_base_id(self) -> str:
        return self._config.knowledge_base_id

    # ----- retrieval ------------------------------------------------------

    async def search_knowledge(self, query: str, *, limit: int) -> ImaKnowledgePage:
        """Return up to *limit* matching documents from the bound knowledge base.

        Pages are followed until the result is full, IMA reports the end of the
        list, or the page budget runs out. Matched *folders* are kept separate
        from matched documents (IMA returns both) so retrieval never treats a
        folder as a source.
        """
        documents = []
        folders = []
        cursor = ""
        is_end = False
        for _ in range(_MAX_SEARCH_PAGES):
            page = parse_knowledge_page(
                await self._wire.post(
                    "search_knowledge",
                    {
                        "query": query,
                        "cursor": cursor,
                        "knowledge_base_id": self._config.knowledge_base_id,
                    },
                )
            )
            documents.extend(page.documents)
            folders.extend(page.folders)
            cursor = page.next_cursor
            is_end = page.is_end
            if len(documents) >= limit or page.is_end or not cursor:
                break
        return ImaKnowledgePage(
            documents=tuple(documents[:limit]),
            folders=tuple(folders),
            next_cursor=cursor,
            is_end=is_end,
        )

    async def get_knowledge_list(
        self,
        *,
        folder_id: str = "",
        cursor: str = "",
        limit: int = MAX_PAGE_LIMIT,
    ) -> ImaKnowledgePage:
        """Return one page of the bound knowledge base's contents.

        Omitting *folder_id* lists the library root; passing one descends into
        that folder. The response carries documents, subfolders and a breadcrumb.
        """
        return parse_knowledge_page(
            await self._wire.post("get_knowledge_list", self._list_body(folder_id, cursor, limit))
        )

    def get_knowledge_list_sync(
        self,
        *,
        folder_id: str = "",
        cursor: str = "",
        limit: int = MAX_PAGE_LIMIT,
    ) -> ImaKnowledgePage:
        """Blocking :meth:`get_knowledge_list`, for the synchronous manifest layer."""
        return parse_knowledge_page(
            self._wire.post_sync("get_knowledge_list", self._list_body(folder_id, cursor, limit))
        )

    def _list_body(self, folder_id: str, cursor: str, limit: int) -> dict[str, Any]:
        body: dict[str, Any] = {
            "knowledge_base_id": self._config.knowledge_base_id,
            "cursor": str(cursor or ""),
            "limit": page_limit(limit),
        }
        folder = str(folder_id or "").strip()
        # The root folder id equals the knowledge base id; sending it is
        # equivalent to omitting the field, so it is dropped for clarity.
        if folder and folder != self._config.knowledge_base_id:
            body["folder_id"] = folder
        return body

    async def get_media_info(self, media_id: str) -> dict[str, Any]:
        """Return one item's metadata (media type, note link, download URL)."""
        normalized = str(media_id or "").strip()
        if not normalized:
            return {}
        return await self._wire.post("get_media_info", {"media_id": normalized})

    async def get_media_content(self, media_id: str) -> ImaMediaContent | None:
        """Fetch full content for one knowledge item.

        IMA notes are returned as plain text by the notes module. File media is
        streamed from the short-lived COS URL with a hard byte limit. Missing or
        inaccessible media returns ``None`` so a caller can degrade to the item's
        title instead of failing outright.
        """
        info = await self.get_media_info(media_id)
        if not info:
            return None

        note_id = _linked_note_id(info)
        if note_id:
            content = await self._notes.get_note_content(note_id)
            return ImaMediaContent(text=content) if content else None

        url_info = info.get("url_info")
        if not isinstance(url_info, dict):
            return None
        url = str(url_info.get("url") or "").strip()
        if not url:
            return None
        return await media_ops.download_media(
            url,
            headers=media_ops.media_headers(url_info.get("headers")),
            timeout=self._timeout,
            transport=self._transport,
        )

    # ----- writing --------------------------------------------------------

    async def import_urls(self, urls: list[str], *, folder_id: str = "") -> list[ImaImportedUrl]:
        """Add up to :data:`MAX_IMPORT_URLS` web pages to the bound library.

        IMA reports a per-URL verdict rather than failing the batch, so partial
        success is normal and is returned as-is for the caller to report.
        """
        cleaned: list[str] = []
        for raw in urls:
            url = str(raw or "").strip()
            if url and url not in cleaned:
                cleaned.append(url)
        if not cleaned:
            raise ValueError("At least one URL is required.")
        if len(cleaned) > MAX_IMPORT_URLS:
            raise ValueError(f"IMA accepts at most {MAX_IMPORT_URLS} URLs per call.")

        # ``folder_id`` is required here, and the root folder's id is the
        # knowledge base id itself.
        target = str(folder_id or "").strip() or self._config.knowledge_base_id
        data = await self._wire.post(
            "import_urls",
            {
                "urls": cleaned,
                "knowledge_base_id": self._config.knowledge_base_id,
                "folder_id": target,
            },
        )
        results = parse_imported_urls(data)
        if results:
            return results
        # Some responses acknowledge the batch without echoing per-URL rows.
        return [ImaImportedUrl(url=url, ok=True) for url in cleaned]

    # ----- probing --------------------------------------------------------

    async def search_knowledge_bases(
        self,
        query: str = "",
        *,
        cursor: str = "",
        limit: int = MAX_DETAIL_IDS,
    ) -> dict[str, Any]:
        """Return one page of knowledge bases available to these credentials.

        A single batch details request enriches descriptions when possible; that
        optional request never prevents a usable name list from being returned.
        Since IMA caps a details batch at :data:`MAX_DETAIL_IDS` while a listing
        page can hold more, libraries past that point simply come back without a
        description — every one is still listed and selectable.
        The shape is the one the connect flow's API contract expects.
        """
        bases, cursor_state = parse_knowledge_bases(
            await self._wire.post(
                "search_knowledge_base",
                {
                    "query": str(query or "").strip(),
                    "cursor": str(cursor or "").strip(),
                    "limit": page_limit(limit),
                },
            )
        )

        details: dict[str, dict[str, Any]] = {}
        if bases:
            try:
                details = await self.get_knowledge_bases(
                    [base.id for base in bases[:MAX_DETAIL_IDS]]
                )
            except Exception:
                # Names from search_knowledge_base are sufficient for selection;
                # description lookup is intentionally best-effort.
                details = {}

        knowledge_bases = []
        for base in bases:
            raw_description = details.get(base.id, {}).get("description")
            description = str(raw_description).strip() if raw_description is not None else ""
            knowledge_bases.append(
                {
                    "id": base.id,
                    "name": base.name,
                    "description": description or None,
                }
            )
        return {
            "knowledge_bases": knowledge_bases,
            "next_cursor": cursor_state.next_cursor,
            "is_end": cursor_state.is_end,
        }

    async def get_knowledge_bases(self, ids: list[str]) -> dict[str, dict[str, Any]]:
        """Return details for at most :data:`MAX_DETAIL_IDS` knowledge base ids."""
        normalized: list[str] = []
        for item in ids:
            kb_id = str(item or "").strip()
            if kb_id and kb_id not in normalized:
                normalized.append(kb_id)
        if not normalized:
            return {}
        if len(normalized) > MAX_DETAIL_IDS:
            raise ValueError(
                f"IMA accepts at most {MAX_DETAIL_IDS} knowledge base IDs per request."
            )

        data = await self._wire.post("get_knowledge_base", {"ids": normalized})
        infos = data.get("infos")
        if not isinstance(infos, dict):
            return {}
        return {str(kb_id): info for kb_id, info in infos.items() if isinstance(info, dict)}

    async def get_knowledge_base(self) -> dict[str, Any]:
        """Return the bound knowledge base's info, or ``{}`` when unknown.

        Doubles as the credential check: bad credentials raise
        :class:`ImaAuthError`, while a well-formed but unknown id simply yields
        no entry for it.
        """
        kb_id = self._config.knowledge_base_id
        return (await self.get_knowledge_bases([kb_id])).get(kb_id, {})


def page_limit(limit: Any, *, maximum: int = MAX_PAGE_LIMIT) -> int:
    """Clamp a caller's page size into IMA's documented ``1..maximum`` range."""
    try:
        value = int(limit)
    except (TypeError, ValueError):
        return maximum
    return max(1, min(value, maximum))


def _linked_note_id(info: dict[str, Any]) -> str:
    """The note id behind a note-type knowledge item, if this item is one."""
    note_info = info.get("notebook_ext_info")
    if info.get("media_type") != _NOTE_MEDIA_TYPE or not isinstance(note_info, dict):
        return ""
    return str(note_info.get("notebook_id") or note_info.get("doc_id") or "").strip()


__all__ = [
    "API_BASE_URL",
    "MAX_DETAIL_IDS",
    "MAX_IMPORT_URLS",
    "MAX_MEDIA_BYTES",
    "MAX_PAGE_LIMIT",
    "ImaAPIError",
    "ImaAuthError",
    "ImaClient",
    "ImaMediaContent",
    "ImaNotesClient",
    "ImaRateLimitError",
    "page_limit",
]
