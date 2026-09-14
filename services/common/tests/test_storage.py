"""Storage: paths under the root, moves, copies and per-job cleanup."""

import os

import pytest

from rmn_common.storage import Storage


def _touch(path, content="x"):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(content)


def _build_job(root, job_id):
    _touch(os.path.join(root, "documents", job_id, "Q1", "c_Q1.pdf"))
    _touch(os.path.join(root, "documents", job_id, "all", "c.pdf"))
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


def test_root_comes_from_the_argument_the_environment_or_the_default(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("STORAGE", str(tmp_path / "env"))
    assert Storage(tmp_path / "arg").path == tmp_path / "arg"
    assert Storage().path == tmp_path / "env"
    monkeypatch.delenv("STORAGE")
    with pytest.raises(ValueError):
        Storage()

    class WithDefault(Storage):
        default_path = tmp_path / "default"

    assert WithDefault().path == tmp_path / "default"


def test_abs_path_joins_the_root_and_keeps_absolute_paths(tmp_path):
    storage = Storage(tmp_path)
    assert storage.abs_path("documents/j/a.pdf") == str(
        tmp_path / "documents" / "j" / "a.pdf"
    )
    assert storage.abs_path("/elsewhere/a.pdf") == "/elsewhere/a.pdf"
    assert storage.rel_path(str(tmp_path / "csv" / "j.csv")) == os.path.join(
        "csv", "j.csv"
    )


def test_move_to_creates_the_tree_and_removes_the_source(tmp_path):
    storage = Storage(tmp_path / "store")
    src = tmp_path / "in.pdf"
    _touch(str(src), "pdf")
    dest = storage.move_to(str(src), "documents/j/in.pdf")
    assert dest == str(tmp_path / "store" / "documents" / "j" / "in.pdf")
    assert not src.exists()
    assert (tmp_path / "store" / "documents" / "j" / "in.pdf").read_text() == "pdf"
    with pytest.raises(ValueError):
        storage.move_to(str(src), "documents/j/in.pdf")


def test_copy_from_keeps_the_stored_file(tmp_path):
    storage = Storage(tmp_path / "store")
    _touch(str(tmp_path / "store" / "csv" / "j.csv"), "a,b")
    dest = tmp_path / "out" / "deep" / "j.csv"
    storage.copy_from("csv/j.csv", str(dest))
    assert dest.read_text() == "a,b"
    assert (tmp_path / "store" / "csv" / "j.csv").exists()
    with pytest.raises(ValueError):
        storage.copy_from("csv/missing.csv", str(dest))


def test_remove_and_remove_tree_tolerate_missing_paths(tmp_path):
    storage = Storage(tmp_path)
    _touch(str(tmp_path / "csv" / "j.csv"))
    _touch(str(tmp_path / "documents" / "j" / "Q1" / "a.pdf"))
    storage.remove("csv/j.csv")
    storage.remove_tree("documents/j")
    assert not (tmp_path / "csv" / "j.csv").exists()
    assert not (tmp_path / "documents" / "j").exists()
    storage.remove("csv/j.csv")  # already gone: no error
    storage.remove_tree("documents/j")


def test_remove_job_deletes_all_job_paths_and_nothing_else(tmp_path):
    root = str(tmp_path)
    _build_job(root, "job-A")
    _build_job(root, "job-B")
    _touch(os.path.join(root, "numbers", "7", "abc.png"))  # shared training data
    _touch(os.path.join(root, "output_zip", "unrelated.zip"))

    Storage(root).remove_job("job-A")

    remaining = sorted(
        os.path.relpath(os.path.join(d, f), root)
        for d, _, files in os.walk(root)
        for f in files
    )
    assert not any("job-A" in p for p in remaining)
    assert len([p for p in remaining if "job-B" in p]) == 13
    assert "numbers/7/abc.png" in remaining
    assert "output_zip/unrelated.zip" in remaining

    Storage(root).remove_job("job-A")  # idempotent
    Storage(root).remove_job("never-existed")
