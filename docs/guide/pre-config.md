# Pre-Configuration

Before starting DeepTutor, you need to complete the following setup steps.

## 1. Clone Repository

```bash
git clone https://github.com/HKUDS/DeepTutor.git
cd DeepTutor
```

## 2. Environment Variables Setup

Create your `.env` file from the template:

```bash
cp .env.example .env
```

Then edit the `.env` file with your API keys:

```bash
# ============================================================================
# Server Configuration
# ============================================================================
BACKEND_PORT=8001                         # Backend API port
FRONTEND_PORT=3782                        # Frontend web port

# For remote/LAN access - set to your server's IP address
# NEXT_PUBLIC_API_BASE=http://192.168.1.100:8001

# ============================================================================
# LLM (Large Language Model) Configuration - Required
# ============================================================================
LLM_BINDING=openai                        # Provider: openai, anthropic, azure_openai, ollama, etc.
LLM_MODEL=gpt-4o                          # Model name: gpt-4o, deepseek-chat, claude-3-5-sonnet, etc.
LLM_HOST=https://api.openai.com/v1        # API endpoint URL
LLM_API_KEY=your_api_key                  # Your LLM API key

# ============================================================================
# Embedding Model Configuration - Required for Knowledge Base
# ============================================================================
EMBEDDING_BINDING=openai                  # Provider type
EMBEDDING_MODEL=text-embedding-3-large    # Embedding model name
EMBEDDING_DIMENSION=3072                  # Must match model dimensions
EMBEDDING_HOST=https://api.openai.com/v1  # API endpoint
EMBEDDING_API_KEY=your_api_key            # Embedding API key

# ============================================================================
# Web Search Configuration - Optional
# ============================================================================
SEARCH_PROVIDER=perplexity                # Options: perplexity, tavily, serper, jina, exa, baidu
SEARCH_API_KEY=your_search_api_key        # API key for search provider
```

### Environment Variables Reference

| Variable | Required | Description |
|:---|:---:|:---|
| `LLM_MODEL` | **Yes** | Model name (e.g., `gpt-4o`, `deepseek-chat`) |
| `LLM_API_KEY` | **Yes** | Your LLM API key |
| `LLM_HOST` | **Yes** | API endpoint URL |
| `EMBEDDING_MODEL` | **Yes** | Embedding model name |
| `EMBEDDING_DIMENSION` | **Yes** | Must match model output dimensions |
| `EMBEDDING_API_KEY` | **Yes** | Embedding API key |
| `EMBEDDING_HOST` | **Yes** | Embedding API endpoint |
| `BACKEND_PORT` | No | Backend port (default: `8001`) |
| `FRONTEND_PORT` | No | Frontend port (default: `3782`) |
| `NEXT_PUBLIC_API_BASE` | No | Set for remote/LAN access |
| `SEARCH_PROVIDER` | No | Web search provider |
| `SEARCH_API_KEY` | No | Search API key |

### Supported LLM Providers

| Provider | `LLM_BINDING` Value | Notes |
|:---------|:--------------------|:------|
| OpenAI | `openai` | GPT-4o, GPT-4, GPT-3.5 |
| Anthropic | `anthropic` | Claude 3.5, Claude 3 |
| Azure OpenAI | `azure_openai` | Enterprise deployments |
| Ollama | `ollama` | Local models |
| DeepSeek | `deepseek` | DeepSeek-V3, DeepSeek-R1 |
| Groq | `groq` | Fast inference |
| OpenRouter | `openrouter` | Multi-model gateway |
| Google Gemini | `gemini` | OpenAI-compatible mode |

### Supported Embedding Providers

| Provider | `EMBEDDING_BINDING` Value | Notes |
|:---------|:--------------------------|:------|
| OpenAI | `openai` | text-embedding-3-large/small |
| Azure OpenAI | `azure_openai` | Enterprise deployments |
| Jina AI | `jina` | jina-embeddings-v3 |
| Cohere | `cohere` | embed-v3 series |
| Ollama | `ollama` | Local embedding models |
| LM Studio | `lm_studio` | Local inference server |
| HuggingFace | `huggingface` | OpenAI-compatible endpoints |

## 3. Configuration Files

DeepTutor uses two YAML configuration files for customization:

### `config/agents.yaml` - Agent Parameters

This file controls LLM parameters for each module:

```yaml
# Solve Module - Problem solving agents
solve:
  temperature: 0.3
  max_tokens: 8192

# Research Module - Deep research agents  
research:
  temperature: 0.5
  max_tokens: 12000

# Question Module - Question generation agents
question:
  temperature: 0.7
  max_tokens: 4096

# Guide Module - Learning guidance agents
guide:
  temperature: 0.5
  max_tokens: 16192

# IdeaGen Module - Idea generation agents
ideagen:
  temperature: 0.7
  max_tokens: 4096

# CoWriter Module - Collaborative writing agents
co_writer:
  temperature: 0.7
  max_tokens: 4096
```

### `config/main.yaml` - System Settings

This file controls paths, tools, and module-specific settings:

```yaml
# System language
system:
  language: en

# Data paths
paths:
  user_data_dir: ./data/user
  knowledge_bases_dir: ./data/knowledge_bases

# Tool configuration
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

# Module-specific settings
research:
  researching:
    execution_mode: series      # "series" or "parallel"
    max_iterations: 5
    enable_rag_hybrid: true
    enable_paper_search: true
    enable_web_search: true
```

> **Tip:** For most users, the default configuration works well. Only modify these files if you need specific customizations.

## 4. Knowledge Base Preparation (Optional)

You can use our pre-built demo knowledge bases to get started quickly.

### Download Demo Knowledge Bases

Download from [Google Drive](https://drive.google.com/drive/folders/1iWwfZXiTuQKQqUYb5fGDZjLCeTUP6DA6?usp=sharing) and extract into the `data/` directory.

::: info Important
The demo knowledge bases use `text-embedding-3-large` with `dimensions = 3072`. Make sure your embedding model has matching dimensions.
:::

### Create Your Own Knowledge Base

After launching DeepTutor:

1. Navigate to `http://localhost:3782/knowledge`
2. Click **"New Knowledge Base"**
3. Enter a unique name
4. Upload PDF/TXT/MD files
5. Monitor progress in the terminal

---

**Next Step:** [Data Preparation →](/guide/data-preparation)
