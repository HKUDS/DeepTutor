---
title: Model setup guide
description: A beginner-friendly guide to DeepTutor's providers, API keys, and seven model categories—showing what you need on day one and what can wait.
quadrant: explanation
---

When you open **Settings → Models & services**, you see seven sections: Providers, Language models, Task models, Embedding models, Search, Voice, and Multimodal. You do not need to configure all of them to start using DeepTutor.

This guide explains what those terms mean, which single model you need on day one, how to choose among the three access paths, and how to avoid the most common beginner mistakes. If you already know the concepts and want default base URLs or local endpoints, go to [Provider reference](/get-started/providers/).

<!-- TODO(screenshot): Add a screenshot of Settings -> Models & services navigation rail showing all seven sections (save to docs/public/screenshots/dev/models-settings-overview.png). -->

## 1. Four core terms in plain language

| Term | Where you see it | What it means |
| --- | --- | --- |
| **Provider** | **Providers** | **Where your AI comes from**—for example OpenAI, DeepSeek, DashScope (Qwen), OpenRouter, or a local Ollama server. Save credentials once on the **Providers** page, and every service that vendor supports can reuse the same key. |
| **Model** | **Language models**, etc. | **The specific AI model doing the work.** One provider usually offers multiple models—some optimize for fast chat, some for step-by-step reasoning, and some for reading images. |
| **API key** | **API key** | **An access credential for programs.** It is a token issued by a platform (often starting with `sk-`) used to authenticate requests and bill usage. It is **not** your website login password. |
| **Base URL** | **Provider URL / Base URL** | **The server address where DeepTutor sends requests.** Leave it blank for official cloud defaults; enter the platform's documented API endpoint only for gateways or self-hosted servers (never the vendor's marketing homepage). |

## 2. Seven services: what you need now vs. later

In **Settings → Runtime status**, DeepTutor grades each capability as a blocker, warning, or suggestion. Optional services that you have not configured are never treated as errors.

### Required on day one (only one)

- **Language models**: The main brain behind Chat, Solve, Practice, Deep Research, Mastery Path, Books, and the Learning Notebook. **Configure one language model and most of DeepTutor works right away.**

### Ready out of the box (no setup needed)

- **Search**: The `web_search` tool is enabled by default and uses credential-free **DuckDuckGo** when no search provider is configured. Configure **Search** only when you want another engine (such as Brave, Tavily, Bocha, Doubao, Zhipu, or self-hosted SearXNG) or want to select `none` to turn web search off.

### Optional (add only when you need the feature)

| Service | What it unlocks | When to configure it |
| --- | --- | --- |
| **Embedding models** | Converts your PDFs and notes into searchable vectors so DeepTutor can retrieve exact passages across large collections. | **When you are ready to build a Knowledge Base.** Attaching a single file in Chat with `+` does not require an embedding model. |
| **Task models** | Handles background jobs such as chat titles, starter suggestions, reading helpers, and Math Animator / Video Lesson code repairs. | When you want a faster or lower-cost model to handle background tasks. Optional—chat works without it. |
| **Voice (TTS / STT)** | **Text-to-Speech (TTS)** reads replies and study materials aloud; **Speech-to-Text (STT)** enables the composer microphone. | When you want spoken explanations or voice input. |
| **Multimodal** | Unlocks the `imagegen` (create images) and `videogen` (create videos) chat tools. | When you want the tutor to generate illustrations or short videos in chat. |

:::caution[Solving a photo does not require Multimodal image generation]
Reading an uploaded problem photo, screenshot, or PDF figure relies on your **Language model's image-input (Vision) capability**, not on the **Multimodal** image-generation service. Choose a vision-capable language model if you plan to use Vision Solver or study illustrated papers.
:::

## 3. Three ways to get a model

| Path | Best for | Cost & setup | Examples |
| --- | --- | --- | --- |
| **Account sign-in (OAuth)** | Readers who already have an eligible subscription and prefer browser login over API keys | Uses your existing account permissions and allowance | **OpenAI Codex** (ChatGPT account), **GitHub Copilot**, **CodeBuddy / WorkBuddy** |
| **Cloud API key (pay-as-you-go)** | Most learners; flexible access to strong models with no local GPU required | Create a key in the provider's developer console and add credit; billed by actual usage | **OpenAI**, **Anthropic**, **Gemini**, **DeepSeek**, **DashScope (Qwen)**, **Zhipu AI**, **SiliconFlow**, **OpenRouter** |
| **Local models** | Privacy-focused or offline study on a computer with enough RAM or GPU | Free, no API key required; speed and quality depend on your hardware | **Ollama**, **LM Studio**, **llama.cpp**, **Lemonade**, **vLLM** |

:::caution[A chat web subscription is not the same as API credit]
Paid web chat plans (such as ChatGPT Plus or standard consumer web memberships) do not automatically include API console credits. For API-key providers, create your key in the vendor's **API developer console** and verify available balance. If you want to reuse a ChatGPT plan directly, choose **OpenAI Codex** (account sign-in) instead of **OpenAI** (API key).
:::

## 4. Reading model capability toggles

In **Settings → Models & services → Language models**, DeepTutor detects each model's capabilities automatically, and you can override four switches per model when needed:

<!-- TODO(screenshot): Add a screenshot of a Language model card in Settings -> Language models showing the Tool calling, Image input, JSON output, and Reasoning toggles (save to docs/public/screenshots/dev/models-capabilities.png). -->

| Capability | What it affects | How to choose |
| --- | --- | --- |
| **Tool calling** | Lets the tutor search files, run web search, save notes, and invoke workspace tools | Pick a model with reliable tool calling to get the full DeepTutor workflow. |
| **Image input (Vision)** | Lets the tutor read photos of homework, screenshots, and figures inside PDFs | Needed for Vision Solver and reading illustrated documents. |
| **Reasoning** | Enables deeper step-by-step thinking and the **Reasoning effort** control | Helpful for difficult math proofs and Deep Research; lower effort speeds up everyday chat. |
| **JSON output** | Improves reliability when generating quizzes, Mastery Paths, and book outlines | Supported by mainstream cloud models; check this switch if a small local model fails structured tasks. |

## 5. How Settings protects your working setup

DeepTutor uses a **draft-and-apply** workflow so a broken edit never overwrites a working setup:

1. **Connect a provider**: Open **Settings → Models & services → Providers**, add your provider, and click **Test provider**.
2. **Add and test a model**: Open **Language models**, import or add a model, click **Test model**, and click **Set as default**.
3. **Apply changes**: Click **Apply changes** in the bottom bar and wait for **Applied**.

All model settings are stored in `data/user/settings/model_catalog.json`. Project-root `.env` files are not loaded.

:::caution[Switching embedding models after building a Knowledge Base]
If you already built a Knowledge Base and later switch to a different **Embedding model** or vector dimension, the existing index will no longer match. DeepTutor detects the mismatch and prompts you to **Re-index** affected Knowledge Bases—your original files stay intact.
:::

## 6. Common beginner issues

| Symptom | Usual cause | Fix |
| --- | --- | --- |
| `No active LLM model is configured` | No model is set as default, or you clicked **Save draft** instead of **Apply changes** | Open **Language models**, confirm the **Default model** badge, and click **Apply changes**. |
| **Test provider** succeeds, but **Test model** fails | The provider is reachable, but your account lacks access to that model, has no credit, or the Model ID has a typo | Pick a model your account can call, verify the exact **Model ID** in provider docs, and check your API balance. |
| Requests time out or fail to connect | The provider's marketing homepage or placeholder `https://api.example.com/v1` was entered as the URL | Leave **Provider URL** blank for official defaults, or paste the exact API endpoint from your provider's integration guide. |
| Docker cannot reach local Ollama | Inside Docker, `localhost` points to the container itself, not your host computer | Replace `localhost` with `host.docker.internal`; see the [Docker guide](/get-started/docker/). |
| Changing the default model did not change an old chat | Existing conversations retain their previous session model | Switch the model using the selector beside the chat composer, or start a new chat. |

## 7. Tip: update settings from chat later

Once one language model is working, you can ask DeepTutor in plain language to adjust settings—for example, switching languages or checking readiness. DeepTutor probes candidate changes before saving them, and whenever an API key is needed, the UI opens a dedicated credential form directly to your local server so **keys never enter model chat context**.

## Next steps

- Look up default URLs, bindings, and local server templates → [Provider reference](/get-started/providers/)
- Walk through installing Open DeepTutor and sending your first message → [Quickstart](/get-started/desktop/)
- Inspect runtime health and readiness grades → [Settings](/self-hosting/settings/)
