from __future__ import annotations

from io import StringIO
from types import SimpleNamespace

from rich.console import Console


def test_gemini_embedding_fallback_prefers_stable_embedding2() -> None:
    from deeptutor_cli.init_wizard import EMBEDDING_FALLBACK_MODELS

    # Embedding 2 leads, but 001 stays offered: it is still a current model and
    # dropping it left the offline wizard with a single choice.
    assert EMBEDDING_FALLBACK_MODELS["gemini"] == (
        "gemini-embedding-2",
        "gemini-embedding-001",
    )


def test_embedding_setup_preserves_saved_endpoint_for_same_provider() -> None:
    from deeptutor.services.config.provider_runtime import EMBEDDING_PROVIDERS
    from deeptutor_cli.init_cmd import _embedding_default_endpoint

    saved = "https://proxy.example.com/google/v1/embeddings"
    endpoint = _embedding_default_endpoint(
        provider="gemini",
        current_binding="gemini",
        current_profile={"base_url": saved},
        spec=EMBEDDING_PROVIDERS["gemini"],
    )
    switched = _embedding_default_endpoint(
        provider="gemini",
        current_binding="openai",
        current_profile={"base_url": "https://api.openai.com/v1/embeddings"},
        spec=EMBEDDING_PROVIDERS["gemini"],
    )

    assert endpoint == saved
    assert switched.endswith("gemini-embedding-2:batchEmbedContents")


def test_gemini_native_embedding_endpoint_derives_native_models_url() -> None:
    from deeptutor_cli.init_wizard import _derive_embedding_models_url

    assert (
        _derive_embedding_models_url(
            (
                "https://generativelanguage.googleapis.com/v1beta/models/"
                "gemini-embedding-2:batchEmbedContents"
            ),
            "gemini",
        )
        == "https://generativelanguage.googleapis.com/v1beta/models"
    )


def test_gemini_models_url_preserves_custom_gateway_path_prefix() -> None:
    from deeptutor_cli.init_wizard import _derive_embedding_models_url

    assert (
        _derive_embedding_models_url(
            (
                "https://proxy.example.com/google/v1beta/models/"
                "gemini-embedding-2:batchEmbedContents?tenant=demo"
            ),
            "gemini",
        )
        == "https://proxy.example.com/google/v1beta/models?tenant=demo"
    )

    assert (
        _derive_embedding_models_url(
            "https://proxy.example.com/google/v1beta/openai/embeddings",
            "gemini",
        )
        == "https://proxy.example.com/google/v1beta/models"
    )

    assert (
        _derive_embedding_models_url(
            "https://proxy.example.com/google/v1/embeddings",
            "gemini",
        )
        == "https://proxy.example.com/google/v1/models"
    )


class _FakeClient:
    captured: list[dict] = []

    def __init__(self, *, timeout: float):
        self.timeout = timeout

    def __enter__(self):
        return self

    def __exit__(self, *_args):
        return None

    def post(self, url: str, *, headers: dict, json: dict):
        self.captured.append({"url": url, "headers": headers, "json": json})
        return SimpleNamespace(status_code=200, text="")

    def get(self, url: str, *, headers: dict):
        self.captured.append({"url": url, "headers": headers})

        class _Response:
            def raise_for_status(self):
                return None

            def json(self):
                return {"models": [{"name": "models/gemini-embedding-2"}]}

        return _Response()


def test_fetch_gemini_models_uses_auth_matching_endpoint_host(monkeypatch) -> None:
    from deeptutor_cli import init_wizard

    _FakeClient.captured = []
    monkeypatch.setattr(init_wizard.httpx, "Client", _FakeClient)
    output = StringIO()
    console = Console(file=output)
    strings = {
        "init.fetch_models": "fetch {url}",
        "init.fetch_models_fail": "failed {error}",
        "init.fetch_models_ok": "found {count}",
    }

    official = init_wizard.fetch_embedding_models(
        console,
        strings,
        endpoint=(
            "https://generativelanguage.googleapis.com/v1beta/models/"
            "gemini-embedding-2:batchEmbedContents"
        ),
        api_key="credential",
        provider="gemini",
    )
    custom = init_wizard.fetch_embedding_models(
        console,
        strings,
        endpoint="https://proxy.example.com/google/v1/embeddings?key=url-secret",
        api_key="credential",
        provider="gemini",
    )

    assert official == ["gemini-embedding-2"]
    assert custom == ["gemini-embedding-2"]
    assert _FakeClient.captured[0]["headers"] == {"x-goog-api-key": "credential"}
    assert _FakeClient.captured[1]["headers"] == {"Authorization": "Bearer credential"}
    assert "url-secret" not in output.getvalue()
    assert "%5BREDACTED%5D" in output.getvalue()


def test_review_panel_redacts_embedding_endpoint_query_key() -> None:
    from deeptutor_cli.init_wizard import EmbeddingChoice, render_review_panel

    output = StringIO()
    console = Console(file=output, force_terminal=False, width=160)
    render_review_panel(
        console,
        {
            "init.review_embedding": "Embedding",
            "init.review_title": "Review",
        },
        llm=None,
        embedding=EmbeddingChoice(
            binding="gemini",
            base_url=("https://proxy.example.com/v1/embeddings?tenant=demo&key=secret"),
            api_key="credential",
            model="gemini-embedding-2",
            dimension="768",
            display_provider="Gemini",
        ),
        search=None,
        backend_port=None,
        frontend_port=None,
    )

    rendered = output.getvalue()
    assert "secret" not in rendered
    assert "%5BREDACTED%5D" in rendered


def test_probe_embedding_uses_gemini_native_request_shape(monkeypatch) -> None:
    from deeptutor_cli import init_wizard

    _FakeClient.captured = []
    monkeypatch.setattr(init_wizard.httpx, "Client", _FakeClient)

    endpoint = (
        "https://generativelanguage.googleapis.com/v1beta/models/"
        "gemini-embedding-2:batchEmbedContents"
    )
    ok, _elapsed_ms, error = init_wizard.probe_embedding(
        base_url=endpoint,
        api_key="credential",
        model="gemini-embedding-2",
        provider="gemini",
    )

    assert ok is True
    assert error == ""
    request = _FakeClient.captured[0]
    assert request["headers"]["x-goog-api-key"] == "credential"
    assert "Authorization" not in request["headers"]
    assert request["json"] == {
        "requests": [
            {
                "model": "models/gemini-embedding-2",
                "content": {"parts": [{"text": "ping"}]},
            }
        ]
    }


def test_probe_embedding_detects_native_custom_url_with_query(monkeypatch) -> None:
    from deeptutor_cli import init_wizard

    _FakeClient.captured = []
    monkeypatch.setattr(init_wizard.httpx, "Client", _FakeClient)

    endpoint = (
        "https://proxy.example.com/google/v1beta/models/"
        "gemini-embedding-2:batchEmbedContents?tenant=demo"
    )
    ok, _elapsed_ms, error = init_wizard.probe_embedding(
        base_url=endpoint,
        api_key="credential",
        model="gemini-embedding-2",
        provider="gemini",
    )

    assert ok is True
    assert error == ""
    request = _FakeClient.captured[0]
    assert request["url"] == endpoint
    assert request["headers"] == {
        "Authorization": "Bearer credential",
        "Content-Type": "application/json",
    }
    assert "requests" in request["json"]


def test_probe_llm_uses_max_completion_tokens_for_gpt5(monkeypatch) -> None:
    from deeptutor_cli import init_wizard

    _FakeClient.captured = []
    monkeypatch.setattr(init_wizard.httpx, "Client", _FakeClient)

    ok, _elapsed_ms, error = init_wizard.probe_llm(
        base_url="https://example.test/v1",
        api_key="sk-test",
        binding="openai",
        model="gpt-5-mini",
    )

    assert ok is True
    assert error == ""
    body = _FakeClient.captured[0]["json"]
    assert body["max_completion_tokens"] == 1
    assert "max_tokens" not in body


def test_probe_llm_keeps_max_tokens_for_legacy_chat_models(monkeypatch) -> None:
    from deeptutor_cli import init_wizard

    _FakeClient.captured = []
    monkeypatch.setattr(init_wizard.httpx, "Client", _FakeClient)

    init_wizard.probe_llm(
        base_url="https://example.test/v1",
        api_key="sk-test",
        binding="openai",
        model="gpt-3.5-turbo",
    )

    body = _FakeClient.captured[0]["json"]
    assert body["max_tokens"] == 1
    assert "max_completion_tokens" not in body


def test_probe_llm_keeps_anthropic_native_max_tokens(monkeypatch) -> None:
    from deeptutor_cli import init_wizard

    _FakeClient.captured = []
    monkeypatch.setattr(init_wizard.httpx, "Client", _FakeClient)

    init_wizard.probe_llm(
        base_url="https://api.anthropic.test/v1",
        api_key="sk-test",
        binding="anthropic",
        model="claude-sonnet-4",
    )

    body = _FakeClient.captured[0]["json"]
    assert body["max_tokens"] == 1
    assert "max_completion_tokens" not in body


def test_wizard_search_providers_match_the_backend_spec_table() -> None:
    """The wizard's own table may add CLI-only detail, never disagree.

    ``deeptutor_cli.init_wizard.SEARCH_PROVIDERS`` carries what only the wizard
    needs (env var names, a default SearXNG URL, one-line hints), but the set of
    providers and which credentials each one needs come from
    ``SEARCH_PROVIDERS`` in the backend spec table. When those drift, the wizard
    writes a profile the runtime then rejects or silently downgrades.
    """
    from deeptutor.services.config.provider_runtime import SEARCH_PROVIDERS as BACKEND
    from deeptutor_cli.init_wizard import SEARCH_PROVIDERS as WIZARD

    wizard = {spec.name: spec for spec in WIZARD}
    assert set(wizard) == set(BACKEND)
    for name, spec in BACKEND.items():
        assert wizard[name].requires_api_key == spec.requires_api_key, name
        assert wizard[name].requires_base_url == spec.requires_base_url, name
