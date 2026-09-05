"""Persistent, versioned wheel installation for the reading extension bundle.

No pip, build hooks or dependency resolution runs in the API process. Wheels
contain only the known package namespace and metadata; Python code is imported
only by a newly started backend. Installation is administrator-owned.
"""

from __future__ import annotations

import configparser
from contextlib import contextmanager
from email.parser import BytesParser
import hashlib
from importlib import import_module, metadata
import json
import os
from pathlib import Path, PurePosixPath
import sqlite3
import sys
import tempfile
from typing import Any
from urllib.parse import urlparse
import zipfile

import httpx
from packaging.requirements import Requirement
from packaging.specifiers import SpecifierSet
from packaging.version import Version

from deeptutor.__version__ import __version__
from deeptutor.runtime.home import get_runtime_home

PACKAGE = "deeptutor-reading-extensions"
NAMESPACE = "deeptutor_reading_extensions"
RELEASE_REPO = "evan188199-tech/deeptutor-reading-extensions"
EXTENSIONS = {
    "read_aloud": f"{NAMESPACE}.read_aloud:ReadAloudExtension",
    "vocabulary": f"{NAMESPACE}.vocabulary:VocabularyExtension",
    "quiz": f"{NAMESPACE}.quiz:ReadingQuizExtension",
}
MAX_BYTES = 10 * 1024 * 1024
DEFAULT = {"mode": "builtin", "disabled": []}


def root() -> Path:
    return get_runtime_home() / "data" / "system" / "reading-plugins"


def read_state() -> dict[str, Any]:
    path = root() / "state.sqlite3"
    if not path.exists():
        try:
            dist = metadata.distribution(PACKAGE)
            return {"mode": "pip", "version": dist.version, "disabled": []}
        except metadata.PackageNotFoundError:
            return dict(DEFAULT)
    with sqlite3.connect(f"{path.as_uri()}?mode=ro", uri=True) as db:
        row = db.execute("SELECT body FROM state WHERE id=1").fetchone()
    return json.loads(row[0]) if row else dict(DEFAULT)


# Each backend worker pins the same persisted generation when it starts.
ACTIVE_STATE = read_state()


@contextmanager
def transaction():
    root().mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(root() / "state.sqlite3", timeout=10) as db:
        db.execute("CREATE TABLE IF NOT EXISTS state (id INTEGER PRIMARY KEY, body TEXT NOT NULL)")
        db.execute("BEGIN IMMEDIATE")
        yield db


def save(db: sqlite3.Connection, state: dict[str, Any]) -> None:
    db.execute("INSERT OR REPLACE INTO state VALUES (1, ?)", (json.dumps(state),))


def status() -> dict[str, Any]:
    from deeptutor.reading import component_plugins

    desired = read_state()
    components = component_plugins.status()
    return {
        "package": PACKAGE,
        "desired": desired,
        "active": ACTIVE_STATE,
        "restart_required": desired != ACTIVE_STATE or components["restart_required"],
        "components": components,
        "extensions": list(EXTENSIONS),
    }


def inspect_wheel(data: bytes) -> dict[str, str]:
    """Validate identity, layout and host compatibility without executing code."""
    import io

    if not data or len(data) > MAX_BYTES:
        raise ValueError("Wheel must be between 1 byte and 10 MB.")
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            infos = archive.infolist()
            names = [row.filename for row in infos]
            if len(names) > 200 or len(names) != len(set(names)):
                raise ValueError("Invalid wheel file inventory.")
            if sum(row.file_size for row in infos) > MAX_BYTES:
                raise ValueError("Expanded wheel exceeds 10 MB.")
            for row in infos:
                name = row.filename
                parts = PurePosixPath(name).parts
                if not parts or name.startswith("/") or ".." in parts or "\\" in name:
                    raise ValueError("Unsafe wheel path.")
                if (row.external_attr >> 16) & 0o170000 == 0o120000:
                    raise ValueError("Wheel cannot contain symbolic links.")
                if parts[0] != NAMESPACE and not parts[0].startswith(NAMESPACE + "-"):
                    raise ValueError("Wheel contains files outside the reading package.")
                if parts[0] != NAMESPACE and not parts[0].endswith(".dist-info"):
                    raise ValueError("Unsupported wheel metadata directory.")
                if not row.is_dir() and not name.endswith(
                    (".py", ".json", ".txt", "METADATA", "WHEEL", "RECORD", "LICENSE")
                ):
                    raise ValueError("Unsupported wheel content.")
            metas = [name for name in names if name.endswith(".dist-info/METADATA")]
            if len(metas) != 1:
                raise ValueError("Expected one distribution.")
            info = BytesParser().parsebytes(archive.read(metas[0]))
            if str(info["Name"]).replace("_", "-").lower() != PACKAGE:
                raise ValueError("This is not the reading extension bundle.")
            version = str(Version(str(info["Version"])))
            if Version(".".join(map(str, sys.version_info[:3]))) not in SpecifierSet(
                str(info["Requires-Python"] or "")
            ):
                raise ValueError("This wheel does not support the backend Python version.")
            requirements = [Requirement(row) for row in info.get_all("Requires-Dist", [])]
            if len(requirements) != 1 or requirements[0].name != "deeptutor" or requirements[0].url:
                raise ValueError("Wheel must depend only on the installed DeepTutor host.")
            if Version(__version__) not in requirements[0].specifier:
                raise ValueError("This wheel is incompatible with the installed DeepTutor version.")
            folder = metas[0].rsplit("/", 1)[0]
            wheel = BytesParser().parsebytes(archive.read(folder + "/WHEEL"))
            if wheel.get_all("Tag") != ["py3-none-any"]:
                raise ValueError("Only pure Python py3-none-any wheels are supported.")
            entries = configparser.ConfigParser(interpolation=None)
            entries.read_string(archive.read(folder + "/entry_points.txt").decode())
            if (
                entries.sections() != ["deeptutor.reading_extensions"]
                or dict(entries["deeptutor.reading_extensions"]) != EXTENSIONS
            ):
                raise ValueError("Wheel entry points do not match the three reading actions.")
            for target in EXTENSIONS.values():
                if target.split(":")[0].replace(".", "/") + ".py" not in names:
                    raise ValueError("Wheel is missing an extension implementation.")
            return {"version": version, "sha256": hashlib.sha256(data).hexdigest()}
    except (zipfile.BadZipFile, KeyError, UnicodeError, configparser.Error, RuntimeError) as exc:
        raise ValueError("Invalid reading extension wheel.") from exc


def install(data: bytes) -> dict[str, Any]:
    try:
        details = inspect_wheel(data)
    except ValueError:
        from deeptutor.reading import component_plugins

        component_plugins.install(data)
        return status()
    with transaction() as db:
        # Store immutable wheels; workers may still be running the previous one.
        filename = f"{details['sha256']}.whl"
        destination = root() / filename
        if not destination.exists():
            fd, temporary = tempfile.mkstemp(dir=root(), suffix=".tmp")
            try:
                with os.fdopen(fd, "wb") as stream:
                    stream.write(data)
                os.replace(temporary, destination)
            finally:
                Path(temporary).unlink(missing_ok=True)
        previous = db.execute("SELECT body FROM state WHERE id=1").fetchone()
        disabled = json.loads(previous[0]).get("disabled", []) if previous else []
        save(db, {"mode": "managed", **details, "wheel": filename, "disabled": disabled})
    return status()


def configure(mode: str | None = None, extension: str | None = None, enabled: bool = True):
    if mode not in (None, "builtin", "disabled"):
        raise ValueError("Invalid plugin mode.")
    if extension is not None and extension not in EXTENSIONS:
        raise ValueError("Unknown reading extension.")
    with transaction() as db:
        row = db.execute("SELECT body FROM state WHERE id=1").fetchone()
        state = json.loads(row[0]) if row else dict(ACTIVE_STATE)
        if mode is not None:
            state = {"mode": mode, "disabled": []}
        if extension:
            disabled = set(state.get("disabled", []))
            disabled.discard(extension) if enabled else disabled.add(extension)
            state["disabled"] = sorted(disabled)
        save(db, state)
    return status()


def load_overrides() -> tuple[dict[str, Any], set[str]]:
    """Load the startup snapshot, or the explicitly installed pip distribution."""
    state = ACTIVE_STATE
    blocked = set(state.get("disabled", []))
    if state["mode"] == "disabled":
        return {}, set(EXTENSIONS)
    if state["mode"] == "managed":
        path = root() / state["wheel"]
        data = path.read_bytes()
        if inspect_wheel(data)["sha256"] != state["sha256"]:
            raise ValueError("Installed reading wheel checksum mismatch.")
        # The wheel is namespace-restricted and cannot shadow host dependencies.
        sys.path.insert(0, str(path))
        return {
            name: getattr(import_module(target.split(":")[0]), target.split(":")[1])
            for name, target in EXTENSIONS.items()
        }, blocked
    # pip installation remains usable when no managed choice has been made.
    if state["mode"] == "pip":
        try:
            dist = metadata.distribution(PACKAGE)
        except metadata.PackageNotFoundError:
            return {}, blocked
        eps = {
            ep.name: ep for ep in dist.entry_points if ep.group == "deeptutor.reading_extensions"
        }
        if {name: ep.value for name, ep in eps.items()} != EXTENSIONS:
            raise ValueError("Invalid installed reading bundle entry points.")
        return {name: ep.load() for name, ep in eps.items()}, blocked
    return {}, blocked


def download_latest(package: str = PACKAGE) -> dict[str, Any]:
    """Download a checksum-verified wheel from the fixed release repository."""
    available = {
        PACKAGE,
        "deeptutor-reading-read-aloud",
        "deeptutor-reading-vocabulary",
        "deeptutor-reading-quiz",
        "deeptutor-reading-dictionary-example",
    }
    if package not in available:
        raise ValueError("Unknown published reading package; upload a trusted wheel instead.")
    with httpx.Client(timeout=30, follow_redirects=True) as client:
        response = client.get(f"https://api.github.com/repos/{RELEASE_REPO}/releases/latest")
        response.raise_for_status()
        assets = response.json().get("assets", [])
        wheels = [
            row
            for row in assets
            if row.get("name", "").startswith(package.replace("-", "_") + "-")
            and row["name"].endswith("-py3-none-any.whl")
        ]
        if len(wheels) != 1:
            raise ValueError("Latest release must contain exactly one reading wheel.")
        asset = wheels[0]
        digest = str(asset.get("digest", ""))
        if not digest.startswith("sha256:") or len(digest) != 71:
            raise ValueError("Release asset has no SHA-256 digest.")
        url = str(asset.get("browser_download_url", ""))
        parsed = urlparse(url)
        if (
            parsed.scheme != "https"
            or parsed.netloc != "github.com"
            or not parsed.path.startswith(f"/{RELEASE_REPO}/releases/download/")
        ):
            raise ValueError("Invalid release download URL.")
        data = bytearray()
        with client.stream("GET", url) as stream:
            stream.raise_for_status()
            for chunk in stream.iter_bytes():
                data.extend(chunk)
                if len(data) > MAX_BYTES:
                    raise ValueError("Wheel exceeds 10 MB.")
        if hashlib.sha256(data).hexdigest() != digest[7:]:
            raise ValueError("Downloaded wheel checksum mismatch.")
    return install(bytes(data))
