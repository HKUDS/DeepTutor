"""Credential-free selection for document image descriptions."""

from pydantic import BaseModel, ConfigDict, Field


class ImageDescriptionModelSelection(BaseModel):
    """Reference a configured vision model without changing the chat default."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)

    profile_id: str = Field(min_length=1)
    model_id: str = Field(min_length=1)


def normalize_image_description_model(value: object) -> dict[str, str] | None:
    if value is None or value == {}:
        return None
    return ImageDescriptionModelSelection.model_validate(value).model_dump()
