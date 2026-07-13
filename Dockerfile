# ============================================
# DeepTutor Multi-Stage Dockerfile
# ============================================
# This Dockerfile builds a production-ready image for DeepTutor
# containing both the FastAPI backend and Next.js frontend
#
# Build/run:
#   docker build -t deeptutor:local .
#   docker run -p 127.0.0.1:3782:3782 -p 127.0.0.1:8001:8001 \
#     -v deeptutor-data:/app/data deeptutor:local
#
# Prerequisites:
#   1. Runtime settings are created under data/user/settings on first start
#   2. Configure provider profiles from the web Settings page or model_catalog.json
# ============================================

# ============================================
# Stage 1: Frontend Builder
# ============================================
# Run on the build platform natively (not under QEMU emulation).
# The output is platform-independent static assets (JS/HTML/CSS),
# so there is no need to cross-compile this stage.
FROM --platform=$BUILDPLATFORM node:22-slim AS frontend-builder

WORKDIR /app/web

# Copy package files first for better caching
COPY web/package.json web/package-lock.json* ./

# Install dependencies with generous timeout for CI environments
RUN npm config set fetch-timeout 600000 && \
    npm config set fetch-retries 5 && \
    npm ci --legacy-peer-deps

# Copy frontend source code
COPY web/ ./

# Provide the single source of truth for the app version so next.config.js
# can read it during ``npm run build`` and inline it into the bundle.
COPY deeptutor/__version__.py /app/deeptutor/__version__.py

# Create .env.local with the single env var the build needs (the app version,
# exposed to the browser via next.config.js). URL knowledge is no longer baked
# into the bundle: `apiUrl`/`wsUrl` in web/lib/api.ts are pass-throughs and
# the actual backend host is read at request time by web/proxy.ts from
# DEEPTUTOR_API_BASE_URL (exported by the entrypoint on every start).
RUN printf 'NEXT_PUBLIC_APP_VERSION=\n' > .env.local

# Build Next.js for production with standalone output
# This allows runtime environment variable injection
RUN npm run build

# ============================================
# Stage 1b: Node Runtime for Target Platform
# ============================================
# Provides the correctly-architected node binary for the final image.
# Unlike frontend-builder (pinned to BUILDPLATFORM), this stage pulls
# the node image matching each target platform (amd64 / arm64).
FROM node:22-slim AS node-runtime

# ============================================
# Stage 2: Python Base with Dependencies
# ============================================
FROM python:3.11-slim AS python-base

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONIOENCODING=utf-8 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Install system dependencies
# Note: libgl1 and libglib2.0-0 are required for OpenCV (used by mineru)
# Rust is required for building tiktoken and other packages without pre-built wheels
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    git \
    build-essential \
    libgl1 \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender1 \
    pkg-config \
    libssl-dev \
    && rm -rf /var/lib/apt/lists/* \
    && curl --proto '=https' --tlsv1.2 -sSf https://sh.rustup.rs | sh -s -- -y

# Add Rust to PATH
ENV PATH="/root/.cargo/bin:${PATH}"

# Copy requirements and install Python dependencies
COPY requirements/ ./requirements/
COPY requirements.txt ./
RUN pip install --upgrade pip && \
    pip install -r requirements.txt

# ============================================
# Stage 3: Production Image
# ============================================
FROM python:3.11-slim AS production

# Labels
LABEL maintainer="DeepTutor Team" \
      description="DeepTutor: AI-Powered Personalized Learning Assistant"

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONIOENCODING=utf-8 \
    NODE_ENV=production \
    DEEPTUTOR_IGNORE_PROCESS_ENV_OVERRIDES=1

# Code-execution sandbox: the restricted-subprocess backend (which the office
# skills — docx/pdf/pptx/xlsx — rely on for `exec` / `code_execution`) is
# enabled by default via the `sandbox_allow_subprocess` runtime setting
# (system.json, default on), exported to DEEPTUTOR_SANDBOX_ALLOW_SUBPROCESS at
# startup. No hardcoded ENV here — that would override the setting and block
# disabling it. docker-compose still routes exec to the hardened runner sidecar
# (DEEPTUTOR_SANDBOX_RUNNER_URL), which build_backend() prefers.

WORKDIR /app

# Install system dependencies
# Note: libgl1 and libglib2.0-0 are required for OpenCV (used by mineru)
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    ca-certificates \
    bash \
    supervisor \
    libgl1 \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender1 \
    && rm -rf /var/lib/apt/lists/*

# Copy Node.js from node-runtime stage (platform-matched binary)
COPY --from=node-runtime /usr/local/bin/node /usr/local/bin/node
COPY --from=node-runtime /usr/local/lib/node_modules /usr/local/lib/node_modules
RUN ln -sf /usr/local/lib/node_modules/npm/bin/npm-cli.js /usr/local/bin/npm \
    && ln -sf /usr/local/lib/node_modules/npm/bin/npx-cli.js /usr/local/bin/npx \
    && node --version && npm --version

# Copy Python packages from builder stage
COPY --from=python-base /usr/local/lib/python3.11/site-packages /usr/local/lib/python3.11/site-packages
COPY --from=python-base /usr/local/bin /usr/local/bin

# Copy built frontend from frontend-builder stage (standalone mode)
# The standalone output contains a self-contained server.js + minimal node_modules
# Static assets and public/ must be copied alongside standalone manually
COPY --from=frontend-builder /app/web/.next/standalone/ ./web/
COPY --from=frontend-builder /app/web/.next/static/ ./web/.next/static/
COPY --from=frontend-builder /app/web/public/ ./web/public/

# Copy application source code
COPY deeptutor/ ./deeptutor/
COPY deeptutor_cli/ ./deeptutor_cli/
COPY scripts/ ./scripts/
COPY pyproject.toml ./
COPY requirements/ ./requirements/
COPY requirements.txt ./

# Create necessary directories (these will be overwritten by volume mounts)
RUN mkdir -p \
    data/user/settings \
    data/memory \
    data/user/workspace/memory \
    data/user/workspace/notebook \
    data/user/workspace/co-writer/audio \
    data/user/workspace/co-writer/tool_calls \
    data/user/workspace/chat/chat \
    data/user/workspace/chat/deep_solve \
    data/user/workspace/chat/deep_question \
    data/user/workspace/chat/deep_research/reports \
    data/user/workspace/chat/math_animator \
    data/user/workspace/chat/_detached_code_execution \
    data/user/logs \
    data/knowledge_bases

# Bake a non-root user (UID 1000) for the supervisord programs. supervisord
# itself runs as PID 1's UID — root under rootful Docker/Podman, or UID 1000
# under rootless podman + `userns_mode: keep-id` (where PID 1 is the host
# user). Each child (backend/frontend) is dropped to this `deeptutor` user via
# the per-program `user=deeptutor` directive, so the app processes stay
# non-root in either runtime. UID 1000 also matches the host user under
# keep-id with a bind mount on ./data.
RUN groupadd --system --gid 1000 deeptutor \
    && useradd --system --uid 1000 --gid 1000 --no-create-home --shell /usr/sbin/nologin deeptutor \
    && chown -R deeptutor:deeptutor /app/data /app/web/.next

# supervisord config is split into two files so the production and development
# images share one daemon-level [supervisord] section instead of duplicating it:
#   - /etc/supervisor/supervisord.conf      — daemon-level settings (shared)
#   - /etc/supervisor/conf.d/programs.conf  — the backend/frontend programs
# Production defines the programs here; the development stage overrides only
# programs.conf, leaving the shared daemon section untouched.
# Program output goes to the container's stdout/stderr so `docker logs` captures it.
RUN mkdir -p /etc/supervisor/conf.d

# Daemon-level config. No `user=` in [supervisord]: supervisord runs as PID 1's
# UID (root under rootful; UID 1000 under rootless podman + keep-id, which has
# no CAP_SETUID and would make a `user=` line fail at startup with
# "Can't drop privilege as nonroot user" — see supervisord options.py). The
# pidfile lives in /tmp, which is world-writable, so supervisord can create it
# whether it runs as root or UID 1000; /var/run is root-owned and not writable
# by UID 1000 under rootless keep-id.
RUN cat > /etc/supervisor/supervisord.conf <<'EOF'
[supervisord]
nodaemon=true
logfile=/dev/null
logfile_maxbytes=0
pidfile=/tmp/supervisord.pid

[include]
files = /etc/supervisor/conf.d/programs.conf
EOF

RUN sed -i 's/\r$//' /etc/supervisor/supervisord.conf

# Program definitions (production). Each child drops to the unprivileged
# deeptutor user (UID 1000) via per-program `user=deeptutor`; see the note on
# the user= design above the daemon config.
RUN cat > /etc/supervisor/conf.d/programs.conf <<'EOF'
[program:backend]
command=/bin/bash /app/start-backend.sh
directory=/app
user=deeptutor
autostart=true
autorestart=true
stdout_logfile=/dev/fd/1
stdout_logfile_maxbytes=0
stderr_logfile=/dev/fd/2
stderr_logfile_maxbytes=0
environment=PYTHONPATH="/app",PYTHONUNBUFFERED="1"

[program:frontend]
command=/bin/bash /app/start-frontend.sh
directory=/app/web
user=deeptutor
autostart=true
autorestart=true
startsecs=5
stdout_logfile=/dev/fd/1
stdout_logfile_maxbytes=0
stderr_logfile=/dev/fd/2
stderr_logfile_maxbytes=0
environment=NODE_ENV="production"
EOF

RUN sed -i 's/\r$//' /etc/supervisor/conf.d/programs.conf

# Create backend startup script
RUN cat > /app/start-backend.sh <<'EOF'
#!/bin/bash
set -e

BACKEND_PORT=${BACKEND_PORT:-8001}
BACKEND_HOST=${BACKEND_HOST:-0.0.0.0}

echo "[Backend]  🚀 Starting FastAPI backend on ${BACKEND_HOST}:${BACKEND_PORT}..."

# Run uvicorn directly - the application's logging system already handles:
# 1. Console output (visible in docker logs)
# 2. File logging to data/user/logs/ai_tutor_*.log
#
# BACKEND_HOST defaults to 0.0.0.0 (LAN-reachable, matches bridge-mode
# port publishing). Set BACKEND_HOST=127.0.0.1 when running with
# network_mode: host to keep the backend on loopback only.
exec python -m uvicorn deeptutor.api.main:app --host ${BACKEND_HOST} --port ${BACKEND_PORT} --no-access-log
EOF

RUN sed -i 's/\r$//' /app/start-backend.sh && chmod +x /app/start-backend.sh

# Create frontend startup script
# This script starts the Next.js standalone server. URL knowledge is no
# longer baked into the bundle: web/proxy.ts rewrites /api/* and /ws/* to
# the configured backend at request time, reading DEEPTUTOR_API_BASE_URL
# (exported by the entrypoint from data/user/settings/system.json).
RUN cat > /app/start-frontend.sh <<'EOF'
#!/bin/bash
set -e

FRONTEND_PORT=${FRONTEND_PORT:-3782}
FRONTEND_HOST=${FRONTEND_HOST:-0.0.0.0}
echo "[Frontend] 🚀 Starting Next.js frontend on ${FRONTEND_HOST}:${FRONTEND_PORT}..."

export PORT=${FRONTEND_PORT}
export HOSTNAME=${FRONTEND_HOST}
exec node /app/web/server.js
EOF

RUN sed -i 's/\r$//' /app/start-frontend.sh && chmod +x /app/start-frontend.sh

# Create entrypoint script
RUN cat > /app/entrypoint.sh <<'EOF'
#!/bin/bash
set -e

echo "============================================"
echo "🚀 Starting DeepTutor"
echo "============================================"

export DEEPTUTOR_IGNORE_PROCESS_ENV_OVERRIDES=1

# Docker is JSON-driven. Ignore runtime env names even if the host or a stale
# Compose environment provides them; the entrypoint re-exports values from
# data/user/settings/*.json below.
for key in \
    BACKEND_PORT \
    FRONTEND_PORT \
    NEXT_PUBLIC_API_BASE_EXTERNAL \
    NEXT_PUBLIC_API_BASE \
    CORS_ORIGIN \
    CORS_ORIGINS \
    DISABLE_SSL_VERIFY \
    CHAT_ATTACHMENT_DIR \
    AUTH_ENABLED \
    NEXT_PUBLIC_AUTH_ENABLED \
    AUTH_USERNAME \
    AUTH_PASSWORD_HASH \
    AUTH_TOKEN_EXPIRE_HOURS \
    AUTH_COOKIE_SECURE \
    POCKETBASE_URL \
    POCKETBASE_PORT \
    POCKETBASE_EXTERNAL_URL \
    POCKETBASE_ADMIN_EMAIL \
    POCKETBASE_ADMIN_PASSWORD \
    DEEPTUTOR_API_BASE_URL \
    DEEPTUTOR_AUTH_ENABLED; do
    unset "$key"
done

# Initialize user data directories if empty
echo "📁 Checking data directories..."
echo "   Ensuring runtime settings and workspace layout..."
python -c "
from pathlib import Path
from deeptutor.services.setup import init_user_directories
init_user_directories(Path('/app'))
" 2>/dev/null || echo "   ⚠️ Directory initialization skipped (will be created on first use)"

# Idempotent: re-chown /app/data so the unprivileged `deeptutor` user (UID 1000)
# owns it. Cheap on no-op; the only first-start cost is one stat per file.
chown -R deeptutor:deeptutor /app/data 2>/dev/null || true

echo "⚙️  Loading runtime JSON settings..."
eval "$(python - <<'PY'
import shlex
from deeptutor.services.config import export_runtime_settings_to_env

for key, value in export_runtime_settings_to_env(overwrite=True).items():
    print(f"export {key}={shlex.quote(str(value))}")
PY
)"

export BACKEND_PORT=${BACKEND_PORT:-8001}
export FRONTEND_PORT=${FRONTEND_PORT:-3782}

# DEEPTUTOR_API_BASE_URL and DEEPTUTOR_AUTH_ENABLED are exported by the
# export_runtime_settings_to_env eval above (see render_environment in
# deeptutor/services/config/runtime_settings.py). web/proxy.ts reads them at
# request time to rewrite /api/* and /ws/* to the backend and to gate the login
# redirect. Keeping them in the single JSON-backed exporter means the Docker and
# `deeptutor start` paths stay in sync.
echo "📌 API Base URL (proxy): ${DEEPTUTOR_API_BASE_URL:-http://localhost:${BACKEND_PORT}}"
echo "📌 Auth enabled: ${DEEPTUTOR_AUTH_ENABLED:-false}"

echo "📌 Backend Port: ${BACKEND_PORT}"
echo "📌 Frontend Port: ${FRONTEND_PORT}"

echo "============================================"
echo "📦 Configuration loaded from:"
echo "   - data/user/settings/system.json"
echo "   - data/user/settings/auth.json"
echo "   - data/user/settings/integrations.json"
echo "   - data/user/settings/model_catalog.json"
echo "   - data/user/settings/main.yaml"
echo "   - data/user/settings/agents.yaml"
echo "============================================"

# Hand off to supervisord as PID 1. The daemon-level config deliberately omits
# `user=` so supervisord inherits PID 1's UID and stays portable across rootful
# and rootless-keep-id runtimes; children drop to the deeptutor user via
# per-program `user=`. Full rationale lives next to the [supervisord] section
# in the build step that writes /etc/supervisor/supervisord.conf.
exec /usr/bin/supervisord -c /etc/supervisor/supervisord.conf
EOF

RUN sed -i 's/\r$//' /app/entrypoint.sh && chmod +x /app/entrypoint.sh

RUN cat > /app/healthcheck.py <<'EOF'
from pathlib import Path
import json
import urllib.request

port = 8001
settings_path = Path("/app/data/user/settings/system.json")
try:
    settings = json.loads(settings_path.read_text(encoding="utf-8"))
    port = int(settings.get("backend_port") or port)
except Exception:
    pass

urllib.request.urlopen(f"http://localhost:{port}/", timeout=5).close()
EOF

# Expose ports
EXPOSE 8001 3782

# Health check. Read the port from JSON so standalone `docker run` does not
# depend on a Dockerfile-level BACKEND_PORT default.
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD python /app/healthcheck.py

# Set entrypoint
ENTRYPOINT ["/app/entrypoint.sh"]

# ============================================
# Stage 4: Development Image (Optional)
# ============================================
FROM production AS development

# Re-add full node_modules for development hot-reload
# (Production uses standalone output which doesn't include full node_modules)
COPY --from=frontend-builder /app/web/node_modules ./web/node_modules
COPY --from=frontend-builder /app/web/package.json ./web/package.json
COPY --from=frontend-builder /app/web/next.config.js ./web/next.config.js

# `next dev` runs as the unprivileged deeptutor user (via `user=deeptutor` in
# the supervisord config) and must create/write its build cache under
# /app/web/.next, so give that user ownership of the web dir and the cache.
RUN mkdir -p /app/web/.next \
    && chown deeptutor:deeptutor /app/web /app/web/.next

# Install development tools
RUN apt-get update && apt-get install -y --no-install-recommends \
    vim \
    git \
    && rm -rf /var/lib/apt/lists/*

# Install development Python packages
RUN pip install --no-cache-dir \
    pre-commit \
    black \
    ruff

# Development overrides only the program definitions (uvicorn --reload and
# `next dev`); the shared daemon-level /etc/supervisor/supervisord.conf from
# the production stage is reused as-is.
RUN cat > /etc/supervisor/conf.d/programs.conf <<'EOF'
[program:backend]
command=python -m uvicorn deeptutor.api.main:app --host 0.0.0.0 --port %(ENV_BACKEND_PORT)s --reload --no-access-log
directory=/app
user=deeptutor
autostart=true
autorestart=true
stdout_logfile=/dev/fd/1
stdout_logfile_maxbytes=0
stderr_logfile=/dev/fd/2
stderr_logfile_maxbytes=0
environment=PYTHONPATH="/app",PYTHONUNBUFFERED="1"

[program:frontend]
command=/bin/bash -c "cd /app/web && node node_modules/next/dist/bin/next dev -H 0.0.0.0 -p ${FRONTEND_PORT:-3782}"
directory=/app/web
user=deeptutor
autostart=true
autorestart=true
startsecs=5
stdout_logfile=/dev/fd/1
stdout_logfile_maxbytes=0
stderr_logfile=/dev/fd/2
stderr_logfile_maxbytes=0
environment=NODE_ENV="development"
EOF

RUN sed -i 's/\r$//' /etc/supervisor/conf.d/programs.conf

# Development ports
EXPOSE 8001 3782
