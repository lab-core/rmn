"""Writing the grades on the cover pages (process_writing)."""

import shutil

from PIL import Image

from process_copy import add_grades as module


def test_a_failed_overlay_keeps_the_original_cover_page(mongo_db, storage_root, pdf_factory, monkeypatch):
    mongo_db["template"].insert_one({"template_id": "front", "grade_box": [0.1, 0.9, 0.6, 0.9]})
    for index, name in ((0, "a"), (1, "b")):
        pdf_factory(storage_root / "documents" / "job" / "all" / f"{name}.pdf")
        mongo_db["job_documents"].insert_one(
            {"job_id": "job", "document_index": index, "status": "VALIDATED", "grades": [4],
             "rel_filepath": f"documents/job/all/{name}.pdf"}
        )
    original_b = (storage_root / "documents" / "job" / "all" / "b.pdf").read_bytes()

    def fake_add_grades(grades, pdf_path, box, img_path, add_border, shape):
        if pdf_path.endswith("a_nograde.pdf"):
            Image.new("RGB", (20, 30), "white").save(img_path)
            return
        raise RuntimeError("box not found")  # copy b: the scratch image still holds copy a

    monkeypatch.setattr(module, "add_grades", fake_add_grades)
    tmp_dir = storage_root / "tmp"
    tmp_dir.mkdir()
    job = {"job_id": "job", "front_template_id": "front", "regular_template_id": None,
           "n_pages_per_question": [["Q1", 2]]}

    failed = module.process_writing(job, tmp_dir, dpi=72)

    assert failed == [1]
    rewritten = (storage_root / "documents" / "job" / "all" / "a.pdf").read_bytes()
    assert rewritten.startswith(b"%PDF") and rewritten != original_b
    # copy b keeps its own cover page instead of receiving copy a's
    assert (storage_root / "documents" / "job" / "all" / "b.pdf").read_bytes() == original_b
    shutil.rmtree(tmp_dir)
