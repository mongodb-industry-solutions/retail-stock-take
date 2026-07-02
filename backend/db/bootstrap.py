"""Startup checks. Fail loud if the demo's invariants aren't met."""
import logging
import os

from db.mdb import MongoDBConnector

log = logging.getLogger("bootstrap")


def ensure_collection_ready() -> None:
    """
    Verify that the inventory collection exists AND has
    changeStreamPreAndPostImages enabled — PowerSync silently fails without
    this on a MongoDB source.
    """
    coll_name = os.environ.get("APP_COLLECTION", "inventory_captures")
    mdb = MongoDBConnector()

    infos = list(mdb.db.list_collections(filter={"name": coll_name}))
    if not infos:
        raise RuntimeError(
            f"collection {coll_name!r} does not exist in {mdb.database_name!r}; "
            "did the mongo-init container run?"
        )

    opts = infos[0].get("options", {})
    pre_post = opts.get("changeStreamPreAndPostImages") or {}
    if not pre_post.get("enabled"):
        raise RuntimeError(
            f"collection {coll_name!r} does not have changeStreamPreAndPostImages enabled. "
            "PowerSync will not replicate updates/deletes correctly. "
            "Re-run scripts/setup.sh or run "
            f"`db.runCommand({{collMod:'{coll_name}',changeStreamPreAndPostImages:{{enabled:true}}}})` "
            "in mongosh."
        )

    log.info("collection %s.%s ready (pre/post images enabled)", mdb.database_name, coll_name)
