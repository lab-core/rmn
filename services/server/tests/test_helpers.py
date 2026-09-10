"""Small server helpers: box conversion, zip update and storage paths."""

import os
import zipfile

import pytest

from utils.box_converter import convert_box_to_dict, convert_box_to_list
from utils.storage import Storage
from utils.zip import update_zip


def test_box_round_trip_between_percent_dict_and_ratio_list():
    box = {"x1": 5, "x2": 85, "y1": 15, "y2": 35}
    ratios = convert_box_to_list(box)
    assert ratios == pytest.approx([0.05, 0.85, 0.15, 0.35])
    assert convert_box_to_dict(ratios) == pytest.approx({"x1": 5.0, "x2": 85.0, "y1": 15.0, "y2": 35.0})


def test_box_conversion_rejects_missing_input():
    assert convert_box_to_list(None) is None
    assert convert_box_to_list({}) is None
    assert convert_box_to_list({"x1": None, "x2": 1, "y1": 1, "y2": 1}) is None
    assert convert_box_to_dict(None) is None
    assert convert_box_to_dict([0.1, 0.2, 0.3]) is None


def test_update_zip_adds_files_and_renames_clashes(tmp_path):
    zip_path = tmp_path / "copies.zip"
    with zipfile.ZipFile(zip_path, "w") as z:
        z.writestr("a.pdf", "old-a")
        z.writestr("sub/b.pdf", "b")
    new_a = tmp_path / "new" / "a.pdf"
    new_c = tmp_path / "new" / "c.pdf"
    new_a.parent.mkdir()
    new_a.write_text("new-a")
    new_c.write_text("c")

    update_zip(str(zip_path), [str(new_a), str(new_c)], str(tmp_path / "work"))

    with zipfile.ZipFile(zip_path) as z:
        assert sorted(z.namelist()) == ["a-0.pdf", "a.pdf", "c.pdf", "sub/b.pdf"]
        assert z.read("a.pdf") == b"old-a"
        assert z.read("a-0.pdf") == b"new-a"
    assert not (tmp_path / "work").exists()
    assert not new_a.exists()  # moved, not copied


def test_storage_rel_path(tmp_path):
    storage = Storage(tmp_path)
    assert storage.rel_path(str(tmp_path / "csv" / "j.csv")) == os.path.join("csv", "j.csv")
    assert storage.rel_path("csv/j.csv") == "csv/j.csv"
    # a path from another storage root: keep what follows "storage/"
    assert storage.rel_path("/mnt/nfs/storage/csv/j.csv") == "csv/j.csv"
    assert storage.rel_path("/elsewhere/j.csv") == "/elsewhere/j.csv"


def test_storage_move_and_copy_report_missing_files(tmp_path):
    storage = Storage(tmp_path / "store")
    with pytest.raises(ValueError, match="local file"):
        storage.move_to(str(tmp_path / "missing.pdf"), "documents/j/x.pdf")
    with pytest.raises(ValueError, match="can't find file"):
        storage.copy_from("documents/j/missing.pdf", str(tmp_path / "out.pdf"))


def test_storage_remove_accepts_globs(tmp_path):
    storage = Storage(tmp_path)
    (tmp_path / "output_zip").mkdir()
    for name in ("j_1.zip", "j_2.zip", "k_1.zip"):
        (tmp_path / "output_zip" / name).write_text("x")

    storage.remove("output_zip/j_*.zip")
    storage.remove("output_zip/nothing-here.zip")  # no match: no error

    assert os.listdir(tmp_path / "output_zip") == ["k_1.zip"]
