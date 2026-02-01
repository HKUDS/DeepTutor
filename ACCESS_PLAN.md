# DeepTutor Application Access Plan

This document provides a comprehensive step-by-step guide to access and run the DeepTutor application.

## Table of Contents
1. [Prerequisites](#prerequisites)
2. [Installation Methods](#installation-methods)
3. [Configuration](#configuration)
4. [Launching the Application](#launching-the-application)
5. [Accessing the Application](#accessing-the-application)
6. [Troubleshooting](#troubleshooting)

---

## Prerequisites

### Required Software

#### Option A: Docker (Recommended for Easy Setup)
- **Docker** (version 20.10+)
- **Docker Compose** (version 2.0+)
- **No Python/Node.js required** when using Docker

**Install Docker:**
- macOS: Download from [Docker Desktop](https://docs.docker.com/get-docker/)
- Linux: Follow [Docker installation guide](https://docs.docker.com/engine/install/)
- Windows: Download from [Docker Desktop](https://docs.docker.com/get-docker/)

#### Option B: Manual Installation
- **Python** 3.10 or higher
- **Node.js** 18 or higher
- **npm** (comes with Node.js)

**Verify installations:**
```bash
python --version  # Should show 3.10.x or higher
node --version    # Should show v18.x.x or higher
npm --version     # Should show version number
```

### API Keys Required

You'll need API keys for:
1. **LLM (Large Language Model)** - Choose one:
   - OpenAI (GPT-4, GPT-3.5)
   - Azure OpenAI
   - Anthropic Claude
   - Other compatible providers

2. **Embedding Model** - For knowledge base:
   - OpenAI embeddings
   - Azure OpenAI embeddings
   - Other compatible providers

3. **Search Provider** (Optional but recommended):
   - Perplexity (default)
   - Tavily
   - Serper
   - Jina
   - Exa
   - Baidu

---

## Installation Methods

### Method 1: Docker Deployment (Easiest)

#### Step 1: Navigate to Project Directory
```bash
cd /Users/anup.singh/Documents/Deeptutor/DeepTutor
```

#### Step 2: Configure Environment Variables
```bash
# Copy the example environment file
cp .env.example .env

# Edit .env file with your API keys
# Use your preferred text editor (nano, vim, VS Code, etc.)
nano .env
# or
code .env
```

#### Step 3: Start with Docker Compose
```bash
# Build and start (first time takes ~11 minutes)
docker compose up

# Or use pre-built image (faster)
docker run -d --name deeptutor \
  -p 8001:8001 -p 3782:3782 \
  --env-file .env \
  -v $(pwd)/data:/app/data \
  -v $(pwd)/config:/app/config:ro \
  ghcr.io/hkuds/deeptutor:latest
```

#### Step 4: Access the Application
- **Frontend**: http://localhost:3782
- **Backend API Docs**: http://localhost:8001/docs

**Common Docker Commands:**
```bash
docker compose up -d      # Start in background
docker compose down         # Stop services
docker compose logs -f     # View logs
docker compose up --build   # Rebuild after changes
```

---

### Method 2: Manual Installation

#### Step 1: Navigate to Project Directory
```bash
cd /Users/anup.singh/Documents/Deeptutor/DeepTutor
```

#### Step 2: Set Up Python Environment

**Option A: Using Conda (Recommended)**
```bash
conda create -n deeptutor python=3.10
conda activate deeptutor
```

**Option B: Using venv**
```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

#### Step 3: Install Dependencies

**One-Click Installation (Recommended):**
```bash
python scripts/install_all.py
```

**Or Manual Installation:**
```bash
# Install backend dependencies
pip install -r requirements.txt

# Install frontend dependencies
cd web
npm install
cd ..
```

#### Step 4: Configure Environment Variables
```bash
# Copy the example environment file
cp .env.example .env

# Edit .env file with your API keys
nano .env
# or
code .env
```

#### Step 5: Launch the Application
```bash
# Start both frontend and backend
python scripts/start_web.py

# Or start separately:
# Backend only:
python src/api/run_server.py
# Frontend only (in another terminal):
cd web && npm run dev -- -p 3782
```

---

## Configuration

### Environment Variables (.env file)

Create a `.env` file in the project root with the following variables:

#### Required Variables

```bash
# LLM Configuration
LLM_MODEL=gpt-4o                    # Model name (e.g., gpt-4o, gpt-3.5-turbo)
LLM_API_KEY=your-api-key-here       # Your LLM API key
LLM_HOST=https://api.openai.com/v1  # API endpoint URL

# Embedding Configuration
EMBEDDING_MODEL=text-embedding-3-large  # Embedding model name
EMBEDDING_API_KEY=your-api-key-here     # Embedding API key
EMBEDDING_HOST=https://api.openai.com/v1 # Embedding API endpoint
```

#### Optional Variables

```bash
# Port Configuration (defaults shown)
BACKEND_PORT=8001                   # Backend API port
FRONTEND_PORT=3782                 # Frontend web port

# Frontend API URL (for remote access)
NEXT_PUBLIC_API_BASE=http://localhost:8001
# For remote/LAN access, use your server IP:
# NEXT_PUBLIC_API_BASE=http://192.168.1.100:8001

# Search Provider (optional)
SEARCH_PROVIDER=perplexity         # Options: perplexity, tavily, serper, jina, exa, baidu
SEARCH_API_KEY=your-search-api-key

# Text-to-Speech (optional)
TTS_API_KEY=your-tts-api-key
```

### Azure OpenAI Configuration

If using Azure OpenAI, add:
```bash
LLM_API_VERSION=2024-02-15-preview
EMBEDDING_API_VERSION=2024-02-15-preview
```

### Remote Access Configuration

If accessing from another device on your network:

1. Find your computer's IP address:
   ```bash
   # macOS/Linux
   ifconfig | grep "inet " | grep -v 127.0.0.1
   
   # Windows
   ipconfig
   ```

2. Update `.env` file:
   ```bash
   NEXT_PUBLIC_API_BASE=http://YOUR_IP_ADDRESS:8001
   ```

3. Ensure firewall allows connections on ports 8001 and 3782

---

## Launching the Application

### Quick Start (Recommended)

```bash
# Navigate to project directory
cd /Users/anup.singh/Documents/Deeptutor/DeepTutor

# Ensure .env file is configured
# Then start:
python scripts/start_web.py
```

### What Happens When You Start

1. **Backend starts** (FastAPI server on port 8001)
2. **Frontend starts** (Next.js server on port 3782)
3. **Services are ready** when you see:
   ```
   ✅ Services are running!
   - Backend:  http://localhost:8001/docs
   - Frontend: http://localhost:3782
   ```

### Starting Services Separately

**Backend Only:**
```bash
python src/api/run_server.py
# Or:
uvicorn src.api.main:app --host 0.0.0.0 --port 8001 --reload
```

**Frontend Only:**
```bash
cd web
npm run dev -- -p 3782
```

**Note:** If starting frontend separately, create `web/.env.local`:
```bash
NEXT_PUBLIC_API_BASE=http://localhost:8001
```

---

## Accessing the Application

### Web Interface

1. **Open your browser** and navigate to:
   ```
   http://localhost:3782
   ```

2. **Main Features Available:**
   - 📚 **Knowledge Base Management** - Upload and manage documents
   - 🧠 **Smart Solver** - AI-powered problem solving
   - 📝 **Question Generator** - Generate practice questions
   - 🔬 **Deep Research** - Comprehensive research reports
   - 💡 **Idea Generation** - Research idea generation
   - 🎓 **Guided Learning** - Interactive learning paths
   - 📓 **Notebook** - Personal learning records

### API Documentation

Access interactive API documentation at:
```
http://localhost:8001/docs
```

This provides:
- Complete API endpoint documentation
- Interactive API testing interface
- Request/response schemas

### First Steps After Launch

1. **Create a Knowledge Base:**
   - Go to http://localhost:3782/knowledge
   - Click "New Knowledge Base"
   - Upload PDF/TXT/MD documents
   - Wait for processing to complete

2. **Try Problem Solving:**
   - Go to http://localhost:3782/solver
   - Select a knowledge base
   - Enter a question
   - Click "Solve"

3. **Explore Other Modules:**
   - Question Generator: http://localhost:3782/question
   - Deep Research: http://localhost:3782/research
   - Guided Learning: http://localhost:3782/guide

---

## Troubleshooting

### Backend Fails to Start

**Symptoms:**
- Port already in use error
- Import errors
- Configuration errors

**Solutions:**

1. **Check if port is in use:**
   ```bash
   # macOS/Linux
   lsof -i :8001
   kill -9 <PID>
   
   # Windows
   netstat -ano | findstr :8001
   taskkill /PID <PID> /F
   ```

2. **Verify Python version:**
   ```bash
   python --version  # Should be 3.10+
   ```

3. **Reinstall dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

4. **Check .env file:**
   - Ensure all required variables are set
   - Verify API keys are correct

### Frontend Cannot Connect to Backend

**Symptoms:**
- "Failed to fetch" errors
- Connection refused errors

**Solutions:**

1. **Verify backend is running:**
   ```bash
   curl http://localhost:8001/docs
   # Should return HTML
   ```

2. **Create `web/.env.local`:**
   ```bash
   NEXT_PUBLIC_API_BASE=http://localhost:8001
   ```

3. **Check firewall settings**

4. **For remote access**, ensure:
   - `NEXT_PUBLIC_API_BASE` is set to your server IP
   - Firewall allows connections on port 8001

### npm: command not found

**Symptoms:**
- `npm: command not found` error
- Exit status 127

**Solutions:**

1. **Install Node.js:**
   ```bash
   # Using conda (recommended)
   conda install -c conda-forge nodejs
   
   # Using Homebrew (macOS)
   brew install node
   
   # Or download from https://nodejs.org/
   ```

2. **Verify installation:**
   ```bash
   node --version
   npm --version
   ```

### Docker Issues

**Problem: Frontend cannot connect in cloud deployment**

**Solution:**
Set `NEXT_PUBLIC_API_BASE_EXTERNAL` in `.env`:
```bash
NEXT_PUBLIC_API_BASE_EXTERNAL=https://your-server.com:8001
```

**Problem: Custom ports not working**

**Solution:**
Set both environment variables AND port mappings:
```bash
docker run -d --name deeptutor \
  -p 9001:9001 -p 4000:4000 \
  -e BACKEND_PORT=9001 \
  -e FRONTEND_PORT=4000 \
  -e NEXT_PUBLIC_API_BASE_EXTERNAL=http://localhost:9001 \
  --env-file .env \
  ghcr.io/hkuds/deeptutor:latest
```

### Knowledge Base Issues

**Problem: Numbered items extraction failed**

**Solution:**
```bash
# Use the shell script
./scripts/extract_numbered_items.sh <kb_name>

# Or direct Python command
python src/knowledge/extract_numbered_items.py --kb <kb_name> --base-dir ./data/knowledge_bases
```

### Windows-Specific Issues

**Problem: Long path names error**

**Solution:**
Enable long path support (run as Administrator):
```cmd
reg add "HKLM\SYSTEM\CurrentControlSet\Control\FileSystem" /v LongPathsEnabled /t REG_DWORD /d 1 /f
```
Restart terminal after running this command.

---

## Quick Reference

### Default Ports
- **Backend**: 8001
- **Frontend**: 3782

### Key URLs
- **Frontend**: http://localhost:3782
- **Backend API**: http://localhost:8001/docs
- **API Base**: http://localhost:8001

### Important Directories
- **Configuration**: `config/`
- **Data Storage**: `data/`
- **Knowledge Bases**: `data/knowledge_bases/`
- **User Data**: `data/user/`

### Common Commands

```bash
# Start application
python scripts/start_web.py

# Install dependencies
python scripts/install_all.py

# Start with Docker
docker compose up

# Stop Docker
docker compose down

# View logs (Docker)
docker compose logs -f

# Check backend health
curl http://localhost:8001/health
```

---

## Next Steps

1. ✅ **Complete installation** using one of the methods above
2. ✅ **Configure API keys** in `.env` file
3. ✅ **Launch the application** using `python scripts/start_web.py`
4. ✅ **Access the web interface** at http://localhost:3782
5. ✅ **Create your first knowledge base**
6. ✅ **Start using DeepTutor features**

---

## Additional Resources

- **Official Documentation**: https://hkuds.github.io/DeepTutor/
- **GitHub Repository**: https://github.com/HKUDS/DeepTutor
- **Issues & Support**: https://github.com/HKUDS/DeepTutor/issues
- **Discord Community**: https://discord.gg/eRsjPgMU4t

---

## Support

If you encounter issues:

1. Check the [FAQ section](https://github.com/HKUDS/DeepTutor#-faq) in the README
2. Search existing [GitHub Issues](https://github.com/HKUDS/DeepTutor/issues)
3. Create a new issue with:
   - Error messages
   - Steps to reproduce
   - System information (OS, Python version, etc.)
4. Join the [Discord community](https://discord.gg/eRsjPgMU4t) for help

---

**Last Updated**: Based on DeepTutor v0.6.0
