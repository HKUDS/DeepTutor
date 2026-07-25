from deeptutor.update import InstallMode, detect_current_installation


def test_current_checkout_is_detected_as_an_editable_full_installation() -> None:
    installation = detect_current_installation()

    assert installation.mode is InstallMode.SOURCE_WEB
    assert installation.package_name == "deeptutor"
    assert installation.source_root is not None
    assert (installation.source_root / "pyproject.toml").is_file()
