from __future__ import annotations

import importlib.util
import locale
from pathlib import Path
import shutil
import sys
import types
from unittest import mock


def _load_start_tour_module():
    module_path = Path(__file__).resolve().parents[2] / "scripts" / "start_tour.py"

    cli_kit = types.ModuleType("_cli_kit")
    for name in (
        "accent",
        "banner",
        "bold",
        "confirm",
        "countdown",
        "dim",
        "log_error",
        "log_info",
        "log_success",
        "log_warn",
        "select",
        "step",
        "text_input",
    ):
        setattr(cli_kit, name, lambda *args, **kwargs: None)

    deeptutor_pkg = types.ModuleType("deeptutor")
    services_pkg = types.ModuleType("deeptutor.services")
    config_module = types.ModuleType("deeptutor.services.config")
    config_module.get_config_test_runner = lambda: None
    config_module.get_env_store = lambda: None
    config_module.get_model_catalog_service = lambda: None

    original_modules = {
        "_cli_kit": sys.modules.get("_cli_kit"),
        "deeptutor": sys.modules.get("deeptutor"),
        "deeptutor.services": sys.modules.get("deeptutor.services"),
        "deeptutor.services.config": sys.modules.get("deeptutor.services.config"),
    }

    services_pkg.config = config_module
    deeptutor_pkg.services = services_pkg
    sys.modules["_cli_kit"] = cli_kit
    sys.modules["deeptutor"] = deeptutor_pkg
    sys.modules["deeptutor.services"] = services_pkg
    sys.modules["deeptutor.services.config"] = config_module

    try:
        spec = importlib.util.spec_from_file_location("start_tour_under_test", module_path)
        assert spec and spec.loader
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        for module_name, original_module in original_modules.items():
            if original_module is None:
                sys.modules.pop(module_name, None)
            else:
                sys.modules[module_name] = original_module


def test_stream_text_kwargs_use_best_effort_decoding() -> None:
    start_tour = _load_start_tour_module()

    kwargs = start_tour._stream_text_kwargs()

    assert kwargs["text"] is True
    assert kwargs["errors"] == "replace"
    assert kwargs["encoding"] == locale.getpreferredencoding(False)


# ---------------------------------------------------------------------------
# _resolve_python tests (issue #289 — Python 3.14+ compatibility)
# ---------------------------------------------------------------------------

def _get_resolve_python():
    """Import _resolve_python without triggering full module load."""
    start_tour = _load_start_tour_module()
    return start_tour._resolve_python


class TestResolvePython:
    """Verify _resolve_python handles broken sys.executable gracefully."""

    def test_returns_resolved_path_when_executable_exists(self) -> None:
        resolve = _get_resolve_python()
        real_python = sys.executable
        with mock.patch("sys.executable", real_python):
            result = resolve()
        assert Path(result).exists()

    def test_falls_back_to_shutil_which_when_executable_missing(self) -> None:
        """Simulates Python 3.14+ on Windows where sys.executable is bogus."""
        resolve = _get_resolve_python()
        fake_path = "/nonexistent/python3.14"
        expected = shutil.which("python3") or shutil.which("python") or "python3"
        with mock.patch("sys.executable", fake_path):
            result = resolve()
        assert result == expected

    def test_falls_back_when_executable_is_empty(self) -> None:
        """sys.executable can be '' in embedded or frozen environments."""
        resolve = _get_resolve_python()
        expected = shutil.which("python3") or shutil.which("python") or "python3"
        with mock.patch("sys.executable", ""):
            result = resolve()
        assert result == expected

    def test_ultimate_fallback_when_nothing_found(self) -> None:
        """If sys.executable is empty and PATH has no python, return 'python3'."""
        resolve = _get_resolve_python()
        with (
            mock.patch("sys.executable", ""),
            mock.patch("shutil.which", return_value=None),
        ):
            result = resolve()
        assert result == "python3"

    def test_preserves_valid_sys_executable(self) -> None:
        """Normal case: sys.executable points to a real file."""
        resolve = _get_resolve_python()
        result = resolve()
        assert Path(result).exists()
        assert "python" in Path(result).name.lower()

    def test_install_commands_use_resolved_python(self) -> None:
        """_install_commands should embed _PYTHON, not raw sys.executable."""
        start_tour = _load_start_tour_module()
        python_used = start_tour._PYTHON
        catalog: dict = {"services": {}}
        cmds = start_tour._install_commands("cli-core", catalog)
        for cmd, _cwd in cmds:
            if cmd[0] != "npm":
                assert cmd[0] == python_used, (
                    f"Expected resolved python {python_used!r}, got {cmd[0]!r}"
                )
