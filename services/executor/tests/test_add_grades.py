"""Writing the grades on the cover pages (process_writing)."""

import shutil

import numpy as np
import pytest

from PIL import Image

from process_copy import add_grades as module
from process_copy.batching import FinishedBatch, InlineBatches


class Killed(BaseException):
    """What a kernel kill looks like from inside a batch: not an Exception,
    so the per-copy error handling of write_cover_page does not swallow it."""


class KilledBatches(InlineBatches):
    """Batches that die where the copy raises Killed."""

    def start(self, target, args):
        try:
            return super().start(target, args)
        except Killed:
            return FinishedBatch(-9)


def _overlay_written(img_path):
    Image.new("RGB", (20, 30), "white").save(img_path)


def _job_with_copies(mongo_db, storage_root, pdf_factory, names):
    mongo_db["template"].insert_one({"template_id": "front", "grade_box": [0.1, 0.9, 0.6, 0.9]})
    for index, name in enumerate(names):
        pdf_factory(storage_root / "cover_pages" / "job" / f"{name}_cover.pdf")
        mongo_db["job_documents"].insert_one(
            {
                "job_id": "job",
                "document_index": index,
                "status": "VALIDATED",
                "grades": [4],
                "rel_filepath": f"cover_pages/job/{name}_cover.pdf",
            }
        )
    return {
        "job_id": "job",
        "front_template_id": "front",
        "regular_template_id": None,
        "n_pages_per_question": [["Q1", 2]],
    }


def _scan(storage_root, name):
    return storage_root / "cover_pages" / "job" / f"{name}_cover.pdf"


def _graded(storage_root, name):
    return storage_root / "cover_pages" / "job" / "graded" / f"{name}_cover.pdf"


def test_the_graded_page_is_written_beside_the_scan_not_over_it(
        mongo_db, storage_root, pdf_factory, monkeypatch, tmp_path):
    # finalizing used to overwrite the cover page and keep the scan as
    # _cover_nograde.pdf, so the validation screen showed the grades and a
    # rerun read back what the previous run had written
    job = _job_with_copies(mongo_db, storage_root, pdf_factory, ("a",))
    monkeypatch.setattr(module, "add_grades",
                        lambda grades, pdf, box, img_path, add_border, shape: _overlay_written(img_path))
    original = _scan(storage_root, "a").read_bytes()

    failed = module.process_writing(job, tmp_path, dpi=72, batches=InlineBatches())

    assert failed == []
    assert _scan(storage_root, "a").read_bytes() == original
    assert _graded(storage_root, "a").read_bytes().startswith(b"%PDF")
    assert not (storage_root / "cover_pages" / "job" / "a_cover_nograde.pdf").exists()


def test_a_page_a_previous_run_overwrote_is_read_from_its_backup(
        mongo_db, storage_root, pdf_factory, monkeypatch, tmp_path):
    # a job finalized before the graded folder existed: the scan is the
    # _nograde backup, and the cover page itself already carries grades
    job = _job_with_copies(mongo_db, storage_root, pdf_factory, ("a",))
    backup = storage_root / "cover_pages" / "job" / "a_cover_nograde.pdf"
    shutil.copy(_scan(storage_root, "a"), backup)
    _scan(storage_root, "a").write_bytes(b"%PDF already graded")
    read_from = []

    def fake_add_grades(grades, pdf_path, box, img_path, add_border, shape):
        read_from.append(pdf_path)
        _overlay_written(img_path)

    monkeypatch.setattr(module, "add_grades", fake_add_grades)

    module.process_writing(job, tmp_path, dpi=72, batches=InlineBatches())

    assert read_from == [str(backup)]
    assert _graded(storage_root, "a").is_file()


def test_a_failed_overlay_leaves_the_copy_to_its_scanned_page(
        mongo_db, storage_root, pdf_factory, monkeypatch, tmp_path):
    job = _job_with_copies(mongo_db, storage_root, pdf_factory, ("a", "b"))

    def fake_add_grades(grades, pdf_path, box, img_path, add_border, shape):
        if pdf_path.endswith("a_cover.pdf"):
            _overlay_written(img_path)
            return
        raise RuntimeError("box not found")  # copy b: the scratch image still holds copy a

    monkeypatch.setattr(module, "add_grades", fake_add_grades)

    failed = module.process_writing(job, tmp_path, dpi=72, batches=InlineBatches())

    assert failed == [1]
    assert _graded(storage_root, "a").is_file()
    # copy b has no graded page at all, rather than copy a's
    assert not _graded(storage_root, "b").exists()


def test_a_graded_page_of_an_earlier_run_does_not_outlive_its_grades(
        mongo_db, storage_root, pdf_factory, monkeypatch, tmp_path):
    job = _job_with_copies(mongo_db, storage_root, pdf_factory, ("a",))
    stale = _graded(storage_root, "a")
    stale.parent.mkdir(parents=True, exist_ok=True)
    stale.write_bytes(b"%PDF the grades of the previous run")

    def no_overlay(grades, pdf_path, box, img_path, add_border, shape):
        raise RuntimeError("box not found")

    monkeypatch.setattr(module, "add_grades", no_overlay)

    failed = module.process_writing(job, tmp_path, dpi=72, batches=InlineBatches())

    assert failed == [0]
    assert not stale.exists()


def test_the_copies_are_written_in_batches_the_memory_guard_closes(
        mongo_db, storage_root, pdf_factory, monkeypatch, tmp_path):
    # one process writing every copy grew out of the container and was
    # OOM-killed mid-finalisation (job d98c2837, killed at copy 314 of 546)
    job = _job_with_copies(mongo_db, storage_root, pdf_factory, ("a", "b", "c", "d"))
    monkeypatch.setenv("MAX_RAM_GB", "4")
    monkeypatch.setattr(module, "memory_used_gb", lambda: 4.2)  # over the guard, always
    monkeypatch.setattr(module, "add_grades",
                        lambda grades, pdf, box, img_path, add_border, shape: _overlay_written(img_path))
    starts = []

    class Counting(InlineBatches):
        def start(self, target, args):
            starts.append(args[1])  # the copy this batch starts at
            return super().start(target, args)

    failed = module.process_writing(job, tmp_path, dpi=72, batches=Counting())

    # a batch per copy, each starting where the previous one stopped
    assert starts == [0, 1, 2, 3]
    assert failed == []
    for name in ("a", "b", "c", "d"):
        assert _graded(storage_root, name).read_bytes().startswith(b"%PDF")


def test_a_batch_that_is_killed_skips_its_copy_and_the_others_are_written(
        mongo_db, storage_root, pdf_factory, monkeypatch, tmp_path):
    job = _job_with_copies(mongo_db, storage_root, pdf_factory, ("a", "b", "c"))
    monkeypatch.setattr(module, "memory_used_gb", lambda: 0.1)

    def fake_add_grades(grades, pdf_path, box, img_path, add_border, shape):
        if pdf_path.endswith("b_cover.pdf"):
            raise Killed("the kernel took the batch down on this page")
        _overlay_written(img_path)

    monkeypatch.setattr(module, "add_grades", fake_add_grades)

    failed = module.process_writing(job, tmp_path, dpi=72, batches=KilledBatches())

    # the copy that killed the batch is reported, not retried for ever
    assert failed == [1]
    assert not _graded(storage_root, "b").exists()
    for name in ("a", "c"):
        assert _graded(storage_root, name).read_bytes().startswith(b"%PDF")


def test_batches_stop_being_restarted_once_too_many_die(
        mongo_db, storage_root, pdf_factory, monkeypatch, tmp_path):
    job = _job_with_copies(mongo_db, storage_root, pdf_factory,
                           tuple(f"c{i}" for i in range(module.MAX_WORKER_DEATHS + 2)))
    monkeypatch.setattr(module, "memory_used_gb", lambda: 0.1)

    def always_killed(grades, pdf_path, box, img_path, add_border, shape):
        raise Killed("every page kills its batch")

    monkeypatch.setattr(module, "add_grades", always_killed)

    with pytest.raises(RuntimeError, match="batches died"):
        module.process_writing(job, tmp_path, dpi=72, batches=KilledBatches())


@pytest.mark.skipif(shutil.which("pdftoppm") is None, reason="poppler not installed")
def test_a_batch_really_runs_in_its_own_process(mongo_db, storage_root, pdf_factory, tmp_path):
    # the other tests run the batch inline; this one takes the default route,
    # a process of its own, and checks the copies and the report come back
    # through it. A blank page carries no grade table, so the overlay fails:
    # what matters is that the batch reported it rather than vanishing.
    job = _job_with_copies(mongo_db, storage_root, pdf_factory, ("a", "b"))

    failed = module.process_writing(job, tmp_path, dpi=72)

    assert failed == [0, 1]
    assert not _graded(storage_root, "a").exists()


@pytest.mark.skipif(shutil.which("pdftoppm") is None, reason="poppler not installed")
def test_add_grades_writes_nothing_when_the_boxes_are_not_found(tmp_path, pdf_factory):
    # a blank page has no grade table: the overlay used to be written anyway
    # (a cover page without grades) and its failure was never reported
    from process_copy import recognize

    pdf = pdf_factory(tmp_path / "blank.pdf")
    img_path = tmp_path / "overlay.jpg"
    ok = recognize.add_grades(
        [1, 2], str(pdf), (0.82, 0.96, 0.15, 0.55), str(img_path), add_border=False, shape=(1275, 1650)
    )
    assert ok is False
    assert not img_path.exists()


# ------------------------------------------- finding the table on the page


def test_the_crops_tried_start_with_the_box_the_template_records():
    from process_copy.annotate import box_candidates

    tried = list(box_candidates((0.80, 0.90, 0.20, 0.40)))

    assert tried[0] == (0.80, 0.90, 0.20, 0.40)
    # then a little wider on every side, then further out on one side only:
    # widening alone never reached a table drawn left of the recorded box
    assert tried[1] == pytest.approx((0.79, 0.91, 0.19, 0.41))
    assert any(left < 0.78 and right == pytest.approx(0.90) for left, right, _, _ in tried)
    assert len(set(tried)) == len(tried)


@pytest.mark.skipif(shutil.which("pdftoppm") is None, reason="poppler not installed")
def test_the_grades_are_written_where_the_cells_were_found(tmp_path, pdf_factory, monkeypatch):
    # the offset used to come from the box the template records while the
    # cells came from the crop that matched, so every copy that needed a
    # wider crop had its grades written that far off their boxes (472 of the
    # 546 copies of job d98c2837)
    from process_copy import annotate

    pdf = pdf_factory(tmp_path / "page.pdf")
    box = (0.60, 0.70, 0.20, 0.40)
    cells = [np.array([[[0, 0]], [[50, 0]], [[50, 40]], [[0, 40]]]),
             np.array([[[0, 50]], [[50, 50]], [[50, 90]], [[0, 90]]])]
    tried = []

    def found_on_the_fourth_try(cropped, add_border, thick=0):
        tried.append(cropped.shape)
        return cells if len(tried) == 4 else []

    offsets = []
    monkeypatch.setattr(annotate, "find_grade_boxes", found_on_the_fourth_try)
    monkeypatch.setattr(annotate, "write_grade_texts",
                        lambda img, boxes, numbers, offset, *a, **k: offsets.append(offset))

    ok = annotate.add_grades([1, 2], str(pdf), box, str(tmp_path / "overlay.jpg"),
                             add_border=False, shape=(2550, 3300))

    assert ok
    # the fourth crop reaches 0.03 further left and 0.02 higher, and that
    # corner is where the grades are written from
    assert offsets == [(int(0.57 * 2550), int(0.18 * 3300))]
