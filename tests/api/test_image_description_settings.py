"""Persist only model IDs and preserve/clear explicit caption selections."""

from fastapi import HTTPException
from pydantic import ValidationError
import pytest

from deeptutor.api.routers import settings as router
from deeptutor.services.config.runtime_settings import RuntimeSettingsService
from deeptutor.services.llm import image_description

SELECTION = {"profile_id": "pictures", "model_id": "vision"}


@pytest.fixture
def service(monkeypatch, tmp_path):
    service = RuntimeSettingsService(tmp_path / "settings", process_env={})
    monkeypatch.setattr(router, "_require_settings_admin", lambda: None)
    monkeypatch.setattr(router, "get_runtime_settings_service", lambda: service)
    monkeypatch.setattr(router, "_document_parsing_payload", service.load_document_parsing)
    monkeypatch.setattr(image_description, "resolve_image_description_config", lambda _: None)
    return service


@pytest.mark.asyncio
async def test_selection_roundtrip_omission_and_explicit_reset(service):
    initial = service.load_document_parsing()
    assert initial["image_description_model"] is None
    selected = await router.update_document_parsing_settings(
        router.DocumentParsingUpdate(image_description_model=SELECTION)
    )
    assert selected["image_description_model"] == SELECTION
    assert selected["engines"] == initial["engines"]
    assert selected["image_caption"] == initial["image_caption"]
    preserved = await router.update_document_parsing_settings(
        router.DocumentParsingUpdate(engine="mineru")
    )
    assert preserved["image_description_model"] == SELECTION
    service.save_mineru({"language": "en"})
    assert service.load_document_parsing()["image_description_model"] == SELECTION
    cleared = await router.update_document_parsing_settings(
        router.DocumentParsingUpdate(image_description_model=None)
    )
    assert cleared["image_description_model"] is None
    assert service.load_document_parsing()["engine"] == "mineru"


@pytest.mark.asyncio
async def test_invalid_or_text_only_selection_does_not_save(service, monkeypatch):
    before = service.load_document_parsing()

    def invalid(_):
        raise ValueError("The image description model must support image input.")

    monkeypatch.setattr(image_description, "resolve_image_description_config", invalid)
    with pytest.raises(HTTPException) as exc:
        await router.update_document_parsing_settings(
            router.DocumentParsingUpdate(engine="mineru", image_description_model=SELECTION)
        )
    assert exc.value.status_code == 400
    assert service.load_document_parsing() == before


@pytest.mark.parametrize(
    "selection",
    [
        {"profile_id": "pictures"},
        {"profile_id": " ", "model_id": "vision"},
        {**SELECTION, "api_key": "must-not-be-accepted"},
    ],
)
def test_model_selection_rejects_incomplete_ids_and_credentials(selection):
    with pytest.raises(ValidationError):
        router.DocumentParsingUpdate(image_description_model=selection)
