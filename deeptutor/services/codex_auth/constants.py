"""Audited OpenAI Codex compatibility constants."""

CODEX_UPSTREAM_COMMIT = "81da9deb065d7adb283816b19b40f89bcc484276"
# Catalog compatibility: rust-v0.171.0, independent of CODEX_UPSTREAM_COMMIT.
CODEX_CLIENT_VERSION = "0.171.0"
CODEX_GITHUB_LATEST_RELEASE_URL = "https://api.github.com/repos/openai/codex/releases/latest"
CODEX_CATALOG_HEADER_SCHEMA = 2
CODEX_AUTO_REFRESH_INTERVAL_SECONDS = 7 * 24 * 3600
CODEX_AUTO_REFRESH_POLL_SECONDS = 300
CODEX_AUTO_REFRESH_FAILURE_BACKOFF_SECONDS = 900
CODEX_AUTO_REFRESH_LEASE_SECONDS = 120
CODEX_VERSION_TOTAL_TIMEOUT_SECONDS = 5
CODEX_STABLE_VERSION_PATTERN = r"(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)\.(0|[1-9][0-9]*)"
CODEX_NPM_LATEST_URL = "https://registry.npmjs.org/@openai%2Fcodex/latest"
CODEX_VERSION_TIMEOUT_SECONDS = 3
CODEX_MAX_VERSION_BYTES = 64 * 1024
CODEX_GITHUB_MAX_RELEASE_BYTES = 1024 * 1024
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
