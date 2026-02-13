from contextlib import asynccontextmanager
from pathlib import Path
import time

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from src.api.routers import (
    agent_config,
    chat,
    co_writer,
    dashboard,
    embedding_provider,
    guide,
    ideagen,
    knowledge,
    llm_provider,
    notebook,
    question,
    research,
    settings,
    solve,
    system,
)
from src.logging import get_logger

logger = get_logger("API")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Application lifecycle management
    Gracefully handle startup and shutdown events, avoid CancelledError
    """
    # Execute on startup
    logger.info("Application startup")
    
    # Ensure "User Notes" Knowledge Base exists
    try:
        from src.knowledge.manager import KnowledgeBaseManager
        kb_manager = KnowledgeBaseManager()
        kb_manager.create_knowledge_base(
            "User Notes", 
            description="Auto-generated knowledge base for user notes", 
            set_default=False
        )
        logger.info("Ensured 'User Notes' knowledge base exists")
    except Exception as e:
        logger.error(f"Failed to initialize 'User Notes' knowledge base: {e}")

    try:
        from src.services.storage import init_storage
        init_storage()
        logger.info("Storage initialized")
    except Exception as e:
        logger.warning(f"Storage initialization skipped/failed: {e}")
        
    yield
    # Execute on shutdown
    logger.info("Application shutdown")


app = FastAPI(title="DeepTutor API", version="1.0.0", lifespan=lifespan)

# Configure CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # In production, replace with specific frontend origin
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def log_requests(request: Request, call_next):
    start_time = time.time()
    response = await call_next(request)
    process_time = time.time() - start_time
    logger.debug(f"Request: {request.method} {request.url.path} - Processed in {process_time:.4f}s")
    return response

# Mount user directory as static root for generated artifacts
# This allows frontend to access generated artifacts (images, PDFs, etc.)
# URL: /api/outputs/solve/solve_xxx/artifacts/image.png
# Physical Path: DeepTutor/data/user/solve/solve_xxx/artifacts/image.png
project_root = Path(__file__).parent.parent.parent
user_dir = project_root / "data" / "user"

# Initialize user directories on startup
try:
    from src.services.setup import init_user_directories

    init_user_directories(project_root)
except Exception:
    # Fallback: just create the main directory if it doesn't exist
    if not user_dir.exists():
        user_dir.mkdir(parents=True)

app.mount("/api/outputs", StaticFiles(directory=str(user_dir)), name="outputs")

# Include routers
app.include_router(solve.router, prefix="/api/v1", tags=["solve"])
app.include_router(chat.router, prefix="/api/v1", tags=["chat"])
app.include_router(question.router, prefix="/api/v1/question", tags=["question"])
app.include_router(research.router, prefix="/api/v1/research", tags=["research"])
app.include_router(knowledge.router, prefix="/api/v1/knowledge", tags=["knowledge"])
app.include_router(dashboard.router, prefix="/api/v1/dashboard", tags=["dashboard"])
app.include_router(co_writer.router, prefix="/api/v1/co_writer", tags=["co_writer"])
app.include_router(notebook.router, prefix="/api/v1/notebook", tags=["notebook"])
app.include_router(guide.router, prefix="/api/v1/guide", tags=["guide"])
app.include_router(ideagen.router, prefix="/api/v1/ideagen", tags=["ideagen"])
app.include_router(settings.router, prefix="/api/v1/settings", tags=["settings"])
app.include_router(system.router, prefix="/api/v1/system", tags=["system"])
app.include_router(llm_provider.router, prefix="/api/v1/config/llm", tags=["config"])
app.include_router(embedding_provider.router, prefix="/api/v1/config/embedding", tags=["config"])
app.include_router(agent_config.router, prefix="/api/v1/config", tags=["config"])


@app.get("/")
async def root():
    return {"message": "Welcome to DeepTutor API"}


if __name__ == "__main__":
    from pathlib import Path

    import uvicorn

    # Get project root directory
    project_root = Path(__file__).parent.parent.parent

    # Ensure project root is in Python path
    import sys

    if str(project_root) not in sys.path:
        sys.path.insert(0, str(project_root))

    # Get port from configuration
    from src.services.setup import get_backend_port

    backend_port = get_backend_port(project_root)

    # Configure reload_excludes with absolute paths to properly exclude directories
    reload_excludes = [
        str(project_root / d)
        for d in [
            "venv",
            ".venv",
            "data",
            "web/node_modules",
            "web/.next",
            ".git",
            "cache",
            "reports",
        ]
    ]

    logger.info(f"Starting backend on port {backend_port} (reload=True)")
    logger.debug(f"Reload excludes: {reload_excludes}")

    uvicorn.run(
        "api.main:app",
        host="0.0.0.0",
        port=backend_port,
        reload=True,
        reload_excludes=reload_excludes,
    )
