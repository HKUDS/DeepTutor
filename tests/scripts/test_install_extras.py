"""Tests for the container's declared-extras installer (#762).

The reporter's scenario is the one that matters: extras installed by hand into
a running container vanish on `compose down`, so the deployment declares them
and every start re-applies them — cheaply when they are already there, and
never fatally when they cannot be had.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
import sys

import pytest


def _load():
    module_path = Path(__file__).resolve().parents[2] / "scripts" / "install_extras.py"
    module_name = "install_extras_under_test"
    sys.modules.pop(module_name, None)
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


install_extras = _load()


@pytest.fixture
def pyproject(tmp_path: Path) -> Path:
    path = tmp_path / "pyproject.toml"
    path.write_text(
        "[project.optional-dependencies]\n"
        'math-animator = ["manim>=0.19.0"]\n'
        'matrix-e2e = ["matrix-nio[e2e]>=0.25.2"]\n',
        encoding="utf-8",
    )
    return path


@pytest.mark.parametrize(
    "raw,expected",
    [
        ("a,b", ["a", "b"]),
        ("a, b", ["a", "b"]),
        ("a b", ["a", "b"]),
        ("  a ,, b  ", ["a", "b"]),
        ("a,a,b", ["a", "b"]),
        ("", []),
    ],
)
def test_parse_names_accepts_the_spellings_people_write(raw, expected) -> None:
    """A Compose value is one string; the separator must not be a gotcha."""
    assert install_extras.parse_names(raw) == expected


def test_underscore_and_dash_spellings_resolve_to_the_same_extra(pyproject) -> None:
    extras = install_extras.load_extras(pyproject)

    dashed, _ = install_extras.resolve(extras, ["matrix-e2e"])
    underscored, _ = install_extras.resolve(extras, ["matrix_e2e"])

    assert dashed == underscored == ["matrix-nio[e2e]>=0.25.2"]


def test_unknown_extra_is_reported_without_dropping_the_valid_ones(pyproject) -> None:
    """One typo must not cost the operator the extras they spelled correctly."""
    extras = install_extras.load_extras(pyproject)

    requirements, unknown = install_extras.resolve(extras, ["nope", "math-animator"])

    assert unknown == ["nope"]
    assert requirements == ["manim>=0.19.0"]


def test_satisfied_requirements_are_not_reinstalled() -> None:
    """The warm-container path: already-present packages cost a lookup, not a pip run."""
    assert install_extras.missing_requirements(["pytest"]) == []
    assert install_extras.missing_requirements(["pytest>=9999"]) == ["pytest>=9999"]
    assert install_extras.missing_requirements(["definitely-not-a-real-package"]) == [
        "definitely-not-a-real-package"
    ]


def test_requirements_for_other_platforms_are_skipped() -> None:
    """An environment marker that excludes this interpreter is not 'missing'."""
    assert install_extras.missing_requirements(['nonexistent-pkg; python_version < "3.0"']) == []


def test_unparseable_requirement_is_left_for_pip_to_judge() -> None:
    assert install_extras.missing_requirements(["=not a requirement="]) == ["=not a requirement="]


def test_dry_run_installs_nothing(pyproject, monkeypatch, capsys) -> None:
    def _fail(*args, **kwargs):
        raise AssertionError("--dry-run must not shell out to pip")

    monkeypatch.setattr(install_extras.subprocess, "run", _fail)
    # Pin the resolver: this asserts the *install* path, and whether manim
    # happens to be present in the runner's environment must not decide
    # which branch runs. The real resolver is covered on its own above.
    monkeypatch.setattr(install_extras, "missing_requirements", lambda reqs: list(reqs))

    code = install_extras.main(["math-animator", "--pyproject", str(pyproject), "--dry-run"])

    assert code == 0
    assert "manim>=0.19.0" in capsys.readouterr().out


def test_pip_failure_does_not_fail_the_start(pyproject, monkeypatch, capsys) -> None:
    """A wheel that will not install leaves one feature off, not the app down."""
    from types import SimpleNamespace

    monkeypatch.setattr(
        install_extras.subprocess,
        "run",
        lambda *a, **k: SimpleNamespace(returncode=1),
    )
    # Pin the resolver: this asserts the *install* path, and whether manim
    # happens to be present in the runner's environment must not decide
    # which branch runs. The real resolver is covered on its own above.
    monkeypatch.setattr(install_extras, "missing_requirements", lambda reqs: list(reqs))

    code = install_extras.main(["math-animator", "--pyproject", str(pyproject)])

    assert code == 0
    assert "stay unavailable" in capsys.readouterr().out


def test_unreadable_pyproject_does_not_fail_the_start(tmp_path, capsys) -> None:
    code = install_extras.main(["math-animator", "--pyproject", str(tmp_path / "gone.toml")])

    assert code == 0
    assert "Could not read" in capsys.readouterr().out


def test_no_declaration_is_a_no_op(monkeypatch) -> None:
    """The default deployment declares nothing and must not pay for the feature."""

    def _fail(*args, **kwargs):
        raise AssertionError("nothing declared; must not read pyproject or run pip")

    monkeypatch.setattr(install_extras, "load_extras", _fail)

    assert install_extras.main([""]) == 0


def test_every_extra_the_project_declares_resolves() -> None:
    """Guards the docs: the names suggested in docker-compose must be real."""
    root = Path(__file__).resolve().parents[2]
    extras = install_extras.load_extras(root / "pyproject.toml")

    _, unknown = install_extras.resolve(extras, ["math-animator", "partners"])

    assert unknown == []
