"""Regression coverage for module wheel contents."""

from pathlib import Path
import zipfile

from build_support import owner
from scripts.build_modules import ROOT, build


def test_core_wheel_contains_qti_schema_bytes(tmp_path: Path) -> None:
    schemas = {
        path.relative_to(ROOT).as_posix(): path.read_bytes()
        for version in ("qti2", "qti3")
        for path in (ROOT / "deeptutor/services/question_content" / version / "schemas").glob(
            "*.xsd"
        )
    }
    assert len(schemas) == 71
    assert all(owner(path) == "core" for path in schemas)
    assert all(
        any(f"/{version}/schemas/" in path for path in schemas) for version in ("qti2", "qti3")
    )

    wheel = build(tmp_path, ["core"])[0]
    with zipfile.ZipFile(wheel) as archive:
        wheel_schemas = {path for path in archive.namelist() if path.endswith(".xsd")}
        assert wheel_schemas == set(schemas)
        for path, contents in schemas.items():
            assert archive.read(path) == contents
