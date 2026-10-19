"""Writing the grades on the cover pages (process_writing)."""

import shutil

import pytest

from PIL import Image

from process_copy import add_grades as module


class Killed(BaseException):
    """What a kernel kill looks like from inside a batch: not an Exception,
    so the per-copy error handling of write_cover_page does not swallow it."""


class InlineBatch:
    """A batch run in this process: the doubles of the suite reach it.

    ``process_writing`` forks its batches to give the memory back; the loop
    around them (where a batch stops, what happens when one dies) is what
    these tests are about.
    """

    def __init__(self, target, args):
        self._target, self._args = target, args
        self.exitcode = None

    def start(self):
        self._target(*self._args)
        self.exitcode = 0

    def join(self, timeout=None):
        pass


class KilledBatch(InlineBatch):
    """A batch the kernel killed: it stops where the copy raised Killed."""

    def start(self):
        try:
            self._target(*self._args)
            self.exitcode = 0
        except Killed:
            self.exitcode = -9


def test_a_failed_overlay_keeps_the_original_cover_page(mongo_db, storage_root, pdf_factory, monkeypatch):
    mongo_db["template"].insert_one({"template_id": "front", "grade_box": [0.1, 0.9, 0.6, 0.9]})
    for index, name in ((0, "a"), (1, "b")):
        pdf_factory(storage_root / "documents" / "job" / "all" / f"{name}.pdf")
        mongo_db["job_documents"].insert_one(
            {
                "job_id": "job",
                "document_index": index,
                "status": "VALIDATED",
                "grades": [4],
                "rel_filepath": f"documents/job/all/{name}.pdf",
            }
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
    job = {
        "job_id": "job",
        "front_template_id": "front",
        "regular_template_id": None,
        "n_pages_per_question": [["Q1", 2]],
    }

    failed = module.process_writing(job, tmp_dir, dpi=72, batch_runner=InlineBatch)

    assert failed == [1]
    rewritten = (storage_root / "documents" / "job" / "all" / "a.pdf").read_bytes()
    assert rewritten.startswith(b"%PDF") and rewritten != original_b
    # copy b keeps its own cover page instead of receiving copy a's
    assert (storage_root / "documents" / "job" / "all" / "b.pdf").read_bytes() == original_b
    shutil.rmtree(tmp_dir)


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


def _job_with_copies(mongo_db, storage_root, pdf_factory, names):
    mongo_db["template"].insert_one({"template_id": "front", "grade_box": [0.1, 0.9, 0.6, 0.9]})
    for index, name in enumerate(names):
        pdf_factory(storage_root / "documents" / "job" / "all" / f"{name}.pdf")
        mongo_db["job_documents"].insert_one(
            {
                "job_id": "job",
                "document_index": index,
                "status": "VALIDATED",
                "grades": [4],
                "rel_filepath": f"documents/job/all/{name}.pdf",
            }
        )
    return {
        "job_id": "job",
        "front_template_id": "front",
        "regular_template_id": None,
        "n_pages_per_question": [["Q1", 2]],
    }


def _overlay_written(img_path):
    Image.new("RGB", (20, 30), "white").save(img_path)


def test_the_copies_are_written_in_batches_the_memory_guard_closes(
        mongo_db, storage_root, pdf_factory, monkeypatch, tmp_path):
    # one process writing every copy grew out of the container and was
    # OOM-killed mid-finalisation (job d98c2837, killed at copy 314 of 546)
    job = _job_with_copies(mongo_db, storage_root, pdf_factory, ("a", "b", "c", "d"))
    monkeypatch.setenv("MAX_RAM_GB", "4")
    monkeypatch.setattr(module, "memory_used_gb", lambda: 4.2)  # over the guard, always
    monkeypatch.setattr(module, "add_grades",
                        lambda grades, pdf, box, img_path, add_border, shape: _overlay_written(img_path))
    batches = []

    def runner(target, args):
        batches.append(args[1])  # the copy this batch starts at
        return InlineBatch(target, args)

    failed = module.process_writing(job, tmp_path, dpi=72, batch_runner=runner)

    # a batch per copy, each starting where the previous one stopped
    assert batches == [0, 1, 2, 3]
    assert failed == []
    for name in ("a", "b", "c", "d"):
        assert (storage_root / "documents" / "job" / "all" / f"{name}.pdf").read_bytes().startswith(b"%PDF")


def test_a_batch_that_is_killed_skips_its_copy_and_the_others_are_written(
        mongo_db, storage_root, pdf_factory, monkeypatch, tmp_path):
    job = _job_with_copies(mongo_db, storage_root, pdf_factory, ("a", "b", "c"))
    monkeypatch.setattr(module, "memory_used_gb", lambda: 0.1)

    def fake_add_grades(grades, pdf_path, box, img_path, add_border, shape):
        if pdf_path.endswith("b_nograde.pdf"):
            raise Killed("the kernel took the batch down on this page")
        _overlay_written(img_path)

    monkeypatch.setattr(module, "add_grades", fake_add_grades)
    originals = {n: (storage_root / "documents" / "job" / "all" / f"{n}.pdf").read_bytes()
                 for n in ("a", "b", "c")}

    failed = module.process_writing(job, tmp_path, dpi=72, batch_runner=KilledBatch)

    # the copy that killed the batch is reported, not retried for ever
    assert failed == [1]
    assert (storage_root / "documents" / "job" / "all" / "b.pdf").read_bytes() == originals["b"]
    for name in ("a", "c"):
        rewritten = (storage_root / "documents" / "job" / "all" / f"{name}.pdf").read_bytes()
        assert rewritten.startswith(b"%PDF") and rewritten != originals[name]


def test_batches_stop_being_restarted_once_too_many_die(
        mongo_db, storage_root, pdf_factory, monkeypatch, tmp_path):
    job = _job_with_copies(mongo_db, storage_root, pdf_factory,
                           tuple(f"c{i}" for i in range(module.MAX_WORKER_DEATHS + 2)))
    monkeypatch.setattr(module, "memory_used_gb", lambda: 0.1)

    def always_killed(grades, pdf_path, box, img_path, add_border, shape):
        raise Killed("every page kills its batch")

    monkeypatch.setattr(module, "add_grades", always_killed)

    with pytest.raises(RuntimeError, match="batches died"):
        module.process_writing(job, tmp_path, dpi=72, batch_runner=KilledBatch)


@pytest.mark.skipif(shutil.which("pdftoppm") is None, reason="poppler not installed")
def test_a_batch_really_runs_in_its_own_process(mongo_db, storage_root, pdf_factory, tmp_path):
    # the other tests run the batch inline; this one takes the default route,
    # a process of its own, and checks the copies and the report come back
    # through it. A blank page carries no grade table, so the overlay fails:
    # what matters is that the batch reported it rather than vanishing.
    job = _job_with_copies(mongo_db, storage_root, pdf_factory, ("a", "b"))
    original = (storage_root / "documents" / "job" / "all" / "a.pdf").read_bytes()

    failed = module.process_writing(job, tmp_path, dpi=72)

    assert failed == [0, 1]
    assert (storage_root / "documents" / "job" / "all" / "a.pdf").read_bytes() == original
