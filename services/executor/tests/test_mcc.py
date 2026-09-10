"""Moodle helpers: grade csv loading, group detection, file copies and batch zips."""

import os
import zipfile

import pandas as pd

from process_copy import mcc
from process_copy.config import MoodleFields as MF


def _write_csv(path, rows):
    pd.DataFrame(rows).to_csv(path, index=False)
    return str(path)


def test_load_csv_indexes_by_matricule_as_text_and_drops_duplicates(tmp_path):
    csv = _write_csv(
        tmp_path / "grades.csv",
        [
            {MF.mat: 1234567, MF.name: "Alice A"},
            {MF.mat: 1234567, MF.name: "Alice A"},
            {MF.mat: 2345678, MF.name: "Bob B"},
        ],
    )

    dfs, names = mcc.load_csv([csv])

    assert names == ["grades"]
    assert list(dfs[0].index) == ["1234567", "2345678"]
    assert dfs[0].at["2345678", MF.name] == "Bob B"
    # the duplicate is removed from the file too
    assert len(pd.read_csv(csv)) == 2


def test_group_label_matches_moodle_group_columns():
    assert mcc.group_label(pd.DataFrame(columns=[MF.mat, "Groupe", MF.name])) == "Groupe"
    assert mcc.group_label(pd.DataFrame(columns=[MF.mat, "Section GR"])) == "Section GR"
    assert mcc.group_label(pd.DataFrame(columns=[MF.mat, "Groupes"])) == "Groupes"
    assert mcc.group_label(pd.DataFrame(columns=[MF.mat, "Grade"])) is None
    assert mcc.group_label(pd.DataFrame(columns=[MF.mat, MF.name])) is None


def test_get_name_searches_every_grade_file(tmp_path):
    a = _write_csv(tmp_path / "a.csv", [{MF.mat: 1234567, MF.name: "Alice A"}])
    b = _write_csv(tmp_path / "b.csv", [{MF.mat: 2345678, MF.name: "Bob B"}])
    dfs, _ = mcc.load_csv([a, b])
    assert mcc.get_name("1234567", dfs) == (0, "Alice A")
    assert mcc.get_name("2345678", dfs) == (1, "Bob B")
    assert mcc.get_name("9999999", dfs) == (-1, None)


def test_copy_file_to_a_folder_or_to_a_new_name(tmp_path):
    src = tmp_path / "src.pdf"
    src.write_text("pdf")

    mcc.copy_file(str(src), str(tmp_path / "out"))
    mcc.copy_file(str(src), str(tmp_path / "out2" / "renamed.pdf"))

    assert (tmp_path / "out" / "src.pdf").read_text() == "pdf"
    assert (tmp_path / "out2" / "renamed.pdf").read_text() == "pdf"
    assert src.exists()


def test_zipdirbatch_splits_by_size_and_consumes_the_files(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    src = tmp_path / "moodle_files"
    src.mkdir()
    for i in range(3):
        (src / f"copy{i}.pdf").write_bytes(os.urandom(mcc.MB))  # 1 MiB each

    zips = mcc.zipdirbatch(str(src), archive="moodle", batch=2)

    assert zips == ["moodle.zip", "moodle1.zip"]
    names = [sorted(zipfile.ZipFile(z).namelist()) for z in zips]
    assert [len(n) for n in names] == [2, 1]
    assert sorted(sum(names, [])) == ["copy0.pdf", "copy1.pdf", "copy2.pdf"]
    assert os.listdir(src) == []


def test_zipdirbatch_keeps_relative_paths_and_one_archive_without_batch(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    src = tmp_path / "moodle_files"
    (src / "sub").mkdir(parents=True)
    (src / "sub" / "a.pdf").write_text("a")
    (src / "b.pdf").write_text("b")

    zips = mcc.zipdirbatch(str(src))

    assert zips == ["moodle.zip"]
    assert sorted(zipfile.ZipFile("moodle.zip").namelist()) == ["b.pdf", "sub/a.pdf"]


def test_zipdirbatch_of_an_empty_folder_creates_nothing(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "empty").mkdir()
    assert mcc.zipdirbatch(str(tmp_path / "empty")) == []
    assert not (tmp_path / "moodle.zip").exists()
