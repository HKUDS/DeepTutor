from __future__ import annotations

import importlib.util
from pathlib import Path
from unittest import mock


def _load_module():
    module_path = Path(__file__).resolve().parents[2] / "scripts" / "start_web.py"
    spec = importlib.util.spec_from_file_location("start_web_under_test", module_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_start_web_parser_supports_home(tmp_path: Path) -> None:
    start_web = _load_module()
    args = start_web.build_parser().parse_args(["--home", str(tmp_path)])

    assert args.home == tmp_path


def test_start_web_delegates_to_runtime_launcher(tmp_path: Path) -> None:
    start_web = _load_module()
    with mock.patch.object(start_web, "start") as start:
        start_web.main(["--home", str(tmp_path)])

    start.assert_called_once_with(home=tmp_path)
