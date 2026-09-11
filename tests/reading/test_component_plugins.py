import io
import json
import zipfile

import pytest

from deeptutor.reading import component_plugins as plugins


def wheel(slot="vocabulary", namespace="deeptutor_reading_test", bad=None):
    buffer = io.BytesIO()
    folder = namespace + "-0.2.0.dist-info"
    with zipfile.ZipFile(buffer, "w") as archive:
        archive.writestr(
            folder + "/METADATA",
            f"Name: {namespace}\nVersion: 0.2.0\nRequires-Python: >=3.11\nRequires-Dist: deeptutor>=1.6.4,<2\n",
        )
        archive.writestr(folder + "/WHEEL", "Tag: py3-none-any\n")
        archive.writestr(
            folder + "/entry_points.txt",
            f"[deeptutor.reading_extensions]\n{slot} = {namespace}.provider:Provider",
        )
        archive.writestr(
            namespace + "/reading_plugin.json",
            json.dumps({"protocol": "1", "name": "Test provider"}),
        )
        archive.writestr(
            namespace + "/provider.py", "raise RuntimeError('installation must not execute code')"
        )
        if bad:
            archive.writestr(bad, "bad")
    return buffer.getvalue()


@pytest.fixture(autouse=True)
def isolated(monkeypatch, tmp_path):
    monkeypatch.setattr(plugins, "root", lambda: tmp_path / "providers")
    monkeypatch.setattr(plugins, "ACTIVE", {"packages": {}, "providers": {}})


def test_independent_install_select_and_remove():
    installed = plugins.install(wheel())
    assert installed["desired"]["providers"] == {}
    assert installed["active"]["packages"] == {}
    selected = plugins.select("vocabulary", "deeptutor-reading-test")
    assert selected["restart_required"]
    assert selected["desired"]["providers"] == {"vocabulary": "deeptutor-reading-test"}
    assert plugins.uninstall("deeptutor-reading-test")["desired"] == plugins.DEFAULT


def test_other_action_types_can_be_installed():
    plugins.install(wheel(slot="anki_export"))
    assert (
        plugins.select("anki_export", "deeptutor-reading-test")["desired"]["providers"][
            "anki_export"
        ]
        == "deeptutor-reading-test"
    )
    with pytest.raises(ValueError):
        plugins.select("quiz", "deeptutor-reading-test")


@pytest.mark.parametrize(
    "bad", ["../escape.py", "deeptutor/__init__.py", "deeptutor_reading_test/native.so"]
)
def test_rejects_invalid_provider_without_changing_state(bad):
    with pytest.raises(ValueError):
        plugins.install(wheel(bad=bad))
    assert plugins.read_state() == plugins.DEFAULT


def test_failed_selected_provider_is_isolated(monkeypatch):
    plugins.install(wheel())
    plugins.select("vocabulary", "deeptutor-reading-test")
    monkeypatch.setattr(plugins, "ACTIVE", plugins.read_state())
    overrides, blocked = plugins.load()
    assert overrides == {}
    assert blocked == {"vocabulary"}
    assert "vocabulary" in plugins.status()["errors"]


def test_uninstall_one_package_retains_other_choices():
    plugins.install(wheel())
    plugins.install(wheel(slot="quiz", namespace="deeptutor_reading_other"))
    plugins.select("vocabulary", "deeptutor-reading-test")
    plugins.select("quiz", "deeptutor-reading-other")
    state = plugins.uninstall("deeptutor-reading-test")["desired"]
    assert list(state["packages"]) == ["deeptutor-reading-other"]
    assert state["providers"] == {"quiz": "deeptutor-reading-other"}
