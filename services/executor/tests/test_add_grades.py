"""Writing the grades on the cover pages (process_writing)."""

import os
import shutil

import numpy as np
import pymupdf
import pytest

from process_copy import add_grades as module
from process_copy.batching import FinishedBatch, InlineBatches


SCAN_FIXTURE = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "fixtures", "ink_grades", "ink_busy_page.pdf")


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


def _page_written(out_path):
    """What the real add_grades leaves behind: the page, with the grades on it."""
    shutil.copy(SCAN_FIXTURE, out_path)
    return True


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
                        lambda grades, pdf, box, out_path, add_border, shape, layout=None:
                        _page_written(out_path))
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

    def fake_add_grades(grades, pdf_path, box, out_path, add_border, shape, layout=None):
        read_from.append(pdf_path)
        return _page_written(out_path)

    monkeypatch.setattr(module, "add_grades", fake_add_grades)

    module.process_writing(job, tmp_path, dpi=72, batches=InlineBatches())

    assert read_from == [str(backup)]
    assert _graded(storage_root, "a").is_file()


def test_a_failed_overlay_leaves_the_copy_to_its_scanned_page(
        mongo_db, storage_root, pdf_factory, monkeypatch, tmp_path):
    job = _job_with_copies(mongo_db, storage_root, pdf_factory, ("a", "b"))

    def fake_add_grades(grades, pdf_path, box, out_path, add_border, shape, layout=None):
        if pdf_path.endswith("a_cover.pdf"):
            return _page_written(out_path)
        raise RuntimeError("box not found")

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

    def no_overlay(grades, pdf_path, box, out_path, add_border, shape, layout=None):
        raise RuntimeError("box not found")

    monkeypatch.setattr(module, "add_grades", no_overlay)

    failed = module.process_writing(job, tmp_path, dpi=72, batches=InlineBatches())

    assert failed == [0]
    assert not stale.exists()


def test_each_copy_records_whether_the_grader_should_look_at_its_cover_page(
        mongo_db, storage_root, pdf_factory, monkeypatch, tmp_path):
    from process_copy.annotate import NOT_WRITTEN, TEMPLATE_POSITION, WRITTEN

    job = _job_with_copies(mongo_db, storage_root, pdf_factory, ("a", "b", "c"))
    # written before, flagged: written now, the flag must go
    mongo_db["job_documents"].update_one({"document_index": 0}, {"$set": {"cover_check": "rules"}})
    placed = {"a": WRITTEN, "b": TEMPLATE_POSITION, "c": None}

    def overlay(grades, pdf_path, box, out_path, add_border, shape, layout=None):
        name = os.path.basename(pdf_path).split("_")[0]
        if placed[name]:
            _page_written(out_path)
        return placed[name]

    monkeypatch.setattr(module, "add_grades", overlay)

    failed = module.process_writing(job, tmp_path, dpi=72, batches=InlineBatches())

    assert failed == [2]
    checks = {d["document_index"]: d.get("cover_check") for d in mongo_db["job_documents"].find()}
    assert checks == {0: None, 1: TEMPLATE_POSITION, 2: NOT_WRITTEN}


def test_the_copies_are_written_in_batches_the_memory_guard_closes(
        mongo_db, storage_root, pdf_factory, monkeypatch, tmp_path):
    # one process writing every copy grew out of the container and was
    # OOM-killed mid-finalisation (job d98c2837, killed at copy 314 of 546)
    job = _job_with_copies(mongo_db, storage_root, pdf_factory, ("a", "b", "c", "d"))
    monkeypatch.setenv("MAX_RAM_GB", "4")
    monkeypatch.setattr(module, "memory_used_gb", lambda: 4.2)  # over the guard, always
    monkeypatch.setattr(module, "add_grades",
                        lambda grades, pdf, box, out_path, add_border, shape, layout=None:
                        _page_written(out_path))
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

    def fake_add_grades(grades, pdf_path, box, out_path, add_border, shape, layout=None):
        if pdf_path.endswith("b_cover.pdf"):
            raise Killed("the kernel took the batch down on this page")
        return _page_written(out_path)

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

    def always_killed(grades, pdf_path, box, out_path, add_border, shape, layout=None):
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
    out_path = tmp_path / "graded.pdf"
    ok = recognize.add_grades(
        [1, 2], str(pdf), (0.82, 0.96, 0.15, 0.55), str(out_path), add_border=False, shape=(1275, 1650)
    )
    assert ok is None
    assert not out_path.exists()


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


CELLS = [np.array([[[0, 0]], [[50, 0]], [[50, 40]], [[0, 40]]]),
         np.array([[[0, 50]], [[50, 50]], [[50, 90]], [[0, 90]]])]


def _red_pixels(pdf_path, dpi=150):
    """Where the red ink is on the first page, in page points."""
    with pymupdf.open(str(pdf_path)) as document:
        page = document[0]
        pix = page.get_pixmap(dpi=dpi)
        img = np.frombuffer(pix.samples, dtype=np.uint8).reshape(pix.height, pix.width, pix.n)
    red = (img[:, :, 0] > 150) & (img[:, :, 1] < 100) & (img[:, :, 2] < 100)
    ys, xs = np.nonzero(red)
    if not len(xs):
        return None
    scale = 72.0 / dpi
    return pymupdf.Rect(xs.min() * scale, ys.min() * scale, xs.max() * scale, ys.max() * scale)


@pytest.mark.skipif(shutil.which("pdftoppm") is None, reason="poppler not installed")
@pytest.mark.parametrize("rotation", [0, 90])
def test_the_grades_land_in_the_cells_that_were_found(tmp_path, monkeypatch, rotation):
    # the cells are found on a raster of the page and written in the page
    # itself: the mapping between the two is what this checks, including for
    # a page stored turned (a /Rotate the scanner left behind)
    from process_copy import annotate

    pdf = tmp_path / "page.pdf"
    with pymupdf.open() as document:
        page = document.new_page(width=612, height=792)  # letter
        page.set_rotation(rotation)
        document.save(str(pdf))
    monkeypatch.setattr(annotate, "find_grade_boxes", lambda *a, **k: CELLS)

    box = (0.60, 0.70, 0.20, 0.40)
    out_path = tmp_path / "graded.pdf"
    assert annotate.add_grades([7, 8], str(pdf), box, str(out_path),
                               add_border=False, shape=(2550, 3300))

    # the cells sit at the top left of the crop, which starts at (0.60, 0.20)
    # of a 612 x 792 page as it is displayed
    with pymupdf.open(str(out_path)) as document:
        displayed = document[0].rect
    expected = pymupdf.Rect(0.60 * displayed.width, 0.20 * displayed.height,
                            0.60 * displayed.width + 52 * displayed.width / 2550,
                            0.20 * displayed.height + 92 * displayed.height / 3300)
    ink = _red_pixels(out_path)
    assert ink is not None, "nothing was written on the page"
    assert expected.contains(ink), f"the grades landed at {ink}, outside the cells at {expected}"


@pytest.mark.skipif(shutil.which("pdftoppm") is None, reason="poppler not installed")
def test_the_scan_is_carried_over_untouched(tmp_path, monkeypatch):
    # the page used to be rasterised at 300 dpi and re-encoded as a jpeg,
    # which turned a 94 kB scan into 1.4 MB and lost what the scanner saw
    import cv2

    from process_copy import annotate
    from process_copy.pages import gray_images

    monkeypatch.setattr(annotate, "find_grade_boxes", lambda *a, **k: CELLS)
    out_path = tmp_path / "graded.pdf"

    assert annotate.add_grades([7, 8], SCAN_FIXTURE, (0.1, 0.2, 0.1, 0.2), str(out_path),
                               add_border=False, shape=(2550, 3300))

    grew = os.path.getsize(out_path) / os.path.getsize(SCAN_FIXTURE)
    assert grew < 1.2, f"the page grew {grew:.1f} times"
    # the scan itself is the same image, not a re-encoding of a picture of it
    before, after = (gray_images(p, [0], straighten=False)[0] for p in (SCAN_FIXTURE, str(out_path)))
    assert before.shape == after.shape
    untouched = np.s_[:, before.shape[1] // 2:]  # away from the cells and the grades
    assert cv2.PSNR(before[untouched], after[untouched]) > 60
