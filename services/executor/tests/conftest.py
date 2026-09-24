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
from collections.abc import Callable
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


RECOGNITION_FIXTURES = Path(__file__).resolve().parent / "fixtures" / "recognition"


def make_scanned_copy(
    path: str | Path, crops: list[tuple[str, list[float]]], n_question_pages: int = 0
) -> Path:
    """Write a copy whose cover page carries real scanned boxes.

    ``crops`` are ``(fixture file, box)`` couples: each crop of
    ``fixtures/recognition`` is pasted at its box on a blank 300 dpi letter
    page, as in ``test_recognition``. ``n_question_pages`` blank pages follow
    the cover page.
    """
    import io

    import cv2
    import img2pdf
    import numpy as np
    from pypdf import PdfReader

    width, height = 2550, 3300
    page = np.full((height, width), 255, np.uint8)
    for crop_file, box in crops:
        crop = cv2.imread(str(RECOGNITION_FIXTURES / crop_file), cv2.IMREAD_GRAYSCALE)
        assert crop is not None, crop_file
        x1, y1 = int(box[0] * width), int(box[2] * height)
        x2, y2 = x1 + crop.shape[1], y1 + crop.shape[0]
        page[y1:y2, x1:x2] = crop
    ok, png = cv2.imencode(".png", page)
    assert ok
    cover = img2pdf.convert(
        png.tobytes(), layout_fun=img2pdf.get_fixed_dpi_layout_fun((300, 300))
    )

    writer = PdfWriter()
    writer.append(PdfReader(io.BytesIO(cover)))
    for _ in range(n_question_pages):
        writer.add_blank_page(width=612, height=792)
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "wb") as f:
        writer.write(f)
    return path


@pytest.fixture
def scanned_copy_factory() -> Callable[..., Path]:
    """``make_scanned_copy``, as a fixture."""
    return make_scanned_copy
