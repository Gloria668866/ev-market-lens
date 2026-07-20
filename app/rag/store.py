"""对象存储（MinIO）：上传/爬取的原始文件先落 MinIO，再异步解析。

为什么先存对象存储再解析（PRD-2 §5.2）：
- 原始文件与解析解耦——解析失败可重放、可换解析器重跑，不用让用户重传。
- source_uri（bucket/object）记进 kb_document，做血缘溯源。
"""
import io
import os
from datetime import datetime

from minio import Minio

from ..config import (MINIO_ENDPOINT, MINIO_ACCESS_KEY, MINIO_SECRET_KEY,
                      MINIO_SECURE, MINIO_BUCKET_UPLOADS)

_client = None


def client() -> Minio:
    global _client
    if _client is None:
        _client = Minio(MINIO_ENDPOINT, access_key=MINIO_ACCESS_KEY,
                        secret_key=MINIO_SECRET_KEY, secure=MINIO_SECURE)
        if not _client.bucket_exists(MINIO_BUCKET_UPLOADS):
            _client.make_bucket(MINIO_BUCKET_UPLOADS)
    return _client


def put_bytes(user_id: int, filename: str, data: bytes, content_type="application/octet-stream") -> str:
    """存原始文件，返回 source_uri（bucket/object_name）。object 名带 user_id + 时间戳防撞。"""
    ts = datetime.now().strftime("%Y%m%d%H%M%S%f")
    object_name = f"u{user_id}/{ts}_{filename}"
    c = client()
    c.put_object(MINIO_BUCKET_UPLOADS, object_name, io.BytesIO(data), length=len(data),
                 content_type=content_type)
    return f"{MINIO_BUCKET_UPLOADS}/{object_name}"


def get_bytes(source_uri: str) -> bytes:
    """按 source_uri(bucket/object) 取回原始文件字节。"""
    bucket, _, object_name = source_uri.partition("/")
    resp = client().get_object(bucket, object_name)
    try:
        return resp.read()
    finally:
        resp.close()
        resp.release_conn()
