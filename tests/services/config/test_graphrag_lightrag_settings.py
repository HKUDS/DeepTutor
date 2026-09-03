"""GraphRAG + LightRAG engine knobs stored in RuntimeSettingsService."""

from __future__ import annotations

from pathlib import Path

from deeptutor.services.config.runtime_settings import RuntimeSettingsService


def test_graphrag_defaults_and_clamp(tmp_path: Path) -> None:
    svc = RuntimeSettingsService(tmp_path, process_env={})
    defaults = svc.load_graphrag()
    assert defaults["response_type"] == "Multiple Paragraphs"
    assert defaults["community_level"] == 2
    assert defaults["dynamic_community_selection"] is False

    saved = svc.save_graphrag(
        {
            "community_level": 99,
            "dynamic_community_selection": "yes",
            "response_type": "  Single Paragraph  ",
        }
    )
    assert saved["community_level"] == 5  # clamped to max
    assert saved["dynamic_community_selection"] is True
    assert saved["response_type"] == "Single Paragraph"
    assert (tmp_path / "graphrag.json").exists()


def test_lightrag_defaults_and_clamp(tmp_path: Path) -> None:
    svc = RuntimeSettingsService(tmp_path, process_env={})
    defaults = svc.load_lightrag()
    assert defaults["top_k"] == 60
    assert defaults["response_type"] == "Multiple Paragraphs"

    saved = svc.save_lightrag({"top_k": 9999})
    assert saved["top_k"] == 200  # clamped to max
    assert (tmp_path / "lightrag.json").exists()

    floored = svc.save_lightrag({"top_k": 0})
    assert floored["top_k"] == 1  # clamped to min


def test_lightrag_indexing_knobs_round_trip_and_clamp(tmp_path: Path) -> None:
    """The indexing knobs the settings UI edits, with the ranges it offers.

    The NumberField min/max in EngineDetail's LightRAG form mirror these
    clamps, so a value the UI accepts is a value the service keeps.
    """
    svc = RuntimeSettingsService(tmp_path, process_env={})
    defaults = svc.load_lightrag()
    assert defaults["max_concurrent_files"] == 1
    assert defaults["llm_model_max_async"] == 4
    assert defaults["entity_extract_max_gleaning"] == 1
    assert defaults["llm_profile_id"] == ""
    assert defaults["llm_model_id"] == ""

    saved = svc.save_lightrag(
        {
            "max_concurrent_files": 4,
            "llm_model_max_async": 8,
            "entity_extract_max_gleaning": 0,
        }
    )
    assert saved["max_concurrent_files"] == 4
    assert saved["llm_model_max_async"] == 8
    assert saved["entity_extract_max_gleaning"] == 0

    clamped = svc.save_lightrag(
        {
            "max_concurrent_files": 999,
            "llm_model_max_async": 0,
            "entity_extract_max_gleaning": 99,
        }
    )
    assert clamped["max_concurrent_files"] == 16
    assert clamped["llm_model_max_async"] == 1
    assert clamped["entity_extract_max_gleaning"] == 5
    # Editing one knob must not reset the query knobs beside it.
    assert clamped["top_k"] == 60
    assert clamped["response_type"] == "Multiple Paragraphs"


def test_lightrag_dedicated_llm_selection_round_trip(tmp_path: Path) -> None:
    """Empty references mean the global model; a complete pair is preserved."""
    svc = RuntimeSettingsService(tmp_path, process_env={})
    assert svc.load_lightrag()["llm_profile_id"] == ""

    saved = svc.save_lightrag({"llm_profile_id": " profile-1 ", "llm_model_id": " model-1 "})
    assert saved["llm_profile_id"] == "profile-1"
    assert saved["llm_model_id"] == "model-1"

    cleared = svc.save_lightrag({"llm_profile_id": "", "llm_model_id": ""})
    assert cleared["llm_profile_id"] == ""
    assert cleared["llm_model_id"] == ""


def test_lightrag_settings_written_before_the_indexing_knobs_still_load(
    tmp_path: Path,
) -> None:
    """A lightrag.json from before these knobs existed gets the defaults."""
    (tmp_path / "lightrag.json").write_text(
        '{"version": 1, "top_k": 25, "response_type": "Single Paragraph"}',
        encoding="utf-8",
    )
    loaded = RuntimeSettingsService(tmp_path, process_env={}).load_lightrag()
    assert loaded["top_k"] == 25
    assert loaded["max_concurrent_files"] == 1
    assert loaded["llm_model_max_async"] == 4
    assert loaded["entity_extract_max_gleaning"] == 1
    assert loaded["llm_profile_id"] == ""
    assert loaded["llm_model_id"] == ""


def test_lightrag_server_defaults_round_trip_without_exposing_shape_drift(
    tmp_path: Path,
) -> None:
    svc = RuntimeSettingsService(tmp_path, process_env={})
    assert svc.load_lightrag_server() == {
        "version": 1,
        "server_url": "",
        "api_key": "",
    }

    saved = svc.save_lightrag_server(
        {"server_url": " http://localhost:9621/ ", "api_key": " secret "}
    )
    assert saved == {
        "version": 1,
        "server_url": "http://localhost:9621",
        "api_key": "secret",
    }
    assert (tmp_path / "lightrag_server.json").exists()


def test_response_type_capped(tmp_path: Path) -> None:
    svc = RuntimeSettingsService(tmp_path, process_env={})
    saved = svc.save_graphrag({"response_type": "x" * 500})
    assert len(saved["response_type"]) == 80


def test_preflight_shape_for_all_engines() -> None:
    from deeptutor.services.rag.preflight import engine_preflight

    for provider in (
        "llamaindex",
        "pageindex",
        "graphrag",
        "lightrag",
        "lightrag-server",
    ):
        report = engine_preflight(provider)
        assert set(report) == {"ok", "checks"}
        assert isinstance(report["ok"], bool)
        assert report["checks"], f"{provider} should report at least one check"
        for check in report["checks"]:
            assert set(check) == {"key", "label", "ok", "detail", "optional"}
        # Overall ok ignores optional checks.
        required_ok = all(c["ok"] for c in report["checks"] if not c["optional"])
        assert report["ok"] == required_ok


def test_graphrag_static_preflight_does_not_guess_structured_output_support(
    monkeypatch,
) -> None:
    from deeptutor.services.rag import preflight
    from deeptutor.services.rag.pipelines.graphrag import config as graphrag_config

    monkeypatch.setattr(graphrag_config, "is_graphrag_available", lambda: True)
    monkeypatch.setattr(preflight, "_active_chat_model", lambda: ("deepseek-v4-flash", "deepseek"))
    monkeypatch.setattr(preflight, "_active_embedding", lambda: ("text-embedding", 1024))

    report = preflight.engine_preflight("graphrag")
    assert all(check["key"] != "structured_output" for check in report["checks"])
    assert report["ok"] is True


def test_preflight_unknown_provider_falls_back_to_default() -> None:
    from deeptutor.services.rag.preflight import engine_preflight

    # Unknown providers normalize to the default (llamaindex) engine.
    report = engine_preflight("does-not-exist")
    assert any(c["key"] == "embedding" for c in report["checks"])
