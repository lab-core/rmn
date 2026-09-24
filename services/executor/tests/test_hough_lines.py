"""Straight lines found by cv2.HoughLinesP, whatever the OpenCV version.

OpenCV 5 (pinned since #159) returns the segments as (N, 4) where OpenCV 4
returned (N, 1, 4); the code indexed ``line[0][2]`` and raised IndexError on
every page with a line: pages were no longer straightened, so no matricule was
read from a page, and templates with a grade box were no longer rendered.
"""

import cv2
import numpy as np
import pytest

from process_copy import recognize
from process_copy.contours import find_edges
from process_copy.imaging import hough_segments
from process_copy.pages import imstraighten
from tests.test_recognition import SPEC, class_list, classifier, page_with  # noqa: F401


def test_segments_come_out_flat_from_either_opencv_layout():
    opencv4 = np.array([[[1, 2, 3, 4]], [[5, 6, 7, 8]]])
    opencv5 = np.array([[1, 2, 3, 4], [5, 6, 7, 8]])
    for lines in (opencv4, opencv5):
        assert hough_segments(lines).tolist() == [[1, 2, 3, 4], [5, 6, 7, 8]]


def _dark_rows(page):
    rows = np.where((page < 128).any(axis=1))[0]
    return rows.max() - rows.min()


def test_a_skewed_page_is_straightened():
    page = np.full((1650, 1275), 255, np.uint8)
    # a long printed rule, tilted by about 2 degrees
    cv2.line(page, (100, 800), (1175, 838), 0, 4)

    straightened = imstraighten(page)

    assert straightened.shape == page.shape
    # the rule now spans a few rows instead of forty
    assert _dark_rows(straightened) < _dark_rows(page) / 4


def test_the_lines_found_on_a_box_are_drawn_over_it():
    box = np.full((300, 600), 255, np.uint8)
    cv2.rectangle(box, (20, 20), (580, 280), 0, 3)

    edged = find_edges(box, thick=5)

    assert edged.shape == box.shape
    assert edged.any()


@pytest.mark.parametrize("case", SPEC["matricules"][:3], ids=lambda c: c["file"])
def test_a_matricule_page_is_straightened_then_read(case, classifier, class_list):
    # the path of every copy whose matricule is not in its file name
    page = imstraighten(page_with(case["file"], SPEC["matricule_box"]))
    found, _id_box, index = recognize.find_matricule(
        [page], SPEC["matricule_box"], SPEC["regular_matricule_box"], classifier, [class_list],
        separate_box=True,
    )
    assert (found, index) == (case["matricule"], 0)
