"""Infra-free functional test of the S3 storage adapter via moto.

Exercises the common S3 subset + the boto3 quirks we depend on (path-style,
sigv4, 404 -> None on head, idempotent delete). The same adapter code runs
against SeaweedFS locally and AWS S3 in cloud.
"""
from moto import mock_aws

from storage.base import ObjectStat
from storage.s3 import S3StorageAdapter


def _adapter() -> S3StorageAdapter:
    # static keys = the local SeaweedFS path; force_path_style mirrors SeaweedFS.
    return S3StorageAdapter(
        bucket="store-media",
        region="us-east-1",
        access_key="testing",
        secret_key="testing",
        force_path_style=True,
    )


@mock_aws
def test_common_s3_subset_roundtrip():
    a = _adapter()
    a.ensure_bucket()
    a.ensure_bucket()  # idempotent

    # head of a missing key returns None (not an exception)
    assert a.head_object("raw/missing.jpg") is None

    stat = a.put_object("raw/store1/dev1/2026/06/05/10/cap.jpg", b"hello", "image/jpeg",
                        {"capture_id": "cap"})
    assert isinstance(stat, ObjectStat) and stat.size_bytes == 5

    head = a.head_object("raw/store1/dev1/2026/06/05/10/cap.jpg")
    assert head is not None and head.size_bytes == 5 and head.content_type == "image/jpeg"

    assert a.get_object("raw/store1/dev1/2026/06/05/10/cap.jpg") == b"hello"

    a.put_object("raw/store1/dev1/2026/06/05/10/cap2.jpg", b"world")
    keys = set(a.list_objects("raw/store1/"))
    assert "raw/store1/dev1/2026/06/05/10/cap.jpg" in keys
    assert "raw/store1/dev1/2026/06/05/10/cap2.jpg" in keys

    a.delete_object("raw/store1/dev1/2026/06/05/10/cap.jpg")
    assert a.head_object("raw/store1/dev1/2026/06/05/10/cap.jpg") is None
    a.delete_object("raw/store1/dev1/2026/06/05/10/cap.jpg")  # idempotent: no error
