"""Unit tests for Storage.remove_job (targeted per-job deletion)."""

import os

from utils.storage import Storage


def _touch(path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write("x")


def _build_job(root, job_id):
    _touch(os.path.join(root, "documents", job_id, "Q1", "c_Q1.pdf"))
    _touch(os.path.join(root, "documents", job_id, "versions", "c_Q1-0.pdf"))
    _touch(os.path.join(root, "cover_pages", job_id, "c_cover.pdf"))
    _touch(os.path.join(root, "corrected_copies", job_id, "c.pdf"))
    _touch(os.path.join(root, "incorrect_files", job_id, "bad.pdf"))
    _touch(os.path.join(root, "zips", job_id, "u.zip"))
    _touch(os.path.join(root, "unverified_numbers", job_id, "0", "0.png"))
    _touch(os.path.join(root, "csv", f"{job_id}.csv"))
    _touch(os.path.join(root, "output_csv", f"{job_id}.csv"))
    _touch(os.path.join(root, "output_stats", f"{job_id}.pdf"))
    _touch(os.path.join(root, "output_zip", f"{job_id}_all.zip"))
    _touch(os.path.join(root, "output_zip", f"{job_id}_1.zip"))


def test_remove_job_deletes_all_job_paths(tmp_path):
    root = str(tmp_path)
    storage = Storage(storage_path=root)
    _build_job(root, "job-A")

    storage.remove_job("job-A")

    for prefix in ("documents", "cover_pages", "corrected_copies",
                   "incorrect_files", "zips", "unverified_numbers"):
        assert not os.path.exists(os.path.join(root, prefix, "job-A"))
    assert not os.path.exists(os.path.join(root, "csv", "job-A.csv"))
    assert not os.path.exists(os.path.join(root, "output_csv", "job-A.csv"))
    assert not os.path.exists(os.path.join(root, "output_stats", "job-A.pdf"))
    assert not os.path.exists(os.path.join(root, "output_zip", "job-A_all.zip"))
    assert not os.path.exists(os.path.join(root, "output_zip", "job-A_1.zip"))


def test_remove_job_leaves_other_jobs_and_shared_data(tmp_path):
    root = str(tmp_path)
    storage = Storage(storage_path=root)
    _build_job(root, "job-A")
    _build_job(root, "job-B")
    # shared / static data that must never be touched
    _touch(os.path.join(root, "numbers", "7", "abc.png"))
    _touch(os.path.join(root, "output_zip", "unrelated.zip"))

    storage.remove_job("job-A")

    assert os.path.exists(os.path.join(root, "documents", "job-B", "Q1", "c_Q1.pdf"))
    assert os.path.exists(os.path.join(root, "csv", "job-B.csv"))
    assert os.path.exists(os.path.join(root, "output_zip", "job-B_all.zip"))
    assert os.path.exists(os.path.join(root, "numbers", "7", "abc.png"))
    assert os.path.exists(os.path.join(root, "output_zip", "unrelated.zip"))


def test_remove_job_is_idempotent(tmp_path):
    storage = Storage(storage_path=str(tmp_path))
    # deleting a job with nothing on disk must not raise
    storage.remove_job("never-existed")
