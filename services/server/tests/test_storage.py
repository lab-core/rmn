"""The server's Storage is the shared one, rooted next to the server by default."""

import os

from rmn_common.storage import Storage as SharedStorage

from utils.storage import ROOT_DIR, Storage


def test_server_storage_is_the_shared_storage_with_a_local_default(monkeypatch):
    assert issubclass(Storage, SharedStorage)
    monkeypatch.delenv("STORAGE", raising=False)
    assert Storage().path == ROOT_DIR.joinpath("storage")
    assert ROOT_DIR.joinpath("app.py").exists()


def test_remove_job_is_the_shared_layout(tmp_path):
    storage = Storage(storage_path=str(tmp_path))
    path = tmp_path / "output_csv" / "job-A.csv"
    os.makedirs(path.parent)
    path.write_text("x")
    storage.remove_job("job-A")
    assert not path.exists()
