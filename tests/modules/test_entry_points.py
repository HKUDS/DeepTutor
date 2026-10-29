"""Official module entries work in source installs without bypassing plugin gates."""

from types import SimpleNamespace

import pytest

from deeptutor.modules import catalog
from deeptutor.plugins import entry_points
from deeptutor.reading.extensions import ReadingExtensionRegistry
from deeptutor.reading.read_aloud import ReadAloudExtension


@pytest.fixture(autouse=True)
def isolated_modules(monkeypatch):
    monkeypatch.setattr(catalog, "source_checkout", lambda: True)
    monkeypatch.setattr(catalog, "selection", lambda: {})
    monkeypatch.setattr(entry_points, "entry_points", lambda **_kwargs: [])


def test_source_reading_extensions_do_not_need_installed_wheel_metadata():
    assert {extension.manifest.id for extension in ReadingExtensionRegistry().all()} == {
        "read_aloud",
        "guided_learning",
        "vocabulary",
        "quiz",
        "translation",
    }


def test_wheel_environment_does_not_invent_missing_entry_points(monkeypatch):
    monkeypatch.setattr(catalog, "source_checkout", lambda: False)
    monkeypatch.setattr(catalog, "module_enabled", lambda _name: True)
    assert ReadingExtensionRegistry().all() == []


def test_disabled_module_never_imports_its_packaged_extension(monkeypatch):
    monkeypatch.setattr(catalog, "selection", lambda: {"reading": False})
    ep = SimpleNamespace(
        name="read_aloud",
        value="deeptutor.reading.read_aloud:ReadAloudExtension",
        load=lambda: pytest.fail("Disabled module extension was imported"),
    )
    monkeypatch.setattr(entry_points, "entry_points", lambda **_kwargs: [ep])
    assert ReadingExtensionRegistry().all() == []


def test_source_and_wheel_metadata_load_each_extension_once(monkeypatch):
    calls = []

    def load():
        calls.append("read_aloud")
        return ReadAloudExtension

    ep = SimpleNamespace(
        name="read_aloud",
        value="deeptutor.reading.read_aloud:ReadAloudExtension",
        load=load,
    )
    monkeypatch.setattr(entry_points, "entry_points", lambda **_kwargs: [ep])
    assert len(ReadingExtensionRegistry().all()) == 5
    assert calls == ["read_aloud"]
