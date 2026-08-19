"""Capability-level tests: activation, prompt, kwarg binding, locate pass, tools.

The store is isolated by pointing ``DEEPTUTOR_HOME`` at a temp dir and resetting
the path-service singleton, so the tools exercise their real resolution path
(``ReadingStore()`` with no arguments) rather than a hand-injected store.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from deeptutor.capabilities.explore_context import ExploreContextCapability
from deeptutor.capabilities.reading import (
    MATERIAL_ID_KEY,
    MATERIAL_KWARG,
    READING_TOOL_NAMES,
    VIEWPORT_KEY,
    ReadingCapability,
)
from deeptutor.capabilities.reading.tools import (
    MaterialOutlineTool,
    ReaderAnnotateTool,
    ReaderGotoTool,
    ReadMaterialTool,
    SearchMaterialTool,
)
from deeptutor.core.context import UnifiedContext
from deeptutor.core.stream_bus import StreamBus
from deeptutor.services.path_service import PathService

pymupdf = pytest.importorskip("pymupdf")


PAGES = [
    "Chapter one. Sequence models process tokens one at a time.",
    "Chapter two. Transformers use scaled dot-product attention over all tokens.",
    "Chapter three. Positional encoding injects order into the representation.",
]


@pytest.fixture
def reading_home(monkeypatch, tmp_path: Path):
    """A real per-user store rooted in a temp DEEPTUTOR_HOME."""
    monkeypatch.setenv("DEEPTUTOR_HOME", str(tmp_path))
    PathService.reset_instance()
    yield tmp_path
    PathService.reset_instance()


@pytest.fixture
def material(reading_home: Path):
    from deeptutor.reading import ReadingStore

    source = reading_home / "attention.pdf"
    doc = pymupdf.open()
    for body in PAGES:
        page = doc.new_page()
        page.insert_textbox(pymupdf.Rect(50, 50, 545, 780), body, fontsize=11)
    doc.set_toc([[1, "Introduction", 1], [1, "Transformers", 2]])
    doc.save(source)
    doc.close()

    store = ReadingStore()
    return store.ingest(source)


def _context(material_id: str = "", **metadata) -> UnifiedContext:
    meta = dict(metadata)
    if material_id:
        meta[MATERIAL_ID_KEY] = material_id
    return UnifiedContext(
        session_id="s1",
        user_message=meta.pop("user_message", "what is attention?"),
        metadata=meta,
    )


# ---------------------------------------------------------------------------
# activation and isolation
# ---------------------------------------------------------------------------


def test_capability_activates_only_when_a_material_is_open() -> None:
    capability = ReadingCapability()

    assert capability.is_active(_context("abc123ff")) is True
    assert capability.is_active(_context()) is False
    assert capability.is_active(_context(**{MATERIAL_ID_KEY: "   "})) is False


def test_reading_turns_do_not_activate_the_explore_context_pre_pass() -> None:
    """Two pre-passes must never read the same document.

    Reading material is addressed by locator through the reading store and is
    deliberately absent from ``source_index``, which is exactly what keeps
    explore_context dormant — no coordination code in either capability.
    """
    context = _context("abc123ff")

    assert ReadingCapability().is_active(context) is True
    assert ExploreContextCapability().is_active(context) is False


def test_capability_owns_exactly_the_five_reading_tools() -> None:
    assert ReadingCapability().owned_tools == READING_TOOL_NAMES
    assert len(READING_TOOL_NAMES) == 5
    # Additive, not exclusive: chat keeps its own surface on a reading turn.
    assert getattr(ReadingCapability(), "exclusive_tools", False) is False


# ---------------------------------------------------------------------------
# prompt
# ---------------------------------------------------------------------------


def test_system_block_states_the_unit_range_and_citation_form(material) -> None:
    block = ReadingCapability().system_block(
        _context(material.material_id), language="en", prompts={}
    )

    assert block is not None
    assert "[p.12]" in block.content
    assert "1..3" in block.content
    assert "attention.pdf" in block.content
    assert "reader_goto" in block.content


def test_system_block_is_localised(material) -> None:
    block = ReadingCapability().system_block(
        _context(material.material_id), language="zh", prompts={}
    )

    assert block is not None
    assert "沉浸式阅读" in block.content
    assert "[p.12]" in block.content


def test_system_block_reports_a_material_that_disappeared(material) -> None:
    from deeptutor.reading import ReadingStore

    ReadingStore().delete(material.material_id)

    block = ReadingCapability().system_block(
        _context(material.material_id), language="en", prompts={}
    )

    assert block is not None
    assert "no longer available" in block.content


def test_no_system_block_without_a_material() -> None:
    assert ReadingCapability().system_block(_context(), language="en", prompts={}) is None


# ---------------------------------------------------------------------------
# kwarg binding
# ---------------------------------------------------------------------------


def test_augment_kwargs_binds_the_material_to_reading_tools_only() -> None:
    capability = ReadingCapability()
    context = _context("abc123ff")

    bound = capability.augment_kwargs("read_material", {"locators": "2"}, context)
    untouched = capability.augment_kwargs("web_search", {"query": "x"}, context)

    assert bound[MATERIAL_KWARG] == "abc123ff"
    assert MATERIAL_KWARG not in untouched


def test_augment_kwargs_is_a_noop_without_an_open_material() -> None:
    bound = ReadingCapability().augment_kwargs("read_material", {"locators": "2"}, _context())
    assert MATERIAL_KWARG not in bound


# ---------------------------------------------------------------------------
# seeds
# ---------------------------------------------------------------------------


def test_pre_loop_seed_reports_viewport_and_selection() -> None:
    context = _context(
        "abc123ff",
        **{VIEWPORT_KEY: {"locator": 7, "selection": "scaled dot-product attention"}},
    )

    seed = ReadingCapability().pre_loop_seed(context)

    assert "locator 7" in seed
    assert "scaled dot-product attention" in seed


def test_pre_loop_seed_is_empty_when_nothing_is_open() -> None:
    assert ReadingCapability().pre_loop_seed(_context()) == ""


@pytest.mark.asyncio
async def test_locate_pre_pass_points_at_the_matching_locator(material) -> None:
    context = _context(material.material_id, user_message="what is scaled dot-product attention?")

    block = await ReadingCapability().pre_loop(context, StreamBus())

    assert block is not None
    assert "page 2" in block.content
    assert "verbatim" in block.content or "loose" in block.content


@pytest.mark.asyncio
async def test_locate_pre_pass_stays_silent_when_nothing_matches(material) -> None:
    context = _context(material.material_id, user_message="quantum flux capacitor calibration")

    assert await ReadingCapability().pre_loop(context, StreamBus()) is None


@pytest.mark.asyncio
async def test_locate_pre_pass_costs_no_tokens(material) -> None:
    """The pre-pass is deterministic search, not a second LLM loop."""

    class _Usage:
        def __init__(self) -> None:
            self.calls: list[object] = []

        def __getattr__(self, name):  # pragma: no cover - fails the test if hit
            raise AssertionError(f"usage.{name} must not be touched by the locate pass")

    context = _context(material.material_id, user_message="attention")

    block = await ReadingCapability().pre_loop(context, StreamBus(), usage=_Usage())

    assert block is not None


@pytest.mark.asyncio
async def test_locate_pre_pass_survives_a_deleted_material(material) -> None:
    from deeptutor.reading import ReadingStore

    ReadingStore().delete(material.material_id)
    context = _context(material.material_id, user_message="attention")

    assert await ReadingCapability().pre_loop(context, StreamBus()) is None


# ---------------------------------------------------------------------------
# tools
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_outline_tool_returns_the_documents_own_headings(material) -> None:
    result = await MaterialOutlineTool().execute(**{MATERIAL_KWARG: material.material_id})

    assert result.success is True
    assert "Transformers" in result.content


@pytest.mark.asyncio
async def test_search_tool_returns_locators_and_citation_sources(material) -> None:
    result = await SearchMaterialTool().execute(
        **{MATERIAL_KWARG: material.material_id, "query": "scaled dot-product"}
    )

    assert "page 2" in result.content
    assert [s["page"] for s in result.sources] == [2]
    assert result.sources[0]["type"] == "reading"


@pytest.mark.asyncio
async def test_search_tool_explains_a_miss_instead_of_failing(material) -> None:
    result = await SearchMaterialTool().execute(
        **{MATERIAL_KWARG: material.material_id, "query": "zzzzqqqq"}
    )

    assert result.success is True
    assert "No match" in result.content


@pytest.mark.asyncio
async def test_read_tool_renders_locator_headers(material) -> None:
    result = await ReadMaterialTool().execute(
        **{MATERIAL_KWARG: material.material_id, "locators": "1-2"}
    )

    assert "--- Page 1 ---" in result.content
    assert "--- Page 2 ---" in result.content
    assert [s["page"] for s in result.sources] == [1, 2]


@pytest.mark.asyncio
async def test_read_tool_reports_an_impossible_locator_without_dying(material) -> None:
    result = await ReadMaterialTool().execute(
        **{MATERIAL_KWARG: material.material_id, "locators": "900"}
    )

    assert result.success is False
    assert "1..3" in result.content


@pytest.mark.asyncio
async def test_tools_report_a_missing_material_binding() -> None:
    result = await ReadMaterialTool().execute(locators="1")

    assert result.success is False
    assert "No reading material is open" in result.content


@pytest.mark.asyncio
async def test_goto_emits_a_reader_action_for_the_client(material) -> None:
    result = await ReaderGotoTool().execute(
        **{
            MATERIAL_KWARG: material.material_id,
            "locator": 2,
            "quote": "scaled dot-product",
        }
    )

    assert result.success is True
    assert result.metadata["reader_action"] == "goto"
    assert result.metadata["locator"] == 2
    assert result.metadata["quote"] == "scaled dot-product"


@pytest.mark.asyncio
async def test_a_hallucinated_quote_never_paints_a_highlight(material) -> None:
    """The view may still move; the ink may not.

    Highlighting invented text would put the assistant's fabrication on the page
    itself, which is the one outcome worth refusing. Moving to the locator is
    harmless by comparison — and see the translation tests below for why refusing
    the move as well was the wrong trade.
    """
    result = await ReaderGotoTool().execute(
        **{
            MATERIAL_KWARG: material.material_id,
            "locator": 2,
            "quote": "the reptilian moon conspiracy",
        }
    )

    assert result.metadata["quote"] == ""


@pytest.mark.asyncio
async def test_goto_corrects_the_locator_when_the_quote_lives_elsewhere(material) -> None:
    result = await ReaderGotoTool().execute(
        **{
            MATERIAL_KWARG: material.material_id,
            "locator": 1,
            "quote": "scaled dot-product",
        }
    )

    assert result.success is True
    assert result.metadata["locator"] == 2
    assert result.metadata["corrected_from"] == 1
    assert "not page 1" in result.content


@pytest.mark.asyncio
async def test_bare_goto_without_a_quote_is_honoured(material) -> None:
    result = await ReaderGotoTool().execute(**{MATERIAL_KWARG: material.material_id, "locator": 3})

    assert result.success is True
    assert result.metadata["locator"] == 3


@pytest.mark.asyncio
async def test_goto_rejects_an_out_of_range_locator(material) -> None:
    result = await ReaderGotoTool().execute(**{MATERIAL_KWARG: material.material_id, "locator": 99})

    assert result.success is False
    assert "between 1 and 3" in result.content


@pytest.mark.asyncio
async def test_annotate_persists_a_mark_attributed_to_the_assistant(material) -> None:
    from deeptutor.reading import ReadingStore

    result = await ReaderAnnotateTool().execute(
        **{
            MATERIAL_KWARG: material.material_id,
            "locator": 2,
            "quote": "scaled dot-product",
            "note": "the core mechanism",
            "color": "green",
        }
    )

    assert result.success is True
    stored = ReadingStore().annotations(material.material_id)
    assert len(stored) == 1
    assert stored[0].author == "assistant"
    assert stored[0].color == "green"
    assert stored[0].note == "the core mechanism"
    assert result.metadata["reader_action"] == "annotate"


@pytest.mark.asyncio
async def test_annotate_refuses_a_quote_that_is_not_in_the_document(material) -> None:
    from deeptutor.reading import ReadingStore

    result = await ReaderAnnotateTool().execute(
        **{
            MATERIAL_KWARG: material.material_id,
            "locator": 2,
            "quote": "not present anywhere",
        }
    )

    assert result.success is False
    assert ReadingStore().annotations(material.material_id) == []


@pytest.mark.asyncio
async def test_annotate_falls_back_to_a_valid_colour(material) -> None:
    from deeptutor.reading import ReadingStore

    await ReaderAnnotateTool().execute(
        **{
            MATERIAL_KWARG: material.material_id,
            "locator": 2,
            "quote": "scaled dot-product",
            "color": "neon-chartreuse",
        }
    )

    assert ReadingStore().annotations(material.material_id)[0].color == "yellow"


@pytest.mark.asyncio
async def test_tool_definitions_never_expose_the_material_id() -> None:
    for tool_type in (
        MaterialOutlineTool,
        SearchMaterialTool,
        ReadMaterialTool,
        ReaderGotoTool,
        ReaderAnnotateTool,
    ):
        definition = tool_type().get_definition()
        names = {p.name for p in definition.parameters}
        assert MATERIAL_KWARG not in names
        assert "material_id" not in names


# ---------------------------------------------------------------------------
# reading mode with nothing open
# ---------------------------------------------------------------------------
#
# Regression: the capability used to activate only on an open material, so a turn
# taken in reading mode before opening anything was an ordinary chat turn. Asking
# "what does the section on positional encoding say, and where is it?" then
# produced a confident answer about a *different* paper — section number, page
# number and a verbatim-looking quote, all from the model's memory — with nothing
# to tell the reader that no document had been read.


def _mode_context(**metadata) -> UnifiedContext:
    from deeptutor.capabilities.reading.capability import MODE_KEY

    return _context(**{MODE_KEY: True, **metadata})


def test_capability_activates_on_the_mode_even_with_nothing_open() -> None:
    assert ReadingCapability().is_active(_mode_context()) is True


def test_an_ordinary_chat_turn_is_still_untouched() -> None:
    assert ReadingCapability().is_active(_context()) is False


def test_the_empty_reader_prompt_forbids_answering_from_memory() -> None:
    block = ReadingCapability().system_block(_mode_context(), language="en", prompts={})

    assert block is not None
    content = block.content.lower()
    assert "no document" in content or "not opened" in content
    # The specific failure it exists to prevent must be named, not implied.
    assert "memory" in content
    assert "ask them to drop a file" in content or "open" in content


def test_the_empty_reader_prompt_is_localised() -> None:
    block = ReadingCapability().system_block(_mode_context(), language="zh", prompts={})

    assert block is not None
    assert "没有任何文档可读" in block.content


def test_nothing_open_means_no_viewport_seed_and_no_locate_pass() -> None:
    from deeptutor.capabilities.reading.capability import VIEWPORT_KEY

    context = _mode_context(**{VIEWPORT_KEY: {"locator": 4, "selection": "stale"}})

    # A viewport with no document behind it is meaningless; it must not reach the
    # model as if a document were open.
    assert ReadingCapability().pre_loop_seed(context) == ""


@pytest.mark.asyncio
async def test_locate_pass_is_skipped_with_nothing_open() -> None:
    context = _mode_context(user_message="what does chapter three say?")
    assert await ReadingCapability().pre_loop(context, StreamBus()) is None


@pytest.mark.asyncio
async def test_reading_tools_report_the_empty_reader_rather_than_guessing() -> None:
    """The tools are mounted, and their guard is the second line of defence."""
    result = await ReadMaterialTool().execute(locators="1")

    assert result.success is False
    assert "no reading material is open" in result.content.lower()


# ---------------------------------------------------------------------------
# reader_goto: moving vs highlighting
# ---------------------------------------------------------------------------
#
# The locator and the quote are trusted differently. The locator comes from text
# the model just read; the quote is only what the highlight needs. Refusing the
# whole jump when a quote could not be verified made the reader sit still for the
# most ordinary case there is — answering in one language about a document
# written in another, where the "quote" is the model's own translation.


@pytest.mark.asyncio
async def test_goto_moves_without_highlighting_when_the_quote_is_a_translation(
    material,
) -> None:
    result = await ReaderGotoTool().execute(
        **{
            MATERIAL_KWARG: material.material_id,
            "locator": 2,
            "quote": "Transformer 使用缩放点积注意力",
        }
    )

    assert result.success is True
    assert result.metadata["reader_action"] == "goto"
    assert result.metadata["locator"] == 2
    # No highlight: the words are not on the page in that form.
    assert result.metadata["quote"] == ""
    # And the model is told why, so it can pass source-language text next time.
    assert "verbatim" in result.content


@pytest.mark.asyncio
async def test_goto_moves_without_highlighting_for_a_paraphrase(material) -> None:
    result = await ReaderGotoTool().execute(
        **{
            MATERIAL_KWARG: material.material_id,
            "locator": 2,
            "quote": "transformers apply scaled dot product attention across all tokens",
        }
    )

    assert result.success is True
    assert result.metadata["locator"] == 2
    assert result.metadata["quote"] == ""


@pytest.mark.asyncio
async def test_a_verbatim_quote_still_highlights(material) -> None:
    result = await ReaderGotoTool().execute(
        **{MATERIAL_KWARG: material.material_id, "locator": 2, "quote": "scaled dot-product"}
    )

    assert result.metadata["quote"] == "scaled dot-product"


@pytest.mark.asyncio
async def test_an_out_of_range_locator_is_still_refused(material) -> None:
    """Moving is forgiving; inventing a page is not."""
    result = await ReaderGotoTool().execute(
        **{MATERIAL_KWARG: material.material_id, "locator": 99, "quote": "anything"}
    )

    assert result.success is False
    assert "reader_action" not in (result.metadata or {})


@pytest.mark.asyncio
async def test_saved_annotations_stay_strict(material) -> None:
    """A mark persists and is exported, so it may not land on unverified text."""
    from deeptutor.reading import ReadingStore

    result = await ReaderAnnotateTool().execute(
        **{
            MATERIAL_KWARG: material.material_id,
            "locator": 2,
            "quote": "Transformer 使用缩放点积注意力",
        }
    )

    assert result.success is False
    assert ReadingStore().annotations(material.material_id) == []
