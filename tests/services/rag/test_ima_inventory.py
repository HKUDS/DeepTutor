"""Tests for the IMA document inventory, and the manifest that consumes it.

The behaviour under test is the one that made a connected IMA library feel broken:
asked "what are my latest 5 documents", the model was *told* by the system prompt
that the document list could not be read, so it declined. It can be read — IMA
exposes ``get_knowledge_list`` — and these tests pin both halves:

* :mod:`~deeptutor.services.rag.pipelines.ima.inventory` — folder traversal,
  request budget, and the cache that keeps a per-turn manifest from re-fetching;
* :mod:`deeptutor.knowledge.manifest` — an ``ima`` KB now enumerates for real,
  falls back to "not listable" only when the library cannot be reached, and marks
  a budget-truncated count as a lower bound rather than a total.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from deeptutor.knowledge.manifest import (
    UNAVAILABLE_REMOTE,
    build_manifest,
    render_manifest_note,
    render_manifest_report,
)
from deeptutor.services.rag.pipelines.ima import inventory as inventory_module
from deeptutor.services.rag.pipelines.ima.inventory import (
    MAX_REQUESTS,
    ImaInventory,
    clear_cache,
    read_inventory,
)
from deeptutor.services.rag.pipelines.ima.models import ImaDocument, ImaFolder, ImaKnowledgePage

ENTRY = {
    "type": "ima",
    "rag_provider": "ima",
    "client_id": "cid",
    "api_key": "key",
    "knowledge_base_id": "kb-1",
}


class _ListStub:
    """A blocking ``get_knowledge_list_sync`` over a scripted folder tree."""

    def __init__(self, tree: dict[str, list[list]], *, error: Exception | None = None) -> None:
        # tree: folder_id -> list of pages, each page a list of documents/folders
        self._tree = tree
        self._error = error
        self.calls: list[tuple[str, str]] = []

    def get_knowledge_list_sync(self, *, folder_id="", cursor="", limit=50) -> ImaKnowledgePage:
        if self._error is not None:
            raise self._error
        self.calls.append((folder_id, cursor))
        pages = self._tree.get(folder_id, [[]])
        index = int(cursor or 0)
        entries = pages[index] if index < len(pages) else []
        is_last = index >= len(pages) - 1
        return ImaKnowledgePage(
            documents=tuple(item for item in entries if isinstance(item, ImaDocument)),
            folders=tuple(item for item in entries if isinstance(item, ImaFolder)),
            next_cursor="" if is_last else str(index + 1),
            is_end=is_last,
        )


def _doc(title: str) -> ImaDocument:
    return ImaDocument(media_id=f"m-{title}", title=title)


def _folder(name: str) -> ImaFolder:
    return ImaFolder(folder_id=f"f-{name}", name=name)


@pytest.fixture(autouse=True)
def _clean_cache():
    clear_cache()
    yield
    clear_cache()


# ---------------------------------------------------------------------------
# traversal
# ---------------------------------------------------------------------------


class TestTraversal:
    def test_root_documents_are_listed(self) -> None:
        stub = _ListStub({"kb-1": [[_doc("a.pdf"), _doc("b.md")]]})

        result = read_inventory(ENTRY, client_factory=lambda _c: stub, use_cache=False)

        assert result == ImaInventory(documents=("a.pdf", "b.md"), complete=True)

    def test_folders_are_descended_and_prefixed_like_a_local_path(self) -> None:
        stub = _ListStub(
            {
                "kb-1": [[_doc("top.pdf"), _folder("Papers")]],
                "f-Papers": [[_doc("inner.pdf"), _folder("2026")]],
                "f-2026": [[_doc("recent.pdf")]],
            }
        )

        result = read_inventory(ENTRY, client_factory=lambda _c: stub, use_cache=False)

        assert result is not None
        assert result.documents == (
            "top.pdf",
            "Papers/inner.pdf",
            "Papers/2026/recent.pdf",
        )
        assert result.complete is True

    def test_pagination_within_a_folder_is_followed(self) -> None:
        stub = _ListStub({"kb-1": [[_doc("a")], [_doc("b")], [_doc("c")]]})

        result = read_inventory(ENTRY, client_factory=lambda _c: stub, use_cache=False)

        assert result is not None
        assert result.documents == ("a", "b", "c")
        assert [cursor for _folder_id, cursor in stub.calls] == ["", "1", "2"]

    def test_request_budget_marks_the_count_as_incomplete(self) -> None:
        # Every page reports more to come, so the budget is what stops it.
        stub = _ListStub({"kb-1": [[_doc(f"d{i}")] for i in range(MAX_REQUESTS + 5)]})

        result = read_inventory(ENTRY, client_factory=lambda _c: stub, use_cache=False)

        assert result is not None
        assert len(stub.calls) == MAX_REQUESTS
        assert result.complete is False

    def test_a_cycle_in_the_folder_graph_cannot_loop(self) -> None:
        stub = _ListStub(
            {
                "kb-1": [[_folder("A")]],
                "f-A": [[_folder("A"), _doc("inside")]],
            }
        )

        result = read_inventory(ENTRY, client_factory=lambda _c: stub, use_cache=False)

        assert result is not None
        assert result.documents == ("A/inside",)

    def test_unreachable_library_is_unknown_not_empty(self) -> None:
        stub = _ListStub({}, error=RuntimeError("offline"))

        assert read_inventory(ENTRY, client_factory=lambda _c: stub, use_cache=False) is None

    def test_missing_credentials_are_unknown(self) -> None:
        assert read_inventory({"type": "ima"}, client_factory=lambda _c: None) is None

    def test_the_production_path_drives_the_real_client(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Without a factory the reader builds a real client: exercise that seam.

        Everything from the credential headers through the status envelope to the
        blocking transport runs here — the one part of the chain the scripted stub
        above deliberately replaces.
        """
        import httpx

        from deeptutor.services.rag.pipelines.ima import client as client_module

        seen: dict = {}

        def handler(request: httpx.Request) -> httpx.Response:
            seen["path"] = request.url.path
            seen["clientid"] = request.headers.get("ima-openapi-clientid")
            return httpx.Response(
                200,
                json={
                    "retcode": 0,
                    "data": {
                        "knowledge_list": [{"media_id": "m1", "title": "最新收集.pdf"}],
                        "is_end": True,
                    },
                },
            )

        real_client = client_module.ImaClient

        def build(config, **kwargs):
            kwargs.pop("transport", None)
            return real_client(config, transport=httpx.MockTransport(handler), **kwargs)

        monkeypatch.setattr(client_module, "ImaClient", build)

        result = read_inventory(ENTRY, use_cache=False)

        assert result is not None
        assert result.documents == ("最新收集.pdf",)
        assert seen["path"] == "/openapi/wiki/v1/get_knowledge_list"
        assert seen["clientid"] == "cid"


class TestCache:
    def test_a_second_read_is_served_from_cache(self) -> None:
        stub = _ListStub({"kb-1": [[_doc("a")]]})

        first = read_inventory(ENTRY, client_factory=lambda _c: stub)
        second = read_inventory(ENTRY, client_factory=lambda _c: stub)

        assert first == second
        assert len(stub.calls) == 1

    def test_expiry_refetches(self, monkeypatch: pytest.MonkeyPatch) -> None:
        stub = _ListStub({"kb-1": [[_doc("a")]]})
        clock = {"now": 1_000.0}
        monkeypatch.setattr(inventory_module.time, "monotonic", lambda: clock["now"])

        read_inventory(ENTRY, client_factory=lambda _c: stub)
        clock["now"] += inventory_module.CACHE_TTL_SECONDS + 1
        read_inventory(ENTRY, client_factory=lambda _c: stub)

        assert len(stub.calls) == 2

    def test_a_failure_is_cached_briefly_too(self) -> None:
        """An unreachable library must not be retried on every turn's prompt."""
        stub = _ListStub({}, error=RuntimeError("offline"))

        assert read_inventory(ENTRY, client_factory=lambda _c: stub) is None
        assert read_inventory(ENTRY, client_factory=lambda _c: stub) is None

    def test_a_cached_failure_expires_sooner_than_a_success(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        clock = {"now": 1_000.0}
        monkeypatch.setattr(inventory_module.time, "monotonic", lambda: clock["now"])
        failing = _ListStub({}, error=RuntimeError("offline"))

        read_inventory(ENTRY, client_factory=lambda _c: failing)
        clock["now"] += inventory_module.FAILURE_TTL_SECONDS + 1
        working = _ListStub({"kb-1": [[_doc("a")]]})
        result = read_inventory(ENTRY, client_factory=lambda _c: working)

        assert result is not None
        assert result.documents == ("a",)

    def test_libraries_are_cached_separately(self) -> None:
        stub = _ListStub({"kb-1": [[_doc("a")]], "kb-2": [[_doc("b")]]})
        other = {**ENTRY, "knowledge_base_id": "kb-2"}

        read_inventory(ENTRY, client_factory=lambda _c: stub)
        read_inventory(other, client_factory=lambda _c: stub)

        assert len(stub.calls) == 2


# ---------------------------------------------------------------------------
# manifest integration
# ---------------------------------------------------------------------------


def _patch_reader(monkeypatch: pytest.MonkeyPatch, result) -> None:
    """Swap the manifest's IMA reader for a scripted one."""
    from deeptutor.knowledge import manifest as manifest_module

    monkeypatch.setitem(
        manifest_module._REMOTE_INVENTORY_READERS,
        "ima",
        lambda _entry: result,
    )


class TestManifestEnumeratesIma:
    def test_documents_are_reported_like_a_local_kb(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _patch_reader(monkeypatch, (["a.pdf", "Papers/b.md"], True))

        manifest = build_manifest(name="IMA", kb_dir=tmp_path / "IMA", entry=ENTRY)

        assert manifest.enumerable
        assert manifest.total == 2
        assert [document.name for document in manifest.documents] == ["a.pdf", "Papers/b.md"]
        assert manifest.total_is_lower_bound is False

    def test_the_report_omits_unknown_sizes(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _patch_reader(monkeypatch, (["a.pdf"], True))

        manifest = build_manifest(name="IMA", kb_dir=tmp_path / "IMA", entry=ENTRY)
        report = render_manifest_report(manifest, language="en")

        assert "1. a.pdf" in report
        assert "0 B" not in report

    def test_a_truncated_listing_is_reported_as_a_lower_bound(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _patch_reader(monkeypatch, ([f"d{i}.pdf" for i in range(400)], False))

        manifest = build_manifest(name="IMA", kb_dir=tmp_path / "IMA", entry=ENTRY, limit=2)

        assert manifest.total_is_lower_bound is True
        assert "400+" in render_manifest_report(manifest, language="en")
        assert "400+" in render_manifest_note([manifest], language="zh")

    def test_pattern_filtering_works_over_a_remote_listing(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _patch_reader(monkeypatch, (["a.pdf", "notes.md", "Papers/b.pdf"], True))

        manifest = build_manifest(name="IMA", kb_dir=tmp_path / "IMA", entry=ENTRY, pattern="*.pdf")

        assert manifest.total == 3
        assert manifest.matched == 2
        assert [document.name for document in manifest.documents] == ["a.pdf", "Papers/b.pdf"]

    def test_an_unreachable_library_falls_back_to_not_listable(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _patch_reader(monkeypatch, None)

        manifest = build_manifest(name="IMA", kb_dir=tmp_path / "IMA", entry=ENTRY)

        assert not manifest.enumerable
        assert manifest.unavailable == UNAVAILABLE_REMOTE
        assert "remote server" in render_manifest_report(manifest, language="en")

    def test_a_reader_that_raises_is_treated_as_unreachable(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from deeptutor.knowledge import manifest as manifest_module

        def boom(_entry):
            raise RuntimeError("offline")

        monkeypatch.setitem(manifest_module._REMOTE_INVENTORY_READERS, "ima", boom)

        manifest = build_manifest(name="IMA", kb_dir=tmp_path / "IMA", entry=ENTRY)

        assert manifest.unavailable == UNAVAILABLE_REMOTE

    def test_an_empty_library_is_reported_as_empty_not_unknown(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _patch_reader(monkeypatch, ([], True))

        manifest = build_manifest(name="IMA", kb_dir=tmp_path / "IMA", entry=ENTRY)

        assert manifest.enumerable
        assert manifest.total == 0
        assert "no documents" in render_manifest_report(manifest, language="en")
