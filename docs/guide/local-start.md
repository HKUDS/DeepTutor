# Local Installation

This guide covers manual installation for development or non-Docker environments.

## Prerequisites

- **Python 3.10+** — [Download](https://www.python.org/downloads/)
- **Node.js 18+** — [Download](https://nodejs.org/)
- **Git** — [Download](https://git-scm.com/)

::: tip Windows Users
If you encounter path length errors during installation, enable long path support:

```cmd
reg add "HKLM\SYSTEM\CurrentControlSet\Control\FileSystem" /v LongPathsEnabled /t REG_DWORD /d 1 /f
```

Restart your terminal after running this command.
:::

## Step 1: Set Up Virtual Environment

Choose one of the following options:

::: code-group

```bash [Conda (Recommended)]
# Create environment
conda create -n deeptutor python=3.10

# Activate environment
conda activate deeptutor
```

```bash [venv]
# Create environment
python -m venv venv

# Activate (Windows)
venv\Scripts\activate

# Activate (macOS/Linux)
source venv/bin/activate
```

:::

## Step 2: Install Dependencies

### Option A: Automated Installation (Recommended)

```bash
# Using Python script
python scripts/install_all.py

# Or using shell script (macOS/Linux)
bash scripts/install_all.sh
```

### Option B: Manual Installation

```bash
# Install Python dependencies
pip install -r requirements.txt

# Install Node.js dependencies
npm install --prefix web
```

::: warning Common Issues
If you see `npm: command not found`:

```bash
# Using Conda
conda install -c conda-forge nodejs

# Or install from https://nodejs.org/
```
:::

## Step 3: Configure Environment

Make sure you have completed the [Pre-Configuration](/guide/pre-config) steps:

1. ✅ Created `.env` file with your API keys
2. ✅ (Optional) Customized `config/agents.yaml`
3. ✅ (Optional) Downloaded demo knowledge bases

## Step 4: Launch Application

### Start Web Interface (Recommended)

```bash
python scripts/start_web.py
```

This starts both the **frontend** (Next.js) and **backend** (FastAPI) servers.

### Alternative: CLI Interface Only

```bash
python scripts/start.py
```

### Access URLs

| Service | URL | Description |
|:---:|:---|:---|
| **Frontend** | http://localhost:3782 | Main web interface |
| **API Docs** | http://localhost:8001/docs | Interactive API documentation |

## Advanced: Start Services Separately

For development, you may want to run frontend and backend separately:

### Backend (FastAPI)

```bash
python src/api/run_server.py

# Or with uvicorn directly
uvicorn src.api.main:app --host 0.0.0.0 --port 8001 --reload
```

### Frontend (Next.js)

First, create `web/.env.local`:

```bash
NEXT_PUBLIC_API_BASE=http://localhost:8001
```

Then start the development server:

```bash
cd web
npm install
npm run dev -- -p 3782
```

## Stopping the Service

Press `Ctrl+C` in the terminal to stop the service.

::: warning Port Still in Use?
If you see "port already in use" after pressing Ctrl+C:

**macOS/Linux:**
```bash
lsof -i :8001
kill -9 <PID>
```

**Windows:**
```bash
netstat -ano | findstr :8001
taskkill /PID <PID> /F
```
:::

## Troubleshooting

### Backend fails to start

**Checklist:**
- Confirm Python version >= 3.10: `python --version`
- Confirm all dependencies installed: `pip install -r requirements.txt`
- Check if port 8001 is in use
- Verify `.env` file configuration

### Frontend cannot connect to backend

**Solutions:**
1. Confirm backend is running: visit http://localhost:8001/docs
2. Check browser console for error messages
3. Create `web/.env.local` with:
   ```bash
   NEXT_PUBLIC_API_BASE=http://localhost:8001
   ```

### WebSocket connection fails

**Checklist:**
- Confirm backend is running
- Check firewall settings
- Verify WebSocket URL format: `ws://localhost:8001/api/v1/...`

---

**Next Step:** [Docker Deployment →](/guide/docker-start)
