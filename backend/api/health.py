import logging
import os

import httpx
from fastapi import APIRouter
from pymongo.errors import PyMongoError

from db.mdb import MongoDBConnector
from storage import get_storage_adapter

log = logging.getLogger("health")
router = APIRouter()


def _check_mongo() -> str:
    try:
        mdb = MongoDBConnector()
        mdb.client.admin.command("ping")
        return "ok"
    except PyMongoError as e:
        log.warning("mongo health failed: %s", e)
        return f"error: {e}"


async def _check_ollama() -> str:
    base = os.environ.get("OLLAMA_BASE_URL", "http://ollama:11434")
    try:
        async with httpx.AsyncClient(timeout=3.0) as c:
            r = await c.get(f"{base}/api/tags")
            r.raise_for_status()
            tags = [m.get("name") for m in r.json().get("models", [])]
            target = os.environ.get("OLLAMA_MODEL", "moondream")
            if target in tags:
                return "ok"
            return f"reachable, model {target!r} not pulled (have: {tags[:5]})"
    except (httpx.HTTPError, ValueError) as e:
        return f"unreachable: {e}"


def _check_storage() -> str:
    try:
        # head a sentinel key: reaches the S3 endpoint without listing the bucket.
        get_storage_adapter().head_object("__healthcheck__")
        return "ok"
    except Exception as e:  # noqa: BLE001
        log.warning("storage health failed: %s", e)
        return f"error: {e}"


async def _check_powersync() -> str:
    # In-cluster service URL for the backend->powersync liveness probe.
    internal = os.environ.get("POWERSYNC_INTERNAL_URL", "http://powersync:8080")
    try:
        async with httpx.AsyncClient(timeout=3.0) as c:
            r = await c.get(f"{internal}/probes/liveness")
            if r.status_code == 200:
                return "ok"
            return f"status {r.status_code}"
    except httpx.HTTPError as e:
        return f"unreachable: {e}"


@router.get("/api/health")
async def health():
    mongo = _check_mongo()
    storage = _check_storage()
    ollama = await _check_ollama()
    powersync = await _check_powersync()
    overall = (
        "ok"
        if mongo == "ok" and storage == "ok" and ollama == "ok" and powersync == "ok"
        else "degraded"
    )
    return {
        "status": overall,
        "mongo": mongo,
        "storage": storage,
        "ollama": ollama,
        "powersync": powersync,
    }
