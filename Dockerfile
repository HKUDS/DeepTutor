# ============================================
# DeepTutor Multi-Stage Dockerfile
# ============================================
# This Dockerfile builds a production-ready image for DeepTutor
# containing both the FastAPI backend and Next.js frontend
#
# Build: docker compose build
# Run:   docker compose up -d
#
# Prerequisites:
#   1. Copy .env.example to .env and configure your API keys
#   2. Runtime settings are created under data/user/settings on first start
# ============================================

# ============================================
# Stage 1: Frontend Builder
# ============================================
FROM node:22-slim AS frontend-builder

WORKDIR /app/web

# Accept build argument for backend port
ARG BACKEND_PORT=8001

# Copy package files first for better caching
COPY web/package.json web/package-lock.json* ./

# Install dependencies
RUN npm ci --legacy-peer-deps

# Copy frontend source code
COPY web/ ./

# Create .env.local with placeholder that will be replaced at runtime
# Use a unique placeholder that can be safely replaced
RUN echo "NEXT_PUBLIC_API_BASE=__NEXT_PUBLIC_API_BASE_PLACEHOLDER__" > .env.local

# Build Next.js for production with standalone output
# This allows runtime environment variable injection
RUN npm run build

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
      description="DeepTutor: AI-Powered Personalized Learning Assistant" \
      version="1.0.0"

# Set environment variables
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PYTHONIOENCODING=utf-8 \
    NODE_ENV=production \
    # Default ports (can be overridden)
    BACKEND_PORT=8001 \
    FRONTEND_PORT=3782

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

# Copy Node.js from frontend-builder stage (avoids re-downloading from NodeSource)
COPY --from=frontend-builder /usr/local/bin/node /usr/local/bin/node
COPY --from=frontend-builder /usr/local/lib/node_modules /usr/local/lib/node_modules
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
    data/user/workspace/guide \
    data/user/workspace/chat/chat \
    data/user/workspace/chat/deep_solve \
    data/user/workspace/chat/deep_question \
    data/user/workspace/chat/deep_research/reports \
    data/user/workspace/chat/math_animator \
    data/user/workspace/chat/_detached_code_execution \
    data/user/logs \
    data/knowledge_bases

# Create supervisord configuration for running both services
# Log output goes to stdout/stderr so docker logs can capture them
RUN mkdir -p /etc/supervisor/conf.d

RUN cat > /etc/supervisor/conf.d/deeptutor.conf <<'EOF'
[supervisord]
nodaemon=true
logfile=/dev/null
logfile_maxbytes=0
pidfile=/var/run/supervisord.pid

[program:backend]
command=/bin/bash /app/start-backend.sh
directory=/app
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
autostart=true
autorestart=true
startsecs=5
stdout_logfile=/dev/fd/1
stdout_logfile_maxbytes=0
stderr_logfile=/dev/fd/2
stderr_logfile_maxbytes=0
environment=NODE_ENV="production"
EOF

RUN sed -i 's/\r$//' /etc/supervisor/conf.d/deeptutor.conf

# Create backend startup script
RUN cat > /app/start-backend.sh <<'EOF'
#!/bin/bash
set -e

BACKEND_PORT=${BACKEND_PORT:-8001}

echo "[Backend]  🚀 Starting FastAPI backend on port ${BACKEND_PORT}..."

# Run uvicorn directly - the application's logging system already handles:
# 1. Console output (visible in docker logs)
# 2. File logging to data/user/logs/ai_tutor_*.log
exec python -m uvicorn deeptutor.api.main:app --host 0.0.0.0 --port ${BACKEND_PORT}
EOF

RUN sed -i 's/\r$//' /app/start-backend.sh && chmod +x /app/start-backend.sh

# Create frontend startup script
# This script handles runtime environment variable injection for Next.js
RUN cat > /app/start-frontend.sh <<'EOF'
#!/bin/bash
set -e

# Get the backend port (default to 8001)
BACKEND_PORT=${BACKEND_PORT:-8001}
FRONTEND_PORT=${FRONTEND_PORT:-3782}

# Determine the API base URL with multiple fallback options
# Priority: NEXT_PUBLIC_API_BASE_EXTERNAL > NEXT_PUBLIC_API_BASE > auto-detect
if [ -n "$NEXT_PUBLIC_API_BASE_EXTERNAL" ]; then
    # Explicit external URL for cloud deployments
    API_BASE="$NEXT_PUBLIC_API_BASE_EXTERNAL"
    echo "[Frontend] 📌 Using external API URL: ${API_BASE}"
elif [ -n "$NEXT_PUBLIC_API_BASE" ]; then
    # Custom API base URL
    API_BASE="$NEXT_PUBLIC_API_BASE"
    echo "[Frontend] 📌 Using custom API URL: ${API_BASE}"
else
    # Default: localhost with configured backend port
    # Note: This only works for local development, not cloud deployments
    API_BASE="http://localhost:${BACKEND_PORT}"
    echo "[Frontend] 📌 Using default API URL: ${API_BASE}"
    echo "[Frontend] ⚠️  For cloud deployment, set NEXT_PUBLIC_API_BASE_EXTERNAL to your server's public URL"
    echo "[Frontend]    Example: -e NEXT_PUBLIC_API_BASE_EXTERNAL=https://your-server.com:${BACKEND_PORT}"
fi

echo "[Frontend] 🚀 Starting Next.js frontend on port ${FRONTEND_PORT}..."

# Replace placeholder in built Next.js files
# This is necessary because NEXT_PUBLIC_* vars are inlined at build time
find /app/web/.next -type f \( -name "*.js" -o -name "*.json" \) -exec \
    sed -i "s|__NEXT_PUBLIC_API_BASE_PLACEHOLDER__|${API_BASE}|g" {} \; 2>/dev/null || true

# Start Next.js standalone server
# The standalone server reads PORT and HOSTNAME from environment variables
export PORT=${FRONTEND_PORT}
export HOSTNAME=0.0.0.0
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

# Set default ports if not provided
export BACKEND_PORT=${BACKEND_PORT:-8001}
export FRONTEND_PORT=${FRONTEND_PORT:-3782}

echo "📌 Backend Port: ${BACKEND_PORT}"
echo "📌 Frontend Port: ${FRONTEND_PORT}"

# Check for required environment variables
if [ -z "$LLM_API_KEY" ]; then
    echo "⚠️  Warning: LLM_API_KEY not set"
    echo "   Please provide LLM configuration via environment variables or .env file"
fi

if [ -z "$LLM_MODEL" ]; then
    echo "⚠️  Warning: LLM_MODEL not set"
    echo "   Please configure LLM_MODEL in your .env file"
fi

# Initialize user data directories if empty
echo "📁 Checking data directories..."
echo "   Ensuring runtime settings and workspace layout..."
python -c "
from pathlib import Path
from deeptutor.services.setup import init_user_directories
init_user_directories(Path('/app'))
" 2>/dev/null || echo "   ⚠️ Directory initialization skipped (will be created on first use)"

echo "============================================"
echo "📦 Configuration loaded from:"
echo "   - Environment variables (.env file)"
echo "   - data/user/settings/main.yaml"
echo "   - data/user/settings/agents.yaml"
echo "============================================"

# Start supervisord
exec /usr/bin/supervisord -c /etc/supervisor/conf.d/deeptutor.conf
EOF

RUN sed -i 's/\r$//' /app/entrypoint.sh && chmod +x /app/entrypoint.sh

# Expose ports
EXPOSE 8001 3782

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD curl -f http://localhost:${BACKEND_PORT:-8001}/ || exit 1

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

# Override supervisord config for development (with reload)
# Log output goes to stdout/stderr so docker logs can capture them
RUN cat > /etc/supervisor/conf.d/deeptutor.conf <<'EOF'
[supervisord]
nodaemon=true
logfile=/dev/null
logfile_maxbytes=0
pidfile=/var/run/supervisord.pid

[program:backend]
command=python -m uvicorn deeptutor.api.main:app --host 0.0.0.0 --port %(ENV_BACKEND_PORT)s --reload
directory=/app
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
autostart=true
autorestart=true
startsecs=5
stdout_logfile=/dev/fd/1
stdout_logfile_maxbytes=0
stderr_logfile=/dev/fd/2
stderr_logfile_maxbytes=0
environment=NODE_ENV="development"
EOF

RUN sed -i 's/\r$//' /etc/supervisor/conf.d/deeptutor.conf

# Development ports
EXPOSE 8001 3782
