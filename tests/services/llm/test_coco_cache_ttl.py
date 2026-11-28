"""CoCo fork: switchable Anthropic prompt-cache TTL."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from deeptutor.services.llm.provider_core import coco_cache_ttl as ttl_mod
from deeptutor.services.llm.provider_core.anthropic_provider import AnthropicProvider


@pytest.fixture(autouse=True)
def _isolated(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    monkeypatch.delenv(ttl_mod.ENV_VAR, raising=False)
    monkeypatch.setattr(ttl_mod, "_settings_dir", lambda: tmp_path)
    ttl_mod._cache.clear()
    return tmp_path


def _write(directory: Path, payload: object) -> None:
    (directory / ttl_mod.SETTINGS_FILE).write_text(json.dumps(payload), encoding="utf-8")


def test_default_is_upstream_marker_without_ttl(_isolated: Path) -> None:
    assert ttl_mod.anthropic_cache_marker() == {"type": "ephemeral"}


def test_settings_file_enables_one_hour(_isolated: Path) -> None:
    _write(_isolated, {"anthropic_cache_ttl": "1h"})
    assert ttl_mod.anthropic_cache_marker() == {"type": "ephemeral", "ttl": "1h"}


def test_env_overrides_file(_isolated: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    _write(_isolated, {"anthropic_cache_ttl": "1h"})
    monkeypatch.setenv(ttl_mod.ENV_VAR, "5m")
    assert ttl_mod.anthropic_cache_ttl() == "5m"


@pytest.mark.parametrize("payload", [{"anthropic_cache_ttl": "2h"}, ["1h"], {"other": 1}])
def test_invalid_values_fall_back_to_default(_isolated: Path, payload: object) -> None:
    _write(_isolated, payload)
    assert ttl_mod.anthropic_cache_ttl() == "5m"


def test_broken_json_falls_back(_isolated: Path) -> None:
    (_isolated / ttl_mod.SETTINGS_FILE).write_text("{not json", encoding="utf-8")
    assert ttl_mod.anthropic_cache_ttl() == "5m"


def test_file_change_is_picked_up(_isolated: Path) -> None:
    import os

    _write(_isolated, {"anthropic_cache_ttl": "1h"})
    assert ttl_mod.anthropic_cache_ttl() == "1h"
    _write(_isolated, {"anthropic_cache_ttl": "5m"})
    path = _isolated / ttl_mod.SETTINGS_FILE
    st = path.stat()
    os.utime(path, (st.st_atime, st.st_mtime + 5))
    assert ttl_mod.anthropic_cache_ttl() == "5m"


def test_provider_marks_every_breakpoint_with_the_ttl(_isolated: Path) -> None:
    _write(_isolated, {"anthropic_cache_ttl": "1h"})
    system, msgs, _ = AnthropicProvider._apply_cache_control(
        "system prompt", [{"role": "user", "content": "hi"}], None
    )
    assert system[-1]["cache_control"] == {"type": "ephemeral", "ttl": "1h"}
    assert msgs[-1]["content"][-1]["cache_control"] == {"type": "ephemeral", "ttl": "1h"}
