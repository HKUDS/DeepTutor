from typing import Optional

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class LLMSettings(BaseSettings):
    # Environment vars: LLM_BINDING, LLM_MODEL, LLM_HOST, LLM_API_KEY, DISABLE_SSL_VERIFY
    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="LLM_",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    binding: str = Field(
        default="openai",
        description="LLM service provider type (Supported types: openai, azure_openai, ollama, lollms, groq, openrouter, ollama-cloud).",
    )

    model: str = Field(
        default="qwen3:0.6b",
        description="LLM model name (make sure you use the correct model name which is supported by binding).",
    )

    host: str = Field(
        default="http://localhost:11434/v1/",
        description="LLM API endpoint URL (e.g. http://localhost:11434/v1/ is for Ollama hosted locally).",
    )

    api_key: str = Field(
        default="ollama",
        description="LLM API authentication key, for Ollama that is locally setup u can leave it empty",
    )

    disable_ssl_verify: bool = Field(
        default=False,
        description="If true, disables SSL verification (useful for self-signed certs).",
        validation_alias="DISABLE_SSL_VERIFY",
    )


class EmbeddingSettings(BaseSettings):
    # Environment vars: EMBEDDING_BINDING, EMBEDDING_MODEL, EMBEDDING_DIMENSION, EMBEDDING_HOST, EMBEDDING_API_KEY
    model_config = SettingsConfigDict(
        env_prefix="EMBEDDING_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    binding: str = Field(
        default="openai",
        description="Embedding service provider type (e.g. openai, azure_openai, ollama, lollms).",
    )

    model: str = Field(
        default="qwen3-embedding:0.6b",
        description="Embedding model name (e.g. text-embedding-3-large from openai).",
    )

    dimension: int = Field(
        default=4096,
        description="Embedding vector dimension. Should check accordingly for selected embedding model",
        validation_alias="EMBEDDING_DIM",
    )

    host: str = Field(
        default="http://localhost:11434/v1/",
        description="Embedding API endpoint URL (e.g. http://localhost:11434/v1/ is for Ollama hosted locally).",
    )

    api_key: str = Field(
        default="ollama",
        description="Embedding API authentication key for ollama locally setup you can pass anything.",
    )


class TTSSettings(BaseSettings):
    # Environment vars: TTS_MODEL, TTS_URL, TTS_API_KEY
    model_config = SettingsConfigDict(
        env_prefix="TTS_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    model: Optional[str] = Field(default=None, description="TTS model name")

    url: Optional[str] = Field(default=None, description="TTS API endpoint URL.")

    api_key: Optional[str] = Field(default=None, description="TTS API authentication key.")


class WebSearchSettings(BaseSettings):
    # Environment var: PERPLEXITY_API_KEY
    model_config = SettingsConfigDict(
        env_prefix="PERPLEXITY_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    api_key: Optional[str] = Field(
        default=None,
        description="Perplexity API key for web search functionality.",
        validation_alias="PERPLEXITY_API_KEY",
    )


class LoggingSettings(BaseSettings):
    # Environment vars: RAG_TOOL_MODULE_LOG_LEVEL
    model_config = SettingsConfigDict(
        env_prefix="LOGGING_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    rag_tool_module_log_level: str = Field(
        default="INFO", description="Log level for RAG tool module (DEBUG, INFO, WARNING, ERROR)."
    )


class RagSettings(BaseSettings):
    # Environment vars: RAG_PROVIDER
    model_config = SettingsConfigDict(
        env_prefix="RAG_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    rag_provider: str = Field(
        default="raganything",
        description="RAG provider identifier. Default is 'raganything' (RAG-Anything with MinerU + LightRAG).",
    )


class Settings(BaseSettings):
    """
    Loads values from .env (env_file).
    """

    llm: LLMSettings = LLMSettings()
    embedding: EmbeddingSettings = EmbeddingSettings()
    tts: TTSSettings = TTSSettings()
    web_search: WebSearchSettings = WebSearchSettings()
    logging: LoggingSettings = LoggingSettings()
    rag: RagSettings = RagSettings()


settings = Settings()
