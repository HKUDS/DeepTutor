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


@pytest.mark.parametrize("engine", ["docling", "markitdown", "pymupdf4llm", "liteparse"])
def test_parser_extra_resolves_source_requirements_without_feature_wheels(engine) -> None:
    from deeptutor.modules.catalog import manifests
    from deeptutor.services.parsing.engines._install import ENGINE_PIP_SPECS

    root = Path(__file__).resolve().parents[2]
    extras = install_extras.load_extras(root / "pyproject.toml")
    requirements, unknown = install_extras.resolve(extras, [f"parse-{engine}"])

    assert unknown == []
    assert set(ENGINE_PIP_SPECS[engine]).issubset(requirements)
    assert set(manifests()["parsing"]["requirements"]).issubset(requirements)
    assert not any(requirement.startswith("deeptutor") for requirement in requirements)


@pytest.mark.parametrize("encoding", ["cp1252", "ascii"])
def test_unknown_unicode_extra_survives_a_strict_narrow_subprocess(encoding, tmp_path) -> None:
    """Regression (#2354): the real CLI must not crash on a strict narrow stdout."""
    import os
    import subprocess

    pyproject = tmp_path / "目录.toml"
    pyproject.write_text(
        "[project.optional-dependencies]\ndemo = []\n",
        encoding="utf-8",
    )
    script = Path(__file__).resolve().parents[2] / "scripts" / "install_extras.py"

    result = subprocess.run(
        [sys.executable, str(script), "未知", "--pyproject", str(pyproject)],
        capture_output=True,
        text=True,
        encoding="utf-8",
        env=dict(os.environ, PYTHONIOENCODING=f"{encoding}:strict"),
    )

    assert result.returncode == 0
    assert "UnicodeEncodeError" not in result.stdout + result.stderr
    assert "Unknown extra" in result.stdout
    assert result.stdout.endswith("\n")
    assert not result.stdout.endswith("\n\n")
    assert "Installing" not in result.stdout


def test_utf8_captured_output_keeps_unknown_unicode_extra_readable(tmp_path, capsys) -> None:
    """A stdout that can represent the name must print it, emoji included."""
    pyproject = tmp_path / "目录.toml"
    pyproject.write_text(
        "[project.optional-dependencies]\ndemo = []\n",
        encoding="utf-8",
    )

    code = install_extras.main(["未知", "--pyproject", str(pyproject)])
    out = capsys.readouterr().out

    assert code == 0
    assert "Unknown extra" in out
    assert "未知" in out
    assert "⚠️" in out
    assert out.endswith("\n")
    assert not out.endswith("\n\n")


@pytest.mark.parametrize("encoding", ["cp1252", "ascii"])
@pytest.mark.parametrize(
    "case",
    [
        "unknown-extra",
        "unreadable-project",
        "all-satisfied",
        "dry-run",
        "pip-success",
        "pip-failure",
    ],
)
def test_strict_narrow_stdout_reports_every_status(encoding, case, monkeypatch) -> None:
    """Regression (#2354): every status path survives a strict narrow stdout.

    The fixtures are non-ASCII well beyond emoji — extra names, a filename,
    an error message and dependency strings — so a fix that only special-cased
    emoji would still fail here.
    """
    import io
    from types import SimpleNamespace

    missing = ["déjà-vù>=1.0", "费米子<2"]
    calls = []

    def fake_run(argv, **kwargs):
        calls.append((argv, kwargs))
        return SimpleNamespace(returncode=0 if case == "pip-success" else 1)

    def fake_load(pyproject):
        if case == "unreadable-project":
            raise OSError("无法读取 « déta »")
        return {"mäté-ω": list(missing)}

    monkeypatch.setattr(
        sys, "stdout", io.TextIOWrapper(io.BytesIO(), encoding=encoding, errors="strict")
    )
    monkeypatch.setattr(install_extras, "load_extras", fake_load)
    monkeypatch.setattr(
        install_extras,
        "missing_requirements",
        lambda reqs: [] if case == "all-satisfied" else list(reqs),
    )
    monkeypatch.setattr(install_extras.subprocess, "run", fake_run)

    argv = ["未知-ω"] if case == "unknown-extra" else ["mäté-ω"]
    if case == "unreadable-project":
        argv += ["--pyproject", "目录-déta.toml"]
    if case == "dry-run":
        argv.append("--dry-run")

    code = install_extras.main(argv)
    sys.stdout.flush()
    out = sys.stdout.buffer.getvalue().decode(encoding)

    def survived(fragment: str) -> bool:
        return fragment.encode(encoding, "backslashreplace").decode(encoding) in out

    fragments = {
        "unknown-extra": ["Unknown extra '未知-ω'", "Available: mäté-ω"],
        "unreadable-project": ["Could not read 目录-déta.toml", "无法读取 « déta »"],
        "all-satisfied": ["Extras already satisfied: mäté-ω"],
        "dry-run": ["Would install 2 package(s) for mäté-ω:", "déjà-vù>=1.0", "费米子<2"],
        "pip-success": ["Installing 2 package(s) for: mäté-ω"],
        "pip-failure": ["Installing 2 package(s) for: mäté-ω", "pip exited 1"],
    }

    assert code == 0
    assert out.endswith("\n")
    assert "\n\n" not in out
    for fragment in fragments[case]:
        assert survived(fragment)
    if case in {"unknown-extra", "unreadable-project", "all-satisfied", "dry-run"}:
        assert calls == []
    if case in {"pip-success", "pip-failure"}:
        assert calls == [
            ([sys.executable, "-m", "pip", "install", "--no-input", *missing], {"check": False})
        ]
    if case == "pip-success":
        assert "pip exited" not in out
