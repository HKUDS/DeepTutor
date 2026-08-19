"""Tools the immersive-reading capability mounts on the chat loop.

Two families, and the split matters:

**Reading** — ``material_outline`` / ``search_material`` / ``read_material``.
These are how the model gets grounded. Because the material is stored per unit,
every one of them returns a *locator*, so a claim is traceable to "page 12" as a
by-product of how the evidence was fetched rather than as an afterthought the
model has to remember to add.

**Driving the reader** — ``reader_goto`` / ``reader_annotate``. These reach out
of the conversation and act on what the user is looking at. ``reader_goto`` is
the one that makes the mode feel alive: ask "what does chapter three argue?" and
the page turns itself.

The two are guarded differently, on purpose. A **highlight** must be real, so it
is drawn only where the quoted text actually occurs; an unverifiable quote still
moves the view, without lighting anything up. A **saved annotation** is stronger
still — it persists and is written into the exported PDF — so it is refused
outright unless the quote checks out. The asymmetry matters in practice: a user
reading an English paper in Chinese gets translated "quotes" that can never match
verbatim, and refusing to move for those made the reader look broken.

The material id is never a parameter: the capability injects ``_material_id``
server-side via ``augment_kwargs``, so the model cannot read a document the user
has not opened, and cannot get the id wrong. Each call builds its own store,
matching the REST router, so concurrent turns never share mutable state.

UI side-effects travel on ``ToolResult.metadata`` under ``reader_action``, which
the pipeline already forwards to the client as part of the ``tool_result``
event — no new stream channel, no change to the chat engine.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from deeptutor.core.tool_protocol import BaseTool, ToolDefinition, ToolParameter, ToolResult
from deeptutor.tools.prompting import load_prompt_hints

logger = logging.getLogger(__name__)

# Mounted together whenever a reading material is open on the turn. Kept here so
# the mount policy and the registration list cannot drift apart.
READING_TOOL_NAMES: tuple[str, ...] = (
    "material_outline",
    "search_material",
    "read_material",
    "reader_goto",
    "reader_annotate",
)

# Private, server-injected kwarg carrying the open material.
MATERIAL_KWARG = "_material_id"

_SEARCH_DEFAULT_LIMIT = 8
_SEARCH_MAX_LIMIT = 20


class _ReadingToolBase(BaseTool):
    """Shared plumbing: resolve the injected material and the store."""

    def get_prompt_hints(self, language: str = "en"):
        return load_prompt_hints(self.name, language=language)

    @staticmethod
    def _material_id(kwargs: dict[str, Any]) -> str:
        material_id = str(kwargs.get(MATERIAL_KWARG) or "").strip()
        if not material_id:
            raise _NoMaterial()
        return material_id

    @staticmethod
    def _store():
        # Imported inside the call: ``reading.store`` reaches the path service,
        # which reaches the runtime and the tool registry — importing it at
        # module scope would close that cycle through the builtin registry.
        from deeptutor.reading import ReadingStore

        return ReadingStore()

    @staticmethod
    def _failure(message: str) -> ToolResult:
        return ToolResult(content=message, success=False)


class _NoMaterial(RuntimeError):
    """Raised when the turn has no open material (should be unreachable)."""


def _guard(func):
    """Turn engine errors into readable tool failures instead of turn deaths.

    A model that asked for page 900 of a 12-page document should be told so and
    given another round, not take the whole turn down with it.
    """

    async def wrapper(self: _ReadingToolBase, **kwargs: Any) -> ToolResult:
        from deeptutor.reading import ReadingError

        try:
            return await func(self, **kwargs)
        except _NoMaterial:
            return self._failure(
                "No reading material is open. Ask the user to open a document in the reader."
            )
        except ReadingError as exc:
            return self._failure(str(exc))
        except Exception:  # pragma: no cover - defensive
            logger.warning("reading tool %s failed", getattr(self, "name", "?"), exc_info=True)
            return self._failure("The reader could not complete that request.")

    return wrapper


class MaterialOutlineTool(_ReadingToolBase):
    """The map of the open document — always cheaper than reading to find out."""

    name = "material_outline"

    def get_definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="material_outline",
            description=(
                "Show the structure of the document the user is reading: its "
                "size and an outline with the locator (page / chapter / slide / "
                "section number) of each heading. Call this FIRST when you need "
                "to find where something is discussed — it is far cheaper than "
                "reading units one by one to look for it."
            ),
            parameters=[],
        )

    @_guard
    async def execute(self, **kwargs: Any) -> ToolResult:
        from deeptutor.reading import render_outline

        material_id = self._material_id(kwargs)
        store = self._store()
        text = await asyncio.to_thread(render_outline, store, material_id)
        return ToolResult(content=text, metadata={"material_id": material_id})


class SearchMaterialTool(_ReadingToolBase):
    """Locator-addressed search — the retrieval substitute for this mode."""

    name = "search_material"

    def get_definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="search_material",
            description=(
                "Search the full text of the document the user is reading. "
                "Returns matching locators (page / chapter / slide / section "
                "numbers) with a snippet from each. Use this to find where a "
                "term, name, formula or phrase appears, then read those "
                "locators with read_material."
            ),
            parameters=[
                ToolParameter(
                    name="query",
                    type="string",
                    description=(
                        "Words or a phrase to look for. A verbatim phrase from "
                        "the document matches most precisely."
                    ),
                ),
                ToolParameter(
                    name="limit",
                    type="integer",
                    description=f"Maximum matches to return (default {_SEARCH_DEFAULT_LIMIT}).",
                    required=False,
                ),
            ],
        )

    @_guard
    async def execute(self, **kwargs: Any) -> ToolResult:
        from deeptutor.reading import search_material

        material_id = self._material_id(kwargs)
        query = str(kwargs.get("query") or "").strip()
        if not query:
            return self._failure("search_material needs a non-empty query.")
        limit = _clamp_int(kwargs.get("limit"), _SEARCH_DEFAULT_LIMIT, 1, _SEARCH_MAX_LIMIT)

        store = self._store()
        manifest = await asyncio.to_thread(store.manifest, material_id)
        result = await asyncio.to_thread(search_material, store, material_id, query, limit=limit)

        unit = manifest.unit
        if result.is_empty:
            return ToolResult(
                content=(
                    f'No match for "{query}". Try fewer or different words, or '
                    f"call material_outline to see what the document covers."
                ),
                metadata={"material_id": material_id, "hits": []},
            )

        lines = [
            f'{len(result.hits)} match(es) for "{query}"'
            f"{' (loose term match — verify before citing)' if result.mode == 'terms' else ''}:"
        ]
        for hit in result.hits:
            lines.append(f"- {unit} {hit.locator}: {hit.snippet}")
        if result.truncated:
            lines.append("… more matches exist; narrow the query or raise the limit.")
        # Next-step guidance sits in the tool output, not only in the system
        # prompt: it reaches the model at the moment it is holding the result,
        # which is when it decides whether to quote a snippet directly. These
        # snippets are windowed and may cut mid-sentence, so quoting one
        # verbatim produces a citation that does not match the document.
        lines.append(
            f"→ These are windowed snippets, not the source. Read the {unit}(s) "
            "with read_material before quoting, then call reader_goto to show "
            "the user the passage."
        )

        return ToolResult(
            content="\n".join(lines),
            sources=[
                {
                    "type": "reading",
                    "material_id": material_id,
                    "title": manifest.filename,
                    "page": hit.locator,
                    "content": hit.snippet,
                }
                for hit in result.hits
            ],
            metadata={
                "material_id": material_id,
                "mode": result.mode,
                "hits": [hit.to_dict() for hit in result.hits],
            },
        )


class ReadMaterialTool(_ReadingToolBase):
    """Verbatim text of specific units — the grounding primitive."""

    name = "read_material"

    def get_definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="read_material",
            description=(
                "Read the exact text of specific parts of the document the user "
                "is reading, addressed by locator (page / chapter / slide / "
                "section number). Accepts a single number ('12'), a range "
                "('12-14') or a list ('3,12,17'). Every claim you make about "
                "the document should come from text you read here, and should "
                "cite the locator it came from."
            ),
            parameters=[
                ToolParameter(
                    name="locators",
                    type="string",
                    description=(
                        "Which parts to read: '12', '12-14', or '3,12,17'. "
                        "Locators are 1-indexed and match what the reader shows."
                    ),
                ),
            ],
        )

    @_guard
    async def execute(self, **kwargs: Any) -> ToolResult:
        from deeptutor.reading import render_units

        material_id = self._material_id(kwargs)
        spec = kwargs.get("locators")
        if spec is None or (isinstance(spec, str) and not spec.strip()):
            return self._failure("read_material needs a locator, e.g. '12' or '12-14'.")

        store = self._store()
        manifest = await asyncio.to_thread(store.manifest, material_id)
        rendered = await asyncio.to_thread(render_units, store, material_id, spec)

        if rendered.is_empty:
            return ToolResult(
                content=(
                    f"Those {manifest.unit}s contain no extractable text "
                    "(they may be images or scans)."
                ),
                metadata={"material_id": material_id, "locators": list(rendered.locators)},
            )
        followup = (
            "\n\n→ Now call reader_goto with the verbatim sentence you are "
            "about to cite, so the user sees it highlighted, and cite it in "
            "prose as [p.N]."
        )
        return ToolResult(
            content=rendered.text + followup,
            sources=[
                {
                    "type": "reading",
                    "material_id": material_id,
                    "title": manifest.filename,
                    "page": locator,
                }
                for locator in rendered.locators
            ],
            metadata={
                "material_id": material_id,
                "locators": list(rendered.locators),
                "truncated": rendered.truncated,
            },
        )


class ReaderGotoTool(_ReadingToolBase):
    """Move the user's viewport — refused unless the quote checks out."""

    name = "reader_goto"

    def get_definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="reader_goto",
            description=(
                "Scroll the user's reader to a specific locator and highlight "
                "the passage you are talking about. Use it whenever you "
                "reference a specific part of the document, so the user sees "
                "what you are reading. Pass the exact quote you are referring "
                "to — if it does not appear in the document the jump is "
                "refused, so quote verbatim rather than paraphrasing."
            ),
            parameters=[
                ToolParameter(
                    name="locator",
                    type="integer",
                    description="The page / chapter / slide / section number to show.",
                ),
                ToolParameter(
                    name="quote",
                    type="string",
                    description=(
                        "Verbatim text from that locator to highlight. Keep it "
                        "short (one sentence or phrase) and copy it exactly."
                    ),
                    required=False,
                ),
            ],
        )

    @_guard
    async def execute(self, **kwargs: Any) -> ToolResult:
        from deeptutor.reading import verify_quote

        material_id = self._material_id(kwargs)
        store = self._store()
        manifest = await asyncio.to_thread(store.manifest, material_id)

        locator = _as_locator(kwargs.get("locator"))
        if not 1 <= locator <= manifest.unit_count:
            return self._failure(
                f"reader_goto needs a locator between 1 and {manifest.unit_count}."
            )
        quote = str(kwargs.get("quote") or "").strip()

        if not quote:
            # No claim to verify: a bare navigation request is honoured.
            return _goto_result(material_id, locator, quote="", manifest=manifest)

        check = await asyncio.to_thread(verify_quote, store, material_id, locator, quote)
        if not check.verified:
            # Move anyway, without a highlight.
            #
            # The locator came from text the model just read; the quote is only
            # what the highlight needs. Refusing the whole jump made the reader
            # sit still for the most ordinary case there is — answering in one
            # language about a document written in another, where the "quote" is
            # the model's own translation and can never match verbatim. Landing
            # on the right page with no highlight is far more useful than not
            # moving at all, and it never paints a highlight over the wrong words.
            return _goto_result(
                material_id,
                locator,
                quote="",
                manifest=manifest,
                unverified_quote=quote,
            )
        target = check.found_locator or locator
        return _goto_result(
            material_id,
            target,
            quote=quote,
            manifest=manifest,
            corrected_from=locator if target != locator else None,
        )


class ReaderAnnotateTool(_ReadingToolBase):
    """Leave a durable mark on the document, exportable with the user's own."""

    name = "reader_annotate"

    def get_definition(self) -> ToolDefinition:
        return ToolDefinition(
            name="reader_annotate",
            description=(
                "Mark a passage in the user's document with an optional note. "
                "The mark persists, appears in the reader's annotation list, "
                "and is included when the user exports their annotated file. "
                "Use it when the user asks you to highlight, mark up or "
                "annotate something — not for ordinary explanation."
            ),
            parameters=[
                ToolParameter(
                    name="locator",
                    type="integer",
                    description="The page / chapter / slide / section number to mark.",
                ),
                ToolParameter(
                    name="quote",
                    type="string",
                    description="Verbatim text from that locator to mark. Must appear there.",
                ),
                ToolParameter(
                    name="note",
                    type="string",
                    description="Optional note to attach to the mark.",
                    required=False,
                ),
                ToolParameter(
                    name="color",
                    type="string",
                    description="Highlight colour.",
                    required=False,
                    enum=["yellow", "green", "blue", "pink", "purple"],
                ),
            ],
        )

    @_guard
    async def execute(self, **kwargs: Any) -> ToolResult:
        from deeptutor.reading import ANNOTATION_COLORS, Annotation, verify_quote

        material_id = self._material_id(kwargs)
        store = self._store()
        manifest = await asyncio.to_thread(store.manifest, material_id)

        locator = _as_locator(kwargs.get("locator"))
        if not 1 <= locator <= manifest.unit_count:
            return self._failure(
                f"reader_annotate needs a locator between 1 and {manifest.unit_count}."
            )
        quote = str(kwargs.get("quote") or "").strip()
        if not quote:
            return self._failure("reader_annotate needs the verbatim quote to mark.")

        check = await asyncio.to_thread(verify_quote, store, material_id, locator, quote)
        if not check.verified:
            return self._failure(
                "That quote does not appear in this document, so nothing was marked. "
                "Read the passage first and copy it exactly."
            )
        target = check.found_locator or locator

        colour = str(kwargs.get("color") or "").strip().lower()
        annotation = Annotation(
            annotation_id="",
            locator=target,
            kind="highlight",
            color=colour if colour in ANNOTATION_COLORS else "yellow",
            quote=quote,
            note=str(kwargs.get("note") or "").strip(),
            author="assistant",
        )
        saved = await asyncio.to_thread(store.save_annotation, material_id, annotation)

        return ToolResult(
            content=(
                f"Marked {manifest.unit} {target}: “{_ellipsis(quote, 80)}”"
                f"{f' — {saved.note}' if saved.note else ''}"
            ),
            metadata={
                "material_id": material_id,
                "reader_action": "annotate",
                "annotation": saved.to_dict(),
                # Marking is also a reason to look: carry the jump so the client
                # can reveal the mark it just made without a second tool call.
                "locator": target,
                "quote": quote,
            },
        )


def _goto_result(
    material_id: str,
    locator: int,
    *,
    quote: str,
    manifest: Any,
    corrected_from: int | None = None,
    unverified_quote: str = "",
) -> ToolResult:
    note = ""
    if corrected_from is not None:
        note = (
            f" (that passage is on {manifest.unit} {locator}, "
            f"not {manifest.unit} {corrected_from} — cite {locator})"
        )
    elif unverified_quote:
        # Say why nothing lit up, so the model can supply source-language text
        # next time instead of repeating a translation or a paraphrase.
        note = (
            " — but nothing was highlighted: that wording does not appear "
            "verbatim in the document. To highlight a passage, pass the text "
            "exactly as the document writes it, in its own language"
        )
    return ToolResult(
        content=f"Reader moved to {manifest.unit} {locator}{note}.",
        metadata={
            "material_id": material_id,
            "reader_action": "goto",
            "locator": locator,
            "quote": quote,
            "corrected_from": corrected_from,
        },
    )


def _clamp_int(value: Any, default: int, low: int, high: int) -> int:
    """Clamp a *bounded preference* (a result limit) into range."""
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return max(low, min(high, parsed))


def _as_locator(value: Any) -> int:
    """Parse a locator without clamping it.

    Deliberately not clamped: silently turning "page 900" into the last page
    would have the model cite text the user never asked about, and it would
    contradict ``parse_locators``, which drops out-of-range values. An invalid
    locator becomes 0 and the caller reports the real range.
    """
    try:
        return int(value)
    except (TypeError, ValueError):
        return 0


def _ellipsis(text: str, limit: int) -> str:
    flat = " ".join((text or "").split())
    return flat if len(flat) <= limit else flat[: limit - 1] + "…"


READING_TOOL_TYPES: tuple[type[BaseTool], ...] = (
    MaterialOutlineTool,
    SearchMaterialTool,
    ReadMaterialTool,
    ReaderGotoTool,
    ReaderAnnotateTool,
)


__all__ = [
    "MATERIAL_KWARG",
    "READING_TOOL_NAMES",
    "READING_TOOL_TYPES",
    "MaterialOutlineTool",
    "ReadMaterialTool",
    "ReaderAnnotateTool",
    "ReaderGotoTool",
    "SearchMaterialTool",
]
