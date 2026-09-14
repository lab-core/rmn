"""Splitting uploaded copies into a cover page and per-question pdfs."""

import os
import zipfile

import pytest
from pypdf import PdfReader

from utils.split import (
    calculate_total_expected_pages,
    insert_copies,
    split_and_save,
    verify_names_and_n_pages,
)
from rmn_common.status import Document_Status

PAGES = {"Q1": 2, "Q2": 1}  # cover page + 3 question pages = 4 pages per copy


def _n_pages(path):
    return len(PdfReader(str(path)).pages)


def test_total_pages_counts_the_cover_page():
    assert calculate_total_expected_pages({}) == 1
    assert calculate_total_expected_pages(PAGES) == 4
    assert calculate_total_expected_pages({"Q1": 2, "Q2": 0}) == 3  # ignored question


def test_wrong_page_count_goes_to_incorrect_files(tmp_path, storage_root, pdf_factory):
    good = pdf_factory(tmp_path / "good.pdf", 4)
    short = pdf_factory(tmp_path / "short.pdf", 3)
    long_ = pdf_factory(tmp_path / "long.pdf", 6)

    kept, errors = verify_names_and_n_pages(PAGES, [str(good), str(short), str(long_)], "job")

    assert kept == [str(good)]
    assert errors == [
        "Erreur: short.pdf a 1 page manquante.",
        "Erreur: long.pdf a 2 pages de trop.",
    ]
    assert (storage_root / "incorrect_files" / "job" / "short.pdf").exists()
    assert (storage_root / "incorrect_files" / "job" / "long.pdf").exists()
    assert not short.exists()


def test_duplicate_names_are_suffixed(tmp_path, storage_root, pdf_factory):
    # a copy named a.pdf already belongs to the job
    pdf_factory(storage_root / "documents" / "job" / "all" / "a.pdf", 4)
    first = pdf_factory(tmp_path / "a.pdf", 4)
    second = pdf_factory(tmp_path / "sub" / "a.pdf", 4)

    kept, errors = verify_names_and_n_pages(PAGES, [str(first), str(second)], "job")

    assert errors == []
    assert [os.path.basename(p) for p in kept] == ["a-0.pdf", "a-1.pdf"]
    assert all(os.path.exists(p) for p in kept)


def test_unsafe_names_are_sanitised(tmp_path, pdf_factory):
    pdf = pdf_factory(tmp_path / "été 2026 (copie).pdf", 4)
    kept, errors = verify_names_and_n_pages(PAGES, [str(pdf)], "job")
    assert errors == []
    assert os.path.basename(kept[0]) == "ete_2026_copie.pdf"


def test_no_questions_accepts_any_page_count(tmp_path, pdf_factory):
    pdf = pdf_factory(tmp_path / "x.pdf", 7)
    kept, errors = verify_names_and_n_pages({}, [str(pdf)], "job")
    assert kept == [str(pdf)]
    assert errors == []


def test_split_and_save_writes_questions_cover_versions_and_db(
    tmp_path, storage_root, mongo_db, pdf_factory
):
    alice = pdf_factory(tmp_path / "alice.pdf", 4)
    bob = pdf_factory(tmp_path / "bob.pdf", 4)

    generated, errors = split_and_save(PAGES, [str(alice), str(bob)], "job")

    assert errors == []
    assert generated == {
        "Q1": ["documents/job/Q1/alice_Q1.pdf", "documents/job/Q1/bob_Q1.pdf"],
        "Q2": ["documents/job/Q2/alice_Q2.pdf", "documents/job/Q2/bob_Q2.pdf"],
    }
    docs = storage_root / "documents" / "job"
    assert _n_pages(docs / "Q1" / "alice_Q1.pdf") == 2
    assert _n_pages(docs / "Q2" / "alice_Q2.pdf") == 1
    assert _n_pages(storage_root / "cover_pages" / "job" / "alice_cover.pdf") == 1
    # first version kept next to the question, whole copy archived, source consumed
    assert (docs / "Q1" / "versions" / "alice_Q1-0.pdf").exists()
    assert (docs / "all" / "alice.pdf").exists()
    assert not alice.exists()

    records = list(mongo_db["job_documents"].find({"job_id": "job"}).sort("document_index"))
    assert [(d["filename"], d["document_index"]) for d in records] == [("alice", 0), ("bob", 1)]
    assert records[0]["grades"] == [None, None]
    assert records[0]["status"] == Document_Status.NOT_READY.value
    assert records[0]["rel_filepath"] == "cover_pages/job/alice_cover.pdf"
    assert records[0]["matricule"] == ""

    versions = list(mongo_db["versions"].find({"job_id": "job"}))
    assert len(versions) == 4
    assert all(v["version"] == 0 and v["annotations"] == [] for v in versions)
    assert {v["version_filepath"] for v in versions} >= {
        "documents/job/Q1/versions/alice_Q1-0.pdf",
        "documents/job/Q2/versions/bob_Q2-0.pdf",
    }


def test_split_and_save_numbers_after_existing_documents(tmp_path, mongo_db, pdf_factory):
    mongo_db["job_documents"].insert_one({"job_id": "job", "document_index": 0})
    pdf = pdf_factory(tmp_path / "carol.pdf", 4)
    split_and_save(PAGES, [str(pdf)], "job")
    carol = mongo_db["job_documents"].find_one({"filename": "carol"})
    assert carol["document_index"] == 1


def test_ignored_question_gets_no_folder_but_keeps_its_grade_slot(
    tmp_path, storage_root, mongo_db, pdf_factory
):
    pages = {"Q1": 2, "Q2": 0, "Q3": 1}
    pdf = pdf_factory(tmp_path / "alice.pdf", 4)
    generated, errors = split_and_save(pages, [str(pdf)], "job")
    assert errors == []
    assert list(generated) == ["Q1", "Q3"]
    assert not (storage_root / "documents" / "job" / "Q2").exists()
    assert mongo_db["job_documents"].find_one({"job_id": "job"})["grades"] == [None, None, None]


def test_split_and_save_reports_bad_copies_but_keeps_the_good_ones(tmp_path, mongo_db, pdf_factory):
    good = pdf_factory(tmp_path / "good.pdf", 4)
    bad = pdf_factory(tmp_path / "bad.pdf", 2)
    generated, errors = split_and_save(PAGES, [str(good), str(bad)], "job")
    assert len(errors) == 1 and "bad.pdf" in errors[0]
    assert generated["Q1"] == ["documents/job/Q1/good_Q1.pdf"]
    assert mongo_db["job_documents"].count_documents({"job_id": "job"}) == 1


def _zip_with(zip_path, pdfs, junk=True):
    zip_path.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path, "w") as z:
        for pdf in pdfs:
            z.write(pdf, os.path.basename(pdf))
        if junk:
            z.writestr("__MACOSX/._alice.pdf", "junk")
            z.writestr("notes.txt", "junk")
            z.writestr(".hidden.pdf", "junk")


def test_insert_copies_reads_the_zips_and_records_the_questions(
    tmp_path, storage_root, mongo_db, pdf_factory
):
    alice = pdf_factory(tmp_path / "alice.pdf", 4)
    zip_path = storage_root / "zips" / "job" / "upload.zip"
    _zip_with(zip_path, [alice])

    insert_copies("zips/job", "job", PAGES, tmp_path / "tmp")

    questions = list(mongo_db["job_questions"].find({"job_id": "job"}).sort("document_index"))
    assert [(q["question"], q["question_index"], q["filename"], q["basename"]) for q in questions] == [
        ("Q1", 1, "alice_Q1", "alice"),
        ("Q2", 2, "alice_Q2", "alice"),
    ]
    assert questions[0]["status"] == Document_Status.TO_VALIDATE.value
    assert questions[0]["rel_filepath"] == "documents/job/Q1/alice_Q1.pdf"
    assert questions[0]["grade"] is None
    assert mongo_db["job_documents"].count_documents({"job_id": "job"}) == 1
    # the zip is consumed and the extraction folder cleaned up
    assert not zip_path.exists()
    assert not (tmp_path / "tmp" / "extracted").exists()


def test_insert_copies_raises_after_saving_the_valid_copies(
    tmp_path, storage_root, mongo_db, pdf_factory
):
    good = pdf_factory(tmp_path / "good.pdf", 4)
    bad = pdf_factory(tmp_path / "bad.pdf", 3)
    _zip_with(storage_root / "zips" / "job" / "upload.zip", [good, bad], junk=False)

    with pytest.raises(ValueError) as exc:
        insert_copies("zips/job", "job", PAGES, tmp_path / "tmp")

    assert "bad.pdf a 1 page manquante" in str(exc.value)
    assert mongo_db["job_questions"].count_documents({"job_id": "job"}) == 2
    assert (storage_root / "incorrect_files" / "job" / "bad.pdf").exists()
