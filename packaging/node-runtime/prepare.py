#!/usr/bin/env python3
"""Prepare a portable Node.js runtime for Electron packaging.

Downloads (or reuses a cached archive) the official Node 22 distribution for
the current platform and writes::

    packaging/node-runtime/<plat-arch>/node[.exe]

Also stages::

    dist/packaging-sidecar/node-runtime/
"""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import tarfile
import urllib.request
import zipfile


NODE_VERSION = "22.23.2"
REPO_ROOT = Path(__file__).resolve().parents[2]
RUNTIME_ROOT = Path(__file__).resolve().parent
CACHE_DIR = RUNTIME_ROOT / "node-runtime-bundle"
SIDECAR_NODE = REPO_ROOT / "dist" / "packaging-sidecar" / "node-runtime"


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


def node_dist_name(tag: str) -> str:
    # Official Node dist folder names.
    mapping = {
        "win-x64": f"node-v{NODE_VERSION}-win-x64",
        "win-arm64": f"node-v{NODE_VERSION}-win-arm64",
        "linux-x64": f"node-v{NODE_VERSION}-linux-x64",
        "linux-arm64": f"node-v{NODE_VERSION}-linux-arm64",
        "macos-x64": f"node-v{NODE_VERSION}-darwin-x64",
        "macos-arm64": f"node-v{NODE_VERSION}-darwin-arm64",
    }
    if tag not in mapping:
        raise SystemExit(f"Unsupported platform tag for Node: {tag}")
    return mapping[tag]


def archive_name(tag: str) -> str:
    dist = node_dist_name(tag)
    if tag.startswith("win-"):
        return f"{dist}.zip"
    if tag.startswith("linux-"):
        return f"{dist}.tar.xz"
    return f"{dist}.tar.gz"


def download_url(tag: str) -> str:
    return f"https://nodejs.org/dist/v{NODE_VERSION}/{archive_name(tag)}"


def node_binary(out_dir: Path) -> Path:
    name = "node.exe" if platform.system().lower() == "windows" else "node"
    return out_dir / name


def ensure_archive(tag: str) -> Path:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    archive = CACHE_DIR / archive_name(tag)
    if archive.is_file() and archive.stat().st_size > 1_000_000:
        print(f"[node-runtime] Using cached archive: {archive}", flush=True)
        return archive
    url = download_url(tag)
    print(f"[node-runtime] Downloading {url} …", flush=True)
    tmp = Path(str(archive) + ".partial")
    urllib.request.urlretrieve(url, tmp)  # noqa: S310 - fixed official URL
    tmp.replace(archive)
    return archive


def extract_archive(archive: Path, staging: Path) -> Path:
    if staging.exists():
        shutil.rmtree(staging)
    staging.mkdir(parents=True, exist_ok=True)
    print(f"[node-runtime] Extracting {archive.name} …", flush=True)
    if archive.suffix == ".zip":
        with zipfile.ZipFile(archive) as zf:
            zf.extractall(staging)
    elif archive.name.endswith(".tar.xz"):
        with tarfile.open(archive, "r:xz") as tf:
            tf.extractall(staging)
    else:
        with tarfile.open(archive, "r:gz") as tf:
            tf.extractall(staging)
    children = [p for p in staging.iterdir() if p.is_dir()]
    if not children:
        raise SystemExit(f"Archive had no top-level directory: {archive}")
    return children[0]


def stage_node(out_dir: Path) -> None:
    if SIDECAR_NODE.exists():
        shutil.rmtree(SIDECAR_NODE)
    SIDECAR_NODE.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(out_dir, SIDECAR_NODE)
    print(f"[node-runtime] Staged electron sidecar: {SIDECAR_NODE}", flush=True)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--no-stage", action="store_true")
    parser.add_argument("--tag", default="", help="Override platform tag (e.g. linux-x64)")
    args = parser.parse_args(argv)

    tag = args.tag or platform_tag()
    out_dir = RUNTIME_ROOT / tag
    exe = node_binary(out_dir)

    if exe.is_file():
        print(f"[node-runtime] Already prepared: {exe}", flush=True)
        subprocess.run([str(exe), "--version"], check=False)
        if not args.no_stage:
            stage_node(out_dir)
        return 0

    archive = ensure_archive(tag)
    staging = RUNTIME_ROOT / "_extract_tmp"
    nested = extract_archive(archive, staging)
    if out_dir.exists():
        shutil.rmtree(out_dir)
    nested.rename(out_dir)
    shutil.rmtree(staging, ignore_errors=True)

    if not exe.is_file():
        # Some archives nest bin/node
        alt = out_dir / "bin" / ("node.exe" if platform.system().lower() == "windows" else "node")
        if alt.is_file():
            # Flatten: electron expects node next to npm in the staged root OR in bin/.
            # Keep official layout (bin/node on unix tarballs).
            pass
        else:
            raise SystemExit(f"node binary missing after extract under {out_dir}")

    # Official unix tarballs use <root>/bin/node — normalize to <root>/node for Electron PATH.
    nested_bin = out_dir / "bin" / "node"
    flat = out_dir / "node"
    if nested_bin.is_file() and not flat.is_file():
        # Keep bin/ layout but also expose node at root via copy for simpler PATH prepend.
        shutil.copy2(nested_bin, flat)
        flat.chmod(flat.stat().st_mode | 0o111)
        npm_bin = out_dir / "bin" / "npm"
        if npm_bin.is_file() and not (out_dir / "npm").exists():
            shutil.copy2(npm_bin, out_dir / "npm")

    exe = node_binary(out_dir)
    if not exe.is_file():
        raise SystemExit(f"node binary missing: {exe}")
    if platform.system().lower() != "windows":
        exe.chmod(exe.stat().st_mode | 0o111)

    print(f"[node-runtime] Ready: {exe}", flush=True)
    subprocess.run([str(exe), "--version"], check=False)
    if not args.no_stage:
        stage_node(out_dir)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
