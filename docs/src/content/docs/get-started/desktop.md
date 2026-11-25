---
title: Desktop quickstart
description: Install Open DeepTutor, connect one language model, and send a first message.
quadrant: tutorial
---

Open DeepTutor is the desktop app. The first launch installs its bundled Python and Node runtime, starts them on this computer, and opens the DeepTutor workspace. You do not install Python, Node, or the source tree.

## 1. Download the app for this computer

| This computer | Download |
| --- | --- |
| Mac with Apple silicon | [Open DeepTutor for macOS (Apple silicon)](https://github.com/HKUDS/DeepTutor/releases/latest/download/Open-DeepTutor-MacOS-Apple-Silicon.dmg) |
| Mac with Intel | [Open DeepTutor for macOS (Intel)](https://github.com/HKUDS/DeepTutor/releases/latest/download/Open-DeepTutor-MacOS-Intel.dmg) |
| Windows | [Open DeepTutor for Windows](https://github.com/HKUDS/DeepTutor/releases/latest/download/Open-DeepTutor-Windows-Setup.exe) |

Open the file you downloaded. On macOS, drag the app to Applications. On Windows, finish the installer. Windows SmartScreen asks for confirmation because the installer is unsigned; choose to run it.

The Windows portable ZIP is on the [same release](https://github.com/HKUDS/DeepTutor/releases/latest). Use the installer above for this path.

## 2. Wait until the workspace opens

Launch **Open DeepTutor**. The first start unpacks the bundled runtime and then shows the DeepTutor window. Wait until the workspace is visible. Quit and reopen if the window is still on the startup screen after a few minutes.

## 3. Connect one language model

1. Open **Settings → Models & services**.
2. Add one language-model profile for a provider you already have a key for, or a local server that is already running.
3. Choose **Test**. A successful test means this profile can complete a minimal call.
4. Choose **Apply**.

Embedding, search, and voice can wait. [Providers & models](/get-started/providers/) lists those services and the provider catalog.

## 4. Send one message

Open **Home → Chat**. Ask one concrete question, for example: “Explain the sampling theorem in one paragraph, then give me two questions.”

You are done when a reply appears in the thread.

## Where your data lives

Learning data and settings stay in the app’s workspace folder. Replacing the app does not replace this folder.

| System | Workspace data |
| --- | --- |
| macOS | `~/Library/Application Support/Open DeepTutor/workspace/data` |
| Windows | `%LOCALAPPDATA%\Open DeepTutor\workspace\data` |

## Next

- [A first study session](/learning-workspace/) — one topic, one source, one question.
- [Changelog](/get-started/changelog/) — read this before replacing an older desktop app. v1.7.4 changes the runtime signing key, so install that app itself rather than importing an update into an older build.
