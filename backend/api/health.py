import logging
import os

import httpx
from fastapi import APIRouter
from pymongo.errors import PyMongoError

from cv import CV_MODEL, CV_PROVIDER
from db.mdb import MongoDBConnector
from storage import get_storage_adapter, storage_enabled

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


async def _check_cv() -> str:
    if CV_PROVIDER == "grove":
        # Don't spend a vision call on every probe — just confirm it's configured.
        if os.environ.get("GROVE_API_KEY"):
            return f"ok (grove: {CV_MODEL})"
        return "GROVE_API_KEY not set"
    # ollama: verify the target model is pulled and the server is reachable.
    base = os.environ.get("OLLAMA_BASE_URL", "http://ollama:11434")
    try:
        async with httpx.AsyncClient(timeout=3.0) as c:
            r = await c.get(f"{base}/api/tags")
            r.raise_for_status()
            tags = [m.get("name") for m in r.json().get("models", [])]
            # Ollama tags carry a ":<tag>" suffix (e.g. "moondream:latest");
            # match on the bare name too.
            if any(t == CV_MODEL or t.split(":")[0] == CV_MODEL for t in tags):
                return "ok"
            return f"reachable, model {CV_MODEL!r} not pulled (have: {tags[:5]})"
    except (httpx.HTTPError, ValueError) as e:
        return f"unreachable: {e}"


def _check_storage() -> str:
    if not storage_enabled():
        return "disabled"
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


def _ok(status: str) -> bool:
    # "disabled" (photo store off) is a healthy, intentional state.
    return status.startswith("ok") or status == "disabled"


@router.get("/api/health")
async def health():
    mongo = _check_mongo()
    storage = _check_storage()
    cv = await _check_cv()
    powersync = await _check_powersync()
    overall = (
        "ok"
        if _ok(mongo) and _ok(storage) and _ok(cv) and _ok(powersync)
        else "degraded"
    )
    return {
        "status": overall,
        "mongo": mongo,
        "storage": storage,
        "cv": cv,
        "cv_provider": CV_PROVIDER,
        "powersync": powersync,
    }
