#!/usr/bin/env python
"""Create / refresh the Windows desktop shortcut for the DeepTutor shell.

The `.lnk` is written byte-for-byte by `scripts/lnk.py` instead of driving
`WScript.Shell` through COM, so the helper works in locked-down environments
where COM instantiation is unavailable. See that module for the format traps
it works around.

Usage:
    python scripts/make-shortcut.py                    # desktop only
    python scripts/make-shortcut.py --start-menu       # + Start Menu entry
    python scripts/make-shortcut.py --source-mode      # ignore packaged build
    python scripts/make-shortcut.py --remove           # delete what we created

Two launch targets are supported, chosen automatically:

  packaged  release/<ver>/win-unpacked/DeepTutor.exe  (preferred, newest win)
  source    node_modules/electron/dist/electron.exe  + path to this folder

A packaged install cannot see the checkout on its own (its app root is the
unpacked folder), so the script also writes `service.home` / `service.pythonPath`
into the app's own config unless they are already set. That is what lets you
double-click the shortcut without passing any CLI flags.
"""

from __future__ import annotations

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import lnk  # noqa: E402  (path bootstrap above)

SHORTCUT_NAME = "DeepTutor Desktop"
DESCRIPTION = "DeepTutor Desktop - local learning workspace"

DESKTOP = "desktop"
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO_ROOT = os.path.dirname(ROOT)


# --------------------------------------------------------------------------- #
# discovery
# --------------------------------------------------------------------------- #


def find_packaged_exe() -> str | None:
    """Newest `release/*/win-unpacked/DeepTutor.exe`, if any."""
    release = os.path.join(ROOT, "release")
    if not os.path.isdir(release):
        return None
    candidates = []
    for entry in os.listdir(release):
        exe = os.path.join(release, entry, "win-unpacked", "DeepTutor.exe")
        if os.path.isfile(exe):
            candidates.append(exe)
    if not candidates:
        return None
    candidates.sort(key=lambda p: os.path.getmtime(p), reverse=True)
    return candidates[0]


def find_source_electron() -> str | None:
    for rel in ("electron.exe",):
        exe = os.path.join(ROOT, "node_modules", "electron", "dist", rel)
        if os.path.isfile(exe):
            return exe
    return None


def find_python() -> str | None:
    """Prefer the checkout's virtualenv; else whatever is on PATH."""
    venv = os.path.join(REPO_ROOT, ".venv", "Scripts", "python.exe")
    if os.path.isfile(venv):
        return venv
    import shutil

    return shutil.which("python") or shutil.which("python3")


def find_icon() -> str:
    ico = os.path.join(ROOT, "build", "icon.ico")
    return ico if os.path.isfile(ico) else ""


def user_data_dir() -> str:
    appdata = os.environ.get("APPDATA") or os.path.expanduser("~")
    return os.path.join(appdata, "DeepTutor")


def desktop_dir() -> str:
    """The real Desktop, even when the profile lives under OneDrive."""
    home = os.path.expanduser("~")
    for candidate in (os.path.join(home, "Desktop"), os.path.join(home, "OneDrive", "Desktop")):
        if os.path.isdir(candidate):
            return candidate
    if sys.platform == "win32":
        from winreg import HKEY_CURRENT_USER, OpenKey, QueryValueEx  # type: ignore

        key = OpenKey(
            HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Explorer\User Shell Folders",
        )
        value = QueryValueEx(key, "Desktop")[0]
        return os.path.expandvars(value)
    return home


def start_menu_dir() -> str:
    appdata = os.environ.get("APPDATA") or os.path.expanduser("~")
    return os.path.join(appdata, "Microsoft", "Windows", "Start Menu", "Programs")


# --------------------------------------------------------------------------- #
# packaged config bootstrap
# --------------------------------------------------------------------------- #


def ensure_service_config(home: str, python_path: str | None) -> str | None:
    """Record `service.home` / `service.pythonPath` if the user has not set them."""
    target_dir = user_data_dir()
    config_path = os.path.join(target_dir, "config.json")
    existing = {}
    if os.path.isfile(config_path):
        try:
            with open(config_path, encoding="utf-8") as handle:
                existing = json.load(handle)
        except (OSError, ValueError):
            backup = config_path + ".bak"
            os.replace(config_path, backup)
            print(f"[warn] config.json was unreadable; moved it to {backup}")
            existing = {}

    service = existing.get("service") if isinstance(existing.get("service"), dict) else {}
    changed = False
    if not service.get("home"):
        service["home"] = home
        changed = True
    if python_path and not service.get("pythonPath"):
        service["pythonPath"] = python_path
        changed = True

    if not changed:
        print(f"[skip] {config_path} already sets service.home / service.pythonPath")
        return None

    existing["service"] = service
    os.makedirs(target_dir, exist_ok=True)
    tmp = config_path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as handle:
        json.dump(existing, handle, ensure_ascii=False, indent=2)
    os.replace(tmp, config_path)
    print(f"[ok] wrote {config_path}: service.home={home}")
    if python_path:
        print(f"     service.pythonPath={python_path}")
    return config_path


# --------------------------------------------------------------------------- #
# shortcut
# --------------------------------------------------------------------------- #


def build_shortcut(exe: str, arguments: str, workdir: str) -> bytes:
    icon = find_icon() or f"{exe},0"
    return lnk.build_lnk(
        target=exe,
        arguments=arguments,
        working_dir=workdir,
        description=DESCRIPTION,
        icon_location=icon,
        icon_index=0,
        show_command=lnk.SHOW_NORMAL,
    )


def resolve_target(prefer_source: bool):
    if not prefer_source:
        exe = find_packaged_exe()
        if exe:
            return {
                "exe": exe,
                "arguments": "",
                "workdir": os.path.dirname(exe),
                "mode": "packaged",
            }
    exe = find_source_electron()
    if exe:
        return {
            "exe": exe,
            "arguments": f'"{ROOT}"',
            "workdir": ROOT,
            "mode": "source",
        }
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description="Create the DeepTutor Desktop shortcut.")
    parser.add_argument("--start-menu", action="store_true", help="also create a Start Menu entry")
    parser.add_argument("--source-mode", action="store_true", help="ignore packaged builds and launch from source")
    parser.add_argument("--no-config", action="store_true", help="do not touch the app config")
    parser.add_argument("--remove", action="store_true", help="delete the shortcuts this script created")
    parser.add_argument("--dir", help="override the shortcut directory (debugging)")
    args = parser.parse_args()

    targets = []
    if args.dir:
        targets.append(args.dir)
    else:
        targets.append(desktop_dir())
        if args.start_menu:
            targets.append(start_menu_dir())

    if args.remove:
        removed = False
        for directory in targets:
            path = os.path.join(directory, f"{SHORTCUT_NAME}.lnk")
            if os.path.isfile(path):
                os.remove(path)
                print(f"[ok] removed {path}")
                removed = True
        if not removed:
            print("[skip] no shortcut found")
        return 0

    if sys.platform != "win32":
        print("[error] .lnk files only matter on Windows; run the app binary instead", file=sys.stderr)
        return 1

    target = resolve_target(args.source_mode)
    if not target:
        print(
            "[error] no launch target found: run `npm run pack` first, or "
            "`npm install` for a source-mode launch",
            file=sys.stderr,
        )
        return 1

    print(f"[info] target ({target['mode']}): {target['exe']}")
    if target["arguments"]:
        print(f"[info] arguments: {target['arguments']}")

    if not args.no_config:
        ensure_service_config(REPO_ROOT, find_python())
    else:
        print("[skip] config untouched; a packaged build may fail to locate the workspace")

    blob = build_shortcut(target["exe"], target["arguments"], target["workdir"])
    created = []
    for directory in targets:
        os.makedirs(directory, exist_ok=True)
        path = os.path.join(directory, f"{SHORTCUT_NAME}.lnk")
        with open(path, "wb") as handle:
            handle.write(blob)
        created.append(path)
        print(f"[ok] shortcut -> {path}")

    print(f"\ndone: {len(created)} shortcut(s), {len(blob)} bytes, named \"{SHORTCUT_NAME}\"")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
