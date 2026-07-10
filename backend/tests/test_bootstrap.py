from unittest.mock import Mock

import pytest
from pymongo.errors import CollectionInvalid

from db import bootstrap


def test_ensure_collection_ready_raises_if_collection_still_missing_after_race(monkeypatch):
    fake_db = Mock()
    fake_db.list_collections.side_effect = [[], []]
    fake_db.create_collection.side_effect = CollectionInvalid("already exists")

    fake_connector = Mock(db=fake_db, database_name="retail_demo")
    monkeypatch.setattr(bootstrap, "MongoDBConnector", lambda: fake_connector)

    with pytest.raises(RuntimeError, match="still missing after concurrent create retry"):
        bootstrap.ensure_collection_ready()

    fake_db.command.assert_not_called()
