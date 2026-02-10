# Configuration

## Config Files

| File | Purpose |
|:-----|:--------|
| `.env` | API keys, ports, providers |
| `config/agents.yaml` | LLM parameters (temperature, max_tokens) |
| `config/main.yaml` | Paths, tools, module settings |

## Environment Variables

### Required

```bash
# LLM
LLM_MODEL=gpt-4o
LLM_API_KEY=your_api_key
LLM_HOST=https://api.openai.com/v1

# Embedding
EMBEDDING_MODEL=text-embedding-3-large
EMBEDDING_API_KEY=your_api_key
EMBEDDING_HOST=https://api.openai.com/v1
EMBEDDING_DIM=3072
```

### Optional

```bash
# Server ports (defaults: 8001/3782)
BACKEND_PORT=8001
FRONTEND_PORT=3782

# Remote access
NEXT_PUBLIC_API_BASE=http://your-server-ip:8001

# Web search
SEARCH_PROVIDER=perplexity  # or: baidu
PERPLEXITY_API_KEY=your_key

# TTS
TTS_MODEL=
TTS_URL=
TTS_API_KEY=
```

## Agent Parameters

Edit `config/agents.yaml`:

```yaml
solve:
  temperature: 0.3
  max_tokens: 8192

research:
  temperature: 0.5
  max_tokens: 12000

question:
  temperature: 0.7
  max_tokens: 4096
```

## Data Locations

```
data/
├── knowledge_bases/    # Your uploaded documents
└── user/
    ├── solve/          # Problem solving outputs
    ├── question/       # Generated questions
    ├── research/       # Research reports
    ├── guide/          # Learning sessions
    └── logs/           # System logs
```

---

📖 **Full reference**: [config/README.md](https://github.com/HKUDS/DeepTutor/tree/main/config)
