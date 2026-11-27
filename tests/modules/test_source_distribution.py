"""Source exports and Docker retain modules without Git or wheel metadata."""

from importlib.metadata import PackageNotFoundError

from deeptutor.modules import catalog


def test_exported_source_enables_modules_without_git(tmp_path, monkeypatch):
    (tmp_path / "pyproject.toml").touch()
    (tmp_path / "scripts").mkdir()
    (tmp_path / "scripts/build_modules.py").touch()
    monkeypatch.setattr(catalog, "__file__", str(tmp_path / "deeptutor/modules/catalog.py"))
    monkeypatch.setattr(catalog, "selection", lambda: {})

    def no_wheel(name):
        raise PackageNotFoundError(name)

    monkeypatch.setattr(catalog.metadata, "distribution", no_wheel)
    catalog.source_checkout.cache_clear()
    try:
        assert catalog.source_checkout()
        assert all(catalog.module_enabled(name) for name in catalog.manifests())
        assert not catalog.module_enabled("server", selected={"server": False})
        # A wheel installation must still require actual distribution metadata.
        (tmp_path / "scripts/build_modules.py").unlink()
        catalog.source_checkout.cache_clear()
        assert not catalog.source_checkout()
        assert not catalog.installed("server")
    finally:
        catalog.source_checkout.cache_clear()
