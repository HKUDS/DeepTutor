from __future__ import annotations

import importlib.util
from pathlib import Path
from unittest import mock


def _load_module():
    module_path = Path(__file__).resolve().parents[2] / "scripts" / "start_tour.py"
    spec = importlib.util.spec_from_file_location("start_tour_under_test", module_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_start_tour_parser_supports_cli_and_home(tmp_path: Path) -> None:
    start_tour = _load_module()
    args = start_tour.build_parser().parse_args(["--cli", "--home", str(tmp_path)])

    assert args.cli is True
    assert args.home == tmp_path


def test_start_tour_delegates_to_init_command(tmp_path: Path) -> None:
    start_tour = _load_module()
    with mock.patch.object(start_tour, "run_init") as run_init:
        start_tour.main(["--cli", "--home", str(tmp_path)])

    run_init.assert_called_once_with(cli_only=True, home=tmp_path)
