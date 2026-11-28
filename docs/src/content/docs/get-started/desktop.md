---
title: Quickstart
description: Learn what DeepTutor is, install Open DeepTutor, connect one language model, and finish your first study exchange.
quadrant: tutorial
---

## What is DeepTutor?

DeepTutor is an **AI learning workspace** that runs on your computer.

If a standard AI web chat is a blank Q&A box, DeepTutor is a **personal study desk**:

- **Study with your own materials**: Attach lecture notes, PDFs, papers, or web pages. Replies point back to the exact passage so you can verify what you read.
- **Separate subjects into workspaces**: Keep calculus, English, and research projects in separate workspaces so chats, notes, practice questions, and knowledge bases stay organized.
- **More than chat**: Alongside conversation, you get photo problem-solving, practice quizzes, guided Mastery Paths, Immersive Reading, and a Learning Notebook.
- **Your data stays local**: Notes, chats, and settings live on your computer. Switching AI models does not erase your study history.

:::note[Why can DeepTutor not reply right after install?]
DeepTutor provides the learning workspace and tools, while an external **AI model** acts as the brain that writes replies. You do not need to configure every model up front—**connecting one language model is enough to start chatting and studying**.
:::

## 1. Download and install Open DeepTutor

**Open DeepTutor** is the desktop app. It bundles Python and Node.js inside the installer, so you do not install developer runtimes or open a terminal.

| This computer | Download | Install |
| --- | --- | --- |
| Mac with Apple silicon (M1/M2/M3/M4) | [Open DeepTutor for macOS (Apple silicon)](https://github.com/HKUDS/DeepTutor/releases/latest/download/Open-DeepTutor-MacOS-Apple-Silicon.dmg) | Open the DMG and drag **Open DeepTutor** into **Applications**. |
| Mac with Intel | [Open DeepTutor for macOS (Intel)](https://github.com/HKUDS/DeepTutor/releases/latest/download/Open-DeepTutor-MacOS-Intel.dmg) | Open the DMG and drag **Open DeepTutor** into **Applications**. |
| Windows (64-bit) | [Open DeepTutor for Windows](https://github.com/HKUDS/DeepTutor/releases/latest/download/Open-DeepTutor-Windows-Setup.exe) | Run the installer wizard. |

:::caution[Windows security prompt]
Windows builds are currently unsigned, so SmartScreen may ask you to confirm. Choose **More info → Run anyway** to continue. A Windows portable ZIP is available on the [same release](https://github.com/HKUDS/DeepTutor/releases/latest). For Docker, PyPI, source, or CLI-only installs, see [Install choices](/get-started/).
:::

Launch **Open DeepTutor**. The first start unpacks the bundled runtime, then opens the workspace window. You can continue when **Home** appears in the sidebar. If the startup screen stays up for several minutes, quit and reopen the app.

<!-- TODO(screenshot): Add a screenshot of the first-launch DeepTutor workspace showing the top-left workspace menu -> Settings entry (save to docs/public/screenshots/dev/quickstart-workspace.png). -->

## 2. Connect your first language model

Before a model is configured, sending a message shows:

> No active LLM model is configured. Please set it in Settings > Language models.

Follow the built-in three-step checklist in Settings:

1. Click the workspace name in the upper-left corner (for example, **General workspace**) and choose **Settings**.
2. On **General**, find **Set up chat first** and complete the three steps in order.

<!-- TODO(screenshot): Add a screenshot of Settings -> General highlighting the "Set up chat first" 3-step checklist (save to docs/public/screenshots/dev/quickstart-setup-checklist.png). -->

### Step 1: Connect a provider

A **provider** is the platform or local server that supplies your AI model. Click **1. Connect a provider** → **Add provider**, then choose the option that matches what you have:

- **Option A: Sign in with an existing account (no API key needed)**
  If you have an eligible ChatGPT account with Codex access, a GitHub Copilot account, or a CodeBuddy account, select **OpenAI Codex**, **GitHub Copilot**, or **CodeBuddy/WorkBuddy** and complete browser sign-in. Return to DeepTutor when you see **Authentication received. You can return to DeepTutor.** and confirm the page shows a connected status with available models.
- **Option B: Enter an API key (works with DeepSeek, OpenAI, Qwen, and more)**
  1. Select the platform that issued your key (such as **OpenAI**, **DeepSeek**, **DashScope (Qwen)**, or **SiliconFlow**) and click **Continue**.
  2. Leave **Provider URL** blank when using the official platform default; enter a custom API address only for gateways or private deployments.
  3. Paste your **API key** (an access credential for programs, not your account password; never share it in screenshots or chats).
  4. Keep **Language-model API protocol** on **Auto** if shown, and confirm **Language models** is listed under available service types.
  5. Scroll to **Provider connection** and click **Test provider**. Once you see **Model list retrieved**, click **Language models →** at the bottom.

:::tip[No API key yet, or unsure which platform to pick?]
Read [Model setup guide](/get-started/models/) first—it explains the three ways to get a model and clears up common beginner pitfalls such as web subscriptions vs. API credits.
:::

<!-- TODO(screenshot): Add a screenshot of Settings -> Providers -> Add provider showing API key input and the "Test provider" button with synthetic/redacted values (save to docs/public/screenshots/dev/quickstart-add-provider.png). -->

### Step 2: Choose a model and test it

Open **Settings → Models & services → Language models** (or return to **General** and click **2. Choose a chat model**):

1. Pick a specific model from your connected provider (or enter the exact **Model ID** from your provider's docs).
2. Click **Test model** to verify that your account can actually call this model.
3. If **Reasoning effort** appears, leave the default or select **low** for your first trial.
4. Click **Set as default**.

### Step 3: Apply changes

Click **Apply changes** on the bottom bar.

Confirm that the model shows **Default model** and the status changes to **Applied**. **Save draft** stores edits without activating them; **Apply changes** makes them live.

<!-- TODO(screenshot): Add a screenshot of Settings -> Language models showing "Test model", "Default model" badge, and the bottom "Apply changes" bar (save to docs/public/screenshots/dev/quickstart-apply-model.png). -->

## 3. Finish your first study exchange

Return to **Home → Chat** and check that your model name appears beside the composer. Existing conversations can keep an earlier selection; use the model selector if you need to switch.

Send this prompt:

> Help me practice English writing. Give me a familiar topic and ask me to write four to six sentences. Wait for my answer, then explain the two most important problems and give me hints so I can revise it myself.

Write your short answer and send it. Revise it using the hints, then reply:

> Here is my revised answer. Did I fix those two problems?

When DeepTutor responds to your revision, you have completed your first study loop: **receive a task → answer → get feedback → revise**.

If you still see the unconfigured-model message, verify that your model is marked **Default model**, click **Apply changes**, check the composer's model selector, and click **Retry**.

## Where your data lives

Your notes, chats, and settings stay inside the app's local workspace folder. Installing a newer version of Open DeepTutor preserves this folder:

| System | Workspace data |
| --- | --- |
| macOS | `~/Library/Application Support/Open DeepTutor/workspace/data` |
| Windows | `%LOCALAPPDATA%\Open DeepTutor\workspace\data` |

## Next steps

You do not need embedding, voice, image, or video models for normal chat. Add them later when you need those features.

- [Model setup guide](/get-started/models/) — Understand all seven model categories and choose models for your study workflow.
- [Study with your materials](/learn/ask-with-a-source/) — Attach a PDF or note and get answers with clickable citations.
- [Solve from a photo](/learn/solve-a-photo/) — Photograph a problem on paper and walk through the solution.
- [A first study session](/learning-workspace/) — Connect one topic, one source, and one question across the workspace.
- [Changelog](/get-started/changelog/) — Check before upgrading an older desktop build. v1.7.4 replaced the runtime signing key, so install the new app rather than importing an update into an older build.
