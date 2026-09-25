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
    _touch(os.path.join(root, "digit_bank", "staged", job_id, "0", "r.npz"))
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


def test_abs_path_joins_the_root_and_keeps_absolute_paths_under_it(tmp_path):
    storage = Storage(tmp_path)
    assert storage.abs_path("documents/j/a.pdf") == str(
        tmp_path / "documents" / "j" / "a.pdf"
    )
    inside = str(tmp_path / "csv" / "j.csv")
    assert storage.abs_path(inside) == inside
    assert storage.abs_path("") == str(tmp_path) + os.sep
    assert storage.abs_path("output_zip/j_*.zip").endswith("j_*.zip")  # globs pass


@pytest.mark.parametrize(
    "path",
    ["/elsewhere/a.pdf", "../a.pdf", "documents/../../a.pdf", "documents/j/../../../x"],
)
def test_abs_path_refuses_paths_that_leave_the_root(tmp_path, path):
    # every storage read and write resolves its path here
    storage = Storage(tmp_path)
    with pytest.raises(ValueError):
        storage.abs_path(path)
    with pytest.raises(ValueError):
        storage.copy_from(path, tmp_path / "out")


def test_rel_path(tmp_path):
    storage = Storage(tmp_path)
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
    assert len([p for p in remaining if "job-B" in p]) == 14
    assert "numbers/7/abc.png" in remaining
    assert "output_zip/unrelated.zip" in remaining

    Storage(root).remove_job("job-A")  # idempotent
    Storage(root).remove_job("never-existed")


def test_the_digits_a_job_contributed_outlive_it(tmp_path):
    """Staged crops belong to the job; a labelled sample belongs to the bank.

    The samples are what the recogniser is retrained on, so deleting the job
    they were cut from -- or the sweep that removes an orphan -- must not take
    them (``process_copy.digit_bank``).
    """
    root = str(tmp_path)
    _build_job(root, "job-A")
    _touch(os.path.join(root, "digit_bank", "samples", "7", "abc.png"))
    _touch(os.path.join(root, "digit_bank", "index.jsonl"))

    Storage(root).remove_job("job-A")

    assert not os.path.exists(os.path.join(root, "digit_bank", "staged", "job-A"))
    assert os.path.exists(os.path.join(root, "digit_bank", "samples", "7", "abc.png"))
    assert os.path.exists(os.path.join(root, "digit_bank", "index.jsonl"))
    owned = [path for _job, path in Storage(root).job_entries()]
    assert not any("samples" in p for p in owned)


def test_corpus_usage_counts_each_corpus_directory(tmp_path):
    root = str(tmp_path)
    _touch(os.path.join(root, "digit_bank", "samples", "7", "a.png"), "aa")
    _touch(os.path.join(root, "digit_bank", "samples", "3", "b.png"), "b")
    _touch(os.path.join(root, "digit_bank", "staged", "job", "0", "r.npz"), "xxxx")
    _touch(os.path.join(root, "numbers", "0", "c.png"), "ccc")

    usage = Storage(root).corpus_usage()

    # the staged crops are not corpus: they belong to a job and die with it
    assert usage == {
        os.path.join("digit_bank", "samples"): {"bytes": 3, "files": 2},
        "numbers": {"bytes": 3, "files": 1},
    }
    assert Storage(tmp_path / "empty").corpus_usage() == {}


def test_the_corpus_is_never_a_stray(tmp_path):
    """``stray_entries`` drives a delete, so it must not reach the corpus."""
    root = str(tmp_path)
    _build_job(root, "job-A")
    _touch(os.path.join(root, "digit_bank", "samples", "7", "a.png"))
    _touch(os.path.join(root, "digit_bank", "index.jsonl"))
    _touch(os.path.join(root, "numbers", "7", "b.png"))

    strays = list(Storage(root).stray_entries())

    assert not any("samples" in s or "numbers" in s or "index" in s for s in strays)


def test_rel_path_of_a_relative_or_foreign_path(tmp_path):
    storage = Storage(tmp_path / "store")
    assert storage.rel_path("csv/j.csv") == "csv/j.csv"
    # a path recorded under another mount of the tree keeps its layout part
    assert storage.rel_path("/mnt/old/storage/csv/j.csv") == "csv/j.csv"
    assert storage.rel_path("/elsewhere/j.csv") == "/elsewhere/j.csv"


def test_remove_job_tolerates_a_directory_named_like_one_of_its_files(tmp_path):
    root = str(tmp_path)
    os.makedirs(os.path.join(root, "output_zip", "job-A_odd.zip"))
    _touch(os.path.join(root, "output_zip", "job-A_all.zip"))
    Storage(root).remove_job("job-A")
    assert os.listdir(os.path.join(root, "output_zip")) == ["job-A_odd.zip"]


def test_job_entries_name_the_owner_of_every_job_path(tmp_path):
    root = str(tmp_path)
    _build_job(root, "job-A")
    _touch(os.path.join(root, "output_zip", "nounderscore.zip"))  # no job id
    _touch(os.path.join(root, "csv", "notes.txt"))  # not a job file
    _touch(os.path.join(root, "documents", "loose.pdf"))  # not a job directory

    entries = sorted(
        (job, os.path.relpath(path, root)) for job, path in Storage(root).job_entries()
    )

    assert entries == sorted(
        [
            ("job-A", os.path.join("documents", "job-A")),
            ("job-A", os.path.join("cover_pages", "job-A")),
            ("job-A", os.path.join("corrected_copies", "job-A")),
            ("job-A", os.path.join("incorrect_files", "job-A")),
            ("job-A", os.path.join("zips", "job-A")),
            ("job-A", os.path.join("unverified_numbers", "job-A")),
            ("job-A", os.path.join("digit_bank", "staged", "job-A")),
            ("job-A", os.path.join("csv", "job-A.csv")),
            ("job-A", os.path.join("output_csv", "job-A.csv")),
            ("job-A", os.path.join("output_stats", "job-A.pdf")),
            ("job-A", os.path.join("output_zip", "job-A_all.zip")),
            ("job-A", os.path.join("output_zip", "job-A_1.zip")),
        ]
    )


def test_an_empty_storage_has_no_entries(tmp_path):
    storage = Storage(tmp_path)
    # a file where a prefix directory is expected holds nothing either
    _touch(str(tmp_path / "template"))
    assert list(storage.job_entries()) == []
    assert list(storage.template_entries()) == []
    assert list(storage.stray_entries()) == []


def test_template_entries_are_the_files_of_the_template_folder(tmp_path):
    root = str(tmp_path)
    _touch(os.path.join(root, "template", "t1.png"))
    os.makedirs(os.path.join(root, "template", "subdir"))
    assert list(Storage(root).template_entries()) == [
        (os.path.join("template", "t1.png"), os.path.join(root, "template", "t1.png"))
    ]


def test_stray_entries_are_what_the_layout_does_not_name(tmp_path):
    root = str(tmp_path)
    _build_job(root, "job-A")
    _touch(os.path.join(root, "template", "t1.png"))
    _touch(os.path.join(root, "csv", "notes.txt"))
    _touch(os.path.join(root, "documents", "loose.pdf"))
    # the shared digit corpus belongs to no row and is never a stray
    _touch(os.path.join(root, "numbers", "7", "abc.png"))

    strays = sorted(os.path.relpath(p, root) for p in Storage(root).stray_entries())

    assert strays == [
        os.path.join("csv", "notes.txt"),
        os.path.join("documents", "loose.pdf"),
    ]


def test_remove_all_match_walks_the_whole_tree(tmp_path):
    root = str(tmp_path)
    _build_job(root, "job-A")
    _build_job(root, "job-B")

    Storage(root).remove_all_match("job-A")

    remaining = [os.path.join(d, f) for d, _, files in os.walk(root) for f in files]
    assert remaining and not any("job-A" in p for p in remaining)
    assert all("job-B" in p for p in remaining)


def test_copy_inside_duplicates_a_stored_file(tmp_path):
    """A task created from another one copies its files rather than sharing
    them: deleting either task must take only its own."""
    root = str(tmp_path)
    _touch(os.path.join(root, "zips", "job-A", "a.zip"), "copies")
    storage = Storage(root)

    written = storage.copy_inside(
        os.path.join("zips", "job-A", "a.zip"), os.path.join("zips", "job-B", "b.zip")
    )

    assert open(written).read() == "copies"
    assert os.path.exists(os.path.join(root, "zips", "job-A", "a.zip"))
    storage.remove_job("job-B")
    assert os.path.exists(os.path.join(root, "zips", "job-A", "a.zip"))


def test_copy_inside_refuses_a_missing_source_or_a_path_outside_the_root(tmp_path):
    storage = Storage(tmp_path)
    with pytest.raises(ValueError):
        storage.copy_inside("zips/none.zip", "zips/copy.zip")
    _touch(str(tmp_path / "zips" / "a.zip"), "x")
    with pytest.raises(ValueError):
        storage.copy_inside("zips/a.zip", "../escaped.zip")
