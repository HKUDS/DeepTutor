"""The ``view_figure`` tool: read one stored figure through a vision model.

Kept in its own module so :mod:`deeptutor.capabilities.reading.tools` stays under
the repository's file-size limit. Behaviour is unchanged from when it lived
beside the other reading tools; ``tools`` re-exports the class.
"""

from __future__ import annotations

import asyncio
from typing import Any

from deeptutor.capabilities.reading._tool_base import _guard, _ReadingToolBase
from deeptutor.core.tool_protocol import ToolDefinition, ToolParameter, ToolResult

# A missing-name failure lists the figures the model could have asked for, capped
# so a media-heavy material does not answer one typo with a wall of file names.
_FIGURE_NAME_LIST_LIMIT = 20

_FIGURE_SYSTEM_PROMPT = (
    "You describe figures for a reader who cannot see them. You state only "
    "what is visibly present and you never guess at intent."
)

_DEFAULT_FIGURE_QUESTION = (
    "Describe this image completely: the text in it, any formulas, and the "
    "structure and labelling of any figure."
)


class ViewFigureTool(_ReadingToolBase):
    """Look at one stored figure through a vision model, as text.

    The chat turn only carries the images on the page the user has open, so any
    other figure is invisible to a text model. This tool closes that gap by
    resolving the named image on disk, asking a vision model about it, and
    returning the *text* — the only channel a tool result has. The pixels never
    travel; the answer does.
    """

    name = "view_figure"

    def get_definition(self) -> ToolDefinition:
        return ToolDefinition(
            name=self.name,
            description=(
                "Look at the pixels of a single figure in the document the user "
                "is reading and answer a question about it. Use it when the body "
                "text and the image list's caption are not enough to tell what "
                "the figure actually shows; if the caption already answers, do "
                "not call it."
            ),
            parameters=[
                ToolParameter(
                    name="name",
                    type="string",
                    description=(
                        "The figure's file name, e.g. 'image-05.png', exactly as "
                        "it appears in the image list returned by read_material."
                    ),
                ),
                ToolParameter(
                    name="question",
                    type="string",
                    description=(
                        "What you want to know about the figure. If omitted, a "
                        "full description is produced."
                    ),
                    required=False,
                ),
            ],
        )

    @_guard
    async def execute(self, **kwargs: Any) -> ToolResult:
        import base64
        import mimetypes

        from deeptutor.services.llm.client import get_llm_client
        from deeptutor.services.rag.pipelines.llamaindex.config import image_description_limits
        from deeptutor.utils.document_images import MAX_IMAGE_BYTES

        material_id = self._material_id(kwargs)
        name = str(kwargs.get("name") or "").strip()
        if not name:
            return self._failure("view_figure needs a figure name, e.g. 'image-05.png'.")

        store = self._store()
        rows = await asyncio.to_thread(store.media_items, material_id)
        row = next((item for item in rows if str(item.get("name") or "") == name), None)
        if row is None:
            available = [str(item.get("name") or "") for item in rows]
            listed = ", ".join(available[:_FIGURE_NAME_LIST_LIMIT])
            if len(available) > _FIGURE_NAME_LIST_LIMIT:
                listed += f" … ({len(available)} images in total)"
            return self._failure(
                f"No figure named “{name}” in this document. Available figures: {listed or 'none'}."
            )

        caption = str(row.get("caption") or "").strip()
        locator = row.get("locator")
        manifest = await asyncio.to_thread(store.manifest, material_id)
        if type(locator) is not int or not 1 <= locator <= manifest.unit_count:
            return self._failure(f"The image “{name}” has no valid document locator.")
        source = {
            "type": "reading",
            "material_id": material_id,
            "material_revision": manifest.revision,
            "title": manifest.filename,
            "page": locator,
        }
        metadata = {
            "material_id": material_id,
            "material_revision": manifest.revision,
            "image": name,
            "locator": locator,
            "caption": caption,
        }
        path = await asyncio.to_thread(store.media_path, material_id, name)
        if path is None:
            return self._failure(
                f"The image “{name}” on {manifest.unit} {locator} is missing on disk "
                "and cannot be viewed."
            )
        size = await asyncio.to_thread(lambda: path.stat().st_size)
        if size > MAX_IMAGE_BYTES:
            return self._failure(
                f"The image “{name}” is {size} bytes, over the {MAX_IMAGE_BYTES}-byte "
                "limit for a single vision call, so it cannot be viewed."
            )

        question = str(kwargs.get("question") or "").strip() or _DEFAULT_FIGURE_QUESTION

        try:
            client = get_llm_client()
        except Exception:  # noqa: BLE001 - no client means no vision, not a crash
            client = None
        if client is None or not client.supports_multimodal_images():
            # Never answer with silence: hand back the caption if there is one,
            # and say plainly that the pixels were not read.
            content = (
                f"{manifest.unit} {locator}: Vision parsing is unavailable for this model, "
                f"so “{name}” could "
                "not be read."
            )
            if caption:
                content += f"\nCaption on record: {caption}"
            return ToolResult(
                content=content,
                sources=[source],
                metadata=metadata,
            )

        mime = str(row.get("mime") or "") or (
            mimetypes.guess_type(name)[0] or "application/octet-stream"
        )
        _, timeout_seconds = image_description_limits()
        data = await asyncio.to_thread(path.read_bytes)
        encoded = base64.b64encode(data).decode("ascii")
        text = await asyncio.wait_for(
            client.complete(
                question,
                system_prompt=_FIGURE_SYSTEM_PROMPT,
                image_data=encoded,
                image_mime_type=mime,
                image_filename=name,
            ),
            timeout=timeout_seconds,
        )
        answer = str(text or "").strip()
        if not answer:
            return self._failure(
                f"The vision model returned nothing for “{name}”. The caption on "
                f"record is: {caption or '(none)'}"
            )
        return ToolResult(
            content=f"{manifest.unit} {locator} ({name}): {answer}",
            sources=[source],
            metadata=metadata,
        )
