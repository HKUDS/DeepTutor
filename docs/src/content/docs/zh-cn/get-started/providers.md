---
title: Provider 配置
---


DeepTutor 的模型 catalog 覆盖 LLM、Task Models、Embedding、Search、语音合成、语音识别、文生图与文生视频。请通过 **设置 → 模型与服务**、`deeptutor init` 或 `data/user/settings/model_catalog.json` 配置 provider profiles。模型 profiles 和选择从该 catalog 解析；旧的 `LLM_*`、`EMBEDDING_*`、`SEARCH_*` 环境变量写法已不能配置它们。项目根目录的 `.env` 文件不会自动加载。


## 配置入口和优先级

日常配置请用 **设置 → 模型与服务**；它会写入 `data/user/settings/model_catalog.json` 并 apply 变更。`deeptutor init` 只覆盖首次启动的 LLM、embedding 与 search 设置。

**提供方。** **设置 → 提供方** 将 vendor 凭据关联到支持的 profiles；未关联服务保留自己的凭据。GitHub Copilot 走设备登录，凭据按用户私有保存。

**Task Models。** `task` service 通过 profile 处理标题、建议、阅读辅助及 Math Animator/Video Lesson 修复，支持按任务覆盖。

## LLM Providers

| Provider                | Binding               | 默认 Base URL                                             |
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
| CodeBuddy / WorkBuddy   | `codebuddy`           | —（SDK 登录）                                            |
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
| <img src="/provider-icons/vllm-color.svg" alt="" width="16" height="16" /> vLLM | `vllm` | —（需显式配置）                                          |
| <img src="/provider-icons/volcengine-color.svg" alt="" width="16" height="16" /> VolcEngine | `volcengine` | `https://ark.cn-beijing.volces.com/api/v3`               |
| <img src="/provider-icons/volcengine-color.svg" alt="" width="16" height="16" /> VolcEngine Coding Plan | `volcengine_coding_plan` | `https://ark.cn-beijing.volces.com/api/coding/v3`       |
| <img src="/provider-icons/xiaomimimo.svg" alt="" width="16" height="16" /> Xiaomi MIMO | `xiaomi_mimo` | `https://api.xiaomimimo.com/v1`                          |
| xAI (Grok)              | `xai`                 | `https://api.x.ai/v1`                                    |
| Y-API                   | `y_api`               | `https://api.y-api.bestvirtualgoods.com/v1`               |
| <img src="/provider-icons/zhipu-color.svg" alt="" width="16" height="16" /> Zhipu AI (GLM) | `zhipu` | `https://open.bigmodel.cn/api/paas/v4`                   |

### 配置

```text
Settings → Language models
Provider: OpenAI
Model: gpt-4o-mini
API key: sk-xxx
Base URL: https://api.openai.com/v1
```

:::tip
LLM/Task 按提供方选 **API format**，**Auto** 自动路由；默认 URL 随格式变，自填保留。凭据修改后自动发现模型，可批量选择导入，能力可覆盖。
:::

## Embedding Providers

| Provider             | Binding       | 模型示例                  | 默认维度    |
| :------------------- | :------------ | :------------------------ | :---------: |
| <img src="/provider-icons/openai.svg" alt="" width="16" height="16" /> OpenAI | `openai` | `text-embedding-3-large`  |    3072     |
| <img src="/provider-icons/gemini-color.svg" alt="" width="16" height="16" /> Gemini | `gemini` | `gemini-embedding-2`     |    3072     |
| <img src="/provider-icons/azure-color.svg" alt="" width="16" height="16" /> Azure OpenAI | `azure_openai` | 部署名称                  |      —      |
| <img src="/provider-icons/cohere-color.svg" alt="" width="16" height="16" /> Cohere | `cohere` | `embed-v4.0`              |    1024     |
| <img src="/provider-icons/jina.svg" alt="" width="16" height="16" /> Jina | `jina` | `jina-embeddings-v3`      |    1024     |
| <img src="/provider-icons/mistral-color.svg" alt="" width="16" height="16" /> Mistral | `mistral` | `mistral-embed`        |    1024     |
| <img src="/provider-icons/ollama.svg" alt="" width="16" height="16" /> Ollama | `ollama` | `nomic-embed-text`        |     768     |
| Lemonade Server       | `lemonade`    | 任意本地 embedding 模型   |      —      |
| <img src="/provider-icons/vllm-color.svg" alt="" width="16" height="16" /> vLLM / LM Studio | `vllm` | 任意 embedding 模型       |      —      |
| <img src="/provider-icons/siliconcloud-color.svg" alt="" width="16" height="16" /> SiliconFlow | `siliconflow` | `Qwen/Qwen3-Embedding-8B` |    4096     |
| <img src="/provider-icons/qwen-color.svg" alt="" width="16" height="16" /> Aliyun DashScope | `aliyun` | `qwen3-vl-embedding`     |    2560     |
| <img src="/provider-icons/openrouter.svg" alt="" width="16" height="16" /> OpenRouter | `openrouter` | 取决于 provider           |      —      |
| Opper                | `opper`      | `openai/text-embedding-3-large` | 3072    |
| 任意 OpenAI 兼容     | `custom`      | —                         |      —      |
| NVIDIA NIM | `nvidia_nim` | `nvidia/nemotron-3.5-embed-8b` | 4096 |
| Custom OpenAI SDK    | `custom_openai_sdk` | —                    |      —      |

### 配置

Embedding profile 的 **Base URL** 会解析为完整 endpoint；可识别的 provider API root 会自动补全。

```text
Settings → Embedding models
Provider: OpenAI
Model: text-embedding-3-large
API key: sk-xxx
Base URL: https://api.openai.com/v1/embeddings
Dimension: 3072
```

:::caution
建好知识库之后再换 embedding 模型会引发维度不匹配。DeepTutor 会检测到并提醒你 —— 换了模型就要把知识库重建。
:::

## 搜索 Providers

| Provider    | Profile 必填字段 | 备注                             |
| :---------- | :--------------- | :------------------------------- |
| <img src="/provider-icons/brave.svg" alt="" width="16" height="16" /> Brave | API key | 有免费额度                       |
| <img src="/provider-icons/tavily-color.svg" alt="" width="16" height="16" /> Tavily | API key |                                  |
| Serper      | API key           |                                  |
| Serply      | API key           | Google SERP；支持 News 与 Scholar 模式 |
| SearchApi | API key | 网页、News 与 Scholar |
| DeepSeek | API key | 独立 SERP 搜索 |
| SpecStream | API key | 搜索与答案 |
| <img src="/provider-icons/jina.svg" alt="" width="16" height="16" /> Jina | API key |                                  |
| <img src="/provider-icons/searxng.svg" alt="" width="16" height="16" /> SearXNG | Base URL | 自部署，不需要 API key           |
| <img src="/provider-icons/duckduckgo.svg" alt="" width="16" height="16" /> DuckDuckGo | 无 | 不需要 API key                   |
| <img src="/provider-icons/perplexity-color.svg" alt="" width="16" height="16" /> Perplexity | API key | 直接返回答案                     |
| <img src="/provider-icons/volcengine-color.svg" alt="" width="16" height="16" /> Doubao 豆包 | API key | 直接返回答案，不只是链接         |
| Bocha 博查  | API key           | 国内托管                         |
| <img src="/provider-icons/zhipu-color.svg" alt="" width="16" height="16" /> Zhipu 智谱 | API key | 国内托管                         |
| Firecrawl   | API key           | 附带整页抽取                     |
| <img src="/provider-icons/baiducloud-color.svg" alt="" width="16" height="16" /> 百度千帆 | API key | 国内托管                         |
| 阿里云 IQS  | API key           | 国内托管                         |
| You.com     | API key           | 直接返回答案                     |
| Google Browser Scraper | Base URL | 通过本地浏览器抓取 Google      |
| None        | 无                | 显式关闭网页搜索                 |

### 配置

```text
Settings → Search
Provider: Brave
API key: your-api-key
```

`web_search` 工具默认启用。没有配置 search profile 时，它使用无需凭据的 DuckDuckGo；只有想换 provider 时才需添加 profile，也可选择 `none` 显式关闭。旧的 `exa`、`baidu`、`openrouter` 值仍只是弃用的兼容选项。

## 语音与生成提供商

除 LLM、嵌入和搜索外，语音与多模态生成页面还提供四项服务。它们的配置方式相同——一个提供商连接加一份模型 id 目录——各自解锁一个具体的功能面。

| 服务 | 提供商 | 解锁什么 |
| :--- | :----- | :------- |
| **语音合成（TTS）** | `openai`、`azure_openai`、`gemini`、`groq`、`siliconflow`、`openrouter`、`vllm`、`dashscope`、`volcengine_speech`、`minimax`、`xiaomi_mimo`、`custom` | 助手回复和阅读材料的朗读。 |
| **语音识别（STT）** | `openai`、`azure_openai`、`groq`、`siliconflow`、`openrouter`、`vllm`、`dashscope`、`volcengine_speech`、`custom` | 输入框上的麦克风。 |
| **文生图** | `openai`、`azure_openai`、`volcengine`、`siliconflow`、`openrouter`、`dashscope`、`custom`、`custom_chat` | `imagegen` 聊天工具。 |
| **文生视频** | `volcengine`、`dashscope`、`custom` | `videogen` 聊天工具。 |

图像与视频生成是**工具，不是模式**：配好模型之后，用自然语言要一张图，智能体就会调用工具，并把结果内联预览、附上可下载的文件。视频生成以异步任务运行，所以这一轮会报告进度，而不是干等着。

:::caution
`custom_chat` 是给那些通过 *chat* 端点而非专门的 `images/generations` 端点提供图像生成的提供商用的。如果 profile 类型选错，key 有效也可能无法出图。
:::

## 本地模型

DeepTutor 通过若干 provider 支持本地托管的模型。Docker 里连接宿主机模型时，`localhost` 指容器自身；请用 `host.docker.internal` 或参考 [Docker 文档](/zh-cn/get-started/docker/#连本地-llmollama--lm-studio--llamacpp--vllm)。

### Ollama

```text
LLM profile: Ollama | llama3.1 | http://localhost:11434/v1
Embedding profile: Ollama | nomic-embed-text | http://localhost:11434/api/embed | 768
API key: 留空
```

### LM Studio

```text
Provider: LM Studio
Model: your-model-name
Base URL: http://localhost:1234/v1
API key: 留空
```

### vLLM

```text
Provider: vLLM
Model: your-model-name
Base URL: http://localhost:8000/v1
API key: 留空；只有服务端要求时才填写
```

### llama.cpp

```text
Provider: llama.cpp
Model: your-model-name
Base URL: http://localhost:8080/v1
API key: 留空
```

### Lemonade

```text
Provider: Lemonade
Model: your-model-name
Base URL: http://localhost:13305/api/v1
API key: 留空
```
