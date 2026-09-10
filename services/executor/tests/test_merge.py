"""Re-assembling the corrected copies from the cover page and question pdfs."""

import os

from pypdf import PdfReader

from utils.merge import find_files_with_base_name, merge_pdfs_by_base_name, process_merge


def _touch(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("x")


def test_find_files_with_base_name_filters_prefix_and_suffix(tmp_path):
    for name in ["alice_Q1.pdf", "alice_Q2.PDF", "alicia_Q1.pdf", "alice_Q1.txt"]:
        _touch(tmp_path / "a" / name)
    _touch(tmp_path / "b" / "alice_Q3.pdf")

    found = find_files_with_base_name("alice", [tmp_path / "a", tmp_path / "b"], ".pdf")

    # prefix match on the name, case-insensitive match on the suffix
    assert sorted(os.path.basename(f) for f in found) == ["alice_Q1.pdf", "alice_Q2.PDF", "alice_Q3.pdf"]


def test_merge_pdfs_concatenates_the_parts_in_order(tmp_path, pdf_factory):
    cover, q1, q2, out = (tmp_path / d for d in ("cover", "q1", "q2", "out"))
    pdf_factory(cover / "alice_cover.pdf", 1)
    pdf_factory(q1 / "alice_Q1.pdf", 2)
    pdf_factory(q2 / "alice_Q2.pdf", 1)
    pdf_factory(cover / "bob_cover.pdf", 1)
    pdf_factory(q1 / "bob_Q1.pdf", 2)
    pdf_factory(q2 / "bob_Q2.pdf", 1)

    parts = [(str(cover), "_cover.pdf"), (str(q1), "_Q1.pdf"), (str(q2), "_Q2.pdf")]
    merge_pdfs_by_base_name(["alice", "bob"], parts, str(out))

    assert sorted(os.listdir(out)) == ["alice.pdf", "bob.pdf"]
    assert len(PdfReader(str(out / "alice.pdf")).pages) == 4


def test_process_merge_skips_deleted_documents_and_ignored_questions(
    storage_root, mongo_db, pdf_factory
):
    job = {"job_id": "job", "n_pages_per_question": [["Q1", 1], ["Q2", 0]]}
    for name in ("alice", "bob"):
        pdf_factory(storage_root / "cover_pages" / "job" / f"{name}_cover.pdf", 1)
        pdf_factory(storage_root / "documents" / "job" / "Q1" / f"{name}_Q1.pdf", 2)
    mongo_db["job_documents"].insert_many(
        [
            {"job_id": "job", "filename": "alice", "status": "VALIDATED"},
            {"job_id": "job", "filename": "bob", "status": "DELETED"},
            {"job_id": "other", "filename": "carol", "status": "VALIDATED"},
        ]
    )

    out = process_merge(job)

    assert out == str(storage_root / "corrected_copies" / "job")
    assert sorted(os.listdir(out)) == ["alice.pdf"]
    assert len(PdfReader(os.path.join(out, "alice.pdf")).pages) == 3
