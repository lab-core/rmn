"""Storage: paths under the storage root, moves, copies and per-job cleanup."""

import os

from utils.storage import Storage


def _touch(path, content="x"):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(content)


def _build_job(root, job_id):
    _touch(os.path.join(root, "documents", job_id, "Q1", "c_Q1.pdf"))
    _touch(os.path.join(root, "documents", job_id, "all", "c.pdf"))
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


def test_abs_path_joins_the_root(tmp_path):
    storage = Storage(tmp_path)
    assert storage.abs_path("documents/j/a.pdf") == str(tmp_path / "documents" / "j" / "a.pdf")


def test_storage_env_var_selects_the_root(storage_root):
    assert Storage().path == storage_root


def test_move_to_creates_the_tree_and_removes_the_source(tmp_path):
    storage = Storage(tmp_path / "store")
    src = tmp_path / "in.pdf"
    _touch(str(src), "pdf")
    storage.move_to(str(src), "documents/j/in.pdf")
    assert not src.exists()
    assert (tmp_path / "store" / "documents" / "j" / "in.pdf").read_text() == "pdf"


def test_copy_from_keeps_the_stored_file(tmp_path):
    storage = Storage(tmp_path / "store")
    _touch(str(tmp_path / "store" / "csv" / "j.csv"), "a,b")
    dest = tmp_path / "out" / "deep" / "j.csv"
    storage.copy_from("csv/j.csv", str(dest))
    assert dest.read_text() == "a,b"
    assert (tmp_path / "store" / "csv" / "j.csv").exists()


def test_remove_and_remove_tree(tmp_path):
    storage = Storage(tmp_path)
    _touch(str(tmp_path / "csv" / "j.csv"))
    _touch(str(tmp_path / "documents" / "j" / "Q1" / "a.pdf"))
    storage.remove("csv/j.csv")
    storage.remove_tree("documents/j")
    assert not (tmp_path / "csv" / "j.csv").exists()
    assert not (tmp_path / "documents" / "j").exists()


def test_remove_job_only_touches_that_job(tmp_path):
    root = str(tmp_path)
    _build_job(root, "job1")
    _build_job(root, "job2")
    _touch(os.path.join(root, "numbers", "7", "x.png"))  # shared training data

    Storage(root).remove_job("job1")

    remaining = sorted(
        os.path.relpath(os.path.join(d, f), root)
        for d, _, files in os.walk(root)
        for f in files
    )
    assert not any("job1" in p for p in remaining)
    assert len([p for p in remaining if "job2" in p]) == 12
    assert "numbers/7/x.png" in remaining

    # idempotent
    Storage(root).remove_job("job1")


def test_clean_storage_tolerates_missing_folders(tmp_path):
    root = str(tmp_path)
    _touch(os.path.join(root, "documents", "j", "Q1", "a.pdf"))
    _touch(os.path.join(root, "incorrect_files", "j", "bad.pdf"))
    storage = Storage(root)
    storage.clean_storage("nope")  # nothing to do, must not raise
    storage.clean_storage("j")  # no cover_pages folder for this job
    assert not (tmp_path / "documents" / "j").exists()
    assert not (tmp_path / "incorrect_files" / "j").exists()
