"""Audited OpenAI Codex compatibility constants."""

CODEX_UPSTREAM_COMMIT = "81da9deb065d7adb283816b19b40f89bcc484276"
# Catalog compatibility: rust-v0.153.4, commit
# 3d2ee51ca2d5db578f328aa75e20aa22c0197c9a. Older versions omit eligible models.
# This request version is independent of the installed CLI and OAuth audit above.
CODEX_CLIENT_VERSION = "0.153.4"
CODEX_OAUTH_ISSUER = "https://auth.openai.com"
CODEX_OAUTH_CLIENT_ID = "app_EMoamEEZ73f0CkXaXp7hrann"
CODEX_OAUTH_SCOPE = "openid profile email offline_access api.connectors.read api.connectors.invoke"
CODEX_OAUTH_ORIGINATOR = "codex_cli_rs"
CODEX_CALLBACK_PORTS = (1455, 1457)
CODEX_CALLBACK_PATH = "/auth/callback"
CODEX_LOGIN_TIMEOUT_SECONDS = 300
CODEX_TOKEN_URL = f"{CODEX_OAUTH_ISSUER}/oauth/token"
CODEX_REVOKE_URL = f"{CODEX_OAUTH_ISSUER}/oauth/revoke"
CODEX_MODELS_URL = "https://chatgpt.com/backend-api/codex/models"
CODEX_RESPONSES_URL = "https://chatgpt.com/backend-api/codex/responses"
CODEX_FRESH_CACHE_SECONDS = 300
CODEX_STALE_CACHE_SECONDS = 86_400
CODEX_MAX_MODELS = 512
CODEX_MAX_CATALOG_BYTES = 8 * 1024 * 1024
# Fallback only, used when a caller does not name a model. The real list always
# comes from the signed-in account's live catalog.
CODEX_DEFAULT_MODEL = "gpt-5.6-sol"
CODEX_DEFAULT_MODEL_ID = f"openai-codex/{CODEX_DEFAULT_MODEL}"
