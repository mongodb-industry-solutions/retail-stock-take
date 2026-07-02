import asyncio
import logging
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api import auth, health, inventory
from db.bootstrap import ensure_collection_ready
from retention.reconciler import run_periodic
from storage import get_storage_adapter

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("backend")


@asynccontextmanager
async def lifespan(_app: FastAPI):
    ensure_collection_ready()
    auth.load_keys()
    try:
        get_storage_adapter().ensure_bucket()
    except Exception as e:  # noqa: BLE001 — soft-fail so partial bring-up still starts
        log.warning("object storage not ready at startup: %s", e)

    stop = asyncio.Event()
    reconciler = asyncio.create_task(run_periodic(stop))
    log.info("backend ready")
    try:
        yield
    finally:
        stop.set()
        reconciler.cancel()
        try:
            await reconciler
        except asyncio.CancelledError:
            pass


app = FastAPI(lifespan=lifespan, title="retail-stock-take backend")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth.router)
app.include_router(health.router)
app.include_router(inventory.router)


@app.get("/")
async def root():
    return {"message": "retail-stock-take backend is running"}
