# 预配置

在启动 DeepTutor 之前，您需要完成以下设置步骤。

## 1. 克隆仓库

```bash
git clone https://github.com/HKUDS/DeepTutor.git
cd DeepTutor
```

## 2. 环境变量配置

从模板创建 `.env` 文件：

```bash
cp .env.example .env
```

然后编辑 `.env` 文件，填入您的 API 密钥：

```bash
# ============================================================================
# 服务器配置
# ============================================================================
BACKEND_PORT=8001                         # 后端 API 端口
FRONTEND_PORT=3782                        # 前端 Web 端口

# 远程/局域网访问 - 设置为您服务器的 IP 地址
# NEXT_PUBLIC_API_BASE=http://192.168.1.100:8001

# ============================================================================
# LLM (大语言模型) 配置 - 必填
# ============================================================================
LLM_BINDING=openai                        # 提供商: openai, anthropic, azure_openai, ollama 等
LLM_MODEL=gpt-4o                          # 模型名: gpt-4o, deepseek-chat, claude-3-5-sonnet 等
LLM_HOST=https://api.openai.com/v1        # API 端点 URL
LLM_API_KEY=your_api_key                  # 您的 LLM API 密钥

# ============================================================================
# 嵌入模型配置 - 知识库必填
# ============================================================================
EMBEDDING_BINDING=openai                  # 提供商类型
EMBEDDING_MODEL=text-embedding-3-large    # 嵌入模型名称
EMBEDDING_DIMENSION=3072                  # 必须与模型维度匹配
EMBEDDING_HOST=https://api.openai.com/v1  # API 端点
EMBEDDING_API_KEY=your_api_key            # 嵌入 API 密钥

# ============================================================================
# 网络搜索配置 - 可选
# ============================================================================
SEARCH_PROVIDER=perplexity                # 选项: perplexity, tavily, serper, jina, exa, baidu
SEARCH_API_KEY=your_search_api_key        # 搜索提供商的 API 密钥
```

### 环境变量参考

| 变量 | 必填 | 说明 |
|:---|:---:|:---|
| `LLM_MODEL` | **是** | 模型名称 (如 `gpt-4o`, `deepseek-chat`) |
| `LLM_API_KEY` | **是** | 您的 LLM API 密钥 |
| `LLM_HOST` | **是** | API 端点 URL |
| `EMBEDDING_MODEL` | **是** | 嵌入模型名称 |
| `EMBEDDING_DIMENSION` | **是** | 必须与模型输出维度匹配 |
| `EMBEDDING_API_KEY` | **是** | 嵌入 API 密钥 |
| `EMBEDDING_HOST` | **是** | 嵌入 API 端点 |
| `BACKEND_PORT` | 否 | 后端端口 (默认: `8001`) |
| `FRONTEND_PORT` | 否 | 前端端口 (默认: `3782`) |
| `NEXT_PUBLIC_API_BASE` | 否 | 设置用于远程/局域网访问 |
| `SEARCH_PROVIDER` | 否 | 网络搜索提供商 |
| `SEARCH_API_KEY` | 否 | 搜索 API 密钥 |

### 支持的 LLM 提供商

| 提供商 | `LLM_BINDING` 值 | 说明 |
|:---------|:--------------------|:------|
| OpenAI | `openai` | GPT-4o, GPT-4, GPT-3.5 |
| Anthropic | `anthropic` | Claude 3.5, Claude 3 |
| Azure OpenAI | `azure_openai` | 企业部署 |
| Ollama | `ollama` | 本地模型 |
| DeepSeek | `deepseek` | DeepSeek-V3, DeepSeek-R1 |
| Groq | `groq` | 快速推理 |
| OpenRouter | `openrouter` | 多模型网关 |
| Google Gemini | `gemini` | OpenAI 兼容模式 |

### 支持的嵌入提供商

| 提供商 | `EMBEDDING_BINDING` 值 | 说明 |
|:---------|:--------------------------|:------|
| OpenAI | `openai` | text-embedding-3-large/small |
| Azure OpenAI | `azure_openai` | 企业部署 |
| Jina AI | `jina` | jina-embeddings-v3 |
| Cohere | `cohere` | embed-v3 系列 |
| Ollama | `ollama` | 本地嵌入模型 |
| LM Studio | `lm_studio` | 本地推理服务器 |
| HuggingFace | `huggingface` | OpenAI 兼容端点 |

## 3. 配置文件

DeepTutor 使用两个 YAML 配置文件进行自定义：

### `config/agents.yaml` - Agent 参数

此文件控制每个模块的 LLM 参数：

```yaml
# 解题模块 - 问题求解 agents
solve:
  temperature: 0.3
  max_tokens: 8192

# 研究模块 - 深度研究 agents  
research:
  temperature: 0.5
  max_tokens: 12000

# 题目模块 - 题目生成 agents
question:
  temperature: 0.7
  max_tokens: 4096

# 引导模块 - 学习引导 agents
guide:
  temperature: 0.5
  max_tokens: 16192

# 灵感生成模块 - 想法生成 agents
ideagen:
  temperature: 0.7
  max_tokens: 4096

# 协作写作模块 - 协作写作 agents
co_writer:
  temperature: 0.7
  max_tokens: 4096
```

### `config/main.yaml` - 系统设置

此文件控制路径、工具和模块特定设置：

```yaml
# 系统语言
system:
  language: en

# 数据路径
paths:
  user_data_dir: ./data/user
  knowledge_bases_dir: ./data/knowledge_bases

# 工具配置
tools:
  rag_tool:
    kb_base_dir: ./data/knowledge_bases
    default_kb: ai_textbook
  run_code:
    workspace: ./data/user/run_code_workspace
  web_search:
    enabled: true
  query_item:
    enabled: true
    max_results: 5

# 模块特定设置
research:
  researching:
    execution_mode: series      # "series" 或 "parallel"
    max_iterations: 5
    enable_rag_hybrid: true
    enable_paper_search: true
    enable_web_search: true
```

> **提示：** 对于大多数用户，默认配置已经足够好用。只有在需要特定自定义时才修改这些文件。

## 4. 知识库准备（可选）

您可以使用我们预构建的示例知识库来快速开始。

### 下载示例知识库

从 [Google Drive](https://drive.google.com/drive/folders/1iWwfZXiTuQKQqUYb5fGDZjLCeTUP6DA6?usp=sharing) 下载并解压到 `data/` 目录。

::: info 重要提示
示例知识库使用 `text-embedding-3-large`，`dimensions = 3072`。请确保您的嵌入模型具有匹配的维度。
:::

### 创建您自己的知识库

启动 DeepTutor 后：

1. 导航到 `http://localhost:3782/knowledge`
2. 点击 **"New Knowledge Base"**
3. 输入唯一的名称
4. 上传 PDF/TXT/MD 文件
5. 在终端中监控进度

---

**下一步：** [数据准备 →](/zh/guide/data-preparation)
