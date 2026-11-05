"""The image-description gate and the model picker must reach the same verdict.

Both read the same catalog, so a model the picker offers has to be savable and a
model it hides has to be refused. They disagreed whenever the profile's declared
binding differed from the provider the runtime detects from ``base_url``: the
picker judged capability from the declared provider, the gate from the detected
one (#2037 follow-up).
"""

from __future__ import annotations

import base64
from pathlib import Path
from typing import Any

import pytest

from deeptutor.services.config import model_catalog, provider_runtime
from deeptutor.services.config.model_catalog import ModelCatalogService
from deeptutor.services.llm import image_description
from deeptutor.services.llm.capabilities import set_catalog_capability_overrides
from deeptutor.services.llm.image_caption_batch import ImageCaptionBatcher
from deeptutor.services.llm.image_description import resolve_image_description_config
from deeptutor.services.model_selection.llm import list_llm_options

GATEWAY_BASE_URL = "http://localhost:11434/v1"
SELECTION = {"profile_id": "gateway", "model_id": "m"}


@pytest.fixture(autouse=True)
def _clean_capability_overrides():
    """The override table is process-global; keep these tests independent."""
    set_catalog_capability_overrides([])
    yield
    set_catalog_capability_overrides([])


def _service(
    tmp_path: Path, models: list[dict[str, Any]], *, binding: str = "openai"
) -> ModelCatalogService:
    service = ModelCatalogService(path=tmp_path / "model_catalog.json")
    catalog = service.load()
    catalog["services"]["llm"]["profiles"] = [
        {
            "id": "gateway",
            "name": "OpenAI binding pointed at a local gateway",
            "binding": binding,
            "base_url": GATEWAY_BASE_URL,
            "api_key": "synthetic-key",
            "models": models,
        }
    ]
    service.save(catalog)
    return service


def _patch_catalog(monkeypatch, service: ModelCatalogService) -> None:
    """Point every catalog lookup on this path at the fixture."""
    monkeypatch.setattr(model_catalog, "get_model_catalog_service", lambda: service)
    monkeypatch.setattr(provider_runtime, "get_model_catalog_service", lambda: service)
    monkeypatch.setattr(
        image_description, "get_model_catalog_service", lambda: service, raising=False
    )


def _offered(service: ModelCatalogService) -> list[bool]:
    return [option["supports_vision"] for option in list_llm_options(service.load())["options"]]


def test_gate_accepts_every_model_the_picker_offers(tmp_path: Path, monkeypatch) -> None:
    service = _service(tmp_path, [{"id": "m", "model": "llama3.2-vision"}])
    _patch_catalog(monkeypatch, service)

    assert _offered(service) == [True]
    assert resolve_image_description_config(SELECTION).model == "llama3.2-vision"


def test_gate_refuses_a_model_the_tables_do_not_know(tmp_path: Path, monkeypatch) -> None:
    service = _service(tmp_path, [{"id": "m", "model": "llama3.2"}], binding="custom")
    _patch_catalog(monkeypatch, service)

    assert _offered(service) == [False]
    with pytest.raises(ValueError, match="must support image input"):
        resolve_image_description_config(SELECTION)


def test_declared_capability_beats_the_provider_table(tmp_path: Path, monkeypatch) -> None:
    service = _service(
        tmp_path, [{"id": "m", "model": "gpt-4o", "capabilities": {"vision": False}}]
    )
    _patch_catalog(monkeypatch, service)

    assert _offered(service) == [False]
    with pytest.raises(ValueError, match="must support image input"):
        resolve_image_description_config(SELECTION)


def test_validated_selection_accepts_images_despite_the_detected_binding(
    tmp_path: Path, monkeypatch
) -> None:
    service = _service(tmp_path, [{"id": "m", "model": "llama3.2-vision"}])
    _patch_catalog(monkeypatch, service)

    config = resolve_image_description_config(SELECTION)
    # The gateway URL makes the runtime detect ollama although ``openai`` was declared.
    assert config.binding == "ollama"
    client = image_description._ImageDescriptionClient(config, configure_env=False)
    assert client.supports_multimodal_images() is True


@pytest.mark.asyncio
async def test_complete_sends_images_for_the_validated_selection(
    tmp_path: Path, monkeypatch
) -> None:
    service = _service(tmp_path, [{"id": "m", "model": "llama3.2-vision"}])
    _patch_catalog(monkeypatch, service)
    config = resolve_image_description_config(SELECTION)
    calls: list[dict[str, Any]] = []

    async def complete(**kwargs: Any) -> str:
        calls.append(kwargs)
        return "a labelled diagram"

    monkeypatch.setattr(image_description, "complete_with_config", complete)
    client = image_description._ImageDescriptionClient(config, configure_env=False)

    assert await client.complete("Describe", image_data="synthetic-image") == "a labelled diagram"
    assert calls[0]["allow_image_fallback"] is False


@pytest.mark.asyncio
async def test_complete_tolerates_a_caller_supplied_fallback_flag(
    tmp_path: Path, monkeypatch
) -> None:
    """The caption batcher passes this flag itself; it must not collide."""
    service = _service(tmp_path, [{"id": "m", "model": "llama3.2-vision"}])
    _patch_catalog(monkeypatch, service)
    config = resolve_image_description_config(SELECTION)
    calls: list[bool | None] = []

    async def complete(
        *,
        config: Any,
        prompt: str,
        system_prompt: str,
        messages: Any,
        allow_image_fallback: bool | None = None,
        **kwargs: Any,
    ) -> str:
        calls.append(allow_image_fallback)
        return "a labelled diagram"

    monkeypatch.setattr(image_description, "complete_with_config", complete)
    client = image_description._ImageDescriptionClient(config, configure_env=False)

    caption = await client.complete(
        "Describe", image_data="synthetic-image", max_retries=0, allow_image_fallback=False
    )
    assert caption == "a labelled diagram"
    assert calls == [False]


@pytest.mark.asyncio
async def test_batcher_drives_the_real_client_end_to_end(tmp_path: Path, monkeypatch) -> None:
    """Wire the real batcher to the real client: the seam both defects lived on.

    The batcher supplies ``allow_image_fallback`` itself and swallows a failure
    into ``[None, None]``, so a client that forwarded the flag twice lost every
    caption in the batch without a visible error.
    """
    service = _service(tmp_path, [{"id": "m", "model": "llama3.2-vision"}])
    _patch_catalog(monkeypatch, service)
    config = resolve_image_description_config(SELECTION)

    async def complete(
        *,
        config: Any,
        prompt: str,
        system_prompt: str,
        messages: Any,
        allow_image_fallback: bool | None = None,
        **kwargs: Any,
    ) -> str:
        return (
            '{"captions": [{"image_id": "IMAGE_0", "caption": "first"},'
            ' {"image_id": "IMAGE_1", "caption": "second"}]}'
        )

    monkeypatch.setattr(image_description, "complete_with_config", complete)
    client = image_description._ImageDescriptionClient(config, configure_env=False)
    batcher = ImageCaptionBatcher(
        client, prompt="Describe the figure.", system_prompt="You describe figures."
    )
    # Unique bytes per run: the caption cache is keyed on the image digest, and
    # a hit would skip the client call this test exists to exercise.
    marker = str(tmp_path).encode()
    images = [
        {
            "base64": base64.b64encode(marker + name.encode()).decode(),
            "mimetype": "image/png",
            "filename": name,
        }
        for name in ("a.png", "b.png")
    ]

    assert await batcher.describe(images) == ["first", "second"]
