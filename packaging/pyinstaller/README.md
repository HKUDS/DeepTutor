# DeepTutor PyInstaller backend (Windows x64)

Produces a self-contained **onedir** CLI at:

```text
dist/pyinstaller/win-x64/deeptutor/deeptutor.exe
```

Electron packs this folder as `python-backend` and launches
`deeptutor.exe start --home <APPDATA/DeepTutor> --no-browser`.
Web assets (`deeptutor_web`) and Node are **not** inside this bundle —
electron-builder ships them beside the exe.

## Prerequisites

- Python 3.11–3.14 in a **writable** venv (or conda env) with DeepTutor importable
- PyInstaller 6.x (installed automatically via `uv pip` or `pip`)
- Do **not** point `-Python` at `packaging/python-runtime/…` unless PyInstaller
  already imports there — that tree is uv-managed (`EXTERNALLY-MANAGED`) and is
  skipped by default

## Build

From the repository root (activate your DeepTutor env first):

```powershell
# e.g. conda activate deeptutor   OR   .\.venv\Scripts\Activate.ps1
powershell -ExecutionPolicy Bypass -File packaging/pyinstaller/build.ps1
```

Optional:

```powershell
# Use a specific interpreter
powershell -File packaging/pyinstaller/build.ps1 -Python E:\path\to\python.exe

# Skip --help smoke checks
powershell -File packaging/pyinstaller/build.ps1 -SkipSmoke
```

## Smoke

```powershell
.\dist\pyinstaller\win-x64\deeptutor\deeptutor.exe --help
.\dist\pyinstaller\win-x64\deeptutor\deeptutor.exe serve --help
```

## Notes

- **No DeepTutor library source changes** — frozen adaptations live only in
  `packaging/pyinstaller/frozen_support.py` and are applied from `entry.py`.
- Frozen child processes rewrite `python -m …` argv (uvicorn / CLI / workers)
  onto `deeptutor.exe serve` / subcommands / `--isolated-worker`.
- Set `DEEPTUTOR_WEB_DIR` to the packaged Next standalone folder when web
  assets live outside the frozen package (Electron does this).
- Do **not** point `-Python` at `packaging/python-runtime/…` unless PyInstaller
  already imports there — that tree is uv-managed (`EXTERNALLY-MANAGED`) and is
  skipped by default.