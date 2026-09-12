"""The executor's Storage is the shared one plus the recognition cleanup."""

import os

from rmn_common.storage import Storage as SharedStorage

from utils.storage import Storage


def _touch(path, content="x"):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(content)


def test_executor_storage_is_the_shared_storage():
    assert issubclass(Storage, SharedStorage)


def test_storage_env_var_selects_the_root(storage_root):
    assert Storage().path == storage_root


def test_clean_storage_tolerates_missing_folders(tmp_path):
    root = str(tmp_path)
    _touch(os.path.join(root, "documents", "j", "Q1", "a.pdf"))
    _touch(os.path.join(root, "incorrect_files", "j", "bad.pdf"))
    storage = Storage(root)
    storage.clean_storage("nope")  # nothing to do, must not raise
    storage.clean_storage("j")  # no cover_pages folder for this job
    assert not (tmp_path / "documents" / "j").exists()
    assert not (tmp_path / "incorrect_files" / "j").exists()
