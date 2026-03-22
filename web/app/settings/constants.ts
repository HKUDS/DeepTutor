// Settings page constants

import { ConfigType } from "./types";

// Language options
export const LANGUAGE_OPTIONS = [
  { value: "en" as const, label: "English" },
  { value: "zh" as const, label: "中文" },
];

// Provider options - Cloud services first, then local deployments
export const PROVIDER_OPTIONS: Record<ConfigType, string[]> = {
  llm: [
    // Cloud providers
    "openai",
    "anthropic",
    "azure_openai",
    "deepseek",
    "openrouter",
    "novita",
    // Local providers
    "ollama",
    "lm_studio",
    "vllm",
    "llama_cpp",
  ],
  embedding: [
    // Cloud providers
    "openai",
    "azure_openai",
    "jina",
    "cohere",
    "huggingface",
    "google",
    "novita",
    // Local providers
    "ollama",
    "lm_studio",
  ],
  tts: ["openai", "azure_openai"],
  search: ["perplexity", "tavily", "exa", "jina", "serper", "baidu"],
};

// Local providers that don't require API keys
export const LOCAL_PROVIDERS = ["ollama", "lm_studio", "vllm", "llama_cpp"];

// Default base URLs for local providers
export const LOCAL_PROVIDER_URLS: Record<string, string> = {
  ollama: "http://localhost:11434/v1",
  lm_studio: "http://localhost:1234/v1",
  vllm: "http://localhost:8000/v1",
  llama_cpp: "http://localhost:8080/v1",
};

// Voice options for TTS
export const VOICE_OPTIONS = [
  "alloy",
  "echo",
  "fable",
  "onyx",
  "nova",
  "shimmer",
];

// Helper functions to get env var names
export function getEnvVarForBaseUrl(configType: ConfigType): string {
  const mapping: Record<ConfigType, string> = {
    llm: "LLM_HOST",
    embedding: "EMBEDDING_HOST",
    tts: "TTS_URL",
    search: "SEARCH_PROVIDER",
  };
  return mapping[configType];
}

export function getEnvVarForApiKey(configType: ConfigType): string {
  const mapping: Record<ConfigType, string> = {
    llm: "LLM_API_KEY",
    embedding: "EMBEDDING_API_KEY",
    tts: "TTS_API_KEY",
    search: "SEARCH_API_KEY",
  };
  return mapping[configType];
}
