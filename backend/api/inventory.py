import asyncio
import hashlib
import logging
import mimetypes
import os
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import Response

from cv import CV_FALLBACK, CV_MODEL, CVError, analyze_shelf_image
from db.mdb import MongoDBConnector
from storage import get_storage_adapter, storage_enabled

log = logging.getLogger("inventory")
router = APIRouter()

_collection = os.environ.get("APP_COLLECTION", "inventory_captures")
_max_bytes = int(os.environ.get("MAX_UPLOAD_BYTES", "10485760"))
_retention_days = int(os.environ.get("RETENTION_DAYS", "7"))
_retention_class = os.environ.get("RETENTION_CLASS", "standard")
# Base key prefix for uploaded frames. Default "raw/" preserves local SeaweedFS
_upload_prefix = os.environ.get("STORAGE_UPLOAD_PREFIX", "raw/")

_EXT_BY_TYPE = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp"}


def _raw_key(capture_id: str, ext: str) -> str:
    # {prefix}{captureId}.{ext} — flat, no store/device/date nesting.
    # (crops/... is reserved for a future detection pass.)
    return f"{_upload_prefix}{capture_id}.{ext}"


@router.post("/api/inventory/capture", status_code=201)
async def capture(
    photo: UploadFile = File(...),
    device_id: str = Form("web-unknown"),
    operator_id: str = Form("demo-operator"),
    store_id: str = Form("store-unknown"),
):
    payload = await photo.read()
    if len(payload) == 0:
        raise HTTPException(400, "empty photo")
    if len(payload) > _max_bytes:
        raise HTTPException(413, f"photo exceeds {_max_bytes} bytes")

    log.info(
        "capture: %d bytes store=%s device=%s operator=%s",
        len(payload), store_id, device_id, operator_id,
    )

    try:
        result, used_model = await analyze_shelf_image(payload, CV_MODEL, CV_FALLBACK)
    except CVError as e:
        log.warning("cv failed: %s", e)
        raise HTTPException(503, f"computer vision unavailable: {e}") from e

    capture_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc)
    content_type = photo.content_type or "image/jpeg"

    # No photo store (e.g. cloud with STORAGE_PROVIDER=none): persist the
    # inventory metadata only, straight to ACTIVE with no asset. CV + Mongo +
    # PowerSync sync all still work; only the raw frame is not retained.
    if not storage_enabled():
        doc = {
            "_id": capture_id,
            "captured_at": now.isoformat(),
            "device_id": device_id,
            "operator_id": operator_id,
            "store_id": store_id,
            "cv_model": used_model,
            "items": [item.model_dump() for item in result.items],
            "status": "ACTIVE",
            "asset": None,
        }
        MongoDBConnector().insert_one(_collection, doc)
        return doc

    ext = _EXT_BY_TYPE.get(content_type, "jpg")
    adapter = get_storage_adapter()
    key = _raw_key(capture_id, ext)
    expires_at = now + timedelta(days=_retention_days)

    # (1) Persist metadata FIRST as PENDING_UPLOAD. If the process dies before
    #     the object is written, the reconciler can clean up / re-drive.
    doc = {
        "_id": capture_id,
        "captured_at": now.isoformat(),
        "device_id": device_id,
        "operator_id": operator_id,
        "store_id": store_id,
        "cv_model": used_model,
        "items": [item.model_dump() for item in result.items],
        "status": "PENDING_UPLOAD",
        "asset": {
            "backend": "s3",
            "bucket": adapter.bucket,
            "key": key,
            "media_type": content_type,
            "size_bytes": None,
            "checksum": None,
            "retention_class": _retention_class,
            "created_at": now.isoformat(),
            "expires_at": expires_at.isoformat(),
        },
    }
    mdb = MongoDBConnector()
    mdb.insert_one(_collection, doc)

    # (2) Upload the bytes to object storage at the deterministic key.
    checksum = hashlib.sha256(payload).hexdigest()
    try:
        await asyncio.to_thread(
            adapter.put_object,
            key,
            payload,
            content_type,
            {"capture_id": capture_id, "store_id": store_id, "operator_id": operator_id},
        )
    except Exception as e:  # noqa: BLE001
        log.error("object upload failed for %s: %s", key, e)
        # Leave the doc PENDING_UPLOAD for the reconciler; surface the failure.
        raise HTTPException(502, "object storage upload failed") from e

    # (3) Promote to ACTIVE with size + checksum.
    mdb.update_one(
        _collection,
        {"_id": capture_id},
        {"$set": {
            "status": "ACTIVE",
            "asset.size_bytes": len(payload),
            "asset.checksum": checksum,
        }},
    )
    doc["status"] = "ACTIVE"
    doc["asset"]["size_bytes"] = len(payload)
    doc["asset"]["checksum"] = checksum

    return doc


@router.get("/api/inventory/{capture_id}/image")
async def capture_image(capture_id: str):
    """Serve the raw captured frame for a capture by id (read-only).

    The browser can't derive a URL from the synced row (asset isn't synced), so
    it asks the backend for the frame by capture id.
    """
    if not storage_enabled():
        raise HTTPException(404, "photo store disabled")
    docs = MongoDBConnector().find(_collection, {"_id": capture_id})
    if not docs:
        raise HTTPException(404, "capture not found")
    asset = (docs[0] or {}).get("asset")
    if not asset or not asset.get("key"):
        raise HTTPException(404, "capture has no stored frame")
    try:
        data = get_storage_adapter().get_object(asset["key"])
    except Exception as e:  # noqa: BLE001 — missing/transient frame is not fatal
        log.warning("get_object(%s) failed: %s", asset["key"], e)
        raise HTTPException(404, "frame not found") from e
    media_type = (
        asset.get("media_type")
        or mimetypes.guess_type(asset["key"])[0]
        or "application/octet-stream"
    )
    return Response(content=data, media_type=media_type)
