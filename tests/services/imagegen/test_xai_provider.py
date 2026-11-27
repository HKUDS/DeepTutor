"""xAI Grok Imagine image-generation provider tests."""

from deeptutor.services.config.provider_runtime import (
    IMAGEGEN_PROVIDERS,
    resolve_imagegen_runtime_config,
)


def test_xai_imagegen_spec() -> None:
    spec = IMAGEGEN_PROVIDERS["xai"]

    assert spec.default_model == "grok-imagine-image-2.0"
    assert spec.default_api_base == "https://api.x.ai/v1"
    assert spec.adapter == "openai_compat"


def test_xai_imagegen_runtime_resolution() -> None:
    catalog = {
        "version": 1,
        "services": {
            "imagegen": {
                "active_profile_id": "imagegen-p",
                "active_model_id": "imagegen-m",
                "profiles": [
                    {
                        "id": "imagegen-p",
                        "name": "xAI (Grok Imagine)",
                        "binding": "xai",
                        "base_url": "",
                        "api_key": "xai-key",
                        "api_version": "",
                        "extra_headers": {},
                        "models": [
                            {
                                "id": "imagegen-m",
                                "name": "Grok Imagine 2.0",
                                "model": "grok-imagine-image-2.0",
                            }
                        ],
                    }
                ],
            }
        },
    }

    resolved = resolve_imagegen_runtime_config(catalog=catalog)

    assert resolved.provider_name == "xai"
    assert resolved.adapter == "openai_compat"
    assert resolved.base_url == "https://api.x.ai/v1"
    assert resolved.model == "grok-imagine-image-2.0"
