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

## 3. Connect an AI account or enter an API key

DeepTutor provides the learning interface and tools. It needs an AI model to write replies. Connect an AI-platform account you have permission to use, or enter an **API key**, an access credential issued by that platform.

Without a configured model, you may see:

> No active LLM model is configured. Please set it in Settings > Language models.

Open the workspace menu in the upper-left corner, such as **General workspace**, and choose **Settings**. On **General**, find **Set up chat first** and choose **1. Connect a provider**. On **Providers**, choose **Add provider**.

A **provider** is where you get access to AI. For interaction in the chat box, look for options labelled **Language models**.

### Option A: Enter an API key

| API key issuer | Select |
| --- | --- |
| OpenAI Platform | **OpenAI** |
| DeepSeek Platform | **DeepSeek** |
| Another supported platform | The matching provider |

Create a key in the platform's API-key management page if you do not have one. A chat account or subscription does not necessarily include API access or credit. An API key is a program's access credential, not your account password.

Select the issuer and choose **Continue**. Configure:

| Field | What to enter |
| --- | --- |
| **Provider URL** | Leave blank as directed for the official default; enter the API address supplied by your gateway or private deployment otherwise |
| **API key** | The selected provider's key |
| **Language-model API protocol** | Keep **Auto** if shown |
| **Available service types** | Confirm **Language models** is supported |
| **Advanced connection settings** | Keep defaults unless the provider requires changes |

`https://api.example.com/v1` is a placeholder, not a working address. The API address is not the vendor's homepage; use its integration instructions. Do not expose keys in screenshots, chats, or issue reports.

Scroll to **Provider connection** and choose **Test provider**. **Model list retrieved** means the model list was fetched, not that a model can answer. Choose **Language models →** at the bottom to add, select, and test a model.

If credentials are rejected, check the provider, key, and account permissions. For timeouts, check the address and network. If connected without a model list, enter the exact model ID from the provider's instructions.

### Option B: Sign in with an existing account

| Account | Select |
| --- | --- |
| ChatGPT account with Codex access | **OpenAI Codex** |
| CodeBuddy account | **CodeBuddy/WorkBuddy** |
| GitHub account with Copilot access | **GitHub Copilot** |

This example uses a ChatGPT account. See [Provider configuration](/get-started/providers/) for other account requirements.

1. Select **OpenAI Codex** in **Add provider**, then **Continue**.
2. Choose **Sign in with Codex**.
3. Select your ChatGPT account in the browser and complete sign-in and authorization.
4. When you see **Authentication received. You can return to DeepTutor.**, return to the app. Confirm that it shows a connected state and available models.

You do not need to have installed or used Codex, or register another account. The account needs eligible access and available allowance. **OpenAI Codex** is the account-sign-in option; **OpenAI** is the API-key option.

If authorization stays pending, finish the browser steps. Cancel a failed or expired attempt before starting another.

## 4. Choose a model and apply settings

An account or platform can offer several models. Open **Language models** in Settings, or return to **General** and choose **2. Choose a chat model**.

1. Select a specific model, such as **GPT-5.6-Sol** or **GPT-6-Astra**. Use the models actually listed for your account.
2. For API-key connections without a configured model, add one from the connected provider; use the platform's exact **Model ID** for manual entry. For Codex, choose an account-provided model.
3. Choose **Test model** to verify that model. A connected provider does not imply permission to use every model.
4. If **Reasoning effort** is available, choose **low** for a first trial or keep the default.
5. Choose **Set as default**, then **Apply changes**.

The selected model should show **Default model**, and the page should show **Applied**. **Save draft** stores edits without activating them; **Apply changes** puts them into effect.

## 5. Complete your first learning exchange

Return to **Home → Chat** and check the model name beside the composer. Existing conversations can retain a previous selection; use the model selector to change it if needed.

Send:

> Help me practice English writing. Give me a familiar topic and ask me to write four to six sentences. Wait for my answer, then explain the two most important problems and give me hints so I can revise it myself.

Write and send your answer. Revise it using the feedback, then ask:

> Here is my revised answer. Did I fix those two problems?

You have completed a first learning exchange when DeepTutor responds to your answer: **receive a task → answer → get feedback → revise**.

If the model-not-configured message remains, check the account connection, default model, **Apply changes**, and conversation model, then choose **Retry**. For failed requests, check the network, authorization, allowance, and model test result. See [Troubleshooting](/self-hosting/troubleshooting/) for more help.

Basic chat does not require embedding, voice, image, or video setup. Add those services when needed.

## Where your data lives

Your notes, chats, and settings stay in the app’s workspace folder. Installing a newer copy of the app leaves this folder where it is.

| System | Workspace data |
| --- | --- |
| macOS | `~/Library/Application Support/Open DeepTutor/workspace/data` |
| Windows | `%LOCALAPPDATA%\Open DeepTutor\workspace\data` |

## Next

- [A first study session](/learning-workspace/) — one topic, one source, one question.
- [Changelog](/get-started/changelog/) — read this before you replace an older desktop app. v1.7.4 changes the runtime signing key, so install that app itself rather than importing an update into an older build.
