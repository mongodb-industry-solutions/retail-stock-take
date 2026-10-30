"""Curated sample-shelf gallery — read-only listing + image bytes from object
storage, served through the same-origin /api/* proxy (the browser never talks to
S3 directly).

Gated by STORAGE_SAMPLES_PREFIX: when it's unset (or storage is off) the gallery
reports `enabled: false` and the UI hides it.
"""

from __future__ import annotations

import logging
import mimetypes
import os

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response

from storage import get_storage_adapter, storage_enabled

log = logging.getLogger("sample_shelves")
router = APIRouter()

_samples_prefix = os.environ.get("STORAGE_SAMPLES_PREFIX", "").strip() or None


def _enabled() -> bool:
    return storage_enabled() and bool(_samples_prefix)


@router.get("/api/sample-shelves")
async def list_sample_shelves():
    if not _enabled():
        return {"enabled": False, "items": []}
    adapter = get_storage_adapter()
    keys = adapter.list_objects(_samples_prefix)
    items = []
    for key in keys:
        # list_objects returns full bucket keys; expose the relative name.
        if not key.startswith(_samples_prefix):
            continue
        name = key[len(_samples_prefix) :]
        if not name or name.endswith("/"):
            continue  # skip folder-marker objects
        items.append({"name": name})
    items.sort(key=lambda i: i["name"])
    return {"enabled": True, "items": items}


@router.get("/api/sample-shelves/image")
async def get_sample_image(
    name: str = Query(..., description="Relative key under STORAGE_SAMPLES_PREFIX"),
):
    if not _enabled():
        raise HTTPException(404, "sample shelves not enabled")
    name = name.strip()
    if (
        not name
        or name.startswith("/")
        or name.startswith("..")
        or "/.." in name
        or "\\" in name
    ):
        raise HTTPException(400, "invalid sample name")
    key = f"{_samples_prefix}{name}"
    if not key.startswith(_samples_prefix):
        raise HTTPException(400, "invalid sample name")
    adapter = get_storage_adapter()
    try:
        data = adapter.get_object(key)
    except Exception as e:  # noqa: BLE001 — missing/transient sample is not fatal to the demo
        log.warning("get_object(%s) failed: %s", key, e)
        raise HTTPException(404, "sample image not found") from e
    media_type = mimetypes.guess_type(name)[0] or "application/octet-stream"
    return Response(content=data, media_type=media_type)
