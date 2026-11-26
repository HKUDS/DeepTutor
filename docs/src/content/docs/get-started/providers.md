---
title: Provider Configuration
description: Configure LLM, task, embedding, search, voice, and multimodal provider profiles in DeepTutor.
quadrant: how-to
---


DeepTutor's model catalog covers LLM, Task Models, Embedding, Search, Text-to-Speech, Speech-to-Text, Image Generation, and Video Generation. Configure provider profiles through **Settings → Models & services**, `deeptutor init`, or `data/user/settings/model_catalog.json`. Model profiles and selections are resolved from that catalog; legacy `LLM_*`, `EMBEDDING_*`, and `SEARCH_*` environment recipes no longer configure them. Project-root `.env` files are not auto-loaded.


## Configuration surfaces and precedence

Use **Settings → Models & services** for normal setup; it writes `data/user/settings/model_catalog.json` and applies changes. `deeptutor init` covers first-boot LLM, embedding, and search setup.

**Providers.** **Settings → Providers** links vendor credentials to supported profiles; unlinked services keep their own. GitHub Copilot uses device login with owner-private credentials.

**Task Models.** The `task` service handles titles, suggestions, reading helpers, and Math Animator/Video Lesson repairs through profiles with per-task overrides.

## LLM Providers

| Provider                | Binding               | Default Base URL                                          |
| :---------------------- | :-------------------- | :-------------------------------------------------------- |
| <img src="/provider-icons/aihubmix-color.svg" alt="" width="16" height="16" /> AiHubMix | `aihubmix` | `https://aihubmix.com/v1`                                |
| <img src="/provider-icons/anthropic.svg" alt="" width="16" height="16" /> Anthropic | `anthropic` | `https://api.anthropic.com/v1`                           |
| API Route               | `api_route`           | `https://global.api-route.com/v1`                        |
| Atlas Cloud             | `atlascloud`          | `https://api.atlascloud.ai/v1`                           |
| <img src="/provider-icons/azure-color.svg" alt="" width="16" height="16" /> Azure OpenAI | `azure_openai` | —                                                        |
| <img src="/provider-icons/bytedance-color.svg" alt="" width="16" height="16" /> BytePlus | `byteplus` | `https://ark.ap-southeast.bytepluses.com/api/v3`         |
| <img src="/provider-icons/bytedance-color.svg" alt="" width="16" height="16" /> BytePlus Coding Plan | `byteplus_coding_plan` | `https://ark.ap-southeast.bytepluses.com/api/coding/v3`  |
| Cheaper Inference       | `cheaperinference`    | `https://api.cheaperinference.com/v1`                     |
| Custom (OpenAI-compat)  | `custom`              | —                                                        |
| CodeBuddy / WorkBuddy   | `codebuddy`           | — (SDK sign-in)                                          |
| <img src="/provider-icons/qwen-color.svg" alt="" width="16" height="16" /> DashScope (Qwen) | `dashscope` | `https://dashscope.aliyuncs.com/compatible-mode/v1`      |
| <img src="/provider-icons/deepseek-color.svg" alt="" width="16" height="16" /> DeepSeek | `deepseek` | `https://api.deepseek.com`                               |
| Eden AI                 | `edenai`              | `https://api.edenai.run/v3`                              |
| FutureInfra             | `futureinfra`         | `https://futureinfra.ai/v1/ai`                            |
| <img src="/provider-icons/gemini-color.svg" alt="" width="16" height="16" /> Gemini | `gemini` | `https://generativelanguage.googleapis.com/v1beta/openai/`|
| <img src="/provider-icons/githubcopilot.svg" alt="" width="16" height="16" /> GitHub Copilot | `github_copilot` | `https://api.githubcopilot.com`                          |
| <img src="/provider-icons/groq.svg" alt="" width="16" height="16" /> Groq | `groq` | `https://api.groq.com/openai/v1`                         |
| Lemonade                | `lemonade`            | `http://localhost:13305/api/v1`                          |
| llama.cpp               | `llama_cpp`           | `http://localhost:8080/v1`                               |
| <img src="/provider-icons/lmstudio.svg" alt="" width="16" height="16" /> LM Studio | `lm_studio` | `http://localhost:1234/v1`                               |
| <img src="/provider-icons/minimax-color.svg" alt="" width="16" height="16" /> MiniMax | `minimax` | `https://api.minimax.io/v1`                              |
| <img src="/provider-icons/mistral-color.svg" alt="" width="16" height="16" /> Mistral | `mistral` | `https://api.mistral.ai/v1`                              |
| <img src="/provider-icons/moonshot.svg" alt="" width="16" height="16" /> Moonshot (Kimi) | `moonshot` | `https://api.moonshot.cn/v1`                             |
| Novita AI               | `novita`              | `https://api.novita.ai/openai`                           |
| <img src="/provider-icons/ollama.svg" alt="" width="16" height="16" /> Ollama | `ollama` | `http://localhost:11434/v1`                              |
| <img src="/provider-icons/nvidia-color.svg" alt="" width="16" height="16" /> NVIDIA NIM | `nvidia_nim` | `https://integrate.api.nvidia.com/v1`                    |
| onomeo                  | `onomeo`              | `https://onomeo.com/v1`                                 |
| <img src="/provider-icons/openai.svg" alt="" width="16" height="16" /> OpenAI | `openai` | `https://api.openai.com/v1`                              |
| <img src="/provider-icons/openai.svg" alt="" width="16" height="16" /> OpenAI Codex | `openai_codex` | `https://chatgpt.com/backend-api`                        |
| <img src="/provider-icons/openrouter.svg" alt="" width="16" height="16" /> OpenRouter | `openrouter` | `https://openrouter.ai/api/v1`                           |
| Opper                   | `opper`               | `https://api.opper.ai/v3/compat`                          |
| OpenVINO Model Server   | `ovms`                | `http://localhost:8000/v3`                               |
| <img src="/provider-icons/baiducloud-color.svg" alt="" width="16" height="16" /> Qianfan (Ernie) | `qianfan` | `https://qianfan.baidubce.com/v2`                        |
| Requesty                | `requesty`            | `https://router.requesty.ai/v1`                           |
| <img src="/provider-icons/siliconcloud-color.svg" alt="" width="16" height="16" /> SiliconFlow | `siliconflow` | `https://api.siliconflow.cn/v1`                          |
| <img src="/provider-icons/stepfun-color.svg" alt="" width="16" height="16" /> Step Fun | `stepfun` | `https://api.stepfun.com/v1`                             |
| Standard Compute | `standardcompute` | `https://api.stdcmpt.com/v1` |
| Unifically              | `unifically`          | `https://api.unifically.com/v1`                          |
| <img src="/provider-icons/vllm-color.svg" alt="" width="16" height="16" /> vLLM | `vllm` | — (configure explicitly)                                 |
| <img src="/provider-icons/volcengine-color.svg" alt="" width="16" height="16" /> VolcEngine | `volcengine` | `https://ark.cn-beijing.volces.com/api/v3`               |
| <img src="/provider-icons/volcengine-color.svg" alt="" width="16" height="16" /> VolcEngine Coding Plan | `volcengine_coding_plan` | `https://ark.cn-beijing.volces.com/api/coding/v3`       |
| <img src="/provider-icons/xiaomimimo.svg" alt="" width="16" height="16" /> Xiaomi MIMO | `xiaomi_mimo` | `https://api.xiaomimimo.com/v1`                          |
| xAI (Grok)              | `xai`                 | `https://api.x.ai/v1`                                    |
| Y-API                   | `y_api`               | `https://api.y-api.bestvirtualgoods.com/v1`               |
| <img src="/provider-icons/zhipu-color.svg" alt="" width="16" height="16" /> Zhipu AI (GLM) | `zhipu` | `https://open.bigmodel.cn/api/paas/v4`                   |

### Configuration

```text
Settings → Language models
Provider: OpenAI
Model: gpt-4o-mini
API key: sk-xxx
Base URL: https://api.openai.com/v1
```

:::tip
Choose a provider-supported **API format** per LLM or Task profile. **Auto** routes automatically. Default URLs follow the selected format; custom URLs stay unchanged. Credential edits trigger model discovery; select matching models for bulk import. Per-model controls override detected capabilities.
:::

## Embedding Providers

| Provider             | Binding       | Model Example             | Default Dim |
| :------------------- | :------------ | :------------------------ | :---------: |
| <img src="/provider-icons/openai.svg" alt="" width="16" height="16" /> OpenAI | `openai` | `text-embedding-3-large`  |    3072     |
| <img src="/provider-icons/gemini-color.svg" alt="" width="16" height="16" /> Gemini | `gemini` | `gemini-embedding-2`     |    3072     |
| <img src="/provider-icons/azure-color.svg" alt="" width="16" height="16" /> Azure OpenAI | `azure_openai` | deployment name           |      —      |
| <img src="/provider-icons/cohere-color.svg" alt="" width="16" height="16" /> Cohere | `cohere` | `embed-v4.0`              |    1024     |
| <img src="/provider-icons/jina.svg" alt="" width="16" height="16" /> Jina | `jina` | `jina-embeddings-v3`      |    1024     |
| <img src="/provider-icons/mistral-color.svg" alt="" width="16" height="16" /> Mistral | `mistral` | `mistral-embed`        |    1024     |
| <img src="/provider-icons/ollama.svg" alt="" width="16" height="16" /> Ollama | `ollama` | `nomic-embed-text`        |     768     |
| Lemonade Server       | `lemonade`    | Any local embedding model |      —      |
| <img src="/provider-icons/vllm-color.svg" alt="" width="16" height="16" /> vLLM / LM Studio | `vllm` | Any embedding model       |      —      |
| <img src="/provider-icons/siliconcloud-color.svg" alt="" width="16" height="16" /> SiliconFlow | `siliconflow` | `Qwen/Qwen3-Embedding-8B` |    4096     |
| <img src="/provider-icons/qwen-color.svg" alt="" width="16" height="16" /> Aliyun DashScope | `aliyun` | `qwen3-vl-embedding`     |    2560     |
| <img src="/provider-icons/openrouter.svg" alt="" width="16" height="16" /> OpenRouter | `openrouter` | provider-dependent        |      —      |
| Opper                | `opper`      | `openai/text-embedding-3-large` | 3072    |
| Any OpenAI-compatible| `custom`      | —                         |      —      |
| NVIDIA NIM | `nvidia_nim` | `nvidia/nemotron-3.5-embed-8b` | 4096 |
| Custom OpenAI SDK    | `custom_openai_sdk` | —                    |      —      |

### Configuration

The embedding profile's **Base URL** resolves to the full embedding endpoint; recognized provider roots are normalized automatically.

```text
Settings → Embedding models
Provider: OpenAI
Model: text-embedding-3-large
API key: sk-xxx
Base URL: https://api.openai.com/v1/embeddings
Dimension: 3072
```

:::caution
Changing the embedding model after creating a knowledge base will cause a mismatch. DeepTutor detects this and warns you — rebuild the knowledge base if you switch models.
:::

## Search Providers

| Provider    | Required profile field | Notes                            |
| :---------- | :--------------------- | :------------------------------- |
| <img src="/provider-icons/brave.svg" alt="" width="16" height="16" /> Brave | API key | Free tier available              |
| <img src="/provider-icons/tavily-color.svg" alt="" width="16" height="16" /> Tavily | API key |                                  |
| Serper      | API key                |                                  |
| Serply      | API key                | Google SERP; News & Scholar modes |
| SearchApi | API key | Web, News & Scholar |
| DeepSeek | API key | Standalone SERP |
| SpecStream | API key | Search with answers |
| <img src="/provider-icons/jina.svg" alt="" width="16" height="16" /> Jina | API key |                                  |
| <img src="/provider-icons/searxng.svg" alt="" width="16" height="16" /> SearXNG | Base URL | Self-hosted, no API key needed   |
| <img src="/provider-icons/duckduckgo.svg" alt="" width="16" height="16" /> DuckDuckGo | None | No API key needed                |
| <img src="/provider-icons/perplexity-color.svg" alt="" width="16" height="16" /> Perplexity | API key | Returns an answer                |
| <img src="/provider-icons/volcengine-color.svg" alt="" width="16" height="16" /> Doubao | API key | Returns an answer, not only links |
| Bocha       | API key                | China-hosted                     |
| <img src="/provider-icons/zhipu-color.svg" alt="" width="16" height="16" /> Zhipu | API key | China-hosted                     |
| Firecrawl   | API key                | Adds page extraction             |
| <img src="/provider-icons/baiducloud-color.svg" alt="" width="16" height="16" /> Baidu Qianfan | API key | China-hosted                     |
| Aliyun IQS  | API key                | China-hosted                     |
| You.com     | API key                | Returns an answer                |
| Google Browser Scraper | Base URL    | Scrapes Google via a local browser |
| None        | None                   | Explicitly disables web search   |

### Configuration

```text
Settings → Search
Provider: Brave
API key: your-api-key
```

The `web_search` tool is enabled by default. With no search profile configured, it uses credential-free DuckDuckGo; add a profile only when you want another provider, or select `none` to disable web search explicitly. Older `exa`, `baidu`, and `openrouter` values remain deprecated compatibility choices.

## Voice and Generation Providers

The Voice and Multimodal generation pages carry four services beyond LLM, embedding, and search. They are configured the same way — a provider connection plus a catalog of model ids — and each unlocks a specific surface.

| Service | Providers | What it unlocks |
| :------ | :-------- | :-------------- |
| **Text-to-Speech** | `openai`, `azure_openai`, `gemini`, `groq`, `siliconflow`, `openrouter`, `vllm`, `dashscope`, `volcengine_speech`, `minimax`, `xiaomi_mimo`, `custom` | Reply and reading-material read-aloud. |
| **Speech-to-Text** | `openai`, `azure_openai`, `groq`, `siliconflow`, `openrouter`, `vllm`, `dashscope`, `volcengine_speech`, `custom` | The composer microphone. |
| **Image Generation** | `openai`, `azure_openai`, `volcengine`, `siliconflow`, `openrouter`, `dashscope`, `custom`, `custom_chat` | The `imagegen` chat tool. |
| **Video Generation** | `volcengine`, `dashscope`, `custom` | The `videogen` chat tool. |

Image and video generation are **tools, not modes**: once a model is configured, ask for a picture in plain language and the agent calls the tool, then previews the result inline with a downloadable file. Video generation runs as an asynchronous job, so the turn reports progress rather than blocking.

:::caution
`custom_chat` exists for providers that expose image generation through their *chat* endpoint rather than a dedicated `images/generations` one. If the wrong profile type is selected, a working key may still produce no image.
:::

## Local Models

DeepTutor works with locally-hosted models through several providers. In Docker, `localhost` means the container itself; use `host.docker.internal` or the pattern in the [Docker guide](/get-started/docker/#connecting-to-a-local-llm-ollama--lm-studio--llamacpp--vllm) when the model server runs on the host.

### Ollama

```text
LLM profile: Ollama | llama3.1 | http://localhost:11434/v1
Embedding profile: Ollama | nomic-embed-text | http://localhost:11434/api/embed | 768
API key: leave blank
```

### LM Studio

```text
Provider: LM Studio
Model: your-model-name
Base URL: http://localhost:1234/v1
API key: leave blank
```

### vLLM

```text
Provider: vLLM
Model: your-model-name
Base URL: http://localhost:8000/v1
API key: leave blank unless the server requires one
```

### llama.cpp

```text
Provider: llama.cpp
Model: your-model-name
Base URL: http://localhost:8080/v1
API key: leave blank
```

### Lemonade

```text
Provider: Lemonade
Model: your-model-name
Base URL: http://localhost:13305/api/v1
API key: leave blank
```
