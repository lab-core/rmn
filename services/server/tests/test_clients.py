"""The Mongo client factory fails closed without credentials."""

import pytest

import utils.clients as clients


def test_mongo_url_requires_credentials(monkeypatch):
    # the defaults were adminuser / example: a missing variable connected with
    # the sample password instead of failing
    monkeypatch.delenv("MONGODB_USER", raising=False)
    monkeypatch.delenv("MONGODB_PASSWORD", raising=False)
    with pytest.raises(RuntimeError):
        clients.mongo_url()
    monkeypatch.setenv("MONGODB_USER", "u")
    monkeypatch.setenv("MONGODB_PASSWORD", "p")
    assert clients.mongo_url().startswith("mongodb://u:p@")
