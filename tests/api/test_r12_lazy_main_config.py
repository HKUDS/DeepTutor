"""R-12 regression: importing a router must not require an initialized runtime home.

Before this fix, ``deeptutor.api.routers.co_writer`` (and the knowledge,
question and quiz_judge routers) called ``load_config_with_main("main.yaml")``
at *module import* time. A checkout that had never run ``deeptutor init``
therefore died with a bare ``FileNotFoundError`` during import — including
inside pytest collection, which is how Phase 0 surfaced it.

The contract these tests lock down:

* importing the router modules is side-effect free and works in a fresh home;
* a code path that genuinely needs ``main.yaml`` raises a *typed*, actionable
  error (:class:`SetupRequiredError`) that names ``deeptutor init``;
* with a valid config the original behaviour is unchanged (the file is read,
  and runtime paths are still injected).
"""

from __future__ import annotations

import importlib
from pathlib import Path
import sys

import pytest

from deeptutor.core.errors import ConfigurationError, SetupRequiredError
from deeptutor.services.config.loader import load_main_config

_AFFECTED_ROUTERS = [
    "deeptutor.api.routers.co_writer",
    "deeptutor.api.routers.knowledge",
    "deeptutor.api.routers.question",
    "deeptutor.api.routers.quiz_judge",
]


def _raise_setup_error() -> dict:
    raise SetupRequiredError("main.yaml", "")


@pytest.fixture()
def fresh_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    """An empty runtime home: no ``data/user/settings/main.yaml`` anywhere."""
    home = tmp_path / "uninitialized-home"
    home.mkdir()
    monkeypatch.setenv("DEEPTUTOR_HOME", str(home))
    return home


def _purge() -> None:
    for name in _AFFECTED_ROUTERS:
        sys.modules.pop(name, None)


def test_router_modules_import_without_an_initialized_home(fresh_home: Path) -> None:
    """Import alone must not touch ``main.yaml``."""
    _purge()
    try:
        for name in _AFFECTED_ROUTERS:
            importlib.import_module(name)
    finally:
        _purge()

    assert not (fresh_home / "data" / "user" / "settings" / "main.yaml").exists()


def test_load_main_config_explains_that_setup_is_required(fresh_home: Path) -> None:
    with pytest.raises(SetupRequiredError) as excinfo:
        load_main_config(fresh_home)

    message = str(excinfo.value)
    assert "deeptutor init" in message
    assert "main.yaml" in message
    # The typed error stays a ConfigurationError so broad handlers keep working.
    assert isinstance(excinfo.value, ConfigurationError)


def test_load_main_config_does_not_invent_defaults(fresh_home: Path) -> None:
    """No silently-created ``main.yaml``: a missing file stays missing."""
    with pytest.raises(SetupRequiredError):
        load_main_config(fresh_home)
    assert not (fresh_home / "data" / "user" / "settings" / "main.yaml").exists()


def test_load_main_config_reads_a_valid_config(tmp_path: Path) -> None:
    settings_dir = tmp_path / "data" / "user" / "settings"
    settings_dir.mkdir(parents=True)
    (settings_dir / "main.yaml").write_text(
        "system:\n  language: fa\nlogging:\n  level: INFO\n", encoding="utf-8"
    )

    config = load_main_config(tmp_path)

    assert config["system"]["language"] == "fa"
    assert config["logging"]["level"] == "INFO"
    # Runtime paths are still injected, exactly like load_config_with_main.
    assert "paths" in config


def test_reply_language_helpers_fall_back_to_english_without_config(
    fresh_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A missing config degrades the default language; it does not raise."""
    from deeptutor.api.routers import question, quiz_judge

    monkeypatch.setattr(question, "load_main_config", lambda: _raise_setup_error())
    monkeypatch.setattr(quiz_judge, "load_main_config", lambda: _raise_setup_error())

    assert question._response_language_default() in {"en", "fa"}
    assert quiz_judge._config_default_language() == "en"


def test_co_writer_current_language_survives_missing_config(
    fresh_home: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from deeptutor.api.routers import co_writer

    monkeypatch.setattr(co_writer, "load_main_config", lambda: _raise_setup_error())

    # The endpoint still answers instead of raising out of the handler.
    assert co_writer._current_language() in {"en", "fa"}
