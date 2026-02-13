from datetime import datetime, timezone
import os

from sqlalchemy import Column, DateTime, JSON, MetaData, String, Table, create_engine

_engine = None
_metadata = MetaData()

co_writer_history = Table(
    "co_writer_history",
    _metadata,
    Column("id", String, primary_key=True),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("payload", JSON, nullable=False),
)

generated_files = Table(
    "generated_files",
    _metadata,
    Column("id", String, primary_key=True),
    Column("created_at", DateTime(timezone=True), nullable=False),
    Column("file_type", String, nullable=False),
    Column("filename", String, nullable=False),
    Column("bucket", String, nullable=False),
    Column("object_key", String, nullable=False),
    Column("content_type", String, nullable=False),
    Column("metadata", JSON, nullable=True),
)


def get_database_url() -> str:
    url = os.getenv("DATABASE_URL")
    if url:
        return url
    host = os.getenv("POSTGRES_HOST", "localhost")
    port = os.getenv("POSTGRES_PORT", "5432")
    user = os.getenv("POSTGRES_USER", "deeptutor")
    password = os.getenv("POSTGRES_PASSWORD", "deeptutor")
    dbname = os.getenv("POSTGRES_DB", "deeptutor")
    return f"postgresql+psycopg://{user}:{password}@{host}:{port}/{dbname}"


def get_engine():
    global _engine
    if _engine is None:
        _engine = create_engine(get_database_url(), pool_pre_ping=True)
    return _engine


def init_db():
    engine = get_engine()
    _metadata.create_all(engine)


def utc_now():
    return datetime.now(timezone.utc)
