# Configuration Directory

This directory contains all configuration files for the DeepTutor system. Configuration files are organized by module and utilize YAML format.

## 📁 Configuration Files

```
config/
├── main.yaml              # Main system configuration (all module settings)
├── agents.yaml            # Unified agent parameters (temperature, max_tokens)
└── README.md              # This documentation
```

## 📋 File Descriptions

### agents.yaml ⭐ NEW

**Unified agent parameters configuration** - The SINGLE source of truth for all agent `temperature` and `max_tokens` settings:

- **Purpose**: Centralized configuration for LLM parameters across all modules
- **Scope**: Each module shares ONE set of parameters for all its agents
- **Exception**: `narrator` has independent settings for TTS integration

**Key sections:**
```yaml
# Guide Module - Learning guidance agents
guide:
  temperature: 0.5
  max_tokens: 8192

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

# IdeaGen Module - Idea generation agents
ideagen:
  temperature: 0.7
  max_tokens: 4096

# CoWriter Module - Collaborative writing agents
co_writer:
  temperature: 0.7
  max_tokens: 4096

# Narrator Agent - Independent config for TTS
narrator:
  temperature: 0.7
  max_tokens: 4000
```

**Usage in code:**
```python
from src.core.core import get_agent_params

# Get parameters for a module
params = get_agent_params("guide")
temperature = params["temperature"]  # 0.5
max_tokens = params["max_tokens"]    # 8192
```

> **Important**: Do NOT hardcode `temperature` or `max_tokens` values in agent code. Always use `get_agent_params()` to load from this configuration.

---

### main.yaml

**Main system configuration file** - Contains shared settings used by all modules:

- **Server Configuration**: Backend and frontend port settings
- **System Settings**: System-wide language configuration
- **Path Configuration**: Data directory paths for all modules
- **Tool Configuration**: General tool settings (RAG, code execution, web search, query item)
- **Logging Configuration**: Logging levels, file output, console output, LightRAG forwarding
- **TTS Configuration**: Text-to-speech default voice
- **Question Module**: Question generation settings (max_rounds, agent-specific non-LLM parameters)
- **Research Module**: Planning, researching, reporting, RAG, queue, and preset configurations
- **Solve Module**: Iteration limits, citation settings, agent-specific non-LLM parameters

**Key sections:**
```yaml
server:
  backend_port: 8001
  frontend_port: 3782

system:
  language: en  # "zh" or "en"

paths:
  user_data_dir: ./data/user
  knowledge_bases_dir: ./data/knowledge_bases
  user_log_dir: ./data/user/logs
  performance_log_dir: ./data/user/performance
  # Module-specific output directories
  guide_output_dir: ./data/user/guide
  question_output_dir: ./data/user/question
  research_output_dir: ./data/user/research/cache
  research_reports_dir: ./data/user/research/reports
  solve_output_dir: ./data/user/solve

tools:
  rag_tool:
    kb_base_dir: ./data/knowledge_bases
    default_kb: ai_textbook
  run_code:
    workspace: ./data/user/run_code_workspace
    allowed_roots:
      - ./data/user
      - ./src/tools
  web_search:
    enabled: true  # Global switch for web search (affects all modules)
  query_item:
    enabled: true
    max_results: 5  # Max results returned by query_item tool

logging:
  level: DEBUG
  save_to_file: true
  console_output: true

tts:
  default_voice: alloy

# Question module settings (non-LLM parameters)
question:
  max_rounds: 10
  agents:
    question_generation:
      max_iterations: 5
      retrieve_top_k: 30
    question_validation:
      strict_mode: true

# Research module settings (non-LLM parameters)
research:
  planning:
    # ... planning settings
  researching:
    max_iterations: 5
    execution_mode: "parallel"
    # ... other settings
  reporting:
    # ... reporting settings
  presets:
    quick: # ...
    medium: # ...
    deep: # ...
    auto: # ...

# Solve module settings (non-LLM parameters)
solve:
  max_solve_correction_iterations: 3
  enable_citations: true
  agents:
    investigate_agent:
      max_actions_per_round: 1  # Max tool calls per investigation round
      max_iterations: 3         # Max analysis loop iterations (authoritative)
    precision_answer_agent:
      enabled: true
```

## 🔧 Configuration Hierarchy

Configuration files follow a hierarchy:

1. **Environment Variables** (`.env` or `DeepTutor.env`)
   - LLM API keys and endpoints
   - Model names
   - Override all other settings

2. **agents.yaml**
   - **SINGLE source of truth** for agent `temperature` and `max_tokens`
   - One set of parameters per module
   - Never hardcode these values in code

3. **main.yaml**
   - System-wide shared settings
   - Path configurations
   - All module-specific settings
   - Tool configurations

## 📝 Configuration Loading

Configuration files are loaded using `src/core/core.py`:

```python
from src.core.core import load_config_with_main, get_agent_params

# Load main configuration (returns main.yaml content)
config = load_config_with_main("main.yaml", project_root)

# Load agent parameters (temperature, max_tokens)
params = get_agent_params("solve")
temperature = params["temperature"]
max_tokens = params["max_tokens"]
```

**`load_config_with_main` function:**
1. Loads `config/main.yaml` as base configuration
2. Returns the configuration dictionary

**`get_agent_params` function:**
1. Loads `config/agents.yaml`
2. Returns the temperature and max_tokens for the specified module
3. Uses defaults if config not found

## 🔑 Environment Variables

Required environment variables (in `.env` or `DeepTutor.env`):

```bash
# LLM Configuration (Required)
LLM_API_KEY=your_api_key
LLM_HOST=https://api.openai.com/v1
LLM_MODEL=gpt-4o

# Optional
PERPLEXITY_API_KEY=your_perplexity_key  # For web search
```

## ⚙️ Configuration Best Practices

1. **Use agents.yaml for LLM parameters**: All `temperature` and `max_tokens` settings should be in `agents.yaml`
2. **Never hardcode LLM parameters**: Always use `get_agent_params()` in agent code
3. **Use main.yaml for all other settings**: Paths, logging, tools, module-specific settings
4. **Environment variables for secrets**: Never commit API keys to config files
5. **Relative paths**: Use relative paths from project root for portability
6. **Presets for common scenarios**: Use presets (e.g., in main.yaml research section) for different use cases

## 🔗 Related Modules

- **Core Configuration**: `src/core/core.py` - Configuration loading utilities
- **Setup**: `src/core/setup.py` - System initialization using config
- **Logging**: `src/core/logging/` - Logging system using config

## 🛠️ Modifying Configuration

### Adding a new configuration option:

1. Add LLM parameters (temperature, max_tokens) to `agents.yaml`
2. Add all other settings to `main.yaml`
3. Update the loading code if needed
4. Document the new option

### Changing default values:

1. Edit `agents.yaml` for LLM parameters
2. Edit `main.yaml` for other settings
3. Test the change
4. Update documentation if needed

## ⚠️ Important Notes

1. **Agent parameters centralization**: All `temperature` and `max_tokens` settings MUST be in `agents.yaml`. Do NOT hardcode these values in agent code.
2. **Model configuration**: LLM model names should only be set via environment variables (`.env` or `DeepTutor.env`), not in config files.
3. **Path consistency**: All modules use paths from `main.yaml` to ensure consistency. Use relative paths from project root for portability.
4. **Language setting**: System language is set in `main.yaml` (`system.language`) and shared by all modules. Individual modules should not override this.
5. **Research presets**: Use presets in `main.yaml` (research.presets: quick/medium/deep/auto) for different research depth requirements.
6. **Code execution safety**: The `run_code` tool in `main.yaml` has restricted `allowed_roots` for security.
7. **Narrator independence**: The `narrator` agent in `agents.yaml` has independent settings because it integrates with TTS API which has specific character limits.
8. **Web search global switch**: The `tools.web_search.enabled` setting in `main.yaml` is a global switch that affects all modules (research, solve). Module-specific enable flags work in conjunction with this global switch.
