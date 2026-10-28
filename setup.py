"""Use the same ownership filter for ordinary pip/source wheel builds."""

from pathlib import Path
import sys

from setuptools import setup

sys.path.insert(0, str(Path(__file__).resolve().parent))
from build_support import CoreBuildPy

setup(cmdclass={"build_py": CoreBuildPy})
