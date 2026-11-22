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

Starting with the release after v1.7.1, every release must include both macOS
architectures: Apple Silicon (`macos-arm64`) and Intel (`macos-x64`), alongside
the Windows installer and portable ZIP. The `verify-release` job requires all
three builds to succeed and checks that all four versioned downloads and their
unversioned aliases are uploaded and nonempty. A missing Intel DMG means the
desktop release is incomplete; fix and rerun the failed build before reporting
the release as complete.

`.github/workflows/desktop-release.yml` runs when a DeepTutor GitHub Release is
published. For each target it verifies the tag matches
`deeptutor/__version__.py`, builds and smoke-tests the runtime, packages the
app and attaches the downloads to the release. Signed builds read the runtime
key and Apple signing and notarization credentials from the protected
`desktop-release` environment after deployment approval.

Pull requests, pushes to `dev` and manual branch validations use disposable
runtime keys. To validate signing, dispatch the workflow on a version tag.
To attach downloads to an existing release, select that same tag as the
workflow ref and the tag input, and enable `publish`. The notarization
diagnostics workflow also runs manually on version tags. Windows Authenticode
signing is not configured by this workflow.

## Core updates

The shell never `git pull`s or mutates a running Python environment. **Core →
Install Core Update…** accepts a signed `runtime.json` beside its `.tar.gz`.
The app verifies the signature, SHA-256, platform, architecture and protocol,
installs into a new version directory, backs up the desktop workspace, then
starts the candidate. A failed or interrupted trial restores the previous
runtime and workspace. Backups are kept. Automatic update discovery is not
connected yet.

Installing a newer app over an older one works the same way: on the next start,
a bundled core whose `coreVersion` is newer than the active one is installed and
trialled with the same backup and rollback. A bundled core that fails its trial
is not tried again, and an older bundled core never replaces a newer one that
was installed by hand.

## ChatGPT Plan privacy notice

Open DeepTutor Desktop offers an optional ChatGPT Plan connection in **Settings → Providers** for single-user local installations. You sign in on OpenAI's website and decide there whether to allow eligible requests to use your plan. Using the connection in DeepTutor is free. Account eligibility and usage limits are set by OpenAI.

Open **DeepTutor data notice** on the provider card for the in-app privacy information. You can save separate ChatGPT accounts or ChatGPT workspaces, give each registration a recognizable local name, and choose which to activate through OpenAI sign-in. One registration is active at a time.

- **Account data on your device.** DeepTutor keeps the account identifier and display label, the OAuth registration, and encrypted credentials in the local Desktop profile. The operating system's credential store protects the encryption key. DeepTutor uses this information to show the connected account, refresh the connection, list available models, and send requests you initiate.
- **Requests sent to OpenAI.** When you use a ChatGPT Plan model, DeepTutor sends your message and relevant context. This can include prior messages, instructions, or text from workspace content, depending on your settings and conversation. A manual model connection test sends a short test prompt. Automatic titles and scheduled tasks do not use this connection.
- **Your controls.** Disconnect in **Settings → Providers → ChatGPT Plan** to stop using the active registration locally and request revocation. The local account label and registration remain for future sign-ins. You can revoke access and manage limits in [ChatGPT usage settings](https://chatgpt.com/settings/usage). Disconnecting preserves your DeepTutor chats. Remove the local Desktop profile to erase its remaining data. Use the [private security reporting form](https://github.com/HKUDS/DeepTutor/security/advisories/new) for security concerns.

DeepTutor detects remote revocation when a subsequent request and token refresh confirm the grant is invalid. It clears the affected registration's tokens and offers sign-in again. Temporary network errors preserve the registration and its credentials.

The encrypted vault is stored outside the workspace so app-managed upgrade backups cannot restore old credentials. If remote revocation fails after disconnecting, DeepTutor retains an encrypted token only for revocation retries. Inference stops locally. Use **Retry revocation** next to that account or revoke access in ChatGPT settings and retry.

Only cores that advertise the isolated vault in their signed manifest can receive the vault key. If a Desktop update rolls back to an older core, the saved connections become available when a compatible core starts.

When you regenerate a ChatGPT Plan reply, DeepTutor keeps existing replies as alternatives. A failed or cancelled regeneration leaves the saved reply in place.

OpenAI processes data it receives under its [Privacy Policy](https://openai.com/policies/privacy-policy/). See the [Sign in with ChatGPT Terms](https://openai.com/policies/sign-in-with-chatgpt-terms/) for the requirements that apply to this connection. Do not submit personal information about children under 13 or the applicable age of digital consent.

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
