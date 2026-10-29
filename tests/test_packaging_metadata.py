"""Published wheel ownership and dependency floors for the modular install."""

from pathlib import Path
import tomllib

from packaging.requirements import Requirement
import pytest

from build_metadata import optional_dependencies, project_version, source_optional_dependencies
from deeptutor.__version__ import __version__
from deeptutor.modules.catalog import manifests
from scripts.sync_module_requirements import generated

ROOT = Path(__file__).resolve().parents[1]


def project(path="pyproject.toml"):
    return tomllib.loads((ROOT / path).read_text())["project"]


def test_core_and_cli_have_one_code_owner():
    assert project()["dependencies"] == manifests()["core"]["requirements"]
    cli = tomllib.loads((ROOT / "packaging/deeptutor-cli/pyproject.toml").read_text())
    assert set(cli["project"]["dynamic"]) == {"version", "dependencies"}
    assert project_version() == __version__
    assert cli["tool"]["setuptools"]["packages"] == []
    assert "scripts" not in cli["project"]
    for spec in (project(), cli["project"]):
        assert spec["requires-python"] == ">=3.11,<3.15"


def test_generated_source_dependency_files_are_current():
    for filename, content in generated().items():
        assert (ROOT / "requirements" / filename).read_text() == content


@pytest.mark.parametrize(
    "module,requirement",
    [
        ("core", "mcp>=1.26.0,<2.0.0"),
        ("core", "typer>=0.9.0"),
        ("core", "tzdata>=2024.1"),
        ("core", "packaging>=24.2"),
        ("core", "loguru>=0.7.3,<1.0.0"),
        ("core", "json-repair>=0.57.0,<1.0.0"),
        ("core", "pyte>=0.8.1"),
        ("partners", "qrcode>=7.4.0,<9.0.0"),
        ("knowledge", "pageindex>=0.2.10,<0.3.0"),
        ("calendar", "croniter>=6.0.0,<7.0.0"),
        ("parsing", "pdfplumber>=0.11.0"),
        ("parsing", "reportlab>=4.0.0"),
        ("parser-markitdown", "markitdown[all]>=0.1.7"),
        ("parser-pymupdf4llm", "pymupdf4llm>=1.28.2"),
        ("parser-liteparse", "liteparse>=2.14.2"),
        ("parser-docling", "docling[xbrl]>=2.123.1"),
        ("parser-docling", "docling-slim[format-iwork,format-opendocument,format-video]>=2.123.1"),
    ],
)
def test_dependency_floor_belongs_to_its_module(module, requirement):
    assert manifests()[module]["requirements"].count(requirement) == 1
    if module != "core":
        assert requirement not in project()["dependencies"]


def test_python_314_rag_guards_are_preserved():
    dependencies = [Requirement(raw) for raw in manifests()["knowledge"]["requirements"]]
    for version, minimum in [("3.13", "1.8.0"), ("3.14", "1.12.0")]:
        faiss = [
            r
            for r in dependencies
            if r.name == "faiss-cpu" and r.marker.evaluate({"python_version": version})
        ]
        assert len(faiss) == 1
        assert minimum in faiss[0].specifier
    bm25 = next(r for r in dependencies if r.name == "llama-index-retrievers-bm25")
    assert not bm25.marker.evaluate({"python_version": "3.14"})
    lexical = next(r for r in dependencies if r.name == "bm25s")
    assert lexical.marker is None or lexical.marker.evaluate({"python_version": "3.14"})


def test_windows_parser_worker_dependency_is_scoped():
    win32 = next(
        Requirement(r) for r in manifests()["parsing"]["requirements"] if r.startswith("pywin32")
    )
    assert win32.marker.evaluate({"sys_platform": "win32"})
    assert not win32.marker.evaluate({"sys_platform": "darwin"})
    assert any(r.startswith("psutil") for r in manifests()["core"]["requirements"])


def test_optional_sdk_constraints_remain_intact():
    extras = optional_dependencies()
    assert extras["rag-lightrag"] == ["lightrag-hku==1.5.7"]
    assert extras["graphrag"] == ["graphrag>=3.0.1,<4.0.0; python_version < '3.14'"]


def test_next_release_pins_every_internal_dependency_to_the_new_version(tmp_path):
    import shutil

    shutil.copy(ROOT / "pyproject.toml", tmp_path)
    (tmp_path / "deeptutor").mkdir()
    (tmp_path / "deeptutor/__version__.py").write_text('__version__ = "9.8.7rc1"\n')
    extras = optional_dependencies(tmp_path)
    internal = [
        Requirement(raw)
        for rows in extras.values()
        for raw in rows
        if Requirement(raw).name.startswith("deeptutor")
    ]
    assert internal
    assert all(str(requirement.specifier) == "==9.8.7rc1" for requirement in internal)
    assert set(Requirement(raw).name for raw in extras["full"]) == {
        row["distribution"]
        for name, row in manifests().items()
        if name not in {"core", "renderer-manim"} and not name.startswith("parser-")
    }


def test_source_extras_install_dependencies_without_module_wheels():
    extras = source_optional_dependencies()
    assert not any(
        Requirement(raw).name.startswith("deeptutor") for rows in extras.values() for raw in rows
    )
    assert "manim>=0.19.0" in extras["math-animator"]
    assert set(manifests()["partners"]["requirements"]) <= set(extras["partners"])
