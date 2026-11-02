"""Build the source compatibility package against the repository's version."""

from email.parser import Parser
from pathlib import Path
import sys

from setuptools import setup

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
if (ROOT / "build_metadata.py").is_file():
    sys.path.insert(0, str(ROOT))
    from build_metadata import project_version

    version = project_version(ROOT)
else:
    # An extracted CLI sdist has no repository parent. Its metadata was
    # generated from the version source when the archive was built.
    version = Parser().parsestr((HERE / "PKG-INFO").read_text(encoding="utf-8"))["Version"]
    if not version:
        raise ValueError("Missing CLI source distribution version")
setup(version=version, install_requires=[f"deeptutor=={version}"])
