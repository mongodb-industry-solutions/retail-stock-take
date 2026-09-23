"""Unit tests for the sample-shelves gallery + upload key prefix.

These avoid TestClient/lifespan (which would need a live Mongo) and call the
router functions directly against a stubbed StorageAdapter.
"""
import asyncio

import pytest
from fastapi import HTTPException

from api import inventory, sample_shelves


class _FakeAdapter:
    bucket = "demo-bucket"

    def __init__(self, objects=None):
        self.objects = objects or {}

    def list_objects(self, prefix=""):
        return [k for k in self.objects if k.startswith(prefix)]

    def get_object(self, key):
        if key not in self.objects:
            raise FileNotFoundError(key)
        return self.objects[key]


def test_raw_key_uses_upload_prefix(monkeypatch):
    monkeypatch.setattr(inventory, "_upload_prefix", "industry/mobile/retail-stock-take/uploads/")
    key = inventory._raw_key("c1", "jpg")
    assert key == "industry/mobile/retail-stock-take/uploads/c1.jpg"


def test_raw_key_default_prefix(monkeypatch):
    monkeypatch.setattr(inventory, "_upload_prefix", "raw/")
    key = inventory._raw_key("c1", "jpg")
    assert key == "raw/c1.jpg"


def test_list_disabled(monkeypatch):
    monkeypatch.setattr(sample_shelves, "_samples_prefix", None)
    r = asyncio.run(sample_shelves.list_sample_shelves())
    assert r == {"enabled": False, "items": []}


def test_list_enabled(monkeypatch):
    monkeypatch.setattr(sample_shelves, "_samples_prefix", "shelves/")
    monkeypatch.setattr(sample_shelves, "storage_enabled", lambda: True)
    fake = _FakeAdapter({"shelves/a.jpg": b"x", "shelves/sub/b.png": b"y", "other/z.jpg": b"z"})
    monkeypatch.setattr(sample_shelves, "get_storage_adapter", lambda: fake)
    r = asyncio.run(sample_shelves.list_sample_shelves())
    assert r["enabled"] is True
    assert r["items"] == [{"name": "a.jpg"}, {"name": "sub/b.png"}]


def test_get_image(monkeypatch):
    monkeypatch.setattr(sample_shelves, "_samples_prefix", "shelves/")
    monkeypatch.setattr(sample_shelves, "storage_enabled", lambda: True)
    fake = _FakeAdapter({"shelves/a.jpg": b"\xff\xd8img"})
    monkeypatch.setattr(sample_shelves, "get_storage_adapter", lambda: fake)
    resp = asyncio.run(sample_shelves.get_sample_image("a.jpg"))
    assert resp.body == b"\xff\xd8img"
    assert resp.headers["content-type"].startswith("image/jpeg")


def test_get_image_rejects_traversal(monkeypatch):
    monkeypatch.setattr(sample_shelves, "_samples_prefix", "shelves/")
    monkeypatch.setattr(sample_shelves, "storage_enabled", lambda: True)
    monkeypatch.setattr(sample_shelves, "get_storage_adapter", lambda: _FakeAdapter())
    with pytest.raises(HTTPException) as ei:
        asyncio.run(sample_shelves.get_sample_image("../secret.jpg"))
    assert ei.value.status_code == 400


def test_get_image_missing_404(monkeypatch):
    monkeypatch.setattr(sample_shelves, "_samples_prefix", "shelves/")
    monkeypatch.setattr(sample_shelves, "storage_enabled", lambda: True)
    monkeypatch.setattr(sample_shelves, "get_storage_adapter", lambda: _FakeAdapter())
    with pytest.raises(HTTPException) as ei:
        asyncio.run(sample_shelves.get_sample_image("missing.jpg"))
    assert ei.value.status_code == 404
