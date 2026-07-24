from deeptutor.services.provider_registry import find_by_name, find_gateway


def test_nvidia_nim_gateway_detection_by_key_and_base() -> None:
    spec = find_by_name("nvidia_nim")

    assert spec is not None
    assert spec.supports_stream_options is False
    assert find_gateway(api_key="nvapi-test-key") == spec
    assert find_gateway(api_base="https://integrate.api.nvidia.com/v1") == spec


def test_atlascloud_provider_aliases_and_base_detection() -> None:
    spec = find_by_name("atlascloud")

    assert spec is not None
    assert spec.display_name == "Atlas Cloud"
    assert spec.env_key == "ATLASCLOUD_API_KEY"
    assert spec.backend == "openai_compat"
    assert spec.mode == "gateway"
    assert spec.default_api_base == "https://api.atlascloud.ai/v1"
    assert find_by_name("atlas-cloud") == spec
    assert find_by_name("atlas_cloud") == spec
    assert find_by_name("atlas") == spec
    assert find_gateway(api_base="https://api.atlascloud.ai/v1") == spec


def test_openai_codex_is_not_detected_from_api_base() -> None:
    assert find_gateway(api_base="https://codex.example.com/v1") is None


def test_openai_codex_provider_exposes_oauth_dynamic_policy() -> None:
    spec = find_by_name("openai_codex")

    assert spec is not None
    assert spec.auth_mode == "oauth"
    assert spec.model_policy == "dynamic_catalog"
    assert spec.requires_api_key is False
    assert spec.experimental is True


def test_github_copilot_oauth_does_not_require_api_key() -> None:
    spec = find_by_name("github_copilot")

    assert spec is not None
    assert spec.auth_mode == "oauth"
    assert spec.requires_api_key is False
