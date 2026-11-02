# Open DeepTutor for MacOS and Windows

A double-clickable desktop app for DeepTutor. On first launch it installs its
bundled runtime, starts the Python and Node services on loopback, and opens
the complete DeepTutor web UI in its window. Users need no terminal, Python,
Node, npm, Git or source checkout.

This is a preview. Models and providers are configured in DeepTutor's normal
Settings; no credentials or user data ship with the app. Optional external
tools (Manim/LaTeX, partner CLIs, remote services) keep their usual
requirements.

## Editions

| Target        | Name                                          | Short                   | Downloads                                                  |
| ------------- | --------------------------------------------- | ----------------------- | ---------------------------------------------------------- |
| `macos-arm64` | Open DeepTutor for MacOS with Apple Silicon   | MacOS (Apple Silicon)   | `Open-DeepTutor-MacOS-Apple-Silicon-v<version>.dmg`        |
| `macos-x64`   | Open DeepTutor for MacOS with Intel Silicon   | MacOS (Intel)           | `Open-DeepTutor-MacOS-Intel-v<version>.dmg`                |
| `windows-x64` | Open DeepTutor for Windows                    | Windows                 | `Open-DeepTutor-Windows-v<version>-Setup.exe`, `…-Portable.zip` |

- The app version is the DeepTutor version it bundles, read from
  `deeptutor/__version__.py` via the sealed runtime, so `package.json` stays at
  `0.0.0`. The start screen and About show the full name with the version;
  the web UI's sidebar uses the short name, and Settings → About shows both.
  The web UI recognises the app by the `OpenDeepTutor/<version> (macOS; arm64)`
  user-agent marker (`(macOS; x64)`, `(Windows; x64)`); names live in
  `src/platform.mjs` and `web/lib/version.ts`.
- The shell (start screen, menus, dialogs) starts in English and then follows
  the interface language and theme chosen in DeepTutor's Settings
  (`data/user/settings/interface.json`), including live changes. Copy lives in
  `src/i18n.mjs` for every language the web UI ships.

## Layout

```
src/                  the shell, shared by every platform
  platform.mjs        every run-time difference between MacOS and Windows
scripts/              build-runtime, seal-runtime, smoke, package (all take --target)
  lib/                target loading, app staging, MacOS packaging
platforms/
  macos-arm64/        target.mjs (Python/Node builds) + package.mjs (DMG)
  macos-x64/          target.mjs + package.mjs (DMG)
  windows-x64/        target.mjs + package.mjs (zip) + installer.nsi (Setup.exe)
```

Every build file of a target goes to `.local/<target>/`; downloads go to `out/`.

## Components

- **Shell**: Electron window, native menus, downloads, runtime supervision.
- **Core bundle**: Python source and modules, the production Next.js standalone
  build, Python 3.12.13 and Node 22.23.4 for the target, built from a
  committed revision.
- **Protocol 1**: the shell only manages startup, readiness, shutdown and core
  artifacts. No business API or React components are copied into the shell.

|          | MacOS                                                  | Windows                                   |
| -------- | ------------------------------------------------------ | ----------------------------------------- |
| Data     | `~/Library/Application Support/Open DeepTutor/workspace/data` | `%LOCALAPPDATA%\Open DeepTutor\workspace\data` |
| Runtimes | `…/Open DeepTutor/runtimes/<runtime-id>`               | same, under `%LOCALAPPDATA%`              |
| Logs     | `…/Open DeepTutor/logs/runtime.log`                    | same, under `%LOCALAPPDATA%`              |
| Window   | the shell's own title bar under the traffic lights     | native title bar and menu bar             |
| Shutdown | SIGTERM to each service's process group, then SIGKILL  | `taskkill /T /F` on each service's tree   |

Quitting stops the services this app started. It does not stop a separately
running `deeptutor start`. Web content has no preload, Node integration or
desktop IPC privileges; only the private shell page owns the native bridge.

## Build

Prerequisites (developers only): Node/npm and `uv`. MacOS targets build on a
Mac (`macos-x64` also on Apple Silicon, through Rosetta); `windows-x64` builds
on Windows 10+ with NSIS (`makensis`) installed.

```sh
cd apps/desktop
npm ci
npm run check && npm test
npm run build:runtime -- --target macos-arm64   # snapshots this checkout's committed HEAD
npm run smoke -- --target macos-arm64           # boots the bundled core with no developer tools on PATH
npm run package -- --target macos-arm64         # out/Open-DeepTutor-MacOS-Apple-Silicon-v<version>.dmg
```

`--target` defaults to the computer you build on. Every build step (npm, Next)
runs on the target's own Node, so native packages match the target
architecture. `build:runtime` uses `git archive HEAD`, so commit first;
uncommitted changes are not bundled. Set `DEEPTUTOR_SOURCE` to build another
checkout. `npm start` runs the shell against this computer's bundled core.
`npm run icon` regenerates `assets/icon.icns` and `assets/icon.ico` from
`assets/mark.png` (MacOS only).

## Signing

- **Core bundles** are signed with one Ed25519 key for every platform; the
  manifest binds platform and architecture, so a bundle only installs on the
  edition it was built for. The private key is `.local/signing-private.pem`
  (ignored) or the `OPEN_DEEPTUTOR_SIGNING_KEY` environment variable; only
  `assets/runtime-public.pem` ships. Sealing refuses a key that does not match
  the public key. Keep a secure backup: losing it means shipped apps can no
  longer accept core updates. `--new-key` deliberately starts a new identity.
- **The MacOS apps** are signed ad hoc by default. Set `APPLE_SIGNING_IDENTITY`
  to a Developer ID Application identity during both runtime building and app
  packaging. Native code in the bundled Python, Node and Web dependencies is
  signed with secure timestamps before the core archive is sealed; interpreter
  entitlements live in `assets/entitlements.runtime.mac.plist`. The outer app
  uses `assets/entitlements.mac.plist`. Then notarize the DMG with
  `node scripts/notarize.mjs`; only an Accepted result is stapled and validated.
- **The Windows app** is unsigned; SmartScreen asks for confirmation on first
  open until an Authenticode certificate is added.

## Releases

`.github/workflows/desktop-release.yml` runs when a DeepTutor GitHub Release is
published. For each target it verifies the tag matches
`deeptutor/__version__.py`, builds and smoke-tests the runtime, packages the
app and attaches the downloads to the release. It needs the
`DESKTOP_RUNTIME_SIGNING_KEY` secret; Developer ID signing and notarization run
when the Apple secrets listed in the workflow are present. Pull requests that
touch `apps/desktop` run the same builds with a throwaway key and keep the
downloads as workflow artifacts instead of publishing them.

Pushes to `dev` that change the desktop app also build all three targets with
the configured runtime key and Apple signing credentials, keeping the results
as workflow artifacts without publishing a release. Manual runs default to the
same validation mode on the selected branch. To attach downloads to an existing
release, explicitly enable `publish` and supply its tag. GitHub only exposes the
manual entry point after the workflow reaches the default branch. Apple
notarization additionally needs `APPLE_ID` and `APPLE_APP_PASSWORD`; a Developer
ID signature alone does not mean the app is notarized. Windows Authenticode
signing is not configured by this workflow.

## Core updates

The shell never `git pull`s or mutates a running Python environment. **Core →
Install Core Update…** accepts a signed `runtime.json` beside its `.tar.gz`.
The app verifies the signature, SHA-256, platform, architecture and protocol,
installs into a new version directory, backs up the desktop workspace, then
starts the candidate. A failed or interrupted trial restores the previous
runtime and workspace. Backups are kept. Automatic update discovery is not
connected yet.

## Verification

`npm test` covers edition names, language resolution, config validation,
signature and platform rejection, process shutdown, cancellation and local
service behaviour; CI runs it on Linux and Windows. `npm run smoke` boots the
real bundled core in a fresh temporary workspace, checks backend, frontend and
API proxy, then verifies both ports close. It does not call a paid model or
test optional external renderers. Windows CI also runs
`platforms/windows-x64/smoke-installer.ps1`: it silently installs the app,
opens the actual Electron window with a fresh data path containing spaces and
Chinese characters, checks UI/API readiness and service shutdown on window
close, then verifies uninstall preserves learning data and unrelated files.
`OPEN_DEEPTUTOR_TEST_HOME` selects a disposable desktop home for UI checks.
