from __future__ import annotations

from unittest.mock import patch
import pytest

from deeptutor.services.config.provider_runtime import ResolvedLLMConfig
from deeptutor.services.config.settings_spec import (
    _LANGUAGE_CHOICES,
    _RESPONSE_LANGUAGE_CHOICES,
)
from deeptutor.services.courses import _parse_syllabus
from scripts.docker_compose import _compose_command


def test_resolved_llm_config_api_key_helper():
    cfg = ResolvedLLMConfig(
        model="test-model",
        provider_name="custom",
        provider_mode="api",
        api_key="secret-key-123",
        base_url="https://api.example.com",
    )
    assert cfg.get_api_key() == "secret-key-123"
    assert cfg.temperature == 0.7
    assert cfg.max_tokens == 4096

    empty_cfg = ResolvedLLMConfig(
        model="test-model",
        provider_name="custom",
        provider_mode="api",
        base_url="https://api.example.com",
    )
    assert empty_cfg.get_api_key() == ""


def test_settings_spec_includes_vietnamese():
    ui_langs = [choice[0] for choice in _LANGUAGE_CHOICES]
    assert "vi" in ui_langs
    vi_ui = next(choice for choice in _LANGUAGE_CHOICES if choice[0] == "vi")
    assert vi_ui[1] == "Tiếng Việt"

    resp_langs = [choice[0] for choice in _RESPONSE_LANGUAGE_CHOICES]
    assert "vi" in resp_langs
    vi_resp = next(choice for choice in _RESPONSE_LANGUAGE_CHOICES if choice[0] == "vi")
    assert vi_resp[1] == "Tiếng Việt"


def test_parse_syllabus_supports_long_topic_names():
    long_topic = "This is a detailed topic name that exceeds eighty characters in length to verify the new maximum limit"
    raw = [
        {
            "position": 1,
            "title": "Unit 1",
            "topics": [long_topic],
        }
    ]
    parsed = _parse_syllabus(raw)
    assert len(parsed) == 1
    assert parsed[0].topics[0] == long_topic


def test_docker_compose_command_default_file_flags():
    with patch("shutil.which", return_value="/usr/bin/docker"):
        cmd = _compose_command(["up", "-d"])
        assert "-f" in cmd
        assert "docker-compose.yml" in cmd
        assert "up" in cmd
        assert "-d" in cmd

        # Custom -f flag should not be duplicated
        cmd_custom = _compose_command(["-f", "custom.yml", "up"])
        assert cmd_custom.count("-f") == 1
        assert "custom.yml" in cmd_custom
        assert "docker-compose.yml" not in cmd_custom
