from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from .db import generated_files, get_engine, utc_now


def save_file_record(
    file_id: str,
    file_type: str,
    filename: str,
    bucket: str,
    object_key: str,
    content_type: str,
    metadata: dict | None = None,
) -> None:
    stmt = pg_insert(generated_files).values(
        id=file_id,
        created_at=utc_now(),
        file_type=file_type,
        filename=filename,
        bucket=bucket,
        object_key=object_key,
        content_type=content_type,
        metadata=metadata,
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=[generated_files.c.id],
        set_={
            "file_type": file_type,
            "filename": filename,
            "bucket": bucket,
            "object_key": object_key,
            "content_type": content_type,
            "metadata": metadata,
        },
    )
    engine = get_engine()
    with engine.begin() as conn:
        conn.execute(stmt)


def get_file_record(file_id: str) -> dict | None:
    engine = get_engine()
    with engine.begin() as conn:
        row = conn.execute(
            select(
                generated_files.c.id,
                generated_files.c.file_type,
                generated_files.c.filename,
                generated_files.c.bucket,
                generated_files.c.object_key,
                generated_files.c.content_type,
                generated_files.c.metadata,
            ).where(generated_files.c.id == file_id)
        ).first()
    if not row:
        return None
    return {
        "id": row.id,
        "file_type": row.file_type,
        "filename": row.filename,
        "bucket": row.bucket,
        "object_key": row.object_key,
        "content_type": row.content_type,
        "metadata": row.metadata,
    }
