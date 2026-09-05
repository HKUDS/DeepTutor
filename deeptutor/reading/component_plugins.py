"""Independently installed providers for the three reading action slots."""

from __future__ import annotations

import configparser
from email.parser import BytesParser
import hashlib
from importlib import import_module
import io
import json
import os
from pathlib import PurePosixPath
import re
import sqlite3
import sys
import zipfile

from packaging.requirements import Requirement
from packaging.specifiers import SpecifierSet
from packaging.version import Version

from deeptutor.__version__ import __version__
from deeptutor.runtime.home import get_runtime_home

SLOTS = {"read_aloud", "vocabulary", "quiz"}
DEFAULT = {"packages": {}, "providers": {}}
MAX_BYTES = 10 * 1024 * 1024


def root():
    return get_runtime_home() / "data" / "system" / "reading-providers"


def read_state():
    file = root() / "state.sqlite3"
    if not file.exists():
        return {"packages": {}, "providers": {}}
    with sqlite3.connect(f"{file.as_uri()}?mode=ro", uri=True) as db:
        row = db.execute("SELECT body FROM state WHERE id=1").fetchone()
    return json.loads(row[0]) if row else {"packages": {}, "providers": {}}


ACTIVE = read_state()
ERRORS = {}


def status():
    desired = read_state()
    return {
        "active": ACTIVE,
        "desired": desired,
        "restart_required": desired != ACTIVE,
        "errors": dict(ERRORS),
    }


def inspect(data):
    if not data or len(data) > MAX_BYTES:
        raise ValueError("Provider wheel must be between 1 byte and 10 MB.")
    try:
        with zipfile.ZipFile(io.BytesIO(data)) as archive:
            rows = archive.infolist()
            names = [row.filename for row in rows]
            if (
                len(names) > 200
                or len(set(names)) != len(names)
                or sum(row.file_size for row in rows) > MAX_BYTES
            ):
                raise ValueError("Invalid provider wheel inventory.")
            metas = [name for name in names if name.endswith(".dist-info/METADATA")]
            if len(metas) != 1:
                raise ValueError("Expected one provider distribution.")
            metadata = BytesParser().parsebytes(archive.read(metas[0]))
            package = str(metadata["Name"]).lower().replace("_", "-")
            if (
                not re.fullmatch(r"deeptutor-reading-[a-z][a-z0-9-]{0,48}", package)
                or package == "deeptutor-reading-extensions"
            ):
                raise ValueError("Provider package must use a unique deeptutor-reading-* name.")
            namespace = package.replace("-", "_")
            folder = metas[0].rsplit("/", 1)[0]
            for row in rows:
                path = PurePosixPath(row.filename)
                if (
                    path.is_absolute()
                    or ".." in path.parts
                    or "\\" in row.filename
                    or not path.parts
                    or path.parts[0] not in (namespace, folder)
                ):
                    raise ValueError("Provider files must stay inside their unique namespace.")
                if (row.external_attr >> 16) & 0o170000 == 0o120000:
                    raise ValueError("Provider wheel cannot contain symbolic links.")
                if not row.is_dir() and not row.filename.endswith(
                    (".py", ".json", ".txt", "METADATA", "WHEEL", "RECORD", "LICENSE")
                ):
                    raise ValueError("Unsupported provider wheel content.")
            version = str(Version(str(metadata["Version"])))
            if Version(".".join(map(str, sys.version_info[:3]))) not in SpecifierSet(
                str(metadata["Requires-Python"] or "")
            ):
                raise ValueError("Provider does not support this Python version.")
            deps = [Requirement(value) for value in metadata.get_all("Requires-Dist", [])]
            if (
                len(deps) != 1
                or deps[0].name != "deeptutor"
                or deps[0].url
                or Version(__version__) not in deps[0].specifier
            ):
                raise ValueError("Provider must depend only on a compatible DeepTutor host.")
            wheel = BytesParser().parsebytes(archive.read(folder + "/WHEEL"))
            if wheel.get_all("Tag") != ["py3-none-any"]:
                raise ValueError("Provider must be a pure Python wheel.")
            manifest = json.loads(archive.read(namespace + "/reading_plugin.json"))
            if (
                manifest.get("protocol") != "1"
                or not isinstance(manifest.get("name"), str)
                or not 1 <= len(manifest["name"]) <= 80
            ):
                raise ValueError("Invalid reading provider manifest.")
            entries = configparser.ConfigParser(interpolation=None)
            entries.read_string(archive.read(folder + "/entry_points.txt").decode())
            if entries.sections() != ["deeptutor.reading_extensions"]:
                raise ValueError("Invalid provider entry-point group.")
            targets = dict(entries["deeptutor.reading_extensions"])
            if (
                not targets
                or len(targets) > 12
                or not all(re.fullmatch(r"[a-z][a-z0-9_-]{0,63}", slot) for slot in targets)
            ):
                raise ValueError("Provider must implement a supported reading slot.")
            for target in targets.values():
                if (
                    not re.fullmatch(namespace + r"\.[a-zA-Z_]\w*:[a-zA-Z_]\w*", target)
                    or target.split(":")[0].replace(".", "/") + ".py" not in names
                ):
                    raise ValueError("Provider entry point must be inside its namespace.")
            return {
                "package": package,
                "name": manifest["name"],
                "version": version,
                "targets": targets,
                "sha256": hashlib.sha256(data).hexdigest(),
            }
    except (
        zipfile.BadZipFile,
        KeyError,
        UnicodeError,
        configparser.Error,
        RuntimeError,
        TypeError,
    ) as exc:
        raise ValueError("Invalid reading provider wheel.") from exc


def mutate(change):
    root().mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(root() / "state.sqlite3", timeout=10) as db:
        db.execute("CREATE TABLE IF NOT EXISTS state (id INTEGER PRIMARY KEY, body TEXT NOT NULL)")
        db.execute("BEGIN IMMEDIATE")
        row = db.execute("SELECT body FROM state WHERE id=1").fetchone()
        state = json.loads(row[0]) if row else {"packages": {}, "providers": {}}
        change(state)
        db.execute("INSERT OR REPLACE INTO state VALUES (1, ?)", (json.dumps(state),))
    return status()


def install(data):
    details = inspect(data)

    def change(state):
        path = root() / (details["sha256"] + ".whl")
        if not path.exists():
            temporary = path.with_suffix(".tmp")
            temporary.write_bytes(data)
            os.replace(temporary, path)
        previous = state["packages"].get(details["package"])
        if previous and not set(previous["targets"]) <= set(details["targets"]):
            raise ValueError("Provider updates cannot remove installed action slots.")
        state["packages"][details["package"]] = details
        # Installing never silently replaces an administrator's chosen provider.

    return mutate(change)


def select(slot, package):
    if not re.fullmatch(r"[a-z][a-z0-9_-]{0,63}", slot):
        raise ValueError("Unknown reading action.")

    def change(state):
        if package:
            details = state["packages"].get(package)
            if not details or slot not in details["targets"]:
                raise ValueError("Provider is not installed for this action.")
            state["providers"][slot] = package
        else:
            state["providers"].pop(slot, None)

    return mutate(change)


def uninstall(package):
    def change(state):
        if package not in state["packages"]:
            raise ValueError("Provider is not installed.")
        state["packages"].pop(package)
        state["providers"] = {
            slot: value for slot, value in state["providers"].items() if value != package
        }

    return mutate(change)


def load():
    from deeptutor.reading.extensions import _coerce

    overrides = {}
    blocked = set()
    for slot, package in ACTIVE["providers"].items():
        try:
            details = ACTIVE["packages"][package]
            path = root() / (details["sha256"] + ".whl")
            checked = inspect(path.read_bytes())
            if checked != details:
                raise ValueError("Provider checksum or metadata changed.")
            sys.path.insert(0, str(path))
            module, name = details["targets"][slot].split(":")
            provider = _coerce(slot, getattr(import_module(module), name))
            if provider is None:
                raise ValueError("Provider manifest does not match its action slot.")
            overrides[slot] = provider
        except Exception as exc:
            ERRORS[slot] = str(exc)
            blocked.add(slot)
    return overrides, blocked
