"""Independent image models preserve the main client and full provider config."""

from copy import deepcopy
import os

import pytest

from deeptutor.services.llm import image_description as mod
from deeptutor.services.llm.config import LLMConfig
from deeptutor.services.model_selection.llm import LLMSelection


@pytest.fixture
def selected(monkeypatch):
    config = LLMConfig(
        model="vision-model",
        binding="openai",
        api_key="synthetic-key",
        base_url="https://example.invalid/v1",
        effective_url="https://example.invalid/v1/responses",
        wire_api="responses",
        reasoning_effort="low",
    )
    monkeypatch.setattr(
        mod,
        "load_document_parsing_settings",
        lambda: {"image_description_model": {"profile_id": "pictures", "model_id": "vision"}},
    )

    def resolve(selection):
        assert selection == LLMSelection(profile_id="pictures", model_id="vision")
        return config

    monkeypatch.setattr(mod, "resolve_llm_config_for_selection", resolve)
    monkeypatch.setattr(mod, "supports_vision", lambda *_: True)
    return config


@pytest.mark.parametrize("value", [None, {}])
def test_unset_selection_reuses_main_client(monkeypatch, value):
    main = object()
    monkeypatch.setattr(
        mod, "load_document_parsing_settings", lambda: {"image_description_model": value}
    )
    monkeypatch.setattr(mod, "get_llm_client", lambda: main)
    assert mod.get_image_description_client() is main


@pytest.mark.asyncio
async def test_explicit_model_preserves_full_config_and_process_state(monkeypatch, selected):
    monkeypatch.setenv("OPENAI_API_KEY", "main-synthetic-key")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://chat.example.invalid")
    original = deepcopy(selected)
    before = dict(os.environ)
    calls = []

    async def complete(**kwargs):
        calls.append(kwargs)
        return "a labelled diagram"

    monkeypatch.setattr(mod, "complete_with_config", complete)
    monkeypatch.setattr(
        mod, "get_llm_client", lambda: pytest.fail("must not replace the main client")
    )
    client = mod.get_image_description_client()
    assert (
        await client.complete("Describe", image_data="synthetic-image", image_mime_type="image/png")
        == "a labelled diagram"
    )
    assert calls[0]["config"] is selected
    assert calls[0]["image_data"] == "synthetic-image"
    assert selected == original
    assert dict(os.environ) == before


def test_explicit_text_model_is_rejected(monkeypatch, selected):
    monkeypatch.setattr(mod, "supports_vision", lambda *_: False)
    with pytest.raises(ValueError, match="must support image input"):
        mod.get_image_description_client()


def test_deleted_selection_does_not_silently_charge_main_model(monkeypatch, selected):
    def missing(_):
        raise ValueError("selected profile/model was not found")

    monkeypatch.setattr(mod, "resolve_llm_config_for_selection", missing)
    monkeypatch.setattr(mod, "get_llm_client", lambda: pytest.fail("unexpected fallback"))
    with pytest.raises(ValueError, match="not found"):
        mod.get_image_description_client()


@pytest.mark.asyncio
async def test_reading_captions_use_selected_model(monkeypatch, tmp_path, selected):
    from deeptutor.reading import captions

    image = tmp_path / "figure.png"
    image.write_bytes(b"synthetic image")
    saved = {}

    class Store:
        def media_items(self, _):
            return [{"name": "figure.png", "mime": "image/png"}]

        def media_path(self, *_):
            return image

        def update_media_captions(self, _, result):
            saved.update(result)
            return len(result)

    async def complete(**kwargs):
        assert kwargs["config"] is selected
        assert kwargs["image_filename"] == "figure.png"
        return "selected vision caption"

    monkeypatch.setattr(mod, "complete_with_config", complete)
    monkeypatch.setattr(mod.LLMClient, "supports_multimodal_images", lambda _: True)
    assert await captions.caption_material_media("material", store=Store()) == 1
    assert saved == {"figure.png": "selected vision caption"}


@pytest.mark.asyncio
async def test_llamaindex_image_descriptions_use_selected_model(monkeypatch, tmp_path, selected):
    from types import SimpleNamespace

    from deeptutor.services.rag.pipelines.llamaindex import document_loader

    image = tmp_path / "figure.png"
    image.write_bytes(b"synthetic image")

    class Embedding:
        config = SimpleNamespace(binding="test", model="test")

        def supports_multimodal_contents(self):
            return True

        async def embed_contents(self, contents):
            return [[0.1, 0.2] for _ in contents]

    async def complete(**kwargs):
        assert kwargs["config"] is selected
        return "selected vision caption"

    monkeypatch.setattr(mod, "complete_with_config", complete)
    monkeypatch.setattr(mod.LLMClient, "supports_multimodal_images", lambda _: True)
    monkeypatch.setattr(document_loader, "get_embedding_client", Embedding)
    nodes = await document_loader.LlamaIndexDocumentLoader()._load_image_nodes(
        [document_loader._ImageSource(path=image, origin=image)]
    )
    assert len(nodes) == 1
    assert "selected vision caption" in nodes[0].text
