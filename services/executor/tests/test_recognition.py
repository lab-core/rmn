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
