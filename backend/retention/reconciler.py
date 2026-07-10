"""Retention reconciler — backend-agnostic, independent of any S3 lifecycle.

Two idempotent duties:
  * promote: PENDING_UPLOAD rows whose object now exists  -> ACTIVE.
             PENDING_UPLOAD rows whose object is still missing past the grace
             window (crashed mid-write) -> the doc is deleted.
  * expire : ACTIVE rows past asset.expires_at -> delete the object, mark DELETED
             (the deletion syncs to clients via PowerSync).

Run modes:
  * in-process periodic loop (started from main.py lifespan), and
  * one-shot CLI:  `python -m retention.reconciler`  (future K8s CronJob).

MongoDB stores the logical retention intent; this job enforces it regardless of
whether the object store offers lifecycle/TTL — SeaweedFS lifecycle support has
caveats, so we never depend on it.
"""
from __future__ import annotations

import asyncio
import logging
import os
from datetime import datetime, timezone

from db.mdb import MongoDBConnector
from storage import get_storage_adapter, storage_enabled

log = logging.getLogger("reconciler")

_collection = os.environ.get("APP_COLLECTION", "inventory_captures")
_pending_grace_seconds = int(os.environ.get("RECONCILER_PENDING_GRACE_SECONDS", "900"))
_interval_seconds = int(os.environ.get("RECONCILER_INTERVAL_SECONDS", "300"))


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _parse(value) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value)
    except (ValueError, TypeError):
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def run_once() -> dict:
    """One reconciliation pass. Returns counts. Safe to call repeatedly."""
    mdb = MongoDBConnector()
    # When the photo store is disabled (STORAGE_PROVIDER=none), docs carry no
    # asset — there are no objects to head/promote/delete, so skip the adapter
    # entirely. Doc-level expiry below still runs and syncs DELETED to clients.
    enabled = storage_enabled()
    adapter = get_storage_adapter() if enabled else None
    now = _now()
    promoted = abandoned = expired = 0

    # --- reconcile PENDING_UPLOAD ---------------------------------------
    for doc in mdb.find(_collection, {"status": "PENDING_UPLOAD"}):
        asset = doc.get("asset") or {}
        key = asset.get("key")
        if not key or adapter is None:
            continue
        stat = adapter.head_object(key)
        if stat is not None:
            mdb.update_one(
                _collection,
                {"_id": doc["_id"]},
                {"$set": {"status": "ACTIVE", "asset.size_bytes": stat.size_bytes}},
            )
            promoted += 1
            continue
        created = _parse(asset.get("created_at") or doc.get("captured_at"))
        if created and (now - created).total_seconds() > _pending_grace_seconds:
            mdb.delete_one(_collection, {"_id": doc["_id"]})
            abandoned += 1

    # --- expire ACTIVE past expires_at ----------------------------------
    # ISO-8601 UTC strings compare lexicographically == chronologically.
    expired_query = {"status": "ACTIVE", "asset.expires_at": {"$lte": now.isoformat()}}
    for doc in mdb.find(_collection, expired_query):
        key = (doc.get("asset") or {}).get("key")
        if key and adapter is not None:
            try:
                adapter.delete_object(key)
            except Exception as e:  # noqa: BLE001
                log.warning("delete_object(%s) failed: %s", key, e)
                continue
        mdb.update_one(
            _collection,
            {"_id": doc["_id"]},
            {"$set": {"status": "DELETED", "asset.deleted_at": now.isoformat()}},
        )
        expired += 1

    result = {"promoted": promoted, "abandoned": abandoned, "expired": expired}
    if promoted or abandoned or expired:
        log.info("reconcile: %s", result)
    return result


async def run_periodic(stop_event: asyncio.Event | None = None) -> None:
    """Background loop for the in-process reconciler (see main.py lifespan)."""
    log.info("reconciler loop started (interval=%ss)", _interval_seconds)
    while not (stop_event and stop_event.is_set()):
        try:
            await asyncio.to_thread(run_once)
        except Exception as e:  # noqa: BLE001
            log.warning("reconcile pass failed: %s", e)
        if stop_event is None:
            await asyncio.sleep(_interval_seconds)
            continue
        try:
            await asyncio.wait_for(stop_event.wait(), timeout=_interval_seconds)
        except asyncio.TimeoutError:
            pass


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    print(run_once())
