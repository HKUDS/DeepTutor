"""The banner must not report a version silently when the two disagree.

On a zip install the runtime home keeps the extracted ``deeptutor/`` tree, and
``python -m`` puts that home first on ``sys.path``. A restart then imports the
old checkout while the distribution metadata reports the version pip just
installed (#2443). Before this, the banner printed only the shadowed value, so
a failed upgrade was visually indistinguishable from a successful one.
"""

from __future__ import annotations

import io

import pytest
from rich.console import Console

from deeptutor.runtime import banner


def _render(language: str = "en") -> str:
    stream = io.StringIO()
    # A wide console keeps the tagline off a wrapped line, so the assertions can
    # look for one contiguous string.
    banner.print_banner(
        Console(file=stream, width=200, legacy_windows=False),
        language=language,
        mode_key="start.mode",
    )
    return stream.getvalue()


@pytest.fixture
def installed(monkeypatch: pytest.MonkeyPatch):
    """Return a setter for the version that ``importlib.metadata`` reports."""

    def _set(value: str) -> None:
        monkeypatch.setattr(banner.metadata, "version", lambda _name: value)

    return _set


def test_matching_versions_render_no_warning(installed) -> None:
    installed(banner.__version__)

    assert banner.loaded_version_mismatch() is None
    output = _render()
    assert banner.__version__ in output
    assert "stale source tree" not in output


def test_mismatch_reports_both_versions_and_the_loaded_origin(installed) -> None:
    installed("9.9.9")

    result = banner.loaded_version_mismatch()

    assert result is not None
    loaded, reported, origin = result
    assert loaded == banner.__version__
    assert reported == "9.9.9"
    assert origin.endswith("__init__.py")
    assert "deeptutor" in origin


def test_banner_shows_loaded_version_and_the_installed_one(installed) -> None:
    """The tagline keeps the running version and names the installed one."""

    installed("9.9.9")

    output = _render()

    assert banner.__version__ in output
    assert "9.9.9" in output
    assert "stale source tree" in output


def test_missing_distribution_metadata_is_not_a_mismatch(installed, monkeypatch) -> None:
    """A source checkout with no installed distribution must stay quiet."""

    def _raise(_name: str) -> str:
        raise banner.metadata.PackageNotFoundError

    monkeypatch.setattr(banner.metadata, "version", _raise)

    assert banner.loaded_version_mismatch() is None
    assert "stale source tree" not in _render()


def test_unreadable_metadata_does_not_break_startup(installed, monkeypatch) -> None:
    """The banner is not allowed to be the reason the CLI cannot start."""

    def _explode(_name: str) -> str:
        raise RuntimeError("corrupt dist-info")

    monkeypatch.setattr(banner.metadata, "version", _explode)

    assert banner.loaded_version_mismatch() is None
    assert banner.__version__ in _render()


@pytest.mark.parametrize("language", ["en", "zh", "fr", "de", "uk", "pt", "tr", "unknown"])
def test_every_locale_renders_a_mismatch(installed, language: str) -> None:
    """Untranslated locales fall back to English instead of raising KeyError."""

    installed("9.9.9")

    output = _render(language)

    assert "9.9.9" in output
    assert banner.__version__ in output


def test_chinese_warning_is_localized(installed) -> None:
    installed("9.9.9")

    output = _render("zh")

    assert "已安装" in output


def test_warning_strings_exist_in_english() -> None:
    """Every locale falls back to English, so English must carry both keys."""

    assert banner.LABELS["en"]["version.mismatch"]
    assert banner.LABELS["en"]["version.shadowed.warning"]
