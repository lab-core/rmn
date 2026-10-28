"""The row of matricule boxes, found the same way on any page of any template.

Job 22fb713e (MTH1007, Oct 2026) had its matricule printed on every page of
the booklet: "MATRICULE" over seven boxes, without the colon the reading of a
later page required, so no later page was ever read, and a cover page the
model misread (or whose table cell was not found) could not be put right.
These pages are drawn here; ``test_recognition`` reads handwritten digits in
them.
"""

import cv2
import numpy as np
import pytest

from process_copy.config import len_mat
from process_copy.contours import find_matricule_digit_boxes

FONT = cv2.FONT_HERSHEY_SIMPLEX


def assert_boxes(cnts, rects, tol=6):
    """The boxes found are the ones drawn, give or take the line width."""
    found = [cv2.boundingRect(c) for c in cnts]
    assert len(found) == len(rects), found
    for f, r in zip(found, rects):
        assert max(abs(a - b) for a, b in zip(f, r)) <= tol, (found, rects)


def draw_boxes(img, x0, y0, w, h, pitch, n=len_mat, thick=3):
    rects = []
    for i in range(n):
        x = x0 + i * pitch
        cv2.rectangle(img, (x, y0), (x + w - 1, y0 + h - 1), 0, thick)
        rects.append((x, y0, w, h))
    return rects


def cover_page_frame():
    """The identification table of the Polytechnique cover page, as a frame
    cuts it: labels, cell lines, the matricule boxes and a wider group box."""
    img = np.full((400, 2000), 255, np.uint8)
    cv2.rectangle(img, (60, 40), (1900, 380), 0, 4)
    cv2.line(img, (60, 160), (1900, 160), 0, 3)
    cv2.line(img, (60, 270), (1900, 270), 0, 3)
    cv2.line(img, (480, 160), (480, 380), 0, 3)
    cv2.line(img, (1420, 270), (1420, 380), 0, 3)
    cv2.putText(img, "Identification de l'etudiant(e)", (600, 120), FONT, 1.5, 0, 3)
    cv2.putText(img, "Nom :", (80, 230), FONT, 1.5, 0, 3)
    cv2.putText(img, "Signature :", (80, 340), FONT, 1.5, 0, 3)
    cv2.putText(img, "Matricule :", (500, 340), FONT, 1.5, 0, 3)
    rects = draw_boxes(img, 790, 290, 65, 62, 83)
    cv2.putText(img, "Groupe :", (1440, 340), FONT, 1.5, 0, 3)
    cv2.rectangle(img, (1680, 290), (1820, 352), 0, 3)
    return img, rects


def later_page_frame():
    """The header of a later page: a title over the boxes, a warning under them."""
    img = np.full((264, 765), 255, np.uint8)
    cv2.putText(img, "MATRICULE", (180, 90), FONT, 1.6, 0, 3)
    cv2.putText(img, "page 2", (630, 40), FONT, 1.0, 0, 2)
    rects = draw_boxes(img, 40, 115, 70, 98, 85, thick=2)
    cv2.putText(
        img, "SANS MATRICULE, CETTE PAGE EST IGNOREE", (0, 250), FONT, 0.9, 0, 2
    )
    return img, rects


@pytest.mark.parametrize("frame", [cover_page_frame, later_page_frame])
def test_the_boxes_are_found_whatever_surrounds_them(frame):
    img, rects = frame()

    assert_boxes(find_matricule_digit_boxes(img, len_mat), rects)


@pytest.mark.parametrize("frame", [cover_page_frame, later_page_frame])
def test_digits_written_in_the_boxes_do_not_hide_them(frame):
    img, rects = frame()
    for i, (x, y, w, h) in enumerate(rects):
        cv2.putText(img, str(i), (x + w // 4, y + 3 * h // 4), FONT, 1.5, 0, 4)

    assert_boxes(find_matricule_digit_boxes(img, len_mat), rects)


@pytest.mark.parametrize("index", [0, 3, len_mat - 1])
def test_a_digit_crossing_a_side_merges_with_its_box_and_it_is_put_back(index):
    # job 22fb713e: the tail of a 2 written over the bottom side of the first
    # box; the outline and the digit are one shape, no longer a rectangle
    img, rects = later_page_frame()
    x, y, w, h = rects[index]
    cv2.line(img, (x + 15, y + 30), (x + w + 12, y + h + 14), 0, 5)

    assert_boxes(find_matricule_digit_boxes(img, len_mat), rects)


def test_no_row_of_boxes_is_no_boxes():
    img = np.full((264, 765), 255, np.uint8)
    cv2.putText(img, "MATRICULE :", (40, 150), FONT, 1.6, 0, 3)
    assert find_matricule_digit_boxes(img, len_mat) == []
    assert find_matricule_digit_boxes(np.full((264, 765), 255, np.uint8), len_mat) == []


def test_a_row_of_fewer_boxes_is_not_a_matricule():
    img = np.full((264, 765), 255, np.uint8)
    draw_boxes(img, 40, 115, 70, 98, 85, n=len_mat - 2)
    assert find_matricule_digit_boxes(img, len_mat) == []
