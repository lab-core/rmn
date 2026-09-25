"""The digit recogniser on real scanned boxes (see fixtures/recognition/README.md).

These are the only tests that load the Keras model. Each crop is pasted on a
blank page at the position its box has on a cover page, then graded exactly
as ``grade_files`` and ``find_matricules`` do.
"""

import json
from pathlib import Path

import cv2
import numpy as np
import pandas as pd
import pytest

from process_copy import recognize
from rmn_common.moodle import MoodleFields as MF

EXECUTOR = Path(__file__).resolve().parent.parent
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "recognition"
SPEC = json.loads((FIXTURES / "expected.json").read_text())


@pytest.fixture(scope="module")
def classifier():
    from process_copy.classifier import load_classifier

    return load_classifier(str(EXECUTOR / "digit_recognizer.tflite"))


def page_with(crop_file, box):
    """A blank page with the crop pasted where its box sits."""
    width, height = SPEC["page_shape"]
    page = np.full((height, width), 255, np.uint8)
    crop = cv2.imread(str(FIXTURES / crop_file), cv2.IMREAD_GRAYSCALE)
    assert crop is not None, crop_file
    x1, y1 = int(box[0] * width), int(box[2] * height)
    page[y1 : y1 + crop.shape[0], x1 : x1 + crop.shape[1]] = crop
    return page


def check_known_miss(case, correct, found):
    """xfail a crop the model is known to misread; a known miss that is now read
    correctly must be un-flagged (strict, like an XPASS), so an improvement is
    recorded in expected.json instead of hiding behind the flag."""
    if not case.get("known_miss"):
        return
    if correct:
        pytest.fail(
            f"{case['file']} is read correctly now: set known_miss to false "
            "(or regenerate the fixtures)"
        )
    pytest.xfail(f"known misread of {case['file']}: {found}")


@pytest.mark.parametrize("case", SPEC["grades"], ids=lambda c: c["file"])
def test_grade_boxes_are_read_and_checked_against_the_total(case, classifier):
    page = page_with(case["file"], SPEC["grade_box"])
    matched, numbers, _cropped, _images, boxes = recognize.grade(
        page, SPEC["grade_box"], classifier=classifier, max_grade=30, max_question=12
    )
    assert len(boxes) == 6  # Q1..Q4, Bonus, Total
    numbers = [float(n) for n in numbers]
    check_known_miss(case, matched and numbers == case["numbers"], numbers)
    assert matched, case["note"]
    assert numbers == case["numbers"], case["note"]


@pytest.mark.parametrize("case", SPEC["matricules"], ids=lambda c: c["file"])
def test_handwritten_matricule_is_read_from_its_boxes(case, classifier):
    page = page_with(case["file"], SPEC["matricule_box"])
    found, _id_box, _id_csv = recognize.find_matricule(
        [page],
        SPEC["matricule_box"],
        SPEC["regular_matricule_box"],
        classifier,
        [],
        separate_box=True,
    )
    check_known_miss(case, found == case["matricule"], found)
    assert found == case["matricule"]


@pytest.fixture(scope="module")
def class_list():
    """A Moodle grades table holding the matricule of every fixture page."""
    matricules = [case["matricule"] for case in SPEC["matricules"]]
    return pd.DataFrame(
        {MF.name: [f"Student {m}" for m in matricules]},
        index=pd.Index(matricules, name=MF.mat),
    )


@pytest.mark.parametrize("case", SPEC["matricules"], ids=lambda c: c["file"])
def test_matricule_is_found_in_the_class_list_even_when_misread(
    case, classifier, class_list
):
    # production passes the class lists: the candidates are walked by
    # probability and the first matricule that exists wins, so a page the model
    # misreads standalone is still matched (config.known_mistmatch_matricule
    # adds the digits it does not propose, with probability 0)
    page = page_with(case["file"], SPEC["matricule_box"])
    found, _id_box, index = recognize.find_matricule(
        [page],
        SPEC["matricule_box"],
        SPEC["regular_matricule_box"],
        classifier,
        [class_list],
        separate_box=True,
    )
    assert (found, index) == (case["matricule"], 0)


# ------------------------------------------------------ matricule confidence


def _read(digits):
    """``possible_digits`` of a clean read of ``digits`` (one box, sure)."""
    return [{int(d): 1.0} for d in digits]


def test_a_clean_read_without_roster_is_certain():
    assert recognize.matricule_confidence(_read("2012345"), "2012345") == pytest.approx(1.0)


def test_without_roster_the_confidence_is_the_likelihood_of_the_digits():
    digits = _read("2012345")
    digits[6] = {5: 0.6, 6: 0.4}
    assert recognize.matricule_confidence(digits, "2012345") == pytest.approx(0.6)
    assert recognize.matricule_confidence(digits, "2012346") == pytest.approx(0.4)


def test_the_roster_settles_a_digit_the_model_hesitates_on():
    digits = _read("2012345")
    digits[6] = {5: 0.6, 6: 0.4}
    # 2012346 is not a student: 2012345 is the only one the read fits
    confidence = recognize.matricule_confidence(digits, "2012345", ["2012345", "1999999"])
    assert confidence > 0.99


def test_a_student_missing_from_the_roster_is_not_matched_confidently():
    # the copy says 2012345; the csv only has a student two digits away
    confidence = recognize.matricule_confidence(_read("2012345"), "2012399", ["2012399", "1999999"])
    assert confidence < 0.2


def test_a_matricule_outside_the_roster_is_at_most_half_its_likelihood():
    assert recognize.matricule_confidence(_read("2012345"), "2012345", ["1999999"]) == pytest.approx(0.5)


def test_nothing_read_has_no_confidence():
    assert recognize.matricule_confidence(_read("2012345"), None) == 0.0
    assert recognize.matricule_confidence([{} for _ in range(7)], "2012345") == 0.0


def test_the_confidence_is_a_plain_float():
    # it goes into a json socket payload: numpy scalars are not serialisable
    digits = [{int(d): np.float32(1.0)} for d in "2012345"]
    assert type(recognize.matricule_confidence(digits, "2012345", ["2012345"])) is float


@pytest.mark.parametrize("case", SPEC["matricules"], ids=lambda c: c["file"])
def test_the_confidence_of_a_real_read_tells_a_clean_read_from_a_rescued_one(case, classifier, class_list):
    page = page_with(case["file"], SPEC["matricule_box"])
    args = ([page], SPEC["matricule_box"], SPEC["regular_matricule_box"], classifier)
    found, _id_box, _index, confidence = recognize.find_matricule(
        *args, [class_list], separate_box=True, return_confidence=True)
    alone = recognize.find_matricule(*args, [], separate_box=True)[0]
    assert found == case["matricule"]
    if alone == case["matricule"]:
        assert confidence >= 0.9
    else:
        # the model misreads it on its own: right thanks to the class list,
        # but worth a look
        assert confidence < 0.9


@pytest.mark.parametrize("case", SPEC["matricules"], ids=lambda c: c["file"])
def test_a_copy_whose_student_is_not_in_the_csv_gets_a_low_confidence(case, classifier, class_list):
    others = class_list.drop(index=case["matricule"])
    page = page_with(case["file"], SPEC["matricule_box"])
    found, _id_box, index, confidence = recognize.find_matricule(
        [page], SPEC["matricule_box"], SPEC["regular_matricule_box"], classifier, [others],
        separate_box=True, return_confidence=True)
    # no other student is made of the digits read: the read matricule is kept,
    # outside the csv (the copy goes to validation), at most half confident
    assert index is None
    assert confidence <= 0.5


def test_the_digits_of_a_matricule_are_staged_and_banked_with_what_a_human_confirms(
    classifier, storage_root, mongo_db
):
    """The bank end to end: the recogniser's own crops, labelled by a validation.

    Only the size and the pairing are checked here -- what the model read does
    not matter, and must not: the point of the bank is the digits it gets
    wrong, labelled by the human who put them right.
    """
    from process_copy import digit_bank
    from process_copy.database import Database

    case = SPEC["matricules"][0]
    job_id = "job-recognition"
    page = page_with(case["file"], SPEC["matricule_box"])

    with digit_bank.recording(job_id, 4, digit_bank.MATRICULE):
        recognize.find_matricule(
            [page], SPEC["matricule_box"], SPEC["regular_matricule_box"], classifier,
            [], separate_box=True)

    staged = sorted((storage_root / digit_bank.STAGED_DIR / job_id).rglob("*.npz"))
    assert staged, "reading a matricule stages its crops"
    with np.load(staged[0], allow_pickle=False) as data:
        crops = data["crops"]
    assert crops.shape == (7, 64, 64), "seven digits, at the bank's size"
    assert crops.dtype == np.uint8 and crops.max() == 255, "the mask the model saw"

    mongo_db["eval_jobs"].insert_one(
        {"job_id": job_id, "user_id": "u", "validate_matricule": True})
    mongo_db["users"].insert_one({"username": "u", "saveVerifiedImages": True})
    mongo_db["job_documents"].insert_one(
        {"job_id": job_id, "document_index": 4, "status": "VALIDATED",
         "matricule": case["matricule"]})

    counts = digit_bank.promote_job(Database(), job_id)
    assert counts["promoted"] == len(staged) and counts["skipped"] == 0
    banked = sorted(
        p.parent.name for p in (storage_root / digit_bank.SAMPLES_DIR).rglob("*.png"))
    # every crop is labelled by its position in the matricule the human
    # confirmed, and nothing else lands in the bank
    assert set(banked) == set(case["matricule"])
    assert len(banked) == counts["samples"]
