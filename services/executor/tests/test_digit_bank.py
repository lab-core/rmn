"""The bank of human-confirmed digits: staging, promotion and export."""

import json

import numpy as np
import pytest

from process_copy import digit_bank
from process_copy.database import Database

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


def a_job(mongo_db, validate_matricule=True, saves_images=True):
    """A job whose owner has, by default, opted into keeping the images."""
    mongo_db["eval_jobs"].insert_one(
        {"job_id": JOB, "user_id": "u", "validate_matricule": validate_matricule}
    )
    mongo_db["users"].insert_one({"username": "u", "saveVerifiedImages": saves_images})


def a_document(mongo_db, index=0, status="VALIDATED", matricule="1234567", grades=None):
    mongo_db["job_documents"].insert_one(
        {"job_id": JOB, "document_index": index, "status": status,
         "matricule": matricule, "grades": grades or []}
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
        (7.0, 1, None, "7"),          # a matricule digit, no decimal part
        (12.0, 2, None, "12"),
        (2.5, 2, 1, "25"),            # "2.5": one whole digit, one decimal
        (10.25, 4, 2, "1025"),
        (0.5, 2, 1, "05"),            # written "0.5"
        (2.5, 3, 2, None),            # three crops cannot be "2.5"
        (2.5, 2, None, None),         # no dot recorded, but the value has one
        (3.0, 2, 1, "30"),            # "3.0" is written with two digits
        (100.0, 2, None, None),       # too many digits for the crops
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
    assert len(staged_files(storage_root)) == 1, "a reading nobody kept must not be staged"

    with np.load(staged_files(storage_root)[0], allow_pickle=False) as data:
        crops, meta = data["crops"], json.loads(str(data["meta"]))
    assert crops.shape == (7, 64, 64)
    assert meta["kind"] == digit_bank.MATRICULE
    assert meta["job_id"] == JOB and meta["document_index"] == 0
    assert meta["size"] == 64


def test_nothing_is_staged_without_a_job_or_when_the_bank_is_off(storage_root, monkeypatch):
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


def test_a_matricule_of_another_length_than_the_crops_is_dropped(storage_root, mongo_db):
    a_job(mongo_db)
    a_document(mongo_db, matricule="123456")  # six digits, seven crops
    stage()
    assert digit_bank.promote_job(Database(), JOB)["skipped"] == 1
    assert bank_files(storage_root) == []


def test_a_confirmed_grade_labels_the_digits_of_its_box(storage_root, mongo_db):
    a_job(mongo_db)
    a_document(mongo_db, grades=[2.5, 3.0])
    stage(kind=digit_bank.GRADE_BOX, n=2, box_index=0, dot=1, seed=1)   # "2.5"
    stage(kind=digit_bank.GRADE_BOX, n=2, box_index=1, dot=1, seed=2)   # "3.0"
    stage(kind=digit_bank.GRADE_BOX, n=2, box_index=2, dot=1, seed=3)   # the total, 5.5

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
        {"job_id": JOB, "document_index": 0, "question_index": 2,
         "grade": None, "auto_grade": 8.5, "auto_grade_confidence": 0.99}
    )
    stage(kind=digit_bank.INK_GRADE, n=2, dot=1, context={"question_index": 2})
    assert digit_bank.promote_job(Database(), JOB)["promoted"] == 0
    assert bank_files(storage_root) == []


def test_nothing_is_banked_from_a_teacher_who_did_not_opt_in(storage_root, mongo_db):
    """``saveVerifiedImages`` in the user profile is the switch: the crops of a
    teacher who leaves it off die with their job instead of outliving it."""
    a_job(mongo_db, saves_images=False)
    a_document(mongo_db, matricule="1234567")
    stage()

    counts = digit_bank.promote_job(Database(), JOB)
    assert counts["refused"] == 1 and counts["samples"] == 0
    assert bank_files(storage_root) == []
    # and they are left where the job cleanup will take them
    assert len(staged_files(storage_root)) == 1


def test_a_job_whose_owner_is_gone_banks_nothing(storage_root, mongo_db):
    mongo_db["eval_jobs"].insert_one({"job_id": JOB, "user_id": "ghost"})
    a_document(mongo_db, matricule="1234567")
    stage()
    assert digit_bank.promote_job(Database(), JOB)["refused"] == 1
    assert bank_files(storage_root) == []


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
