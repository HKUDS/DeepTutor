"""
Settings API Router
Manages user settings: theme, language, environment variables, etc.
"""

import json
import os
from pathlib import Path
from typing import Any, Dict, Literal

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from src.services.embedding import get_embedding_config
from src.services.llm import get_llm_config
from src.services.tts import get_tts_config
from src.utils.config_manager import ConfigManager

router = APIRouter()
config_manager = ConfigManager()

# ==================== Environment Variables Configuration ====================
# Define all supported environment variables with descriptions
# These variables can be modified at runtime without restarting the server

ENV_VAR_DEFINITIONS = {
    # LLM Mode Configuration
    "LLM_MODE": {
        "description": "LLM deployment mode: 'api' (cloud only), 'local' (self-hosted only), 'hybrid' (both, use active provider)",
        "category": "llm",
        "required": False,
        "default": "hybrid",
        "sensitive": False,
    },
    # LLM Configuration (supports both cloud and local)
    "LLM_BINDING": {
        "description": "LLM protocol type: openai (for OpenAI-compatible APIs including Ollama, vLLM), anthropic (for Claude)",
        "category": "llm",
        "required": False,
        "default": "openai",
        "sensitive": False,
    },
    "LLM_MODEL": {
        "description": "Model name. Cloud: gpt-4o, deepseek-chat. Local: llama3.2, qwen2.5, mistral-nemo",
        "category": "llm",
        "required": True,
        "default": "",
        "sensitive": False,
    },
    "LLM_HOST": {
        "description": "API endpoint. Cloud: https://api.openai.com/v1. Local: http://localhost:11434/v1 (Ollama), http://localhost:1234/v1 (LM Studio)",
        "category": "llm",
        "required": True,
        "default": "",
        "sensitive": False,
    },
    "LLM_API_KEY": {
        "description": "API key (required for cloud, optional for local - use 'ollama' or any string for Ollama)",
        "category": "llm",
        "required": True,
        "default": "",
        "sensitive": True,
    },
    # Embedding Configuration (supports both cloud and local)
    "EMBEDDING_BINDING": {
        "description": "Embedding provider: openai, ollama, lm_studio, azure_openai, jina, cohere, huggingface",
        "category": "embedding",
        "required": False,
        "default": "openai",
        "sensitive": False,
    },
    "EMBEDDING_MODEL": {
        "description": "Model name. Cloud: text-embedding-3-large. Local: nomic-embed-text, mxbai-embed-large",
        "category": "embedding",
        "required": True,
        "default": "",
        "sensitive": False,
    },
    "EMBEDDING_DIM": {
        "description": "Vector dimension: 3072 (text-embedding-3-large), 768 (nomic-embed-text), 1024 (mxbai)",
        "category": "embedding",
        "required": False,
        "default": "3072",
        "sensitive": False,
    },
    "EMBEDDING_HOST": {
        "description": "API endpoint. Cloud: https://api.openai.com/v1. Local: http://localhost:11434 (Ollama)",
        "category": "embedding",
        "required": True,
        "default": "",
        "sensitive": False,
    },
    "EMBEDDING_API_KEY": {
        "description": "API key (required for cloud providers, not needed for Ollama/local)",
        "category": "embedding",
        "required": False,
        "default": "",
        "sensitive": True,
        "conditional": "Required for cloud providers (OpenAI, Jina, Cohere, etc.). Not needed for Ollama or local models.",
    },
    # TTS Configuration (OpenAI compatible API)
    "TTS_MODEL": {
        "description": "OpenAI TTS model (tts-1 for speed, tts-1-hd for quality)",
        "category": "tts",
        "required": False,
        "default": "",
        "sensitive": False,
    },
    "TTS_URL": {
        "description": "OpenAI compatible API endpoint (e.g., https://api.openai.com/v1)",
        "category": "tts",
        "required": False,
        "default": "",
        "sensitive": False,
    },
    "TTS_API_KEY": {
        "description": "TTS API authentication key (OpenAI API Key)",
        "category": "tts",
        "required": False,
        "default": "",
        "sensitive": True,
    },
    "TTS_VOICE": {
        "description": "Default voice: alloy, echo, fable, onyx, nova, shimmer",
        "category": "tts",
        "required": False,
        "default": "alloy",
        "sensitive": False,
    },
    # BananaPPT Image Configuration
    "BANANA_PPT_IMAGE_MODEL": {
        "description": "Image model name (e.g., gemini-2.5-flash-image, dall-e-3)",
        "category": "banana_ppt",
        "required": False,
        "default": "",
        "sensitive": False,
    },
    "BANANA_PPT_IMAGE_API_KEY": {
        "description": "API key for BananaPPT image generation",
        "category": "banana_ppt",
        "required": False,
        "default": "",
        "sensitive": True,
    },
    "BANANA_PPT_IMAGE_BASE_URL": {
        "description": "Image API base URL (e.g., https://generativelanguage.googleapis.com/v1beta)",
        "category": "banana_ppt",
        "required": False,
        "default": "",
        "sensitive": False,
    },
    "BANANA_PPT_IMAGE_BINDING": {
        "description": "Image provider binding: gemini or openai",
        "category": "banana_ppt",
        "required": False,
        "default": "gemini",
        "sensitive": False,
    },
    "BANANA_PPT_IMAGE_ASPECT_RATIO": {
        "description": "Image aspect ratio (default: 16:9)",
        "category": "banana_ppt",
        "required": False,
        "default": "16:9",
        "sensitive": False,
    },
    # Web Search Configuration
    "PERPLEXITY_API_KEY": {
        "description": "Perplexity API key for web search functionality",
        "category": "search",
        "required": False,
        "default": "",
        "sensitive": True,
    },
}

# Categories for organizing the UI
ENV_CATEGORIES = {
    "llm": {
        "name": "LLM Configuration",
        "description": "LLM settings for AI reasoning. Supports cloud APIs (OpenAI, DeepSeek) and local servers (Ollama, LM Studio).",
        "icon": "brain",
    },
    "embedding": {
        "name": "Embedding Configuration",
        "description": "Embedding settings for RAG. Supports cloud (OpenAI) and local (Ollama with nomic-embed-text).",
        "icon": "database",
    },
    "tts": {
        "name": "TTS Configuration",
        "description": "Text-to-Speech settings (OpenAI-compatible API).",
        "icon": "volume",
    },
    "search": {
        "name": "Web Search Configuration",
        "description": "External search API settings (Perplexity)",
        "icon": "search",
    },
    "banana_ppt": {
        "name": "BananaPPT Image Configuration",
        "description": "Image generation settings for Banana PPT export",
        "icon": "settings",
    },
}

# Settings file path (for local client/UI prefs not appropriate for main.yaml)
SETTINGS_FILE = Path(__file__).parent.parent.parent.parent / "data" / "user" / "settings.json"

# Default UI settings
DEFAULT_UI_SETTINGS = {
    "theme": "light",
    "language": "zh",
    "output_language": "zh",
}


class UISettings(BaseModel):
    theme: Literal["light", "dark"] = "light"
    language: Literal["zh", "en"] = "en"
    output_language: Literal["zh", "en"] = "en"


class FullSettingsResponse(BaseModel):
    ui: UISettings
    config: Dict[str, Any]
    env: Dict[str, str]


# Environment variable models
class EnvVarInfo(BaseModel):
    """Information about a single environment variable"""

    key: str
    value: str
    description: str
    category: str
    required: bool
    default: str
    sensitive: bool
    is_set: bool  # Whether the variable has a non-empty value


class EnvCategoryInfo(BaseModel):
    """Information about an environment variable category"""

    id: str
    name: str
    description: str
    icon: str


class EnvConfigResponse(BaseModel):
    """Response for environment configuration"""

    variables: list[EnvVarInfo]
    categories: list[EnvCategoryInfo]


class EnvVarUpdate(BaseModel):
    """Single environment variable update"""

    key: str
    value: str


class EnvConfigUpdate(BaseModel):
    """Batch environment variables update"""

    variables: list[EnvVarUpdate]


class ConfigUpdate(BaseModel):
    config: Dict[str, Any]


class ThemeUpdate(BaseModel):
    theme: Literal["light", "dark"]


def load_ui_settings() -> dict:
    """Load UI-specific settings from json file"""
    if SETTINGS_FILE.exists():
        try:
            with open(SETTINGS_FILE, encoding="utf-8") as f:
                saved = json.load(f)
                return {**DEFAULT_UI_SETTINGS, **saved}
        except Exception:
            pass
    return DEFAULT_UI_SETTINGS.copy()


def save_ui_settings(settings: dict):
    """Save UI settings"""
    SETTINGS_FILE.parent.mkdir(parents=True, exist_ok=True)
    with open(SETTINGS_FILE, "w", encoding="utf-8") as f:
        json.dump(settings, f, ensure_ascii=False, indent=2)


@router.get("", response_model=FullSettingsResponse)
async def get_settings():
    """
    Get all settings:
    1. UI preferences (theme, etc)
    2. Backend Configuration (main.yaml)
    3. Environment Info (models, etc)
    """
    ui_settings = load_ui_settings()
    main_config = config_manager.load_config()
    env_info = config_manager.get_env_info()

    return {"ui": ui_settings, "config": main_config, "env": env_info}


@router.put("/config")
async def update_config(update: ConfigUpdate):
    """Update main.yaml configuration"""
    # Filter out immutable sections if needed (e.g. server port),
    # but for now we trust `save_config` to handle the merge.
    # Ideally should validate against a schema.

    success = config_manager.save_config(update.config)
    if not success:
        raise HTTPException(status_code=500, detail="Failed to save configuration")

    return config_manager.load_config()


@router.put("/theme")
async def update_theme(update: ThemeUpdate):
    """Update UI theme"""
    current_ui = load_ui_settings()
    current_ui["theme"] = update.theme
    save_ui_settings(current_ui)
    return {"theme": update.theme}


@router.put("/ui")
async def update_ui_settings(update: UISettings):
    """Update all UI settings"""
    current_ui = load_ui_settings()
    update_dict = update.model_dump(exclude_none=True)
    current_ui.update(update_dict)
    save_ui_settings(current_ui)
    return current_ui


@router.post("/reset")
async def reset_settings():
    """Reset UI settings to default"""
    save_ui_settings(DEFAULT_UI_SETTINGS)
    return DEFAULT_UI_SETTINGS


@router.get("/themes")
async def get_themes():
    """Get available theme list"""
    return {
        "themes": [
            {"id": "light", "name": "Light"},
            {"id": "dark", "name": "Dark"},
        ]
    }


# Legacy/Specific endpoints required by current frontend (will be deprecated/updated)
# Keeping them for now if needed, or rewriting them to use new logic if frontend calls them.
# The user wants "Refactor entire backend logic", so I can break old endpoints if I update frontend.
# But keeping some compatibility or simple redirect is good practice.


@router.get("/system-language")
async def get_system_language():
    """Get system language from main.yaml"""
    config = config_manager.load_config()
    system_config = config.get("system", {})
    language = system_config.get("language", "en")
    return {"language": language}


class SystemLanguageUpdate(BaseModel):
    language: Literal["zh", "en"]


@router.put("/system-language")
async def update_system_language(update: SystemLanguageUpdate):
    """Update system language in main.yaml"""
    config = config_manager.load_config()
    if "system" not in config:
        config["system"] = {}
    config["system"]["language"] = update.language
    if config_manager.save_config(config):
        return {"language": update.language}
    raise HTTPException(status_code=500, detail="Failed to save system language")


@router.get("/config-info")
async def get_config_info():
    """Get configuration information (paths, kb settings, etc.)"""
    config = config_manager.load_config()

    paths = config.get("paths", {})
    user_data_dir = paths.get("user_data_dir", "./data/user")
    kb_base_dir = (
        config.get("tools", {}).get("rag_tool", {}).get("kb_base_dir", "./data/knowledge_bases")
    )
    default_kb = config.get("tools", {}).get("rag_tool", {}).get("default_kb", "ai_textbook")
    workspace = (
        config.get("tools", {})
        .get("run_code", {})
        .get("workspace", "./data/user/run_code_workspace")
    )

    return {
        "kb_base_dir": kb_base_dir,
        "user_data_dir": user_data_dir,
        "default_kb": default_kb,
        "workspace": workspace,
    }


# ==================== Environment Variables API ====================


def _mask_sensitive_value(value: str, sensitive: bool) -> str:
    """Mask sensitive values for display (show first 4 and last 4 chars)"""
    if not sensitive or not value:
        return value
    if len(value) <= 8:
        return "*" * len(value)
    return f"{value[:4]}{'*' * (len(value) - 8)}{value[-4:]}"


@router.get("/env", response_model=EnvConfigResponse)
async def get_env_config():
    """
    Get all environment variables configuration.

    Returns current values (with sensitive values masked), descriptions,
    and category information for the frontend to display.

    Note: This returns the runtime values, which may differ from .env file
    if they have been updated via the API.
    """
    variables = []

    for key, definition in ENV_VAR_DEFINITIONS.items():
        current_value = os.environ.get(key, definition["default"])
        is_set = bool(current_value and current_value.strip())

        variables.append(
            EnvVarInfo(
                key=key,
                value=_mask_sensitive_value(current_value, definition["sensitive"]),
                description=definition["description"],
                category=definition["category"],
                required=definition["required"],
                default=definition["default"],
                sensitive=definition["sensitive"],
                is_set=is_set,
            )
        )

    categories = [
        EnvCategoryInfo(id=cat_id, **cat_info) for cat_id, cat_info in ENV_CATEGORIES.items()
    ]

    return EnvConfigResponse(variables=variables, categories=categories)


@router.get("/env/{key}")
async def get_env_var(key: str):
    """
    Get a single environment variable value.

    For sensitive variables, returns masked value.
    """
    if key not in ENV_VAR_DEFINITIONS:
        raise HTTPException(status_code=404, detail=f"Unknown environment variable: {key}")

    definition = ENV_VAR_DEFINITIONS[key]
    current_value = os.environ.get(key, definition["default"])

    return {
        "key": key,
        "value": _mask_sensitive_value(current_value, definition["sensitive"]),
        "description": definition["description"],
        "category": definition["category"],
        "required": definition["required"],
        "is_set": bool(current_value and current_value.strip()),
    }


def _update_dot_env(updates: Dict[str, str], removals: list[str]):
    """Update variables in .env file preserving comments and structure."""
    env_path = Path(__file__).parent.parent.parent.parent / ".env"

    if not env_path.exists():
        # Create new if doesn't exist
        with open(env_path, "w", encoding="utf-8") as f:
            for k, v in updates.items():
                if " " in v or "#" in v:
                    f.write(f'{k}="{v}"\n')
                else:
                    f.write(f"{k}={v}\n")
        return

    # Read existing
    try:
        with open(env_path, "r", encoding="utf-8") as f:
            lines = f.readlines()
    except Exception as e:
        print(f"Error reading .env: {e}")
        return

    new_lines = []
    processed_keys = set()

    for line in lines:
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            new_lines.append(line)
            continue

        # Parse key
        if "=" in stripped:
            key = stripped.split("=")[0].strip()

            if key in removals:
                continue  # Skip/Remove this line

            if key in updates:
                # Update this line
                val = updates[key]
                # Simple quoting suggestion
                if " " in val or "#" in val or '"' in val or "'" in val:
                    # minimal escape of double quotes
                    val = val.replace('"', '\\"')
                    new_lines.append(f'{key}="{val}"\n')
                else:
                    new_lines.append(f"{key}={val}\n")
                processed_keys.add(key)
                continue

        new_lines.append(line)

    # Append new keys that weren't found
    for k, v in updates.items():
        if k not in processed_keys and k not in removals:
            if " " in v or "#" in v or '"' in v or "'" in v:
                val = v.replace('"', '\\"')
                new_lines.append(f'\n{k}="{val}"\n')
            else:
                new_lines.append(f"\n{k}={v}\n")

    # Write back
    try:
        with open(env_path, "w", encoding="utf-8") as f:
            f.writelines(new_lines)
    except Exception as e:
        print(f"Error writing .env: {e}")


@router.put("/env")
async def update_env_config(update: EnvConfigUpdate):
    """
    Update environment variables at runtime and persist to .env.
    """
    updated_vars = []
    errors = []

    env_updates = {}
    env_removals = []

    for var_update in update.variables:
        key = var_update.key
        value = var_update.value

        # Validate the variable is known
        if key not in ENV_VAR_DEFINITIONS:
            errors.append(f"Unknown environment variable: {key}")
            continue

        definition = ENV_VAR_DEFINITIONS[key]

        # Skip if value is masked (user didn't change it)
        if definition["sensitive"] and "*" in value:
            # Value is masked, skip update
            continue

        # Update the environment variable
        if value:
            os.environ[key] = value
            env_updates[key] = value
        elif key in os.environ:
            # If value is empty and variable exists, remove it
            del os.environ[key]
            env_removals.append(key)

        updated_vars.append(key)

    # Persist to .env
    if env_updates or env_removals:
        _update_dot_env(env_updates, env_removals)

    if errors:
        raise HTTPException(status_code=400, detail={"errors": errors, "updated": updated_vars})

    # Return the updated configuration
    return {
        "success": True,
        "updated": updated_vars,
        "message": f"Updated {len(updated_vars)} environment variables.",
    }


@router.put("/env/{key}")
async def update_single_env_var(key: str, value: str):
    """
    Update a single environment variable at runtime.

    Note: Changes are NOT persisted to .env file.
    """
    if key not in ENV_VAR_DEFINITIONS:
        raise HTTPException(status_code=404, detail=f"Unknown environment variable: {key}")

    definition = ENV_VAR_DEFINITIONS[key]

    # Skip if value is masked (user didn't change it)
    if definition["sensitive"] and "*" in value:
        return {"success": False, "message": "Cannot update with masked value"}

    # Update the environment variable
    if value:
        os.environ[key] = value
        _update_dot_env({key: value}, [])
    elif key in os.environ:
        del os.environ[key]
        _update_dot_env({}, [key])

    return {
        "success": True,
        "key": key,
        "message": f"Environment variable {key} updated.",
    }


@router.post("/env/test")
async def test_env_config():
    """
    Test current environment configuration by validating all services.

    Returns the status of each service (LLM, Embedding, TTS).
    """
    results = {
        "llm": {"status": "unknown", "model": None, "error": None},
        "embedding": {"status": "unknown", "model": None, "error": None},
        "tts": {"status": "unknown", "model": None, "error": None},
    }

    # Test LLM configuration
    try:
        llm_config = get_llm_config()
        results["llm"]["model"] = llm_config.model
        results["llm"]["status"] = "configured"
    except ValueError as e:
        results["llm"]["status"] = "not_configured"
        results["llm"]["error"] = str(e)
    except Exception as e:
        results["llm"]["status"] = "error"
        results["llm"]["error"] = str(e)

    # Test Embedding configuration
    try:
        embedding_config = get_embedding_config()
        results["embedding"]["model"] = embedding_config.model
        results["embedding"]["status"] = "configured"
    except ValueError as e:
        results["embedding"]["status"] = "not_configured"
        results["embedding"]["error"] = str(e)
    except Exception as e:
        results["embedding"]["status"] = "error"
        results["embedding"]["error"] = str(e)

    # Test TTS configuration
    try:
        tts_config = get_tts_config()
        results["tts"]["model"] = tts_config.get("model")
        results["tts"]["status"] = "configured"
    except ValueError as e:
        results["tts"]["status"] = "not_configured"
        results["tts"]["error"] = str(e)
    except Exception as e:
        results["tts"]["status"] = "error"
        results["tts"]["error"] = str(e)

    return results


@router.post("/env/test/{service}")
async def test_single_service(service: Literal["llm", "embedding", "tts"]):
    """
    Test a single service configuration with actual API call.

    Args:
        service: The service to test (llm, embedding, tts)

    Returns:
        Test result with status, model info, and response time.
    """
    import time

    result = {
        "status": "unknown",
        "model": None,
        "error": None,
        "response_time_ms": None,
        "message": None,
    }

    start_time = time.time()

    if service == "llm":
        try:
            from src.services.llm import complete as llm_complete

            llm_config = get_llm_config()
            result["model"] = llm_config.model

            # Actually test the LLM with a simple prompt
            response = await llm_complete(
                model=llm_config.model,
                prompt="Say 'OK' if you can hear me.",
                system_prompt="You are a test assistant. Reply with just 'OK'.",
                api_key=llm_config.api_key,
                base_url=llm_config.base_url,
                binding=llm_config.binding,
                max_tokens=10,
            )
            result["status"] = "success"
            result["message"] = (
                f"Response: {response[:50]}..." if len(response) > 50 else f"Response: {response}"
            )
        except ValueError as e:
            result["status"] = "not_configured"
            result["error"] = str(e)
        except Exception as e:
            result["status"] = "error"
            result["error"] = str(e)

    elif service == "embedding":
        try:
            from src.services.embedding import get_embedding_client

            embedding_config = get_embedding_config()
            result["model"] = embedding_config.model

            # Actually test embedding with a simple text
            embedding_client = get_embedding_client()
            embeddings = await embedding_client.embed(["Test embedding"])
            if embeddings and len(embeddings) > 0:
                result["status"] = "success"
                result["message"] = f"Dimension: {len(embeddings[0])}"
            else:
                result["status"] = "error"
                result["error"] = "Empty embedding returned"
        except ValueError as e:
            result["status"] = "not_configured"
            result["error"] = str(e)
        except Exception as e:
            result["status"] = "error"
            result["error"] = str(e)

    elif service == "tts":
        try:
            tts_config = get_tts_config()
            result["model"] = tts_config.get("model")

            # For TTS, just check if config is valid (actual audio test is expensive)
            if tts_config.get("model") and tts_config.get("base_url"):
                result["status"] = "success"
                result["message"] = f"Voice: {tts_config.get('voice', 'alloy')}"
            else:
                result["status"] = "not_configured"
                result["error"] = "Missing model or base_url"
        except ValueError as e:
            result["status"] = "not_configured"
            result["error"] = str(e)
        except Exception as e:
            result["status"] = "error"
            result["error"] = str(e)

    result["response_time_ms"] = int((time.time() - start_time) * 1000)
    return result


# ==================== RAG Provider Configuration ====================


@router.get("/rag/providers")
async def get_rag_providers():
    """
    Get list of available RAG providers.

    Returns:
        {
            "providers": [...],
            "current": "lightrag"
        }
    """
    try:
        from src.tools.rag_tool import get_available_providers, get_current_provider

        providers = get_available_providers()
        current = get_current_provider()

        return {"providers": providers, "current": current}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to get RAG providers: {str(e)}")
