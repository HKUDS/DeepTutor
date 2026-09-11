"""A draft is somewhere the runtime does not look."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from deeptutor.services.config.model_catalog import CATALOG_SECRET_MASK
from deeptutor.services.config.settings_draft import (
    SettingsDraftService,
    is_empty_draft,
    merge_draft_secrets,
    redact_draft,
)


def _service(tmp_path: Path) -> SettingsDraftService:
    return SettingsDraftService(path=tmp_path / "settings_draft.json")


def _catalog(api_key: str) -> dict[str, Any]:
    return {
        "version": 1,
        "connections": [],
        "services": {
            "llm": {
                "active_profile_id": "p1",
                "active_model_id": "m1",
                "profiles": [
                    {
                        "id": "p1",
                        "name": "OpenAI",
                        "api_key": api_key,
                        "models": [{"id": "m1", "model": "gpt-5"}],
                    }
                ],
            }
        },
    }


def test_missing_file_reads_as_an_empty_draft(tmp_path: Path) -> None:
    assert is_empty_draft(_service(tmp_path).load())


def test_a_corrupt_draft_does_not_take_the_page_down(tmp_path: Path) -> None:
    service = _service(tmp_path)
    service.path.parent.mkdir(parents=True, exist_ok=True)
    service.path.write_text("{ not json", encoding="utf-8")

    assert is_empty_draft(service.load())


def test_saving_records_both_halves_and_a_timestamp(tmp_path: Path) -> None:
    service = _service(tmp_path)

    saved = service.save(
        {"catalog": _catalog("sk-live"), "extensions": {"chat-starters": {"trace_count": 44}}}
    )

    assert saved["extensions"]["chat-starters"] == {"trace_count": 44}
    assert saved["updated_at"]
    reloaded = service.load()
    assert reloaded["extensions"] == saved["extensions"]


def test_redaction_masks_the_catalog_half(tmp_path: Path) -> None:
    service = _service(tmp_path)
    saved = service.save({"catalog": _catalog("sk-live"), "extensions": {}})

    redacted = redact_draft(saved)

    profile = redacted["catalog"]["services"]["llm"]["profiles"][0]
    assert profile["api_key"] == CATALOG_SECRET_MASK
    # The stored copy is untouched — redaction is for the wire only.
    assert service.load()["catalog"]["services"]["llm"]["profiles"][0]["api_key"] == "sk-live"


def test_a_key_typed_only_into_a_draft_survives_re_saving_it(tmp_path: Path) -> None:
    """The placeholder has to resolve against the draft, not just the live file."""
    service = _service(tmp_path)
    stored = service.save({"catalog": _catalog("sk-drafted"), "extensions": {}})
    # What the browser sends back after a round trip: everything masked.
    proposed = redact_draft(stored)
    proposed["catalog"]["services"]["llm"]["profiles"][0]["name"] = "Renamed"

    merged = merge_draft_secrets(proposed, stored, _catalog("sk-live"))

    profile = merged["catalog"]["services"]["llm"]["profiles"][0]
    assert profile["api_key"] == "sk-drafted"
    assert profile["name"] == "Renamed"


def test_an_untouched_key_still_falls_back_to_the_live_catalog(tmp_path: Path) -> None:
    service = _service(tmp_path)
    proposed = redact_draft({"catalog": _catalog(CATALOG_SECRET_MASK), "extensions": {}})

    merged = merge_draft_secrets(proposed, service.load(), _catalog("sk-live"))

    assert merged["catalog"]["services"]["llm"]["profiles"][0]["api_key"] == "sk-live"


def test_clearing_removes_the_file(tmp_path: Path) -> None:
    service = _service(tmp_path)
    service.save({"catalog": _catalog("sk-live"), "extensions": {}})

    service.clear()

    assert not service.path.exists()
    assert is_empty_draft(service.load())
