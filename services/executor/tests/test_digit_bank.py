"""The bank of human-confirmed digits: staging, promotion and export."""

import json
import pathlib

import numpy as np
import pytest

from process_copy import digit_bank
from process_copy.database import Database
from rmn_common import settings

JOB = "job-bank"


def crop(value=255, size=40):
    """A crop that looks like a digit: a white block on black, of ``size`` px."""
    roi = np.zeros((size, size - 8), dtype="uint8")
    roi[5:-5, 3:-3] = value
    return roi


def stage(kind=digit_bank.MATRICULE, n=7, document_index=0, keep=True, seed=0, **meta):
    """Stage one reading of ``n`` crops, as the recogniser would.

    ``seed`` shifts the pixels so two readings do not hand the bank the same
    image: the samples are named after their content, so identical crops are
    deduplicated (which is its own test below).
    """
    with digit_bank.recording(JOB, document_index, kind, **meta.pop("context", {})):
        with digit_bank.reading(**meta):
            for i in range(n):
                digit_bank.record(crop(255 - i - 10 * seed))
            if keep:
                digit_bank.keep()


def staged_files(storage_root, job=JOB):
    root = storage_root / digit_bank.STAGED_DIR / job
    return sorted(str(p) for p in root.rglob("*.npz")) if root.exists() else []


def bank_files(storage_root):
    root = storage_root / digit_bank.SAMPLES_DIR
    if not root.exists():
        return []
    return sorted(p.relative_to(root).as_posix() for p in root.rglob("*.png"))


def bank_switch(mongo_db, on):
    """What an admin chose on the admin page."""
    settings.set_save_verified_images(mongo_db[settings.SETTINGS_COLLECTION], on)


def a_job(mongo_db, validate_matricule=True, saves_images=True):
    """A job, with the bank switched on by default."""
    mongo_db["eval_jobs"].insert_one(
        {"job_id": JOB, "user_id": "u", "validate_matricule": validate_matricule}
    )
    bank_switch(mongo_db, saves_images)


def a_document(mongo_db, index=0, status="VALIDATED", matricule="1234567", grades=None):
    mongo_db["job_documents"].insert_one(
        {
            "job_id": JOB,
            "document_index": index,
            "status": status,
            "matricule": matricule,
            "grades": grades or [],
        }
    )


# --------------------------------------------------------------- the size --
def test_a_sample_is_stored_at_64_and_framed_for_the_model_on_the_way_out():
    sample = digit_bank.canonical(crop())
    assert sample.shape == (digit_bank.SAMPLE_SIZE, digit_bank.SAMPLE_SIZE) == (64, 64)
    assert sample.dtype == np.uint8
    # the bank is not the model's input: it is reframed for whatever the model
    # wants, which is what storing the native 64 px crop buys
    assert digit_bank.view(sample, size=28, margin=0.1).shape == (28, 28)
    assert digit_bank.view(sample, size=48, margin=0.25).shape == (48, 48)
    # a crop wider than tall keeps its shape: make_square pads, it does not squash
    wide = np.zeros((10, 40), dtype="uint8")
    wide[2:-2, 2:-2] = 255
    assert digit_bank.canonical(wide).shape == (64, 64)


# ----------------------------------------------------- confirmed -> digits --
@pytest.mark.parametrize(
    "value, n_digits, dot, expected",
    [
        (7.0, 1, None, "7"),  # a matricule digit, no decimal part
        (12.0, 2, None, "12"),
        (2.5, 2, 1, "25"),  # "2.5": one whole digit, one decimal
        (10.25, 4, 2, "1025"),
        (0.5, 2, 1, "05"),  # written "0.5"
        (2.5, 3, 2, None),  # three crops cannot be "2.5"
        (2.5, 2, None, None),  # no dot recorded, but the value has one
        (3.0, 2, 1, "30"),  # "3.0" is written with two digits
        (3.5, 3, 1, None),  # "3.50": the third crop is no decimal
        (9.5, 5, 1, None),  # "9.5/10" read whole: slash, 1, 0
        (10.0, 4, 2, None),  # "10.00"
        (100.0, 2, None, None),  # too many digits for the crops
        (-1.0, 1, None, None),
        (None, 7, None, None),
    ],
)
def test_a_confirmed_number_only_labels_crops_it_can_be_written_with(
    value, n_digits, dot, expected
):
    assert digit_bank.digits_of(value, n_digits, dot) == expected


# ------------------------------------------------------------- the staging --
def test_a_kept_reading_is_staged_and_a_dropped_one_is_not(storage_root):
    stage(keep=True)
    assert len(staged_files(storage_root)) == 1
    stage(keep=False)
    assert (
        len(staged_files(storage_root)) == 1
    ), "a reading nobody kept must not be staged"

    with np.load(staged_files(storage_root)[0], allow_pickle=False) as data:
        crops, meta = data["crops"], json.loads(str(data["meta"]))
    assert crops.shape == (7, 64, 64)
    assert meta["kind"] == digit_bank.MATRICULE
    assert meta["job_id"] == JOB and meta["document_index"] == 0
    assert meta["size"] == 64


def test_nothing_is_staged_without_a_job_or_when_the_bank_is_off(
    storage_root, monkeypatch
):
    with digit_bank.recording(None, 0, digit_bank.MATRICULE):
        with digit_bank.reading():
            digit_bank.record(crop())
            digit_bank.keep()
    assert staged_files(storage_root) == []

    monkeypatch.setenv("DIGIT_BANK", "0")
    stage()
    assert staged_files(storage_root) == []


def test_the_ink_pass_can_keep_the_candidate_it_settles_on_afterwards(storage_root):
    """``ink_grades.pick`` reads every mark and only then knows which is the grade."""
    with digit_bank.recording(JOB, 3, digit_bank.INK_GRADE, question_index=2):
        for value in (1, 2, 3):
            with digit_bank.reading(dot=None):
                digit_bank.record(crop(value * 60))
        digit_bank.keep_last(value=9.0)  # the third mark is the grade
    files = staged_files(storage_root)
    assert len(files) == 1
    with np.load(files[0], allow_pickle=False) as data:
        meta = json.loads(str(data["meta"]))
    assert meta["question_index"] == 2 and meta["value"] == 9.0


# ----------------------------------------------------------- the promotion --
def test_a_validated_matricule_labels_its_seven_crops(storage_root, mongo_db):
    a_job(mongo_db)
    a_document(mongo_db, matricule="1234567")
    stage()

    counts = digit_bank.promote_job(Database(), JOB)
    assert counts == {"readings": 1, "promoted": 1, "samples": 7, "skipped": 0}
    assert sorted(f.split("/")[0] for f in bank_files(storage_root)) == list("1234567")
    assert staged_files(storage_root) == [], "a promoted reading is not kept staged"

    index = (storage_root / digit_bank.INDEX_FILE).read_text().strip().split("\n")
    assert len(index) == 7
    first = json.loads(index[0])
    assert first["label"] == 1 and first["position"] == 0 and first["size"] == 64
    assert first["kind"] == digit_bank.MATRICULE


def test_the_same_digit_is_only_banked_once(storage_root, mongo_db):
    a_job(mongo_db)
    a_document(mongo_db, matricule="1111111")
    # seven crops, all different, but the reading is staged twice
    stage()
    stage()
    counts = digit_bank.promote_job(Database(), JOB)
    assert counts["readings"] == 2 and counts["promoted"] == 2
    # the pixels are the file name, so the second reading adds nothing
    assert counts["samples"] == 7
    assert len(bank_files(storage_root)) == 7


def test_a_matricule_the_job_never_asked_a_human_to_check_is_not_banked(
    storage_root, mongo_db
):
    """Without ``validate_matricule`` the copies are marked VALIDATED by the
    executor itself (``batch.process_all``), so the status proves nothing."""
    a_job(mongo_db, validate_matricule=False)
    a_document(mongo_db, matricule="1234567")
    stage()
    counts = digit_bank.promote_job(Database(), JOB)
    assert counts["promoted"] == 0 and counts["skipped"] == 1
    assert bank_files(storage_root) == []


def test_a_copy_still_waiting_for_a_human_is_not_banked(storage_root, mongo_db):
    a_job(mongo_db)
    a_document(mongo_db, status="TO VALIDATE", matricule="1234567")
    stage()
    assert digit_bank.promote_job(Database(), JOB)["promoted"] == 0
    assert bank_files(storage_root) == []


def test_a_matricule_of_another_length_than_the_crops_is_dropped(
    storage_root, mongo_db
):
    a_job(mongo_db)
    a_document(mongo_db, matricule="123456")  # six digits, seven crops
    stage()
    assert digit_bank.promote_job(Database(), JOB)["skipped"] == 1
    assert bank_files(storage_root) == []


def test_a_confirmed_grade_labels_the_digits_of_its_box(storage_root, mongo_db):
    a_job(mongo_db)
    a_document(mongo_db, grades=[2.5, 3.0])
    stage(kind=digit_bank.GRADE_BOX, n=2, box_index=0, dot=1, seed=1)  # "2.5"
    stage(kind=digit_bank.GRADE_BOX, n=2, box_index=1, dot=1, seed=2)  # "3.0"
    stage(kind=digit_bank.GRADE_BOX, n=2, box_index=2, dot=1, seed=3)  # the total, 5.5

    counts = digit_bank.promote_job(Database(), JOB)
    assert counts["promoted"] == 3
    # the last box of the table is the total: the sum of the grades confirmed
    # for the copy, which is what a human validating them settled
    assert sorted(f.split("/")[0] for f in bank_files(storage_root)) == list("023555")


def test_an_ink_grade_is_labelled_with_the_grade_the_human_confirmed(
    storage_root, mongo_db
):
    a_job(mongo_db)
    a_document(mongo_db)
    mongo_db["job_questions"].insert_one(
        {"job_id": JOB, "document_index": 0, "question_index": 2, "grade": 8.5}
    )
    stage(kind=digit_bank.INK_GRADE, n=2, dot=1, context={"question_index": 2})

    counts = digit_bank.promote_job(Database(), JOB)
    assert counts["promoted"] == 1
    assert sorted(f.split("/")[0] for f in bank_files(storage_root)) == ["5", "8"]


def test_an_ink_grade_nobody_confirmed_is_not_banked(storage_root, mongo_db):
    a_job(mongo_db)
    a_document(mongo_db)
    mongo_db["job_questions"].insert_one(
        {
            "job_id": JOB,
            "document_index": 0,
            "question_index": 2,
            "grade": None,
            "auto_grade": 8.5,
            "auto_grade_confidence": 0.99,
        }
    )
    stage(kind=digit_bank.INK_GRADE, n=2, dot=1, context={"question_index": 2})
    assert digit_bank.promote_job(Database(), JOB)["promoted"] == 0
    assert bank_files(storage_root) == []


def test_nothing_is_banked_while_an_admin_keeps_the_bank_off(storage_root, mongo_db):
    """The switch of the admin page: while it is off, the crops die with
    their job instead of outliving it."""
    a_job(mongo_db, saves_images=False)
    a_document(mongo_db, matricule="1234567")
    stage()

    counts = digit_bank.promote_job(Database(), JOB)
    assert counts["refused"] == 1 and counts["samples"] == 0
    assert bank_files(storage_root) == []
    # and they are left where the job cleanup will take them
    assert len(staged_files(storage_root)) == 1


def test_the_switch_is_the_admins_not_a_profile_nor_the_task(storage_root, mongo_db):
    """One switch for every task, read when the bank is filled.

    The ``saveVerifiedImages`` that older user rows and tasks carry -- the
    profile switch it replaces -- has no say either way.
    """
    mongo_db["eval_jobs"].insert_one(
        {
            "job_id": JOB,
            "user_id": "u",
            "validate_matricule": True,
            "source_job_id": "an-older-task",
            "saveVerifiedImages": False,
        }
    )
    mongo_db["users"].insert_one({"username": "u", "saveVerifiedImages": False})
    bank_switch(mongo_db, True)
    a_document(mongo_db, matricule="1234567")
    stage()

    assert digit_bank.promote_job(Database(), JOB)["samples"] == 7

    # and the other way round: the admin turns it off, no profile can allow it
    bank_switch(mongo_db, False)
    mongo_db["users"].update_one(
        {"username": "u"}, {"$set": {"saveVerifiedImages": True}}
    )
    mongo_db["eval_jobs"].update_one(
        {"job_id": JOB}, {"$set": {"saveVerifiedImages": True}}
    )
    stage(document_index=1)
    a_document(mongo_db, index=1, matricule="7654321")

    assert digit_bank.promote_job(Database(), JOB)["refused"] == 1
    assert len(bank_files(storage_root)) == 7  # only the first pass


def test_the_bank_is_on_until_an_admin_turns_it_off(storage_root, mongo_db):
    """No settings at all -- a database no admin changed anything in -- keeps
    the digits, whoever owns the task (a deleted user included)."""
    mongo_db["eval_jobs"].insert_one(
        {"job_id": JOB, "user_id": "ghost", "validate_matricule": True}
    )
    a_document(mongo_db, matricule="1234567")
    stage()

    assert digit_bank.promote_job(Database(), JOB)["samples"] == 7
    assert len(bank_files(storage_root)) == 7


# ------------------------------------------------------- the end of a task --
def test_finalising_drops_what_could_not_be_labelled(storage_root, mongo_db):
    """Once the humans are done, a reading nobody confirmed never will be."""
    a_job(mongo_db)
    a_document(mongo_db, matricule="1234567")
    stage()  # labelled by the matricule
    stage(n=5, document_index=1, seed=1)  # five crops, no copy to confirm them

    counts = digit_bank.promote_job(Database(), JOB, final=True)

    assert counts["promoted"] == 1 and counts["skipped"] == 1
    assert counts["dropped"] == 1
    assert len(bank_files(storage_root)) == 7
    assert staged_files(storage_root) == []
    # the job's whole staging area, empty directories included
    assert not (storage_root / digit_bank.STAGED_DIR / JOB).exists()


def test_finalising_drops_the_crops_of_a_teacher_who_opted_out(storage_root, mongo_db):
    """They will never be banked, so they go now rather than waiting for the
    job to be deleted: they are the ink of real students."""
    a_job(mongo_db, saves_images=False)
    a_document(mongo_db, matricule="1234567")
    stage()

    counts = digit_bank.promote_job(Database(), JOB, final=True)

    assert counts["refused"] == 1
    assert bank_files(storage_root) == []
    assert not (storage_root / digit_bank.STAGED_DIR / JOB).exists()


def test_a_task_still_being_validated_keeps_what_it_could_not_label(
    storage_root, mongo_db
):
    """The copies are validated one by one: a reading that no confirmation
    matches today may well match tomorrow's."""
    a_job(mongo_db)
    a_document(mongo_db, status="TO VALIDATE", matricule="1234567")
    stage()

    counts = digit_bank.promote_job(Database(), JOB)

    assert counts["skipped"] == 1 and "dropped" not in counts
    assert len(staged_files(storage_root)) == 1

    # the copy is validated, and the reading finds its labels
    mongo_db["job_documents"].update_one(
        {"job_id": JOB, "document_index": 0}, {"$set": {"status": "VALIDATED"}}
    )
    assert digit_bank.promote_job(Database(), JOB)["samples"] == 7


# --------------------------------------------------------------- the export --
def test_the_bank_exports_the_arrays_the_training_reads(storage_root, mongo_db):
    a_job(mongo_db)
    a_document(mongo_db, matricule="1234567")
    stage()
    digit_bank.promote_job(Database(), JOB)

    x, y = digit_bank.samples(size=28, margin=0.1)
    assert x.shape == (7, 28, 28) and x.dtype == np.uint8
    assert sorted(y.tolist()) == [1, 2, 3, 4, 5, 6, 7]
    assert digit_bank.counts() == {d: 1 for d in range(1, 8)}

    native, _ = digit_bank.samples(size=digit_bank.SAMPLE_SIZE)
    assert native.shape == (7, 64, 64)


def test_an_empty_bank_exports_an_empty_set():
    x, y = digit_bank.samples(size=28)
    assert x.shape == (0, 28, 28) and len(y) == 0
    assert digit_bank.counts() == {}


# ------------------------------------------------------------------ the tool --
def test_promoting_every_job_survives_one_that_banks_nothing(
    storage_root, mongo_db, capsys
):
    """``promote --all`` walks jobs it knows nothing about: a job that banks
    nothing reports a count the others do not have, and must not stop the run."""
    import sys

    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "tools"))
    import build_digit_bank

    a_job(mongo_db, saves_images=False)
    a_document(mongo_db, matricule="1234567")
    stage()
    mongo_db["eval_jobs"].insert_one(
        {"job_id": "other", "user_id": "bob", "validate_matricule": True}
    )
    with digit_bank.recording("other", 0, digit_bank.MATRICULE):
        with digit_bank.reading():
            digit_bank.record(crop())
            digit_bank.keep()

    assert build_digit_bank.main(["promote", "--all"]) == 0

    printed = capsys.readouterr().out
    assert printed.count("refused=1") == 2
    assert bank_files(storage_root) == []


# ------------------------------------------------------- purge and rebuild --
GRADE_MARKS = json.load(
    open(pathlib.Path(__file__).parent / "fixtures" / "ink_grades" / "grade_marks.json")
)


def bank_index(storage_root):
    path = storage_root / digit_bank.INDEX_FILE
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line]


def bank_two_jobs(storage_root, mongo_db):
    """``JOB`` (seven crops) and ``other`` (one) banked."""
    a_job(mongo_db)
    a_document(mongo_db, matricule="1234567")
    stage()
    mongo_db["eval_jobs"].insert_one(
        {"job_id": "other", "user_id": "u", "validate_matricule": True}
    )
    mongo_db["job_documents"].insert_one(
        {
            "job_id": "other",
            "document_index": 0,
            "status": "VALIDATED",
            "matricule": "1",
        }
    )
    with digit_bank.recording("other", 0, digit_bank.MATRICULE):
        with digit_bank.reading():
            digit_bank.record(crop(100))
            digit_bank.keep()
    digit_bank.promote_job(Database(), JOB)
    digit_bank.promote_job(Database(), "other")


def test_a_job_is_purged_from_the_bank_and_its_index(storage_root, mongo_db):
    bank_two_jobs(storage_root, mongo_db)
    assert len(bank_files(storage_root)) == 8

    counts = digit_bank.purge_job(digit_bank.default_storage, JOB)

    assert counts == {"lines": 7, "files": 7}
    assert [e["job_id"] for e in bank_index(storage_root)] == ["other"]
    assert bank_files(storage_root) == [
        "1/" + bank_index(storage_root)[0]["sha1"] + ".png"
    ]


def test_a_dry_purge_changes_nothing(storage_root, mongo_db):
    bank_two_jobs(storage_root, mongo_db)
    files, index = bank_files(storage_root), bank_index(storage_root)

    counts = digit_bank.purge_job(digit_bank.default_storage, JOB, dry_run=True)

    assert counts == {"lines": 7, "files": 7}
    assert bank_files(storage_root) == files
    assert bank_index(storage_root) == index


def ink_page(storage_root, name, mark, offset=(0.0, 0.0)):
    """A question page carrying one grade mark of ``grade_marks.json``."""
    import pymupdf

    rel = f"documents/{JOB}/Q1/{name}.pdf"
    path = storage_root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    doc = pymupdf.open()
    page = doc.new_page(width=612, height=792)
    dx, dy = offset
    page.add_ink_annot(
        [[(x + dx, y + dy) for x, y in stroke] for stroke in mark["strokes"]]
    )
    doc.save(str(path))
    doc.close()
    return rel


def graded_question(storage_root, mongo_db, grades, offsets=None):
    """Question 1 of ``JOB``: one "7/10" page per grade, graded by a human."""
    mark = GRADE_MARKS["marks"]["seven_over_ten"]
    mongo_db["eval_jobs"].update_one(
        {"job_id": JOB},
        {"$set": {"n_max_points_per_question": [["Q1", 10.0]]}},
    )
    for index, grade in enumerate(grades):
        offset = (offsets or {}).get(index, (0.0, 0.0))
        mongo_db["job_questions"].insert_one(
            {
                "job_id": JOB,
                "document_index": index,
                "question_index": 1,
                "grade": grade,
                "rel_filepath": ink_page(storage_root, f"copy{index}", mark, offset),
            }
        )
        if index:
            a_document(mongo_db, index=index)


def test_a_rebuild_reads_the_graded_pages_with_the_reader_of_today(
    storage_root, mongo_db
):
    from process_copy import auto_grade
    from process_copy.classifier import load_classifier

    a_job(mongo_db)
    a_document(mongo_db)
    # five pages to learn where the grade sits; a sixth with no grade
    graded_question(storage_root, mongo_db, [7.0] * 5 + [None])
    job = mongo_db["eval_jobs"].find_one({"job_id": JOB})

    counts = auto_grade.restage_question(
        Database(), digit_bank.default_storage, job, 1, load_classifier()
    )

    assert counts == {"pages": 5, "staged": 5}
    promoted = digit_bank.promote_job(Database(), JOB)
    assert promoted["promoted"] == 5
    # the 7 of "7/10", nothing of the slash or the 10
    assert {f.split("/")[0] for f in bank_files(storage_root)} == {"7"}
    # read for the bank only: no reading reaches the correction screen
    assert all(
        "auto_grade" not in q for q in mongo_db["job_questions"].find({"job_id": JOB})
    )


def test_a_rebuild_does_not_label_another_mark_with_the_grade(storage_root, mongo_db):
    """No total written: the teacher typed 3 and the reader found a 7 elsewhere."""
    from process_copy import auto_grade
    from process_copy.classifier import load_classifier

    a_job(mongo_db)
    a_document(mongo_db)
    graded_question(
        storage_root, mongo_db, [7.0] * 5 + [3.0], offsets={5: (-200.0, 180.0)}
    )
    job = mongo_db["eval_jobs"].find_one({"job_id": JOB})

    counts = auto_grade.restage_question(
        Database(), digit_bank.default_storage, job, 1, load_classifier()
    )

    assert counts == {"pages": 6, "staged": 5}


def test_a_deleted_copy_is_not_read_again(storage_root, mongo_db):
    from process_copy import auto_grade
    from process_copy.classifier import load_classifier

    a_job(mongo_db)
    a_document(mongo_db)
    graded_question(storage_root, mongo_db, [7.0] * 6)
    mongo_db["job_documents"].update_one(
        {"job_id": JOB, "document_index": 5}, {"$set": {"status": "DELETED"}}
    )
    job = mongo_db["eval_jobs"].find_one({"job_id": JOB})

    counts = auto_grade.restage_question(
        Database(), digit_bank.default_storage, job, 1, load_classifier()
    )

    assert counts["pages"] == 5


def test_the_rebuild_command_replaces_a_jobs_samples(storage_root, mongo_db, capsys):
    import sys

    sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent.parent / "tools"))
    import build_digit_bank

    a_job(mongo_db)
    a_document(mongo_db)
    graded_question(storage_root, mongo_db, [7.0] * 5)
    # what an older reader banked from a "7/10" read whole: 7, 0, 0, 0 --
    # written by hand, the padding being refused now
    for position, label in enumerate("7000"):
        digit_bank.add_sample(
            digit_bank.default_storage,
            crop(200 - position),
            label,
            {"job_id": JOB, "kind": digit_bank.INK_GRADE, "position": position},
        )

    assert build_digit_bank.main(["rebuild", "--job", JOB, "--dry-run"]) == 0
    assert len(bank_index(storage_root)) == 4  # a dry run changes nothing
    assert "would replace 4 samples by" in capsys.readouterr().out

    assert build_digit_bank.main(["rebuild", "--job", JOB]) == 0
    assert {e["label"] for e in bank_index(storage_root)} == {7}
    assert {f.split("/")[0] for f in bank_files(storage_root)} == {"7"}
