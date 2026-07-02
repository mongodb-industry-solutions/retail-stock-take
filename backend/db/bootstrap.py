"""Startup checks. Ensure the demo's invariants — self-bootstrapping so the
same code works locally (where mongo-init pre-creates the collection) and in
cloud/Atlas (no mongo-init; Atlas creates collections lazily)."""
import logging
import os

from pymongo.errors import CollectionInvalid

from db.mdb import MongoDBConnector

log = logging.getLogger("bootstrap")


def ensure_collection_ready() -> None:
    """
    Make sure the inventory collection exists AND has
    changeStreamPreAndPostImages enabled — PowerSync silently fails without
    this on a MongoDB source. Idempotent: creates/enables what's missing rather
    than failing (the backend user has readWrite, which covers createCollection
    and collMod). Locally this is a no-op (mongo-init already did it).
    """
    coll_name = os.environ.get("APP_COLLECTION", "inventory_captures")
    mdb = MongoDBConnector()

    infos = list(mdb.db.list_collections(filter={"name": coll_name}))
    if not infos:
        log.info(
            "collection %s.%s missing — creating it (no mongo-init in cloud)",
            mdb.database_name, coll_name,
        )
        try:
            mdb.db.create_collection(coll_name)
        except CollectionInvalid:
            pass  # created concurrently by another replica — fine
        infos = list(mdb.db.list_collections(filter={"name": coll_name}))

    opts = infos[0].get("options", {})
    pre_post = opts.get("changeStreamPreAndPostImages") or {}
    if not pre_post.get("enabled"):
        log.info(
            "enabling changeStreamPreAndPostImages on %s.%s",
            mdb.database_name, coll_name,
        )
        mdb.db.command({"collMod": coll_name, "changeStreamPreAndPostImages": {"enabled": True}})

    log.info("collection %s.%s ready (pre/post images enabled)", mdb.database_name, coll_name)
