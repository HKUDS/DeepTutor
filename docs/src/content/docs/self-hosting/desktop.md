---
title: Desktop editions
description: The four Open DeepTutor downloads and where each edition stores data and logs.
quadrant: reference
---

Open DeepTutor is the double-click app for macOS and Windows. The first launch installs the bundled runtime, starts the services on loopback, and opens the web UI. Packaging and signing stay in the repository's `apps/desktop/README.md`.

## Downloads

Each release publishes four files. `<version>` is the DeepTutor version bundled in that build.

| Target | App | Download |
| --- | --- | --- |
| `macos-arm64` | Open DeepTutor for MacOS with Apple Silicon | `Open-DeepTutor-MacOS-Apple-Silicon-v<version>.dmg` |
| `macos-x64` | Open DeepTutor for MacOS with Intel | `Open-DeepTutor-MacOS-Intel-v<version>.dmg` |
| `windows-x64` | Open DeepTutor for Windows | `Open-DeepTutor-Windows-v<version>-Setup.exe` and `Open-DeepTutor-Windows-v<version>-Portable.zip` |

The GitHub Release also keeps unversioned aliases for the latest files. Install steps are in the [Desktop tutorial](/get-started/desktop/).

## Data and logs

| | macOS | Windows |
| --- | --- | --- |
| Data | `~/Library/Application Support/Open DeepTutor/workspace/data` | `%LOCALAPPDATA%\Open DeepTutor\workspace\data` |
| Runtimes | `…/Open DeepTutor/runtimes/<runtime-id>` | the same path under `%LOCALAPPDATA%` |
| Logs | `…/Open DeepTutor/logs/runtime.log` | the same path under `%LOCALAPPDATA%` |

Quitting the app stops the services that app started. It does not stop a separate `deeptutor start`.
