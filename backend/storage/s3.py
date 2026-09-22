"""S3-compatible storage adapter (boto3).

One implementation serves both backends:
  - LOCAL  : SeaweedFS S3 gateway — explicit endpoint_url + static keys + path-style.
  - CLOUD  : AWS S3 — no endpoint, no static keys (boto3's default credential
             chain resolves IRSA on Kanopy), virtual-host addressing.

Only the common S3 subset is used (Put/Get/Head/Delete/ListV2).
"""
from __future__ import annotations

import logging

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

from .base import ObjectStat, StorageAdapter

log = logging.getLogger("storage")

_NOT_FOUND_CODES = {"404", "NoSuchKey", "NoSuchBucket", "NotFound"}


class S3StorageAdapter(StorageAdapter):
    def __init__(
        self,
        *,
        bucket: str,
        region: str | None = None,
        endpoint_url: str | None = None,
        access_key: str | None = None,
        secret_key: str | None = None,
        force_path_style: bool = False,
    ):
        self.bucket = bucket
        self._region = region
        self._endpoint_url = endpoint_url

        cfg = Config(
            signature_version="s3v4",
            s3={"addressing_style": "path" if force_path_style else "auto"},
            retries={"max_attempts": 3, "mode": "standard"},
        )
        client_kwargs: dict = {"config": cfg}
        if endpoint_url:
            client_kwargs["endpoint_url"] = endpoint_url
        if region:
            client_kwargs["region_name"] = region
        # When keys are omitted, boto3 falls back to the default credential
        # chain (env / instance / IRSA) — the cloud path.
        if access_key and secret_key:
            client_kwargs["aws_access_key_id"] = access_key
            client_kwargs["aws_secret_access_key"] = secret_key

        self._client = boto3.client("s3", **client_kwargs)

    # -- lifecycle --------------------------------------------------------
    def ensure_bucket(self) -> None:
        try:
            self._client.head_bucket(Bucket=self.bucket)
            return
        except ClientError as e:
            code = e.response.get("Error", {}).get("Code")
            if code not in _NOT_FOUND_CODES:
                # e.g. AccessDenied on a pre-provisioned cloud bucket — leave it.
                log.warning("head_bucket(%s) inconclusive (%s); assuming it exists", self.bucket, code)
                return
        # Bucket missing — create it (local SeaweedFS path).
        params: dict = {"Bucket": self.bucket}
        if self._region and self._region != "us-east-1":
            params["CreateBucketConfiguration"] = {"LocationConstraint": self._region}
        try:
            self._client.create_bucket(**params)
            log.info("created bucket %s", self.bucket)
        except ClientError as e:
            code = e.response.get("Error", {}).get("Code")
            if code in ("BucketAlreadyOwnedByYou", "BucketAlreadyExists"):
                return
            raise

    # -- common S3 subset -------------------------------------------------
    def put_object(self, key, data, content_type=None, metadata=None) -> ObjectStat:
        extra: dict = {}
        if content_type:
            extra["ContentType"] = content_type
        if metadata:
            extra["Metadata"] = {k: str(v) for k, v in metadata.items()}
        resp = self._client.put_object(Bucket=self.bucket, Key=key, Body=data, **extra)
        return ObjectStat(
            key=key, size_bytes=len(data), etag=resp.get("ETag"), content_type=content_type
        )

    def get_object(self, key) -> bytes:
        resp = self._client.get_object(Bucket=self.bucket, Key=key)
        return resp["Body"].read()

    def head_object(self, key) -> ObjectStat | None:
        try:
            resp = self._client.head_object(Bucket=self.bucket, Key=key)
        except ClientError as e:
            if e.response.get("Error", {}).get("Code") in _NOT_FOUND_CODES:
                return None
            raise
        return ObjectStat(
            key=key,
            size_bytes=int(resp.get("ContentLength", 0)),
            etag=resp.get("ETag"),
            content_type=resp.get("ContentType"),
        )

    def delete_object(self, key) -> None:
        self._client.delete_object(Bucket=self.bucket, Key=key)

    def list_objects(self, prefix="") -> list[str]:
        keys: list[str] = []
        paginator = self._client.get_paginator("list_objects_v2")
        for page in paginator.paginate(Bucket=self.bucket, Prefix=prefix):
            keys.extend(obj["Key"] for obj in page.get("Contents", []))
        return keys
