"""Tests for the IMA calls beyond retrieval: envelope, browse, import, notes.

Retrieval itself is covered by ``test_ima_pipeline``. This module pins the parts
that make an IMA library *usable* rather than merely searchable:

* the status envelope in both documented spellings — the failure this guards
  against is silent and total (reading only one spelling turns every successful
  call into an error), so it is asserted directly rather than assumed;
* ``get_knowledge_list``: the browse call that answers "what is in this library",
  including the folder/document split and the root-folder convention;
* ``import_urls`` and the notes module: the additive writes;
* ``page_limit``: IMA's documented 1..50 bound.

Everything runs against an injected ``httpx.MockTransport`` — no network.
"""

from __future__ import annotations

import asyncio
import json

import httpx
import pytest

from deeptutor.services.rag.pipelines.ima.client import (
    API_BASE_URL,
    MAX_IMPORT_URLS,
    MAX_PAGE_LIMIT,
    ImaAPIError,
    ImaAuthError,
    ImaClient,
    ImaRateLimitError,
    page_limit,
)
from deeptutor.services.rag.pipelines.ima.config import ImaConfig
from deeptutor.services.rag.pipelines.ima.envelope import unwrap
from deeptutor.services.rag.pipelines.ima.models import parse_knowledge_page, parse_note
from deeptutor.services.rag.pipelines.ima.notes import SORT_BY_CREATED, SORT_BY_UPDATED

CONFIG = ImaConfig(client_id="cid", api_key="key", knowledge_base_id="kb-1")


def _client(handler) -> ImaClient:
    return ImaClient(CONFIG, transport=httpx.MockTransport(handler))


def _responder(data: dict, *, style: str = "code"):
    """A handler returning ``data`` in one of the two envelope spellings."""

    def handler(request: httpx.Request) -> httpx.Response:
        if style == "retcode":
            return httpx.Response(200, json={"retcode": 0, "errmsg": "成功", "data": data})
        return httpx.Response(200, json={"code": 0, "msg": "ok", "data": data})

    return handler


# ---------------------------------------------------------------------------
# envelope
# ---------------------------------------------------------------------------


class TestEnvelope:
    @pytest.mark.parametrize(
        "payload",
        [
            {"code": 0, "msg": "ok", "data": {"value": 1}},
            {"retcode": 0, "errmsg": "成功", "data": {"value": 1}},
            {"retcode": "0", "data": {"value": 1}},
        ],
    )
    def test_success_is_unwrapped_in_either_spelling(self, payload: dict) -> None:
        assert unwrap(payload, status_code=200) == {"value": 1}

    @pytest.mark.parametrize("field", ["code", "retcode"])
    def test_credential_rejection_maps_to_auth_error_in_either_spelling(self, field: str) -> None:
        with pytest.raises(ImaAuthError):
            unwrap({field: 20004, "msg": "bad key"}, status_code=200)

    @pytest.mark.parametrize("field", ["code", "retcode"])
    def test_rate_limit_maps_to_rate_limit_error_in_either_spelling(self, field: str) -> None:
        with pytest.raises(ImaRateLimitError):
            unwrap({field: 110021}, status_code=200)

    def test_retryable_upstream_failure_says_so(self) -> None:
        with pytest.raises(ImaAPIError, match="temporarily unavailable"):
            unwrap({"retcode": 110010}, status_code=200)

    def test_business_error_surfaces_ima_message(self) -> None:
        with pytest.raises(ImaAPIError, match="参数非法"):
            unwrap({"retcode": 110001, "errmsg": "参数非法"}, status_code=200)

    def test_payload_without_any_status_field_is_rejected(self) -> None:
        with pytest.raises(ImaAPIError, match="unrecognized"):
            unwrap({"data": {"value": 1}}, status_code=200)

    def test_non_dict_payload_is_rejected(self) -> None:
        with pytest.raises(ImaAPIError, match="unexpected payload"):
            unwrap(["not", "an", "envelope"], status_code=200)

    def test_client_accepts_a_retcode_response_end_to_end(self) -> None:
        """The guard that matters: a retcode-only deployment must still work."""
        page = asyncio.run(
            _client(
                _responder(
                    {"knowledge_list": [{"media_id": "m1", "title": "Alpha"}], "is_end": True},
                    style="retcode",
                )
            ).get_knowledge_list()
        )

        assert [document.title for document in page.documents] == ["Alpha"]


# ---------------------------------------------------------------------------
# browse
# ---------------------------------------------------------------------------


class TestKnowledgeList:
    def test_root_listing_posts_the_documented_body(self) -> None:
        seen: dict = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["url"] = str(request.url)
            seen["body"] = json.loads(request.content)
            return httpx.Response(200, json={"code": 0, "data": {"is_end": True}})

        asyncio.run(_client(handler).get_knowledge_list())

        assert seen["url"] == f"{API_BASE_URL}/openapi/wiki/v1/get_knowledge_list"
        assert seen["body"] == {"knowledge_base_id": "kb-1", "cursor": "", "limit": MAX_PAGE_LIMIT}

    def test_folder_id_equal_to_the_library_id_is_dropped(self) -> None:
        """IMA's root folder id *is* the knowledge base id — sending it is noise."""
        seen: dict = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["body"] = json.loads(request.content)
            return httpx.Response(200, json={"code": 0, "data": {"is_end": True}})

        asyncio.run(_client(handler).get_knowledge_list(folder_id="kb-1"))

        assert "folder_id" not in seen["body"]

    def test_subfolder_listing_sends_the_folder(self) -> None:
        seen: dict = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["body"] = json.loads(request.content)
            return httpx.Response(200, json={"code": 0, "data": {"is_end": True}})

        asyncio.run(_client(handler).get_knowledge_list(folder_id="f-9", cursor="c1", limit=10))

        assert seen["body"] == {
            "knowledge_base_id": "kb-1",
            "cursor": "c1",
            "limit": 10,
            "folder_id": "f-9",
        }

    def test_documents_folders_and_breadcrumb_are_separated(self) -> None:
        page = parse_knowledge_page(
            {
                "knowledge_list": [
                    {"media_id": "m1", "title": "Alpha"},
                    {"folder_id": "f1", "name": "Papers", "file_number": 2, "folder_number": 1},
                ],
                "current_path": [{"folder_id": "root", "name": "Library"}],
                "next_cursor": "c2",
                "is_end": False,
            }
        )

        assert [document.title for document in page.documents] == ["Alpha"]
        assert [folder.name for folder in page.folders] == ["Papers"]
        assert page.folders[0].file_number == 2
        assert page.path == ("Library",)
        assert (page.next_cursor, page.is_end) == ("c2", False)

    def test_entries_that_are_neither_are_discarded(self) -> None:
        page = parse_knowledge_page({"knowledge_list": [{"highlight_content": "orphan"}, {}]})

        assert page.documents == ()
        assert page.folders == ()

    def test_duplicate_ids_within_a_page_are_collapsed(self) -> None:
        page = parse_knowledge_page(
            {
                "knowledge_list": [
                    {"media_id": "m1", "title": "Alpha"},
                    {"media_id": "m1", "title": "Alpha again"},
                ]
            }
        )

        assert len(page.documents) == 1

    def test_blocking_flavour_shares_the_same_wire(self) -> None:
        """The manifest layer is synchronous; its call must be identical."""
        seen: dict = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["headers"] = dict(request.headers)
            return httpx.Response(
                200,
                json={"code": 0, "data": {"knowledge_list": [{"media_id": "m", "title": "T"}]}},
            )

        page = _client(handler).get_knowledge_list_sync()

        assert [document.title for document in page.documents] == ["T"]
        assert seen["headers"]["ima-openapi-clientid"] == "cid"


class TestPageLimit:
    @pytest.mark.parametrize(
        ("requested", "expected"),
        [(0, 1), (1, 1), (50, 50), (51, 50), (None, 50), ("nonsense", 50)],
    )
    def test_limits_are_clamped_to_the_documented_range(self, requested, expected: int) -> None:
        assert page_limit(requested) == expected


# ---------------------------------------------------------------------------
# writes
# ---------------------------------------------------------------------------


class TestImportUrls:
    def test_urls_are_posted_with_the_root_folder_convention(self) -> None:
        seen: dict = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["body"] = json.loads(request.content)
            return httpx.Response(
                200,
                json={
                    "code": 0,
                    "data": {
                        "url_data_list": [
                            {"url": "https://a.test", "ret_code": 0, "media_id": "m1"},
                            {"url": "https://b.test", "ret_code": 110001},
                        ]
                    },
                },
            )

        results = asyncio.run(_client(handler).import_urls(["https://a.test", " https://b.test "]))

        # Root folder is addressed by the knowledge base id itself.
        assert seen["body"] == {
            "urls": ["https://a.test", "https://b.test"],
            "knowledge_base_id": "kb-1",
            "folder_id": "kb-1",
        }
        assert [(item.url, item.ok, item.media_id) for item in results] == [
            ("https://a.test", True, "m1"),
            ("https://b.test", False, ""),
        ]

    def test_a_batch_without_per_url_rows_is_reported_as_accepted(self) -> None:
        results = asyncio.run(_client(_responder({})).import_urls(["https://a.test"]))

        assert [(item.url, item.ok) for item in results] == [("https://a.test", True)]

    def test_duplicates_are_collapsed_and_the_batch_is_bounded(self) -> None:
        client = _client(_responder({}))

        results = asyncio.run(client.import_urls(["https://a.test", "https://a.test"]))
        assert len(results) == 1

        with pytest.raises(ValueError, match=f"at most {MAX_IMPORT_URLS}"):
            asyncio.run(client.import_urls([f"https://{i}.test" for i in range(11)]))

        with pytest.raises(ValueError, match="At least one URL"):
            asyncio.run(client.import_urls(["   "]))


class TestNotes:
    def test_search_defaults_to_recency_and_a_title_query(self) -> None:
        seen: dict = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["url"] = str(request.url)
            seen["body"] = json.loads(request.content)
            return httpx.Response(200, json={"retcode": 0, "data": {"docs": [], "is_end": True}})

        asyncio.run(_client(handler).notes.search_notes("plasma", limit=5))

        assert seen["url"] == f"{API_BASE_URL}/openapi/note/v1/search_note_book"
        assert seen["body"] == {
            "search_type": 0,
            "sort_type": SORT_BY_UPDATED,
            "query_info": {"title": "plasma"},
            "start": 0,
            "end": 5,
        }

    def test_content_search_and_sort_order_are_honoured(self) -> None:
        seen: dict = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["body"] = json.loads(request.content)
            return httpx.Response(200, json={"retcode": 0, "data": {"docs": []}})

        asyncio.run(
            _client(handler).notes.search_notes(
                "plasma", by_content=True, sort_type=SORT_BY_CREATED, limit=3
            )
        )

        assert seen["body"]["search_type"] == 1
        assert seen["body"]["sort_type"] == SORT_BY_CREATED
        assert seen["body"]["query_info"] == {"content": "plasma"}

    def test_search_flattens_the_nested_note_payload(self) -> None:
        def handler(request: httpx.Request) -> httpx.Response:
            return httpx.Response(
                200,
                json={
                    "retcode": 0,
                    "data": {
                        "docs": [
                            {
                                "doc": {
                                    "basic_info": {
                                        "docid": "n1",
                                        "title": "Plasma notes",
                                        "summary": "about plasma",
                                        "folder_name": "Physics",
                                        "create_time": 111,
                                        "modify_time": 222,
                                    }
                                }
                            },
                            {"doc": {"basic_info": {"docid": "n2", "title": "Gone", "status": 1}}},
                        ],
                        "is_end": True,
                    },
                },
            )

        notes, is_end = asyncio.run(_client(handler).notes.search_notes())

        assert [(note.note_id, note.title, note.updated_at) for note in notes] == [
            ("n1", "Plasma notes", 222)
        ]
        assert is_end is True

    def test_notebook_listing_starts_at_the_zero_cursor(self) -> None:
        seen: dict = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["body"] = json.loads(request.content)
            return httpx.Response(
                200,
                json={
                    "retcode": 0,
                    "data": {
                        "note_book_folders": [
                            {
                                "folder": {
                                    "basic_info": {
                                        "folder_id": "f1",
                                        "name": "Physics",
                                        "note_number": 4,
                                    }
                                }
                            }
                        ],
                        "next_cursor": "c2",
                    },
                },
            )

        notebooks, cursor = asyncio.run(_client(handler).notes.list_notebooks())

        assert seen["body"]["cursor"] == "0"
        assert [(book.folder_id, book.note_number) for book in notebooks] == [("f1", 4)]
        assert cursor.next_cursor == "c2"

    def test_create_note_sends_markdown_and_returns_the_id(self) -> None:
        seen: dict = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["url"] = str(request.url)
            seen["body"] = json.loads(request.content)
            return httpx.Response(200, json={"retcode": 0, "data": {"doc_id": "n9"}})

        note_id = asyncio.run(_client(handler).notes.create_note("# Title\nbody", folder_id="f1"))

        assert note_id == "n9"
        assert seen["url"].endswith("/openapi/note/v1/import_doc")
        assert seen["body"] == {
            "content_format": 1,
            "content": "# Title\nbody",
            "folder_id": "f1",
        }

    def test_append_note_requires_a_target_and_content(self) -> None:
        client = _client(_responder({"doc_id": "n1"}))

        assert asyncio.run(client.notes.append_note("n1", "more")) == "n1"
        with pytest.raises(ValueError, match="target note id"):
            asyncio.run(client.notes.append_note("  ", "more"))
        with pytest.raises(ValueError, match="Content to append"):
            asyncio.run(client.notes.append_note("n1", "   "))

    def test_note_parsing_accepts_a_bare_basic_info_dict(self) -> None:
        note = parse_note({"basic_info": {"doc_id": "n1", "title": "T"}})

        assert note is not None
        assert (note.note_id, note.title) == ("n1", "T")
