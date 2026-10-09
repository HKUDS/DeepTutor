# DeepTutor PyInstaller backend (cross-platform onedir)

Produces a self-contained **onedir** CLI at:

```text
dist/pyinstaller/<plat-arch>/deeptutor/deeptutor[.exe]
```

and stages it for electron-builder at:

```text
dist/packaging-sidecar/python-backend/
```

Electron launches `python-backend/deeptutor[.exe] start --home … --no-browser`.
Web assets (`deeptutor_web`) and Node are **not** inside this bundle.

| Tag example   | Binary                         |
| ------------- | ------------------------------ |
| `win-x64`     | `deeptutor.exe`                |
| `linux-x64`   | `deeptutor`                    |
| `linux-arm64` | `deeptutor`                    |
| `macos-arm64` | `deeptutor`                    |
| `macos-x64`   | `deeptutor`                    |

## Prerequisites

- Python 3.11–3.14 in a **writable** venv with DeepTutor importable
- PyInstaller 6.x (installed by the build script)

## Build

```bash
# Linux / macOS
python packaging/pyinstaller/build.py
# or
bash packaging/pyinstaller/build.sh

# Windows
powershell -ExecutionPolicy Bypass -File packaging/pyinstaller/build.ps1
```

Options:

```bash
python packaging/pyinstaller/build.py --python /path/to/python --skip-smoke
python packaging/pyinstaller/build.py --no-stage   # skip packaging-sidecar copy
```

## Notes

- **No DeepTutor library source changes** — frozen adaptations live only in
  `packaging/pyinstaller/frozen_support.py` (applied from `entry.py`).
- Build on the **same OS/arch** you ship (PyInstaller does not cross-compile).
