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


def test_edenai_provider_aliases_and_base_detection() -> None:
    spec = find_by_name("edenai")

    assert spec is not None
    assert spec.display_name == "Eden AI"
    assert spec.env_key == "EDENAI_API_KEY"
    assert spec.backend == "openai_compat"
    assert spec.mode == "gateway"
    assert spec.default_api_base == "https://api.edenai.run/v3"
    assert find_by_name("eden-ai") == spec
    assert find_by_name("eden_ai") == spec
    assert find_gateway(api_base="https://api.edenai.run/v3") == spec


def test_novita_provider_aliases_and_base_detection() -> None:
    spec = find_by_name("novita")

    assert spec is not None
    assert spec.display_name == "Novita AI"
    assert spec.env_key == "NOVITA_API_KEY"
    assert spec.backend == "openai_compat"
    assert spec.mode == "gateway"
    assert spec.default_api_base == "https://api.novita.ai/openai"
    assert find_by_name("novita-ai") == spec
    assert find_by_name("novita_ai") == spec
    assert find_gateway(api_base="https://api.novita.ai/openai") == spec


def test_openai_codex_is_not_detected_from_api_base() -> None:
    assert find_gateway(api_base="https://codex.example.com/v1") is None


def test_openai_codex_provider_is_oauth_backed() -> None:
    spec = find_by_name("openai_codex")

    assert spec is not None
    assert spec.auth_mode == "oauth"
    assert spec.env_key == ""


def test_github_copilot_is_oauth_backed() -> None:
    spec = find_by_name("github_copilot")

    assert spec is not None
    assert spec.auth_mode == "oauth"
    assert spec.env_key == ""
