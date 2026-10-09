# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller spec for the DeepTutor onedir backend (all platforms).

Build (from repo root)::

    python packaging/pyinstaller/build.py

Output::

    dist/pyinstaller/<plat-arch>/deeptutor/deeptutor[.exe]
    dist/packaging-sidecar/python-backend/
"""

from __future__ import annotations

from pathlib import Path

from PyInstaller.building.api import COLLECT, EXE, PYZ
from PyInstaller.building.build_main import Analysis
from PyInstaller.utils.hooks import collect_all, collect_data_files, collect_submodules

SPECDIR = Path(SPECPATH).resolve()
REPO_ROOT = SPECDIR.parents[1]

block_cipher = None


def _collect_package(name: str) -> tuple[list, list, list]:
    try:
        return collect_all(name)
    except Exception:
        return [], [], []


datas: list = []
binaries: list = []
hiddenimports: list = []

# Core app packages (do NOT collect deeptutor_web — Electron ships it separately).
for _pkg in ("deeptutor", "deeptutor_cli"):
    d, b, h = _collect_package(_pkg)
    datas += d
    binaries += b
    hiddenimports += h

# Runtime / server stack that is often missed by static analysis.
for _pkg in (
    "uvicorn",
    "fastapi",
    "starlette",
    "pydantic",
    "pydantic_core",
    "anyio",
    "httpx",
    "httpcore",
    "multipart",
    "websockets",
    "yaml",
    "tiktoken",
    "tiktoken_ext",
    "certifi",
    "aiohttp",
    "openai",
    "anthropic",
    "llama_index",
    "faiss",
    "numpy",
    "PIL",
    "fitz",  # PyMuPDF
    "croniter",
    "jose",
    "bcrypt",
    "mcp",
    "pageindex",
):
    d, b, h = _collect_package(_pkg)
    datas += d
    binaries += b
    hiddenimports += h

# Explicit capability / tool modules loaded via string class paths.
hiddenimports += collect_submodules("deeptutor.agents")
hiddenimports += collect_submodules("deeptutor.capabilities")
hiddenimports += collect_submodules("deeptutor.tools")
hiddenimports += collect_submodules("deeptutor.api")
hiddenimports += [
    "deeptutor.runtime.worker_process",
    "deeptutor.runtime.launcher",
    "deeptutor.runtime.frozen",
    "deeptutor.api.main",
    "uvicorn.logging",
    "uvicorn.loops",
    "uvicorn.loops.auto",
    "uvicorn.protocols",
    "uvicorn.protocols.http",
    "uvicorn.protocols.http.auto",
    "uvicorn.protocols.websockets",
    "uvicorn.protocols.websockets.auto",
    "uvicorn.lifespan",
    "uvicorn.lifespan.on",
]

# Ensure prompt / skill data files are present even if collect_all missed some.
datas += collect_data_files("deeptutor", includes=["**/*.yaml", "**/*.yml", "**/*.md", "**/*.json", "**/*.j2", "**/*.jinja"])
datas += collect_data_files("deeptutor_cli", includes=["**/*.md"])

a = Analysis(
    [str(SPECDIR / "entry.py")],
    pathex=[str(REPO_ROOT), str(SPECDIR)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports + ["frozen_support"],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "deeptutor_web",
        "tkinter",
        "matplotlib",
        "IPython",
        "notebook",
        "pytest",
        "manim",
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="deeptutor",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=True,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="deeptutor",
)
