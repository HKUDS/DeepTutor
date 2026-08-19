"""Tests for the IMA loop capability: binding, additive mounting, tools.

Two design decisions are pinned here because getting either wrong is silent:

* **The capability is additive, not exclusive.** An IMA library is searchable over
  HTTP, so ``rag`` must keep serving it and chat's own tools must survive. If this
  ever became a ``KnowledgeCapability``, attaching an IMA library would quietly
  strip web search, memory and every other built-in from the turn.
* **Credentials never travel through tool kwargs.** The capability injects only
  the turn's library bindings (name + library id); each tool loads the credential
  pair itself, re-checking the user's access, so a trace or log of tool arguments
  cannot leak a key and a model cannot name a library that was not attached.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest

from deeptutor.agents._shared.tool_composition import ToolMountFlags, compose_enabled_tools
from deeptutor.capabilities import any_exclusive_capability_active
from deeptutor.capabilities.ima import IMA_TOOL_NAMES, ImaCapability
from deeptutor.capabilities.ima import binding as ima_binding
from deeptutor.capabilities.ima import tools as ima_tools
from deeptutor.capabilities.ima.binding import ImaBinding, select_binding
from deeptutor.capabilities.ima.tools import (
    BINDINGS_KWARG,
    ImaAddUrlTool,
    ImaListTool,
    ImaNoteSearchTool,
    ImaReadTool,
    ImaWriteNoteTool,
)
from deeptutor.core.context import UnifiedContext
from deeptutor.runtime.registry.tool_registry import get_tool_registry
from deeptutor.services.rag.pipelines.ima.config import ImaNotConfiguredError
from deeptutor.services.rag.pipelines.ima.envelope import ImaAuthError
from deeptutor.services.rag.pipelines.ima.media import ImaMediaContent
from deeptutor.services.rag.pipelines.ima.models import (
    ImaDocument,
    ImaFolder,
    ImaImportedUrl,
    ImaKnowledgePage,
    ImaNote,
)

LIBRARY = ImaBinding(kb_ref="ima知识库", name="ima知识库", knowledge_base_id="kb-1")
OTHER = ImaBinding(kb_ref="Research", name="Research", knowledge_base_id="kb-2")


def _context(kbs: list[str]) -> UnifiedContext:
    return UnifiedContext(user_message="q", knowledge_bases=kbs)


def _metadata(kb_type: str, name: str = "ima知识库") -> dict[str, Any]:
    return {"name": name, "type": kb_type, "knowledge_base_id": "kb-1"}


class _ClientStub:
    def __init__(self, **behaviour: Any) -> None:
        self._behaviour = behaviour
        self.calls: list[tuple[str, dict]] = []
        self.notes = _NotesStub(self)

    async def get_knowledge_list(self, **kwargs):
        self.calls.append(("get_knowledge_list", kwargs))
        return self._result("page")

    async def get_media_content(self, media_id: str):
        self.calls.append(("get_media_content", {"media_id": media_id}))
        return self._result("media")

    async def import_urls(self, urls, *, folder_id=""):
        self.calls.append(("import_urls", {"urls": urls, "folder_id": folder_id}))
        return self._result("imported")

    def _result(self, key: str):
        value = self._behaviour.get(key)
        if isinstance(value, Exception):
            raise value
        return value


class _NotesStub:
    def __init__(self, owner: _ClientStub) -> None:
        self._owner = owner

    async def search_notes(self, query="", **kwargs):
        self._owner.calls.append(("search_notes", {"query": query, **kwargs}))
        return self._owner._behaviour.get("notes", ([], True))

    async def create_note(self, content, *, folder_id=""):
        self._owner.calls.append(("create_note", {"content": content, "folder_id": folder_id}))
        return self._owner._behaviour.get("created", "n1")

    async def append_note(self, note_id, content):
        self._owner.calls.append(("append_note", {"note_id": note_id, "content": content}))
        return self._owner._behaviour.get("appended", note_id)


def _run(tool, **kwargs):
    return asyncio.run(tool.execute(**kwargs))


def _payload(result):
    return json.loads(result.content)


@pytest.fixture
def stub_client(monkeypatch: pytest.MonkeyPatch):
    """Install a client stub, and record how it was resolved."""
    created: dict[str, Any] = {}

    def install(**behaviour):
        client = _ClientStub(**behaviour)

        def resolve(kb_ref: str, *, for_write: bool = False):
            created["kb_ref"] = kb_ref
            created["for_write"] = for_write
            return client

        monkeypatch.setattr(ima_tools, "resolve_client", resolve)
        return client

    install.created = created  # type: ignore[attr-defined]
    return install


# ---------------------------------------------------------------------------
# binding
# ---------------------------------------------------------------------------


class TestBinding:
    def test_only_ima_knowledge_bases_bind(self, monkeypatch: pytest.MonkeyPatch) -> None:
        metadata = {"ima知识库": _metadata("ima"), "Papers": {"name": "Papers"}}
        monkeypatch.setattr(ima_binding, "resolve_kb_metadata", metadata.get, raising=False)
        monkeypatch.setattr(
            "deeptutor.multi_user.knowledge_access.resolve_kb_metadata",
            metadata.get,
            raising=False,
        )

        bindings = ima_binding.ima_bindings(_context(["ima知识库", "Papers"]))

        assert [binding.name for binding in bindings] == ["ima知识库"]

    def test_resolution_is_cached_on_the_turn(self, monkeypatch: pytest.MonkeyPatch) -> None:
        calls: list[str] = []

        def resolve(ref: str):
            calls.append(ref)
            return _metadata("ima")

        monkeypatch.setattr(
            "deeptutor.multi_user.knowledge_access.resolve_kb_metadata", resolve, raising=False
        )
        context = _context(["ima知识库"])

        ima_binding.ima_bindings(context)
        ima_binding.ima_bindings(context)

        assert calls == ["ima知识库"]

    def test_a_single_library_needs_no_kb_name(self) -> None:
        assert select_binding((LIBRARY,)) is LIBRARY
        assert select_binding((LIBRARY,), "typo") is LIBRARY

    def test_several_libraries_require_an_unambiguous_name(self) -> None:
        assert select_binding((LIBRARY, OTHER)) is None
        assert select_binding((LIBRARY, OTHER), "Research") is OTHER
        assert select_binding((LIBRARY, OTHER), "kb-1") is LIBRARY
        assert select_binding((LIBRARY, OTHER), "nope") is None

    def test_no_libraries_binds_to_nothing(self) -> None:
        assert select_binding(()) is None


# ---------------------------------------------------------------------------
# capability wiring
# ---------------------------------------------------------------------------


class TestCapability:
    def test_active_only_when_an_ima_library_is_attached(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            "deeptutor.multi_user.knowledge_access.resolve_kb_metadata",
            lambda ref: _metadata("ima") if ref == "ima知识库" else {"name": ref},
            raising=False,
        )
        capability = ImaCapability()

        assert capability.is_active(_context(["ima知识库"])) is True
        assert capability.is_active(_context(["Papers"])) is False
        assert capability.is_active(_context([])) is False

    def test_the_capability_is_additive_not_exclusive(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """rag stays mounted, chat's built-ins survive, IMA tools are added."""
        monkeypatch.setattr(
            "deeptutor.multi_user.knowledge_access.resolve_kb_metadata",
            lambda _ref: _metadata("ima"),
            raising=False,
        )
        context = _context(["ima知识库"])

        assert any_exclusive_capability_active(context) is False

        composed = compose_enabled_tools(
            registry=get_tool_registry(),
            requested_tools=["web_search"],
            optional_whitelist=["web_search"],
            mount_flags=ToolMountFlags(has_kb=True),
            capability_owned=IMA_TOOL_NAMES,
            exclusive=False,
        )

        assert "rag" in composed
        assert "kb_files" in composed
        assert "web_search" in composed
        assert set(IMA_TOOL_NAMES).issubset(composed)

    def test_system_block_names_the_attached_libraries(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            "deeptutor.multi_user.knowledge_access.resolve_kb_metadata",
            lambda _ref: _metadata("ima"),
            raising=False,
        )

        block = ImaCapability().system_block(_context(["ima知识库"]), language="zh", prompts={})

        assert block is not None
        assert "ima知识库" in block.content
        assert "{kb_names}" not in block.content

    def test_no_system_block_without_a_library(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            "deeptutor.multi_user.knowledge_access.resolve_kb_metadata",
            lambda _ref: None,
            raising=False,
        )

        assert ImaCapability().system_block(_context(["x"]), language="en", prompts={}) is None

    def test_bindings_are_injected_and_carry_no_credentials(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            "deeptutor.multi_user.knowledge_access.resolve_kb_metadata",
            lambda _ref: {
                **_metadata("ima"),
                # Even if a credential leaked into KB metadata, it must not be
                # forwarded into tool kwargs.
                "api_key": "secret",
                "client_id": "secret",
            },
            raising=False,
        )
        context = _context(["ima知识库"])

        kwargs = ImaCapability().augment_kwargs("ima_list", {"folder_id": "f1"}, context)

        assert [binding.name for binding in kwargs[BINDINGS_KWARG]] == ["ima知识库"]
        assert "secret" not in json.dumps(
            [
                binding.__dict__ if hasattr(binding, "__dict__") else str(binding)
                for binding in kwargs[BINDINGS_KWARG]
            ],
            default=str,
        )

    def test_a_model_supplied_bindings_value_is_overwritten(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            "deeptutor.multi_user.knowledge_access.resolve_kb_metadata",
            lambda _ref: _metadata("ima"),
            raising=False,
        )

        kwargs = ImaCapability().augment_kwargs(
            "ima_list", {BINDINGS_KWARG: [OTHER]}, _context(["ima知识库"])
        )

        assert [binding.knowledge_base_id for binding in kwargs[BINDINGS_KWARG]] == ["kb-1"]

    def test_other_tools_kwargs_are_untouched(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr(
            "deeptutor.multi_user.knowledge_access.resolve_kb_metadata",
            lambda _ref: _metadata("ima"),
            raising=False,
        )

        kwargs = ImaCapability().augment_kwargs("rag", {"query": "q"}, _context(["ima知识库"]))

        assert kwargs == {"query": "q"}

    def test_every_owned_tool_is_registered(self) -> None:
        registry = get_tool_registry()
        for name in IMA_TOOL_NAMES:
            assert registry.get(name) is not None


# ---------------------------------------------------------------------------
# tools
# ---------------------------------------------------------------------------


class TestTools:
    def test_without_a_binding_the_tool_says_so(self) -> None:
        result = _run(ImaListTool(), **{BINDINGS_KWARG: []})

        assert result.success is False
        assert "No Tencent IMA knowledge base" in result.content

    def test_ambiguous_libraries_ask_for_a_name(self) -> None:
        result = _run(ImaListTool(), **{BINDINGS_KWARG: [LIBRARY, OTHER]})

        assert result.success is False
        assert "kb_name" in result.content
        assert "Research" in result.content

    def test_list_returns_documents_folders_and_the_breadcrumb(self, stub_client) -> None:
        stub_client(
            page=ImaKnowledgePage(
                documents=(ImaDocument(media_id="m1", title="Alpha"),),
                folders=(ImaFolder(folder_id="f1", name="Papers", file_number=2),),
                path=("Library",),
                next_cursor="c2",
            )
        )

        result = _run(ImaListTool(), folder_id="f1", limit=10, **{BINDINGS_KWARG: [LIBRARY]})
        payload = _payload(result)

        assert payload["documents"] == [{"media_id": "m1", "title": "Alpha"}]
        assert payload["folders"][0]["folder_id"] == "f1"
        assert payload["path"] == ["Library"]
        assert payload["next_cursor"] == "c2"

    def test_list_is_a_read_and_targets_the_selected_library(self, stub_client) -> None:
        client = stub_client(page=ImaKnowledgePage())

        _run(ImaListTool(), **{BINDINGS_KWARG: [LIBRARY]})

        assert stub_client.created == {"kb_ref": "ima知识库", "for_write": False}
        assert client.calls[0][0] == "get_knowledge_list"

    def test_read_returns_extracted_text(self, stub_client) -> None:
        stub_client(media=ImaMediaContent(text="the whole document"))

        payload = _payload(_run(ImaReadTool(), media_id="m1", **{BINDINGS_KWARG: [LIBRARY]}))

        assert payload["content"] == "the whole document"
        assert payload["truncated"] is False

    def test_read_requires_a_media_id(self, stub_client) -> None:
        stub_client(media=None)

        result = _run(ImaReadTool(), **{BINDINGS_KWARG: [LIBRARY]})

        assert result.success is False
        assert "media_id is required" in result.content

    def test_read_reports_an_item_with_no_text(self, stub_client) -> None:
        stub_client(media=None)

        result = _run(ImaReadTool(), media_id="m1", **{BINDINGS_KWARG: [LIBRARY]})

        assert result.success is False
        assert "no readable text" in result.content

    def test_note_search_reports_timestamps(self, stub_client) -> None:
        stub_client(
            notes=(
                [ImaNote(note_id="n1", title="Plasma", summary="s", updated_at=222)],
                True,
            )
        )

        payload = _payload(_run(ImaNoteSearchTool(), **{BINDINGS_KWARG: [LIBRARY]}))

        assert payload["notes"][0]["updated_at"] == 222
        assert payload["is_end"] is True

    def test_note_search_maps_the_sort_name(self, stub_client) -> None:
        client = stub_client(notes=([], True))

        _run(ImaNoteSearchTool(), sort="created", **{BINDINGS_KWARG: [LIBRARY]})

        assert client.calls[0][1]["sort_type"] == 1

    def test_add_url_requires_write_access(self, stub_client) -> None:
        stub_client(imported=[ImaImportedUrl(url="https://a.test", ok=True, media_id="m1")])

        _run(ImaAddUrlTool(), urls=["https://a.test"], **{BINDINGS_KWARG: [LIBRARY]})

        assert stub_client.created["for_write"] is True

    def test_add_url_reports_partial_failure(self, stub_client) -> None:
        stub_client(
            imported=[
                ImaImportedUrl(url="https://a.test", ok=True, media_id="m1"),
                ImaImportedUrl(url="https://b.test", ok=False, code=110001),
            ]
        )

        result = _run(
            ImaAddUrlTool(),
            urls=["https://a.test", "https://b.test"],
            **{BINDINGS_KWARG: [LIBRARY]},
        )
        payload = _payload(result)

        assert result.success is True
        assert payload["added"] == [{"url": "https://a.test", "media_id": "m1"}]
        assert payload["failed"] == [{"url": "https://b.test", "code": 110001}]

    @pytest.mark.parametrize(
        "url",
        [
            "https://www.bilibili.com/video/BV1",
            "https://www.youtube.com/watch?v=x",
            "file:///Users/me/page.html",
        ],
    )
    def test_add_url_rejects_what_ima_cannot_accept(self, stub_client, url: str) -> None:
        client = stub_client(imported=[])

        result = _run(ImaAddUrlTool(), urls=[url], **{BINDINGS_KWARG: [LIBRARY]})

        assert result.success is False
        assert "desktop app" in result.content
        assert client.calls == []

    def test_write_note_creates_by_default(self, stub_client) -> None:
        client = stub_client(created="n9")

        payload = _payload(
            _run(ImaWriteNoteTool(), content="# T\nbody", **{BINDINGS_KWARG: [LIBRARY]})
        )

        assert payload == {"note_id": "n9", "action": "created"}
        assert client.calls[0][0] == "create_note"
        assert stub_client.created["for_write"] is True

    def test_write_note_appends_to_a_named_note(self, stub_client) -> None:
        client = stub_client(appended="n1")

        payload = _payload(
            _run(
                ImaWriteNoteTool(),
                content="more",
                note_id="n1",
                **{BINDINGS_KWARG: [LIBRARY]},
            )
        )

        assert payload == {"note_id": "n1", "action": "appended"}
        assert client.calls[0][0] == "append_note"

    def test_missing_credentials_are_explained(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def resolve(_ref: str, *, for_write: bool = False):
            raise ImaNotConfiguredError("missing API key")

        monkeypatch.setattr(ima_tools, "resolve_client", resolve)

        result = _run(ImaListTool(), **{BINDINGS_KWARG: [LIBRARY]})

        assert result.success is False
        assert "missing API key" in result.content

    def test_inaccessible_knowledge_base_is_reported(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def resolve(_ref: str, *, for_write: bool = False):
            raise RuntimeError("403")

        monkeypatch.setattr(ima_tools, "resolve_client", resolve)

        result = _run(ImaWriteNoteTool(), content="x", **{BINDINGS_KWARG: [LIBRARY]})

        assert result.success is False
        assert "write access" in result.content

    def test_upstream_auth_failure_is_reported_cleanly(self, stub_client) -> None:
        stub_client(page=ImaAuthError("rejected"))

        result = _run(ImaListTool(), **{BINDINGS_KWARG: [LIBRARY]})

        assert result.success is False
        assert "rejected the credentials" in result.content
