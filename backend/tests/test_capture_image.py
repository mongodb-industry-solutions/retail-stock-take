"""Unit tests for GET /api/inventory/{capture_id}/image.

Calls the route function directly with a stubbed StorageAdapter + MongoDBConnector
(no live DB/object store needed).
"""
import asyncio

import pytest
from fastapi import HTTPException

from api import inventory


class _FakeAdapter:
    bucket = "demo-bucket"

    def __init__(self, objects=None):
        self.objects = objects or {}

    def get_object(self, key):
        if key not in self.objects:
            raise FileNotFoundError(key)
        return self.objects[key]


class _FakeMongo:
    def __init__(self, doc):
        self._doc = doc

    def find(self, collection, query):
        return [self._doc] if query.get("_id") == (self._doc or {}).get("_id") else []


def _mdb_connector(doc):
    return lambda: _FakeMongo(doc)


def test_capture_image_ok(monkeypatch):
    monkeypatch.setattr(inventory, "storage_enabled", lambda: True)
    doc = {"_id": "c1", "asset": {"key": "raw/c1.jpg", "media_type": "image/jpeg"}}
    monkeypatch.setattr(inventory, "MongoDBConnector", _mdb_connector(doc))
    monkeypatch.setattr(inventory, "get_storage_adapter", lambda: _FakeAdapter({"raw/c1.jpg": b"\xff\xd8img"}))
    resp = asyncio.run(inventory.capture_image("c1"))
    assert resp.body == b"\xff\xd8img"
    assert resp.headers["content-type"].startswith("image/jpeg")


def test_capture_image_not_found(monkeypatch):
    monkeypatch.setattr(inventory, "storage_enabled", lambda: True)
    monkeypatch.setattr(inventory, "MongoDBConnector", _mdb_connector(None))
    monkeypatch.setattr(inventory, "get_storage_adapter", lambda: _FakeAdapter())
    with pytest.raises(HTTPException) as ei:
        asyncio.run(inventory.capture_image("missing"))
    assert ei.value.status_code == 404


def test_capture_image_no_asset(monkeypatch):
    monkeypatch.setattr(inventory, "storage_enabled", lambda: True)
    monkeypatch.setattr(inventory, "MongoDBConnector", _mdb_connector({"_id": "c1", "asset": None}))
    monkeypatch.setattr(inventory, "get_storage_adapter", lambda: _FakeAdapter())
    with pytest.raises(HTTPException) as ei:
        asyncio.run(inventory.capture_image("c1"))
    assert ei.value.status_code == 404


def test_capture_image_storage_disabled(monkeypatch):
    monkeypatch.setattr(inventory, "storage_enabled", lambda: False)
    with pytest.raises(HTTPException) as ei:
        asyncio.run(inventory.capture_image("c1"))
    assert ei.value.status_code == 404
