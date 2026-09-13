"""The digit recogniser on real scanned boxes (see fixtures/recognition/README.md).

These are the only tests that load the Keras model. Each crop is pasted on a
blank page at the position its box has on a cover page, then graded exactly
as ``grade_files`` and ``find_matricules`` do.
"""

import json
from pathlib import Path

import cv2
import numpy as np
import pytest

from process_copy import recognize

EXECUTOR = Path(__file__).resolve().parent.parent
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "recognition"
SPEC = json.loads((FIXTURES / "expected.json").read_text())


@pytest.fixture(scope="module")
def classifier():
    from keras.models import load_model

    return load_model(str(EXECUTOR / "digit_recognizer.h5"))


def page_with(crop_file, box):
    """A blank page with the crop pasted where its box sits."""
    width, height = SPEC["page_shape"]
    page = np.full((height, width), 255, np.uint8)
    crop = cv2.imread(str(FIXTURES / crop_file), cv2.IMREAD_GRAYSCALE)
    assert crop is not None, crop_file
    x1, y1 = int(box[0] * width), int(box[2] * height)
    page[y1 : y1 + crop.shape[0], x1 : x1 + crop.shape[1]] = crop
    return page


@pytest.mark.parametrize("case", SPEC["grades"], ids=lambda c: c["file"])
def test_grade_boxes_are_read_and_checked_against_the_total(case, classifier):
    page = page_with(case["file"], SPEC["grade_box"])
    matched, numbers, _cropped, _images, boxes = recognize.grade(
        page, SPEC["grade_box"], classifier=classifier, max_grade=30, max_question=12
    )
    assert len(boxes) == 6  # Q1..Q4, Bonus, Total
    numbers = [float(n) for n in numbers]
    if case.get("known_miss"):
        pytest.xfail(f"known misread of this table: {numbers} for {case['numbers']}")
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
    if case.get("known_miss"):
        pytest.xfail(f"known misread of this page: {found} for {case['matricule']}")
    assert found == case["matricule"]
