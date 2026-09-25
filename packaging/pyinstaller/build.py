#!/usr/bin/env python3
"""Cross-platform PyInstaller onedir build for the DeepTutor CLI backend.

Output::

    dist/pyinstaller/<plat-arch>/deeptutor/deeptutor[.exe]

Also stages a copy for electron-builder::

    dist/packaging-sidecar/python-backend/
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys


REPO_ROOT = Path(__file__).resolve().parents[2]
SPEC = Path(__file__).resolve().parent / "deeptutor.spec"
SIDECAR_BACKEND = REPO_ROOT / "dist" / "packaging-sidecar" / "python-backend"


def platform_tag() -> str:
    system = platform.system().lower()
    machine = platform.machine().lower()
    if machine in {"x86_64", "amd64"}:
        arch = "x64"
    elif machine in {"arm64", "aarch64"}:
        arch = "arm64"
    else:
        arch = machine.replace(" ", "")
    if system == "windows":
        return f"win-{arch}"
    if system == "darwin":
        return f"macos-{arch}"
    if system == "linux":
        return f"linux-{arch}"
    return f"{system}-{arch}"


def binary_name() -> str:
    return "deeptutor.exe" if platform.system().lower() == "windows" else "deeptutor"


def run(cmd: list[str], *, env: dict[str, str] | None = None) -> None:
    print("[pyinstaller]", " ".join(cmd), flush=True)
    subprocess.run(cmd, check=True, cwd=REPO_ROOT, env=env)


def ensure_pyinstaller(python: str) -> None:
    probe = subprocess.run(
        [python, "-c", "import PyInstaller"],
        cwd=REPO_ROOT,
        capture_output=True,
    )
    if probe.returncode == 0:
        print("[pyinstaller] PyInstaller already available", flush=True)
        return
    print("[pyinstaller] Installing PyInstaller…", flush=True)
    uv = shutil.which("uv")
    if uv:
        try:
            run([uv, "pip", "install", "--python", python, "pyinstaller>=6.0,<7"])
            return
        except subprocess.CalledProcessError:
            print("[pyinstaller] uv pip failed; trying pip…", flush=True)
    run([python, "-m", "pip", "install", "pyinstaller>=6.0,<7"])


def ensure_deeptutor(python: str) -> None:
    probe = subprocess.run(
        [python, "-c", "import deeptutor, deeptutor_cli"],
        cwd=REPO_ROOT,
        capture_output=True,
    )
    if probe.returncode == 0:
        return
    print("[pyinstaller] Installing DeepTutor editable…", flush=True)
    uv = shutil.which("uv")
    if uv:
        try:
            run([uv, "pip", "install", "--python", python, "-e", "."])
            return
        except subprocess.CalledProcessError:
            pass
    run([python, "-m", "pip", "install", "-e", "."])


def stage_backend(built_dir: Path) -> None:
    if SIDECAR_BACKEND.exists():
        shutil.rmtree(SIDECAR_BACKEND)
    SIDECAR_BACKEND.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(built_dir, SIDECAR_BACKEND)
    print(f"[pyinstaller] Staged electron sidecar: {SIDECAR_BACKEND}", flush=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--python", default=sys.executable, help="Python interpreter to use")
    parser.add_argument("--skip-smoke", action="store_true")
    parser.add_argument("--no-stage", action="store_true", help="Do not copy into packaging-sidecar")
    args = parser.parse_args(argv)

    python = args.python
    tag = platform_tag()
    out_root = REPO_ROOT / "dist" / "pyinstaller" / tag
    work_path = out_root / "build"
    dist_path = out_root
    built_dir = dist_path / "deeptutor"
    exe = built_dir / binary_name()

    print(f"[pyinstaller] platform={tag} python={python}", flush=True)
    os.chdir(REPO_ROOT)
    ensure_pyinstaller(python)
    ensure_deeptutor(python)
    out_root.mkdir(parents=True, exist_ok=True)

    run(
        [
            python,
            "-m",
            "PyInstaller",
            "--noconfirm",
            "--clean",
            f"--distpath={dist_path}",
            f"--workpath={work_path}",
            str(SPEC),
        ]
    )
    if not exe.is_file():
        raise SystemExit(f"Expected output missing: {exe}")
    if platform.system().lower() != "windows":
        exe.chmod(exe.stat().st_mode | 0o111)

    print(f"[pyinstaller] Built: {exe}", flush=True)
    if not args.no_stage:
        stage_backend(built_dir)

    if not args.skip_smoke:
        for smoke in (["--help"], ["serve", "--help"], ["start", "--help"]):
            print(f"[pyinstaller] Smoke: {' '.join(smoke)}", flush=True)
            run([str(exe), *smoke])

    print("[pyinstaller] Done.", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
