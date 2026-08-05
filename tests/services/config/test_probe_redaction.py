"""FT-05: probe-failure redaction (MOD-01).

Provider backends echo the failing request — an Authorization header, a Bearer
token, an API key — into exception text. ``sanitize_probe_message`` is the
single scrub point for capability-probe failures; these tests prove the
redaction happens before a secret can reach the stored catalog, the SSE event
stream, or the browser-safe ``redact_catalog`` payload.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from deeptutor.services.config.model_catalog import (
    ModelCatalogService,
    redact_catalog,
    sanitize_probe_message,
)

# Representative credential material providers echo back in error text:
# an OpenAI key, an Anthropic key, a Bearer token, an Authorization header,
# and an explicit api-key header. Each sample pairs the raw text with the
# actual secret token that must never survive redaction.
LEAK_SAMPLES: list[tuple[str, str]] = [
    ("401 Invalid API key sk-abc123def456ghi789 provided", "sk-abc123def456ghi789"),
    (
        "authentication_error: sk-ant-api03-abc123def456ghi789jkl is invalid",
        "sk-ant-api03-abc123def456ghi789jkl",
    ),
    ("Access denied for Bearer sk-abc123def456ghi789", "sk-abc123def456ghi789"),
    ("Authorization: Bearer sk-abc123def456ghi789 was rejected", "sk-abc123def456ghi789"),
    ("x-api-key: sk-abc123def456ghi789 is not allowed", "sk-abc123def456ghi789"),
    ("api_key = abcdef1234567890 failed quota check", "abcdef1234567890"),
    ("x-goog-api-key=AIzaSyBlaHBlahBlaH1234567890 denied", "AIzaSyBlaHBlahBlaH1234567890"),
]


def test_sanitize_probe_message_redacts_all_secret_shapes() -> None:
    for message, secret in LEAK_SAMPLES:
        safe = sanitize_probe_message(message)
        assert "[REDACTED]" in safe, f"no redaction marker for: {message!r}"
        # The credential token itself never survives redaction.
        assert secret not in safe, f"secret leaked in: {safe!r}"
    # No `sk-` shaped material survives any sample.
    assert all("sk-" not in sanitize_probe_message(m) for m, _ in LEAK_SAMPLES)


def test_sanitize_probe_message_preserves_benign_text() -> None:
    message = "Connection refused to https://api.example.com/v1 (timeout after 30s)"
    assert sanitize_probe_message(message) == message
    assert sanitize_probe_message("") == ""
    assert sanitize_probe_message(None) == ""


def test_sanitize_probe_message_handles_duplicate_material() -> None:
    message = "sk-abc123def456ghi789 and sk-xyz9876543210 failed; retry sk-abc123def456ghi789"
    safe = sanitize_probe_message(message)
    assert safe.count("[REDACTED]") == 3
    assert "sk-" not in safe


def test_redact_catalog_scrubs_stored_probe_message(tmp_path) -> None:
    """The browser-safe catalog must scrub a stored probe message that somehow
    carried credential material."""
    catalog = _llm_catalog()
    profile = catalog["services"]["llm"]["profiles"][0]
    profile["capability_probe_status"] = "failed"
    profile["capability_probe_message"] = LEAK_SAMPLES[3]

    redacted = redact_catalog(catalog)

    echoed = redacted["services"]["llm"]["profiles"][0]
    assert echoed["api_key"] == ""
    assert echoed["api_key_set"] is True
    assert "[REDACTED]" in echoed["capability_probe_message"]
    assert "sk-abc123" not in echoed["capability_probe_message"]
    # Original catalog untouched.
    assert profile["api_key"] == "sk-test"


def _llm_catalog() -> dict[str, Any]:
    return {
        "version": 1,
        "services": {
            "llm": {
                "active_profile_id": "llm-p",
                "active_model_id": "llm-m",
                "profiles": [
                    {
                        "id": "llm-p",
                        "name": "LLM",
                        "binding": "openai",
                        "base_url": "https://api.example.com/v1",
                        "api_key": "sk-test",
                        "api_version": "",
                        "extra_headers": {},
                        "api_protocol": "auto",
                        "strict_protocol": False,
                        "capability_probe_status": "unknown",
                        "capability_probe_at": "",
                        "capability_probe_message": "",
                        "models": [{"id": "llm-m", "name": "m", "model": "gpt-4o"}],
                    }
                ],
            }
        },
    }


def test_run_sync_llm_failure_redacts_sse_and_persisted_probe_message(
    tmp_path, monkeypatch
) -> None:
    """A failed LLM probe must emit a redacted SSE ``failed`` event, persist a
    redacted ``capability_probe_message``, and return a browser-safe catalog
    event — never the raw provider error text."""
    from deeptutor.services.config import test_runner as test_runner_module
    from deeptutor.services.config.test_runner import ConfigTestRunner, TestRun

    catalog = _llm_catalog()
    service = ModelCatalogService(path=tmp_path / "model_catalog.json")
    service.save(catalog)

    async def _boom(self, run: TestRun, catalog: dict[str, Any]) -> None:
        raise RuntimeError(
            "Provider 401: Authorization: Bearer sk-ant-api03-secret1234567890 failed "
            "with x-api-key: sk-otherkey9999"
        )

    monkeypatch.setattr(test_runner_module, "get_model_catalog_service", lambda: service)
    monkeypatch.setattr(ConfigTestRunner, "_test_llm", _boom)

    runner = ConfigTestRunner()
    run = TestRun(id="llm-fail", service="llm")
    runner._run_sync(run, catalog)

    assert run.status == "failed"

    failed = next(event for event in run.events if event["type"] == "failed")
    assert "[REDACTED]" in failed["message"]
    assert "sk-ant-api03" not in failed["message"]
    assert "sk-otherkey" not in failed["message"]

    # Persisted probe message is redacted in the stored catalog.
    stored_profile = service.load()["services"]["llm"]["profiles"][0]
    assert stored_profile["capability_probe_status"] == "failed"
    assert "[REDACTED]" in stored_profile["capability_probe_message"]
    assert "sk-ant-api03" not in stored_profile["capability_probe_message"]

    # The catalog event is browser-safe: secret stripped + message scrubbed.
    catalog_event = next(event for event in run.events if event["type"] == "catalog")
    echoed = catalog_event["catalog"]["services"]["llm"]["profiles"][0]
    assert echoed["api_key"] == ""
    assert echoed["api_key_set"] is True
    assert "[REDACTED]" in echoed["capability_probe_message"]
    assert "sk-ant-api03" not in echoed["capability_probe_message"]

    # No event in the whole SSE stream carries credential material.
    assert "sk-ant-api03" not in json.dumps(run.events)
    assert "sk-otherkey" not in json.dumps(run.events)


def test_run_sync_llm_failure_keeps_api_key_out_of_config_event(tmp_path, monkeypatch) -> None:
    """Even before the probe runs, the config event masks the api_key."""
    from deeptutor.services.config import test_runner as test_runner_module
    from deeptutor.services.config.test_runner import ConfigTestRunner, TestRun

    catalog = _llm_catalog()
    service = ModelCatalogService(path=tmp_path / "model_catalog.json")
    service.save(catalog)

    async def _boom(self, run: TestRun, catalog: dict[str, Any]) -> None:
        raise RuntimeError("boom")

    monkeypatch.setattr(test_runner_module, "get_model_catalog_service", lambda: service)
    monkeypatch.setattr(ConfigTestRunner, "_test_llm", _boom)

    runner = ConfigTestRunner()
    run = TestRun(id="llm-fail-config", service="llm")
    runner._run_sync(run, catalog)

    config_event = next(event for event in run.events if event["type"] == "config")
    assert "sk-test" not in config_event["profile"]["api_key"]
    assert config_event["profile"]["api_key"] in {"****", "(empty)"}
