"""Model selection shared by the existing document image-description passes."""

from typing import Any

from deeptutor.services.config.runtime_settings import load_document_parsing_settings
from deeptutor.services.model_selection.llm import LLMSelection
from deeptutor.services.model_selection.runtime import resolve_llm_config_for_selection

from .capabilities import supports_vision
from .client import LLMClient, get_llm_client
from .config import LLMConfig
from .factory import complete_with_config


def resolve_image_description_config(selection: dict[str, str]) -> LLMConfig:
    """Validate an explicit selection without installing a global override."""
    config = resolve_llm_config_for_selection(LLMSelection.from_payload(selection))
    if not supports_vision(config.binding, config.model):
        raise ValueError("The image description model must support image input.")
    return config


class _ImageDescriptionClient(LLMClient):
    async def complete(
        self,
        prompt: str,
        system_prompt: str | None = None,
        history: list[dict[str, str]] | None = None,
        **kwargs: Any,
    ) -> str:
        # Preserve the full resolved profile (including wire API and endpoint)
        # rather than rebuilding an override from a subset of its fields.
        return await complete_with_config(
            config=self.config,
            prompt=prompt,
            system_prompt=system_prompt or "You are a helpful assistant.",
            messages=history or None,
            **kwargs,
        )


def get_image_description_client() -> LLMClient:
    selection = load_document_parsing_settings().get("image_description_model")
    if not selection:
        return get_llm_client()
    return _ImageDescriptionClient(resolve_image_description_config(selection), configure_env=False)
