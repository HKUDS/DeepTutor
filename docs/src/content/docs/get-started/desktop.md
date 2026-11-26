---
title: Desktop quickstart
description: Install Open DeepTutor, connect one language model, and send a first message.
quadrant: tutorial
---

Open DeepTutor is the desktop app. The first time you open it, the app unpacks the Python and Node runtime that came with it, starts those services on this computer, and shows the workspace. You do not install Python, Node, or the source tree yourself.

## 1. Download the app for this computer

| This computer | Download |
| --- | --- |
| Mac with Apple silicon | [Open DeepTutor for macOS (Apple silicon)](https://github.com/HKUDS/DeepTutor/releases/latest/download/Open-DeepTutor-MacOS-Apple-Silicon.dmg) |
| Mac with Intel | [Open DeepTutor for macOS (Intel)](https://github.com/HKUDS/DeepTutor/releases/latest/download/Open-DeepTutor-MacOS-Intel.dmg) |
| Windows | [Open DeepTutor for Windows](https://github.com/HKUDS/DeepTutor/releases/latest/download/Open-DeepTutor-Windows-Setup.exe) |

Open the file you downloaded. On a Mac, drag the app into Applications. On Windows, finish the installer. Windows SmartScreen asks you to confirm because the installer is unsigned; choose to run it. After that, **Open DeepTutor** is in your applications list.

The Windows portable ZIP is on the [same release](https://github.com/HKUDS/DeepTutor/releases/latest). This tutorial uses the installer above.

## 2. Wait until the workspace opens

Launch **Open DeepTutor**. The first start unpacks the bundled runtime, then opens the DeepTutor window. You can continue when the workspace is on screen and Home is in the sidebar. If the window is still on the startup screen after a few minutes, quit and open the app again.

## 3. Connect one language model

A language model writes the replies. A provider is the vendor, or the local server, that hosts that model. This step gives DeepTutor one model it can call.

1. Open **Settings → Models & services**.
2. Add one language-model profile for a provider you already have a key for, or a local server that is already running. A profile is the saved connection: the provider, the model, and the key or address.
3. Choose **Test**. When the test succeeds, this profile can complete a minimal call.
4. Choose **Apply**. The profile is saved, and the next message can use it.

Embedding, search, and voice can wait. [Providers & models](/get-started/providers/) lists those services and the provider catalog.

## 4. Send one message

Open **Home → Chat**. Ask one concrete question, for example: “Explain the sampling theorem in one paragraph, then give me two questions.”

You are finished when a reply appears in the thread.

## Where your data lives

Your notes, chats, and settings stay in the app’s workspace folder. Installing a newer copy of the app leaves this folder where it is.

| System | Workspace data |
| --- | --- |
| macOS | `~/Library/Application Support/Open DeepTutor/workspace/data` |
| Windows | `%LOCALAPPDATA%\Open DeepTutor\workspace\data` |

## Next

- [A first study session](/learning-workspace/) — one topic, one source, one question.
- [Changelog](/get-started/changelog/) — read this before you replace an older desktop app. v1.7.4 changes the runtime signing key, so install that app itself rather than importing an update into an older build.
