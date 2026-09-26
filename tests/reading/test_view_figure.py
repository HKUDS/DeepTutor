"""Figure viewing returns a grounded locator, including when vision is unavailable."""

from __future__ import annotations

import asyncio
import base64
from pathlib import Path
from types import SimpleNamespace

import pytest

from deeptutor.capabilities.reading.figure_view import ViewFigureTool


class _FigureStore:
    def __init__(self, image: Path | None) -> None:
        self.image = image

    def media_items(self, material_id: str) -> list[dict]:
        assert material_id == "material-1"
        return [
            {
                "name": "image-05.png",
                "locator": 2,
                "mime": "image/png",
                "caption": "A chart with two axes.",
            }
        ]

    def media_path(self, material_id: str, name: str) -> Path | None:
        assert (material_id, name) == ("material-1", "image-05.png")
        return self.image

    def manifest(self, material_id: str) -> SimpleNamespace:
        assert material_id == "material-1"
        return SimpleNamespace(unit="page", unit_count=3, revision=4, filename="paper.pdf")


@pytest.fixture
def configure_tool(monkeypatch):
    monkeypatch.setattr(ViewFigureTool, "_material_id", staticmethod(lambda _kwargs: "material-1"))
    monkeypatch.setattr(
        "deeptutor.services.rag.pipelines.llamaindex.config.image_description_limits",
        lambda: (0, 2.0),
    )

    def configure(image: Path | None, client: object) -> ViewFigureTool:
        monkeypatch.setattr(ViewFigureTool, "_store", staticmethod(lambda: _FigureStore(image)))
        monkeypatch.setattr("deeptutor.services.llm.client.get_llm_client", lambda: client)
        return ViewFigureTool()

    return configure


def test_view_figure_sends_the_stored_pixels_and_returns_page_source(
    configure_tool, tmp_path: Path
) -> None:
    image = tmp_path / "image-05.png"
    image.write_bytes(b"\x89PNG\r\nfigure")

    class _VisionClient:
        call: tuple[str, dict] | None = None

        def supports_multimodal_images(self) -> bool:
            return True

        async def complete(self, question: str, **kwargs):
            self.call = (question, kwargs)
            return "The vertical axis is probability."

    client = _VisionClient()
    tool = configure_tool(image, client)
    result = asyncio.run(tool.execute(name="image-05.png", question="What is the vertical axis?"))

    assert result.success is True
    assert result.content == "page 2 (image-05.png): The vertical axis is probability."
    assert result.sources == [
        {
            "type": "reading",
            "material_id": "material-1",
            "material_revision": 4,
            "title": "paper.pdf",
            "page": 2,
        }
    ]
    assert client.call is not None
    assert client.call[0] == "What is the vertical axis?"
    assert client.call[1]["image_data"] == base64.b64encode(image.read_bytes()).decode("ascii")
    assert client.call[1]["image_mime_type"] == "image/png"
    assert client.call[1]["image_filename"] == "image-05.png"


def test_view_figure_without_vision_identifies_the_unread_page_and_caption(
    configure_tool, tmp_path: Path
) -> None:
    image = tmp_path / "image-05.png"
    image.write_bytes(b"image")

    class _TextOnlyClient:
        def supports_multimodal_images(self) -> bool:
            return False

        async def complete(self, *_args, **_kwargs):
            raise AssertionError("The tool must not send pixels to a text-only client")

    result = asyncio.run(configure_tool(image, _TextOnlyClient()).execute(name="image-05.png"))

    assert result.success is True
    assert "page 2" in result.content
    assert "could not be read" in result.content
    assert "A chart with two axes." in result.content
    assert result.sources[0]["page"] == 2


def test_view_figure_reports_a_missing_stored_image_without_calling_vision(
    configure_tool,
) -> None:
    class _UnexpectedClient:
        def supports_multimodal_images(self) -> bool:
            raise AssertionError("Missing image must not reach the vision client")

    result = asyncio.run(configure_tool(None, _UnexpectedClient()).execute(name="image-05.png"))

    assert result.success is False
    assert "page 2" in result.content
    assert "missing on disk" in result.content
