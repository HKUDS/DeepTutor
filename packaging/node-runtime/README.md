# Bundled Node.js for DeepTutor Electron

Electron’s launcher needs `node` to run the packaged Next.js `server.js`.
This folder holds a portable Node 22 distribution shipped as `node-runtime/`
beside the app (win/linux) or under `Contents/` (mac).

## Prepare

```bash
# Linux / macOS / Windows
python packaging/node-runtime/prepare.py
```

Wrappers:

```bash
bash packaging/node-runtime/prepare.sh
powershell -File packaging/node-runtime/prepare.ps1
```

Downloads Node **v22.23.2** for the current platform into
`packaging/node-runtime/<plat-arch>/` and stages
`dist/packaging-sidecar/node-runtime/` for electron-builder.

## Layout after prepare

```text
packaging/node-runtime/linux-x64/node
packaging/node-runtime/macos-arm64/node
packaging/node-runtime/win-x64/node.exe
…
dist/packaging-sidecar/node-runtime/   # copy used by electron-builder
```
