# Data Directory

This directory stores all data files for the AI-Tutor system, including knowledge bases, user data, logs, etc.

## Directory Structure

```
data/
├── knowledge_bases/              # Knowledge base storage
└── user/                         # User activity data
    ├── agent/                    # Agent interaction history
    │   ├── solve/               # Problem-solving sessions
    │   │   ├── sessions.json    # Session list
    │   │   └── solve_xxx/       # Individual task outputs
    │   ├── chat/                # Chat sessions
    │   │   └── sessions.json    # Session list
    │   ├── question/            # Question generation
    │   │   └── batch_xxx/       # Batch outputs
    │   ├── research/            # Research outputs
    │   │   └── reports/         # Research reports
    │   ├── co-writer/           # Co-Writer outputs
    │   │   ├── history.json     # Operation history
    │   │   ├── audio/           # TTS audio files
    │   │   └── tool_calls/      # Tool call records
    │   ├── guide/               # Guided-learning sessions
    │   ├── run_code_workspace/  # Code execution workspace
    │   └── logs/                # Application logs
    │
    ├── workspace/               # User workspace
    │   └── notebook/            # User notebooks
    │       ├── notebooks_index.json
    │       └── {notebook_id}.json
    │
    └── settings/                # User settings
        ├── interface.json       # UI preferences
        ├── llm_configs.json     # LLM configurations
        ├── embedding_configs.json
        ├── tts_configs.json
        ├── search_configs.json
        └── knowledge_base_configs.json
```

## Directory Description

### knowledge_bases/

Stores all knowledge base data files for the AI-Tutor system.

### user/

Stores all user-generated data and output files.

#### agent/

Contains all agent interaction history, organized by module:

- **solve/**: Problem-solving module outputs
  - `sessions.json`: List of solver sessions with messages
  - `solve_xxx/`: Individual task directories with detailed outputs

- **chat/**: Chat module outputs
  - `sessions.json`: List of chat sessions with messages

- **question/**: Question generation module outputs
  - `batch_xxx/`: Batch generation directories

- **research/**: Research module outputs
  - `reports/`: Generated research reports and metadata

- **co-writer/**: Co-Writer module outputs
  - `history.json`: Operation history
  - `audio/`: TTS audio files
  - `tool_calls/`: Tool call records

- **guide/**: Guided-learning module outputs

- **run_code_workspace/**: Code execution workspace for temporarily storing files

- **logs/**: Application logs

#### workspace/

User workspace for organizing content:

- **notebook/**: User notebooks for saving and organizing content

#### settings/

User configuration files:

- **interface.json**: UI preferences (theme, language, sidebar)
- **llm_configs.json**: LLM provider configurations
- **embedding_configs.json**: Embedding provider configurations
- **tts_configs.json**: TTS provider configurations
- **search_configs.json**: Web search configurations
- **knowledge_base_configs.json**: KB-specific settings

## Configuration

Data directory paths are managed by `PathService` in `src/services/path_service.py`:

```python
from src.services.path_service import get_path_service

path_service = get_path_service()

# Agent paths
solve_dir = path_service.get_solve_dir()
chat_session_file = path_service.get_chat_session_file()

# Workspace paths
notebook_dir = path_service.get_notebook_dir()

# Settings paths
settings_dir = path_service.get_settings_dir()
interface_file = path_service.get_settings_file("interface")
```

## Notes

1. **Backup Important Data**: Recommend regularly backing up `knowledge_bases/` and important user data
2. **Version Control**: Recommend adding `data/` directory to `.gitignore` to avoid committing large files
3. **Disk Space**: Knowledge bases and user data may occupy significant disk space, clean old data regularly
4. **Permission Management**: Ensure application has read/write permissions
5. **Path Consistency**: All modules use `PathService` for unified path management

## Related Modules

- **Path Service**: `src/services/path_service.py` - Centralized path management
- **Session Management**: `src/services/session/` - Unified session storage
- **Knowledge Base Management**: `src/knowledge/` - Knowledge base operations
- **Logging System**: `src/logging/` - Unified logging management

## Maintenance Operations

### Clean Old Data

```bash
# Clean old task directories (customize based on retention policy)
find data/user/agent -type d -name "*_20*" -mtime +30 -exec rm -rf {} \;

# Clean temporary workspace files
find data/user/agent/run_code_workspace -type f -mtime +7 -delete
```

### Backup Knowledge Base

```bash
# Backup entire knowledge base directory
tar -czf knowledge_bases_backup_$(date +%Y%m%d).tar.gz data/knowledge_bases/

# Backup specific knowledge base
tar -czf kb_backup.tar.gz data/knowledge_bases/{kb_name}/
```

### Restore Knowledge Base

```bash
# Restore knowledge base
tar -xzf knowledge_bases_backup_20250101.tar.gz -C data/
```

## Migration

If migrating from an older directory structure, use the migration script:

```bash
python scripts/migrate_user_data.py
```

This will:
1. Move session files to `agent/{module}/sessions.json`
2. Move module directories under `agent/`
3. Move notebooks to `workspace/notebook/`
4. Delete deprecated files (user_history.json, etc.)
