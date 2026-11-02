"""Model selection shared by the existing document image-description passes."""

from typing import Any

from deeptutor.services.config.model_catalog import get_model_catalog_service
from deeptutor.services.config.runtime_settings import load_document_parsing_settings
from deeptutor.services.model_selection.llm import LLMSelection, list_llm_options
from deeptutor.services.model_selection.runtime import resolve_llm_config_for_selection

from .capabilities import supports_vision_declared
from .client import LLMClient, get_llm_client
from .config import LLMConfig
from .factory import complete_with_config


def _vision_support(selection: LLMSelection, config: LLMConfig) -> bool:
    """Take the verdict from the picker so the two can never disagree.

    Falls back to the resolved binding for selections the global catalog does
    not list, such as a per-user model.
    """
    for option in list_llm_options(get_model_catalog_service().load())["options"]:
        if (option["profile_id"], option["model_id"]) == (
            selection.profile_id,
            selection.model_id,
        ):
            return option["supports_vision"]
    return supports_vision_declared(None, config.binding, config.model)


def resolve_image_description_config(selection: dict[str, str]) -> LLMConfig:
    """Validate an explicit selection without installing a global override."""
    payload = LLMSelection.from_payload(selection)
    config = resolve_llm_config_for_selection(payload)
    if not _vision_support(payload, config):
        raise ValueError("The image description model must support image input.")
    return config


class _ImageDescriptionClient(LLMClient):
    def supports_multimodal_images(self) -> bool:
        """Trust the gate: this client only exists for a validated selection.

        ``self.config.binding`` is the provider detected from ``base_url``, which
        can differ from the declared binding ``resolve_image_description_config``
        validated, so re-deriving capability here would veto a valid selection.
        """
        return True

    async def complete(
        self,
        prompt: str,
        system_prompt: str | None = None,
        history: list[dict[str, str]] | None = None,
        **kwargs: Any,
    ) -> str:
        # The caption batcher passes this flag too; the validated verdict wins.
        kwargs.pop("allow_image_fallback", None)
        # Preserve the full resolved profile (including wire API and endpoint)
        # rather than rebuilding an override from a subset of its fields.
        return await complete_with_config(
            config=self.config,
            prompt=prompt,
            system_prompt=system_prompt or "You are a helpful assistant.",
            messages=history or None,
            # The validated selection decided images are supported; the factory
            # would otherwise strip them for the model it detects on its own.
            allow_image_fallback=False,
            **kwargs,
        )


def get_image_description_client() -> LLMClient:
    selection = load_document_parsing_settings().get("image_description_model")
    if not selection:
        return get_llm_client()
    return _ImageDescriptionClient(resolve_image_description_config(selection), configure_env=False)
