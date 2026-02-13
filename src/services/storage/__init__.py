from .db import init_db
from .object_store import ensure_bucket, get_bucket_name


def init_storage():
    init_db()
    bucket = get_bucket_name()
    if bucket:
        ensure_bucket(bucket)


__all__ = ["init_storage"]
