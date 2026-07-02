"""Startup checks. Self-bootstrapping so the same code works locally (mongo-init
pre-creates the collection) and in cloud/Atlas (no mongo-init; Atlas creates
collections lazily)."""
import logging
import os

from pymongo.errors import CollectionInvalid, OperationFailure

from db.mdb import MongoDBConnector

log = logging.getLogger("bootstrap")


def ensure_collection_ready() -> None:
    """
    Make sure the inventory collection exists AND has
    changeStreamPreAndPostImages enabled — PowerSync silently fails without
    this on a MongoDB source.

    Idempotent and least-privilege-friendly: when the collection is missing it's
    created WITH pre/post images in one step, since `createCollection` (granted
    by the `readWrite` role) accepts that option — no `collMod` needed. If the
    collection already exists without pre/post images, we fall back to `collMod`,
    which requires `dbAdmin`; if the user lacks it we log a clear warning rather
    than crash (PowerSync's `post_images: auto_configure` can also enable it).
    Locally this is a no-op — mongo-init already created it with pre/post images.
    """
    coll_name = os.environ.get("APP_COLLECTION", "inventory_captures")
    mdb = MongoDBConnector()

    infos = list(mdb.db.list_collections(filter={"name": coll_name}))
    if not infos:
        log.info(
            "collection %s.%s missing — creating it with pre/post images (no mongo-init in cloud)",
            mdb.database_name, coll_name,
        )
        try:
            mdb.db.create_collection(coll_name, changeStreamPreAndPostImages={"enabled": True})
            return  # freshly created with pre/post images — done
        except CollectionInvalid:
            # Raced with another replica (or a stale pre-check). Fall through and
            # verify pre/post images rather than trusting how it got created.
            log.info("collection %s.%s created concurrently — verifying", mdb.database_name, coll_name)
        infos = list(mdb.db.list_collections(filter={"name": coll_name}))
        if not infos:
            msg = (
                f"collection {mdb.database_name}.{coll_name} still missing after concurrent "
                "create retry; refusing to run collMod"
            )
            log.error(msg)
            raise RuntimeError(msg)

    opts = infos[0].get("options", {}) if infos else {}
    pre_post = opts.get("changeStreamPreAndPostImages") or {}
    if pre_post.get("enabled"):
        log.info("collection %s.%s ready (pre/post images enabled)", mdb.database_name, coll_name)
        return

    log.info("enabling changeStreamPreAndPostImages on %s.%s", mdb.database_name, coll_name)
    try:
        mdb.db.command({"collMod": coll_name, "changeStreamPreAndPostImages": {"enabled": True}})
    except OperationFailure as e:
        log.warning(
            "could not enable changeStreamPreAndPostImages on %s.%s (%s). collMod needs "
            "dbAdmin; enable it with an admin user, or rely on PowerSync post_images: "
            "auto_configure.", mdb.database_name, coll_name, e,
        )
