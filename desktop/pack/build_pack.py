#!/usr/bin/env python3
"""Build a DeepTutor desktop runtime pack.

A pack is everything the shell needs to run DeepTutor on a machine that has
nothing installed: a relocatable CPython, a virtualenv with DeepTutor and its
locked dependencies, the Node runtime, and a manifest the shell verifies.

Packs are built **on the platform they target** (CI matrix: macos-14, macos-13,
windows-2022). A relocatable venv still embeds platform-specific wheels and a
platform-specific interpreter, so cross-building would only move the failure
somewhere harder to read.

Usage (from the repository root):

    python3 desktop/pack/build_pack.py                 # host platform
    python3 desktop/pack/build_pack.py --skip-web-build
    python3 desktop/pack/build_pack.py --stage-only    # keep the tree, no archive

Outputs (default ``desktop/pack/dist``):

    runtime-<app_version>-<platform>.tar.gz
    runtime-<app_version>-<platform>.tar.gz.sha256
    runtime-<app_version>-<platform>.catalog.json   # feeds runtime-packs.json
"""

from __future__ import annotations

import argparse
import hashlib
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import time
import urllib.request
import zipfile

REPO_ROOT = Path(__file__).resolve().parents[2]
PACK_DIR = Path(__file__).resolve().parent
DEFAULT_LOCK = PACK_DIR / "runtime.lock.txt"

# python-build-standalone ships every interpreter we need under one tag; pinning
# the tag keeps pack builds reproducible.
DEFAULT_PBS_TAG = "20260901"
DEFAULT_PYTHON_VERSION = "3.12.14"
DEFAULT_NODE_VERSION = "20.18.0"

# Linux is a v1.x target (the shell ships macOS + Windows first), but the pack
# side is platform-agnostic: same CPython tag, same locked wheels, same Node.
# Keeping the keys here means "add Linux" is a CI matrix entry, not a rewrite.
SUPPORTED_PLATFORMS = (
    "macos-aarch64",
    "macos-x86_64",
    "windows-x86_64",
    "linux-x86_64",
    "linux-aarch64",
)

PBS_TRIPLES = {
    "macos-aarch64": "aarch64-apple-darwin",
    "macos-x86_64": "x86_64-apple-darwin",
    "windows-x86_64": "x86_64-pc-windows-msvc",
    "linux-x86_64": "x86_64-unknown-linux-gnu",
    "linux-aarch64": "aarch64-unknown-linux-gnu",
}

NODE_ARCHIVES = {
    "macos-aarch64": ("node-v{version}-darwin-arm64.tar.gz", "darwin-arm64", "tar.gz"),
    "macos-x86_64": ("node-v{version}-darwin-x64.tar.gz", "darwin-x64", "tar.gz"),
    "windows-x86_64": ("node-v{version}-win-x64.zip", "win-x64", "zip"),
    "linux-x86_64": ("node-v{version}-linux-x64.tar.gz", "linux-x64", "tar.gz"),
    "linux-aarch64": ("node-v{version}-linux-arm64.tar.gz", "linux-arm64", "tar.gz"),
}


def host_platform() -> str:
    system = platform.system()
    machine = platform.machine().lower()
    if system == "Darwin":
        return "macos-aarch64" if machine in {"arm64", "aarch64"} else "macos-x86_64"
    if system == "Windows":
        return "windows-x86_64"
    if system == "Linux":
        # v1.x target: the shell does not ship for Linux yet, but a pack built
        # here is usable the moment it does.
        return "linux-aarch64" if machine in {"aarch64", "arm64"} else "linux-x86_64"
    return f"unsupported-{system.lower()}-{machine}"


def app_version() -> str:
    text = (REPO_ROOT / "deeptutor" / "__version__.py").read_text(encoding="utf-8")
    match = re.search(r'__version__\s*=\s*["\']([^"\']+)["\']', text)
    if not match:
        raise SystemExit("could not read __version__ from deeptutor/__version__.py")
    return match.group(1)


def log(message: str) -> None:
    print(f"[pack] {message}", flush=True)


def run(command: list[str], *, cwd: Path | None = None) -> None:
    log("$ " + " ".join(command))
    subprocess.run(command, cwd=str(cwd) if cwd else None, check=True)


def download(url: str, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        log(f"cached {destination.name}")
        return
    _download_uncached(url, destination)


def _download_uncached(url: str, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    log(f"downloading {url}")
    partial = destination.with_suffix(destination.suffix + ".part")
    with urllib.request.urlopen(url) as response, partial.open("wb") as handle:
        shutil.copyfileobj(response, handle, length=1024 * 1024)
    partial.rename(destination)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def parse_checksums(text: str) -> dict[str, str]:
    """`<digest>  <filename>` lines, the format PBS and nodejs.org both publish.

    A leading `*` marks a binary-mode entry in some tools; it is not part of the
    name.
    """

    checksums: dict[str, str] = {}
    for line in text.splitlines():
        parts = line.split()
        if len(parts) != 2 or not re.fullmatch(r"[0-9a-fA-F]{64}", parts[0]):
            continue
        checksums[parts[1].lstrip("*")] = parts[0].lower()
    return checksums


def fetch_checksums(url: str) -> dict[str, str]:
    log(f"downloading {url}")
    with urllib.request.urlopen(url) as response:
        return parse_checksums(response.read().decode("utf-8", "replace"))


def download_verified(
    url: str, destination: Path, *, checksums_url: str, source: str
) -> None:
    """Fetch `url` and refuse to keep bytes upstream does not vouch for.

    A truncated or swapped download of CPython or Node ends up *executed* inside
    every pack, so the published digest is checked before the archive is
    unpacked — and a stale cache entry that fails the check is re-fetched once
    instead of failing the release.
    """

    checksums = fetch_checksums(checksums_url)
    expected = checksums.get(destination.name)
    if expected is None:
        raise SystemExit(
            f"{source} publishes no checksum for {destination.name}; refusing to "
            "stage an unverified runtime"
        )
    if destination.exists():
        actual = sha256_file(destination)
        if actual == expected:
            log(f"cached {destination.name} (checksum ok)")
            return
        log(f"cached {destination.name} does not match {source}; re-downloading")
        destination.unlink()
    _download_uncached(url, destination)
    actual = sha256_file(destination)
    if actual != expected:
        destination.unlink(missing_ok=True)
        raise SystemExit(
            f"{destination.name} failed its {source} checksum: expected {expected}, "
            f"got {actual}"
        )
    log(f"checksum ok for {destination.name}")


def _escapes(root: Path, candidate: Path) -> bool:
    resolved = candidate.resolve()
    return resolved != root and root not in resolved.parents


class _ZipEntry:
    """The slice of `tarfile.TarInfo` the safety check asks a zip entry for."""

    def __init__(self, info: zipfile.ZipInfo) -> None:
        self.name = info.filename
        self._mode = info.external_attr >> 16

    def isdev(self) -> bool:
        return (
            stat.S_ISCHR(self._mode)
            or stat.S_ISBLK(self._mode)
            or stat.S_ISFIFO(self._mode)
        )

    def issym(self) -> bool:
        return False

    def islnk(self) -> bool:
        return False

    @property
    def linkname(self) -> str:
        return ""


def _reject_unsafe_members(destination: Path, members: list, *, kind: str) -> None:
    """Refuse archive entries that would write outside `destination`.

    The runtimes come from upstream over TLS but are not verified against a
    digest pinned in this repository, and a tampered mirror or a corrupted
    transfer is exactly what this catches: no absolute paths, no `..`, no links
    pointing out, no device nodes. Everything a real runtime archive contains
    (relative symlinks included) still passes.
    """

    root = destination.resolve()
    for member in members:
        name = member.name
        target = root / name
        if Path(name).is_absolute() or ".." in Path(name).parts:
            raise SystemExit(f"{kind} entry escapes the destination: {name}")
        if _escapes(root, target):
            raise SystemExit(f"{kind} entry escapes the destination: {name}")
        if member.isdev():
            raise SystemExit(f"{kind} entry is a device node: {name}")
        if member.issym() or member.islnk():
            link = member.linkname
            if Path(link).is_absolute() or _escapes(root, target.parent / link):
                raise SystemExit(
                    f"{kind} link escapes the destination: {name} -> {link}"
                )


def extract_archive(archive: Path, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    if archive.suffix == ".zip" or zipfile.is_zipfile(archive):
        with zipfile.ZipFile(archive) as handle:
            infos = handle.infolist()
            for info in infos:
                # A zip symlink keeps its target in the entry *data*, so the
                # generic check cannot see it; nothing legitimate needs one here.
                if stat.S_ISLNK(info.external_attr >> 16):
                    raise SystemExit(f"zip entry is a symlink: {info.filename}")
            _reject_unsafe_members(
                destination, [_ZipEntry(info) for info in infos], kind="zip"
            )
            handle.extractall(destination, members=infos)
        return
    with tarfile.open(archive, "r:gz") as handle:
        members = handle.getmembers()
        _reject_unsafe_members(destination, members, kind="tar")
        try:
            handle.extractall(destination, members=members, filter="fully_trusted")
        except TypeError:  # Python < 3.11.4 has no `filter` argument
            handle.extractall(destination, members=members)


def single_child(directory: Path) -> Path:
    children = [child for child in directory.iterdir() if child.is_dir()]
    if len(children) != 1:
        raise SystemExit(f"expected exactly one directory inside {directory}, found {children}")
    return children[0]


def find_python_dir(root: Path) -> Path:
    """Locate the interpreter directory inside an extracted PBS archive.

    `install_only` puts `python/` at the top level while the `full` archives
    wrap it in `cpython-<version>+<tag>-<triple>/`; rather than encode both
    layouts, look for the interpreter itself.
    """

    for candidate in [root, *sorted(path for path in root.rglob("*") if path.is_dir())]:
        if (candidate / "bin" / "python3").exists() or (candidate / "python.exe").exists():
            return candidate
    raise SystemExit(f"no interpreter found under {root}")


def sha256_of(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def directory_size(path: Path) -> int:
    total = 0
    for root, dirs, files in os.walk(path):
        for name in files:
            candidate = Path(root) / name
            if candidate.is_symlink():
                continue
            total += candidate.stat().st_size
    return total


def prepare_web(skip_build: bool) -> None:
    """Make sure the wheel will carry the packaged Next.js standalone server."""

    web_dir = REPO_ROOT / "web"
    standalone = web_dir / ".next" / "standalone" / "server.js"
    if skip_build:
        if not standalone.exists():
            raise SystemExit(
                f"--skip-web-build needs an existing build at {standalone}"
            )
    elif not standalone.exists():
        if not (web_dir / "node_modules").exists():
            run(["npm", "ci", "--legacy-peer-deps"], cwd=web_dir)
        run(["npm", "run", "build"], cwd=web_dir)
    run(
        [
            sys.executable,
            str(REPO_ROOT / "scripts" / "prepare_web_package.py"),
            "--skip-build",
        ],
        cwd=REPO_ROOT,
    )


def build_wheel(stage: Path) -> Path:
    wheel_dir = stage / "wheel"
    wheel_dir.mkdir(parents=True, exist_ok=True)
    run(["uv", "build", "--wheel", "--out-dir", str(wheel_dir)], cwd=REPO_ROOT)
    wheels = sorted(wheel_dir.glob("deeptutor-*.whl"))
    if not wheels:
        raise SystemExit(f"no deeptutor wheel produced in {wheel_dir}")
    return wheels[-1]


def wheel_version(wheel: Path) -> str:
    """The version baked into a wheel name: `deeptutor-1.6.11-py3-none-any.whl`."""

    match = re.match(r"deeptutor-([^-]+)-", wheel.name)
    if not match:
        raise SystemExit(f"unexpected wheel name: {wheel.name}")
    return match.group(1)


def assert_wheel_matches_label(wheel: Path, label: str) -> None:
    """Refuse to publish a pack whose label disagrees with its contents.

    `--app-version` only names the archive; the wheel comes from
    `deeptutor/__version__.py`. Passing a version that was never written into
    that file produces a pack that *says* 1.6.11 while running 1.6.10 — a
    mistake that survives every checksum, because the archive is internally
    consistent. It only shows up as "the update installed but nothing changed".
    """

    built = wheel_version(wheel)
    if built != label:
        raise SystemExit(
            f"the wheel is {built} but the pack would be labelled {label}: bump "
            "deeptutor/__version__.py (the single source of truth) instead of "
            "passing --app-version, so the archive, the wheel and the release tag agree."
        )


def fetch_python(stage: Path, *, tag: str, version: str, target: str) -> tuple[Path, str]:
    triple = PBS_TRIPLES[target]
    name = f"cpython-{version}+{tag}-{triple}-install_only.tar.gz"
    release = (
        "https://github.com/astral-sh/python-build-standalone/releases/download/"
        f"{tag}"
    )
    archive = PACK_DIR / ".cache" / name
    # This tree becomes the interpreter every pack runs, so the bytes are checked
    # against what the release publishes before they are unpacked.
    download_verified(
        f"{release}/{name}",
        archive,
        checksums_url=f"{release}/SHA256SUMS",
        source="python-build-standalone",
    )
    extract_archive(archive, stage / "python-download")
    extracted = find_python_dir(stage / "python-download")
    shutil.move(str(extracted), str(stage / "python"))
    shutil.rmtree(stage / "python-download", ignore_errors=True)
    return stage / "python", triple


def fetch_node(stage: Path, *, version: str, target: str) -> Path:
    template, label, _kind = NODE_ARCHIVES[target]
    name = template.format(version=version)
    base = f"https://nodejs.org/dist/v{version}"
    archive = PACK_DIR / ".cache" / name
    download_verified(
        f"{base}/{name}",
        archive,
        checksums_url=f"{base}/SHASUMS256.txt",
        source="nodejs.org",
    )
    extract_archive(archive, stage / "node-download")
    extracted = single_child(stage / "node-download")
    shutil.move(str(extracted), str(stage / "node"))
    shutil.rmtree(stage / "node-download", ignore_errors=True)
    log(f"node {version} ({label}) staged")
    return stage / "node"


def python_in_python_dir(python_dir: Path) -> Path:
    candidate = (
        python_dir / "python.exe" if os.name == "nt" else python_dir / "bin" / "python3"
    )
    if not candidate.exists():
        raise SystemExit(f"no interpreter at {candidate}")
    return candidate


def venv_python(venv: Path) -> Path:
    return venv / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def create_venv(stage: Path, python_dir: Path, wheel: Path, lock: Path) -> Path:
    venv = stage / "venv"
    run(
        [
            "uv",
            "venv",
            "--relocatable",
            "--python",
            str(python_in_python_dir(python_dir)),
            str(venv),
        ]
    )
    # One resolver pass over the same lock the wheel was built against.
    run(
        [
            "uv",
            "pip",
            "install",
            "--python",
            str(venv_python(venv)),
            "--requirement",
            str(lock),
            str(wheel),
        ]
    )
    return venv


def smoke_test(stage: Path, venv: Path, node_dir: Path) -> dict[str, str]:
    interpreter = venv_python(venv)
    probe = (
        "import json, importlib.util, sys;"
        "spec = importlib.util.find_spec('deeptutor_web');"
        "import deeptutor_cli.main;"
        "print(json.dumps({'python': sys.version.split()[0],"
        " 'web_package': spec.origin if spec else None}))"
    )
    result = subprocess.run(
        [str(interpreter), "-c", probe],
        check=True,
        capture_output=True,
        text=True,
    )
    payload = json.loads(result.stdout.strip().splitlines()[-1])
    package_dir = Path(payload["web_package"]).parent if payload["web_package"] else None
    server = package_dir / "server.js" if package_dir else None
    if server is None or not server.exists():
        raise SystemExit("the installed deeptutor_web package has no server.js")
    node_binary = node_dir / ("node.exe" if os.name == "nt" else "bin/node")
    node_version = subprocess.run(
        [str(node_binary), "--version"], check=True, capture_output=True, text=True
    ).stdout.strip()
    log(f"smoke ok: python {payload['python']}, server.js present, node {node_version}")
    return {"python": payload["python"], "node": node_version.lstrip("v")}


def write_manifest(
    stage: Path,
    *,
    pack_id: str,
    version: str,
    target: str,
    python_version: str,
    pbs_tag: str,
    node_version: str,
) -> Path:
    python_relative = "venv/Scripts/python.exe" if os.name == "nt" else "venv/bin/python"
    manifest = {
        "schema_version": 1,
        "pack_id": pack_id,
        "app_version": version,
        "platform": target,
        "created_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "python": {"version": python_version, "source": f"python-build-standalone {pbs_tag}"},
        "node": {"version": node_version, "source": "nodejs.org"},
        "paths": {
            "python": python_relative,
            "node_dir": "node/bin" if os.name != "nt" else "node",
        },
        "requires_shell": ">=1.0.0",
    }
    path = stage / "manifest.json"
    path.write_text(json.dumps(manifest, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return path


def archive_pack(stage: Path, out_dir: Path, pack_id: str) -> tuple[Path, int, str]:
    out_dir.mkdir(parents=True, exist_ok=True)
    archive = out_dir / f"{pack_id}.tar.gz"
    log(f"archiving {archive.name}")
    with tarfile.open(archive, "w:gz", compresslevel=6) as handle:
        for entry in sorted(stage.iterdir()):
            handle.add(entry, arcname=entry.name)
    digest = sha256_of(archive)
    # `with_suffix` would replace only ".gz" and produce a double extension.
    (archive.parent / f"{archive.name}.sha256").write_text(
        f"{digest}  {archive.name}\n", encoding="utf-8"
    )
    return archive, archive.stat().st_size, digest


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--platform", default=host_platform(), choices=SUPPORTED_PLATFORMS)
    parser.add_argument("--app-version", default=app_version())
    parser.add_argument("--python-version", default=DEFAULT_PYTHON_VERSION)
    parser.add_argument("--pbs-tag", default=DEFAULT_PBS_TAG)
    parser.add_argument("--node-version", default=DEFAULT_NODE_VERSION)
    parser.add_argument("--lock", type=Path, default=DEFAULT_LOCK)
    parser.add_argument("--out", type=Path, default=PACK_DIR / "dist")
    parser.add_argument("--skip-web-build", action="store_true")
    parser.add_argument("--stage-only", action="store_true", help="build the tree, skip the archive")
    args = parser.parse_args()

    if args.platform != host_platform():
        raise SystemExit(
            f"{args.platform} packs must be built on {args.platform}: a relocatable venv "
            f"still contains that platform's interpreter and wheels (host is {host_platform()}). "
            "Use the CI matrix in .github/workflows/desktop-release.yml."
        )
    if not args.lock.exists():
        raise SystemExit(f"missing lock file {args.lock}; generate it with uv pip compile")

    version = args.app_version
    pack_id = f"{version}-{args.platform}"
    stage = args.out / f"stage-{pack_id}"
    if stage.exists():
        shutil.rmtree(stage)
    stage.mkdir(parents=True)

    started = time.time()
    log(f"building pack {pack_id}")
    prepare_web(args.skip_web_build)
    wheel = build_wheel(stage)
    assert_wheel_matches_label(wheel, version)
    log(f"wheel: {wheel.name}")
    python_dir, triple = fetch_python(
        stage, tag=args.pbs_tag, version=args.python_version, target=args.platform
    )
    log(f"python staged from {triple}")
    node_dir = fetch_node(stage, version=args.node_version, target=args.platform)
    venv = create_venv(stage, python_dir, wheel, args.lock)
    versions = smoke_test(stage, venv, node_dir)
    manifest_path = write_manifest(
        stage,
        pack_id=pack_id,
        version=version,
        target=args.platform,
        python_version=versions["python"],
        pbs_tag=args.pbs_tag,
        node_version=versions["node"],
    )
    shutil.rmtree(stage / "wheel", ignore_errors=True)
    unpacked = directory_size(stage)
    log(f"staged tree {unpacked / 1e6:.0f} MB in {time.time() - started:.0f}s")

    if args.stage_only:
        log(f"stage kept at {stage}")
        log(f"manifest: {manifest_path}")
        return 0

    archive, size, digest = archive_pack(stage, args.out, pack_id)
    catalog = {
        "pack_id": pack_id,
        "app_version": version,
        "platform": args.platform,
        "archive": archive.name,
        "size": size,
        "sha256": digest,
        "unpacked_size": unpacked,
        "python": versions["python"],
        "node": versions["node"],
        "requires_shell": ">=1.0.0",
    }
    catalog_path = args.out / f"{pack_id}.catalog.json"
    catalog_path.write_text(
        json.dumps(catalog, indent=2, ensure_ascii=False) + "\n", encoding="utf-8"
    )
    log(f"archive {archive.name}: {size / 1e6:.0f} MB, sha256 {digest[:16]}…")
    log(f"catalog: {catalog_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
