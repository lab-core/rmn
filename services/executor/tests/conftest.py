"""Test harness for the executor.

The tests cover the pure helpers and the pieces that touch storage and
MongoDB. The storage root is a temporary directory (``STORAGE``), MongoDB is
``mongomock`` (patched into ``utils.clients`` BEFORE any executor module is
imported, since the modules create their ``Storage``/``Database`` at import
time) and matplotlib draws off-screen. No Redis, Socket.IO or TensorFlow is
needed: the Keras model is only loaded inside the recognition functions, which
are not exercised here.
"""

import atexit
import os
import shutil
import sys
import tempfile
from pathlib import Path

import pytest

EXECUTOR_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(EXECUTOR_DIR))
sys.path.insert(0, str(EXECUTOR_DIR / "python"))

# --- configure the environment BEFORE importing any executor module ---
_STORAGE = Path(tempfile.mkdtemp(prefix="rmn-executor-tests-"))
os.environ["STORAGE"] = str(_STORAGE)
os.environ.setdefault("MPLBACKEND", "Agg")
atexit.register(shutil.rmtree, _STORAGE, True)

import mongomock  # noqa: E402
import utils.clients as clients  # noqa: E402

_MONGO = mongomock.MongoClient()
clients.mongo_client = lambda: _MONGO

from pypdf import PdfWriter  # noqa: E402


@pytest.fixture(autouse=True)
def _isolate_state():
    """Empty the storage root and Mongo before every test."""
    for child in _STORAGE.iterdir():
        if child.is_dir():
            shutil.rmtree(child, ignore_errors=True)
        else:
            child.unlink()
    db = _MONGO["RMN"]
    for name in db.list_collection_names():
        db[name].delete_many({})
    yield


@pytest.fixture
def storage_root():
    """The temporary storage root the executor modules were imported with."""
    return _STORAGE


@pytest.fixture
def mongo_db():
    """The in-memory ``RMN`` database."""
    return _MONGO["RMN"]


def make_pdf(path, n_pages=1):
    """Write a pdf of ``n_pages`` blank US-letter pages at ``path``."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    writer = PdfWriter()
    for _ in range(n_pages):
        writer.add_blank_page(width=612, height=792)
    with open(path, "wb") as f:
        writer.write(f)
    return path


@pytest.fixture
def pdf_factory():
    return make_pdf
