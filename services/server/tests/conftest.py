"""Test harness for the Flask server.

``app.py`` connects to MongoDB, Redis and Socket.IO at import time, so the
client factories in ``utils.clients`` are patched with in-memory doubles
(``mongomock`` / ``fakeredis`` / a mock) BEFORE the app is imported. Every test
then drives the app through Flask's test client against those doubles, so the
suite needs no running services.
"""

import os
import sys
from pathlib import Path
from unittest.mock import MagicMock

import pytest

# --- make the server package importable (app.py uses absolute imports) ---
SERVER_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(SERVER_DIR))

# --- configure the environment BEFORE importing the app ---
os.environ["ENVIRONMENT"] = "test"
os.environ["ADMIN_API_KEY"] = "test-admin-key"
_STORAGE_DIR = SERVER_DIR / "tests" / "_storage"
_STORAGE_DIR.mkdir(parents=True, exist_ok=True)
os.environ["STORAGE"] = str(_STORAGE_DIR)

# --- swap the external clients for in-memory doubles before importing app ---
import mongomock  # noqa: E402
import fakeredis  # noqa: E402
import utils.clients as clients  # noqa: E402

_MONGO = mongomock.MongoClient()
clients.mongo_client = lambda: _MONGO
clients.redis_client = lambda **_: fakeredis.FakeStrictRedis()
clients.socketio_client = lambda: MagicMock()

# the health-check background thread is irrelevant to the tests
import service.health_check as health_check  # noqa: E402

health_check.start_health_check = lambda *a, **k: None

import app as app_module  # noqa: E402  (imported after the patches above)
from werkzeug.security import generate_password_hash  # noqa: E402


@pytest.fixture
def app_module_fixture():
    """The imported ``app`` module (for monkeypatching module globals)."""
    return app_module


@pytest.fixture(autouse=True)
def _isolate_state():
    """Wipe Mongo and Redis before every test for isolation."""
    db = app_module.mongo["RMN"]
    for name in db.list_collection_names():
        db[name].delete_many({})
    try:
        app_module.redis.flushall()
    except Exception:
        pass
    yield


@pytest.fixture
def client():
    app_module.app.config["TESTING"] = True
    return app_module.app.test_client()


# ---------------------------------------------------------------- helpers ----
def make_user(username="alice", password="pass123", role="Utilisateur"):
    """Insert a user directly (password hashed like the real signup)."""
    app_module.mongo["RMN"]["users"].insert_one(
        {
            "username": username,
            "password": generate_password_hash(password),
            "role": role,
            "saveVerifiedImages": False,
            "moodleStructureInd": True,
        }
    )


def make_job(job_id, owner, status="VALIDATION", **extra):
    doc = {
        "job_id": job_id,
        "user_id": owner,
        "job_name": "test job",
        "job_status": status,
        "bonus_enabled_map": [],
        "n_pages_per_question": [],
        "n_max_points_per_question": [],
        "students_list": [],
    }
    doc.update(extra)
    app_module.mongo["RMN"]["eval_jobs"].insert_one(doc)
    return job_id


@pytest.fixture
def user_factory():
    return make_user


@pytest.fixture
def job_factory():
    return make_job


@pytest.fixture
def login(client):
    def _login(username="alice", password="pass123"):
        resp = client.post("/users/login", data={"username": username, "password": password})
        assert resp.status_code == 200, resp.data
        return resp.get_json(force=True)["response"]["token"]

    return _login
