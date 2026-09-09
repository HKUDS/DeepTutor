# Bundled Node.js for DeepTutor Electron (Windows x64)

Electron’s launcher needs `node` to run the packaged Next.js `server.js`.
This folder holds a portable Node 22 distribution shipped as `node-runtime/`
next to `DeepTutor.exe`.

## Prepare

```powershell
powershell -ExecutionPolicy Bypass -File packaging/node-runtime/prepare.ps1
```

Uses the cached zip at `node-runtime-bundle/node-v22.23.2-win-x64.zip` and
writes `win-x64/node.exe`.

## Layout after prepare

```text
packaging/node-runtime/win-x64/node.exe
packaging/node-runtime/win-x64/npm.cmd
...
```

`electron-builder.yml` copies `win-x64` → `node-runtime` in the app package.
