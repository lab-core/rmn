"""Test harness for the socketIO relay.

``app.py`` reads its configuration and creates the Mongo client at import
time, so the environment is set and ``pymongo.MongoClient`` is swapped for
``mongomock`` BEFORE the app is imported. eventlet's monkey patching is
disabled: the tests run under plain threads with Flask-SocketIO's test client,
which drives the handlers directly and needs no server loop.
"""

import datetime as dt
import os
import sys
from pathlib import Path

import pytest

SOCKETIO_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SOCKETIO_DIR))

SERVICE_TOKEN = "svc-secret"

os.environ["ENVIRONMENT"] = "test"
os.environ["SOCKETIO_SERVICE_TOKEN"] = SERVICE_TOKEN
os.environ["TOKEN_TTL_DAYS"] = "30"
os.environ["SOCKETIO_CORS_ORIGINS"] = "*"

import eventlet  # noqa: E402

eventlet.monkey_patch = lambda **kwargs: None

import mongomock  # noqa: E402
import pymongo  # noqa: E402

pymongo.MongoClient = mongomock.MongoClient

import app as app_module  # noqa: E402  (imported after the patches above)


@pytest.fixture(autouse=True)
def _isolate_state():
    """Wipe Mongo and the connection table before every test."""
    db = app_module.mongo["RMN"]
    for name in db.list_collection_names():
        db[name].delete_many({})
    app_module.connections.clear()
    yield


@pytest.fixture
def db():
    return app_module.mongo["RMN"]


@pytest.fixture
def make_token(db):
    """Insert a login token like the server does."""

    def _make(username="alice", token=None, age_days=0):
        token = token or f"tok-{username}"
        created = dt.datetime.now(dt.UTC) - dt.timedelta(days=age_days)
        db["tokens"].insert_one(
            {"token": token, "username": username, "role": "Utilisateur", "creation_time": created}
        )
        return token

    return _make


@pytest.fixture
def connect():
    """Open a Flask-SocketIO test client with the given handshake ``auth``."""
    clients = []

    def _connect(auth=None):
        client = app_module.socketio.test_client(app_module.app, auth=auth)
        clients.append(client)
        return client

    yield _connect
    for client in clients:
        if client.is_connected():
            client.disconnect()
