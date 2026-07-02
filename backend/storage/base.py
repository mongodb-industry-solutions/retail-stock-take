"""Vendor-agnostic object-storage adapter interface.

Business logic depends ONLY on this interface and the common S3 subset it
exposes — never on SeaweedFS-, MinIO-, or AWS-specific behaviour. The same
implementation (see s3.py) is pointed at SeaweedFS locally and AWS S3 in cloud
by configuration alone.
"""
from __future__ import annotations

import abc
from dataclasses import dataclass


@dataclass(frozen=True)
class ObjectStat:
    """Minimal, portable object metadata returned by head/put."""

    key: str
    size_bytes: int
    etag: str | None = None
    content_type: str | None = None


class StorageAdapter(abc.ABC):
    """The common S3 subset every backend must support.

    Implementations bind a single default bucket at construction; callers pass
    keys only. Keep this surface to broadly portable operations only.
    """

    bucket: str

    @abc.abstractmethod
    def ensure_bucket(self) -> None:
        """Idempotently make sure the configured bucket exists (best-effort)."""

    @abc.abstractmethod
    def put_object(
        self,
        key: str,
        data: bytes,
        content_type: str | None = None,
        metadata: dict | None = None,
    ) -> ObjectStat:
        """PutObject. Returns the resulting object's stat."""

    @abc.abstractmethod
    def get_object(self, key: str) -> bytes:
        """GetObject. Raises if the key does not exist."""

    @abc.abstractmethod
    def head_object(self, key: str) -> ObjectStat | None:
        """HeadObject. Returns None if the object does not exist."""

    @abc.abstractmethod
    def delete_object(self, key: str) -> None:
        """DeleteObject. Idempotent — deleting a missing key is not an error."""

    @abc.abstractmethod
    def list_objects(self, prefix: str = "") -> list[str]:
        """ListObjectsV2 — returns keys under an optional prefix."""

    @abc.abstractmethod
    def create_presigned_url(
        self, key: str, ttl_seconds: int = 3600, method: str = "get_object"
    ) -> str:
        """Presigned URL for direct client access (use sparingly)."""
