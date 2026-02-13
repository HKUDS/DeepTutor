import io
import os

from minio import Minio

_client = None


def get_bucket_name() -> str | None:
    return os.getenv("MINIO_BUCKET")


def get_minio_client() -> Minio | None:
    global _client
    if _client is not None:
        return _client
    endpoint = os.getenv("MINIO_ENDPOINT")
    access_key = os.getenv("MINIO_ACCESS_KEY")
    secret_key = os.getenv("MINIO_SECRET_KEY")
    if not endpoint or not access_key or not secret_key:
        return None
    secure_raw = os.getenv("MINIO_SECURE", "false").lower()
    secure = secure_raw in {"1", "true", "yes"}
    _client = Minio(endpoint, access_key=access_key, secret_key=secret_key, secure=secure)
    return _client


def ensure_bucket(bucket: str) -> None:
    client = get_minio_client()
    if client is None:
        raise ValueError("MinIO configuration missing")
    if not client.bucket_exists(bucket):
        client.make_bucket(bucket)


def upload_file(bucket: str, object_key: str, file_path: str, content_type: str) -> None:
    client = get_minio_client()
    if client is None:
        raise ValueError("MinIO configuration missing")
    client.fput_object(bucket, object_key, file_path, content_type=content_type)


def upload_bytes(
    bucket: str, object_key: str, data: bytes, content_type: str
) -> None:
    client = get_minio_client()
    if client is None:
        raise ValueError("MinIO configuration missing")
    client.put_object(
        bucket,
        object_key,
        data=io.BytesIO(data),
        length=len(data),
        content_type=content_type,
    )


def get_object_stream(bucket: str, object_key: str):
    client = get_minio_client()
    if client is None:
        raise ValueError("MinIO configuration missing")
    return client.get_object(bucket, object_key)
