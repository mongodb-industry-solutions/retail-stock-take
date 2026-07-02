"""Storage adapter factory.

Selects the backend by configuration only. Today there is a single portable
implementation (S3-compatible); `STORAGE_PROVIDER` exists so future backends
can be added without touching business logic.

Local (SeaweedFS):  STORAGE_ENDPOINT + STORAGE_ACCESS_KEY/SECRET_KEY + STORAGE_FORCE_PATH_STYLE=true
Cloud (AWS S3):     omit endpoint + keys (IRSA via the default credential chain); set AWS_REGION + STORAGE_BUCKET
"""
from __future__ import annotations

import functools
import os

from .base import ObjectStat, StorageAdapter
from .s3 import S3StorageAdapter

__all__ = ["StorageAdapter", "ObjectStat", "get_storage_adapter"]


def _truthy(value: str | None) -> bool:
    return (value or "").strip().lower() in ("1", "true", "yes", "on")


@functools.lru_cache(maxsize=1)
def get_storage_adapter() -> StorageAdapter:
    provider = os.environ.get("STORAGE_PROVIDER", "s3").lower()
    if provider != "s3":
        raise ValueError(f"unsupported STORAGE_PROVIDER {provider!r} (only 's3' is supported)")

    return S3StorageAdapter(
        bucket=os.environ.get("STORAGE_BUCKET", "store-media"),
        region=os.environ.get("STORAGE_REGION") or os.environ.get("AWS_REGION"),
        endpoint_url=os.environ.get("STORAGE_ENDPOINT") or None,
        access_key=os.environ.get("STORAGE_ACCESS_KEY") or None,
        secret_key=os.environ.get("STORAGE_SECRET_KEY") or None,
        force_path_style=_truthy(os.environ.get("STORAGE_FORCE_PATH_STYLE")),
    )
