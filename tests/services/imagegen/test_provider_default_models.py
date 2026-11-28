"""Image-generation Settings prefills must name models the provider still serves.

OpenAI retired gpt-image-1 on 2026-10-23 (dall-e-2 and dall-e-3 on 2026-05-12) and
shuts gpt-image-2 down on 2027-02-10, naming gpt-image-2.6-flare or -sunburst:
https://platform.openai.com/docs/deprecations. OpenRouter no longer lists
google/gemini-2.5-flash-image-preview.
"""

from deeptutor.services.config.provider_runtime import IMAGEGEN_PROVIDERS

RETIRED = {
    "openai": {"gpt-image-2", "gpt-image-1", "dall-e-3", "dall-e-2"},
    "openrouter": {"google/gemini-2.5-flash-image-preview"},
}


def test_openai_prefill_is_a_served_image_model() -> None:
    spec = IMAGEGEN_PROVIDERS["openai"]

    assert spec.default_model == "gpt-image-2.6-flare"
    assert spec.default_model not in RETIRED["openai"]


def test_openrouter_prefill_is_a_listed_image_model() -> None:
    spec = IMAGEGEN_PROVIDERS["openrouter"]

    assert spec.default_model == "google/gemini-3.1-flash-image"
    assert spec.default_model not in RETIRED["openrouter"]
    assert spec.adapter == "chat_completions"
