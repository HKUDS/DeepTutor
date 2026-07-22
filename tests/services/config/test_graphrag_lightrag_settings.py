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


def test_response_type_capped(tmp_path: Path) -> None:
    svc = RuntimeSettingsService(tmp_path, process_env={})
    saved = svc.save_graphrag({"response_type": "x" * 500})
    assert len(saved["response_type"]) == 80


def test_preflight_shape_for_all_engines() -> None:
    from deeptutor.services.rag.preflight import engine_preflight

    for provider in ("llamaindex", "pageindex", "graphrag", "lightrag"):
        report = engine_preflight(provider)
        assert set(report) == {"ok", "checks"}
        assert isinstance(report["ok"], bool)
        assert report["checks"], f"{provider} should report at least one check"
        for check in report["checks"]:
            assert set(check) == {"key", "label", "ok", "detail", "optional"}
        # Overall ok ignores optional checks.
        required_ok = all(c["ok"] for c in report["checks"] if not c["optional"])
        assert report["ok"] == required_ok


def test_preflight_unknown_provider_falls_back_to_default() -> None:
    from deeptutor.services.rag.preflight import engine_preflight

    # Unknown providers normalize to the default (llamaindex) engine.
    report = engine_preflight("does-not-exist")
    assert any(c["key"] == "embedding" for c in report["checks"])
