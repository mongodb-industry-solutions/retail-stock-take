import asyncio
import hashlib
import logging
import os
import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, File, Form, HTTPException, UploadFile

from cv import CV_FALLBACK, CV_MODEL, CVError, analyze_shelf_image
from db.mdb import MongoDBConnector
from storage import get_storage_adapter, storage_enabled

log = logging.getLogger("inventory")
router = APIRouter()

_collection = os.environ.get("APP_COLLECTION", "inventory_captures")
_max_bytes = int(os.environ.get("MAX_UPLOAD_BYTES", "10485760"))
_retention_days = int(os.environ.get("RETENTION_DAYS", "7"))
_retention_class = os.environ.get("RETENTION_CLASS", "standard")

_EXT_BY_TYPE = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp"}


def _raw_key(store_id: str, device_id: str, capture_id: str, ext: str, now: datetime) -> str:
    # raw/{storeId}/{deviceId}/YYYY/MM/DD/HH/{captureId}.{ext}
    # (crops/... is reserved for a future detection pass.)
    return f"raw/{store_id}/{device_id}/{now:%Y/%m/%d/%H}/{capture_id}.{ext}"


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
    key = _raw_key(store_id, device_id, capture_id, ext, now)
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
