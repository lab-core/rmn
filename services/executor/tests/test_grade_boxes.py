"""The grade boxes: aligned, in a column or in a row, and empty on the template.

The frame a template gives may hold more than the grade boxes: the labels
(Q1, Q2...) and the maximums (/6, /8...) printed in the cells beside them.
On the template the grade boxes are the aligned ones left empty; on a copy,
where they hold the grades, the aligned boxes covering the most area.
"""

import cv2
import numpy as np
import pytest

from process_copy.contours import find_grade_boxes
from process_copy.imaging import cells_in_frame, frame_to_cells

FONT = cv2.FONT_HERSHEY_SIMPLEX


def assert_boxes(cnts, rects, tol=6):
    """The boxes found are the ones drawn, give or take the line width."""
    found = [cv2.boundingRect(c) for c in cnts]
    assert len(found) == len(rects), found
    for f, r in zip(found, rects):
        assert max(abs(a - b) for a, b in zip(f, r)) <= tol, (found, rects)


def column_table(grades=None, maximums_width=140):
    """The Réservé table of a cover page: label, grade and maximum columns,
    five questions and a taller total. Returns the frame and the grade cells
    (inside the lines)."""
    img = np.full((1100, 700), 255, np.uint8)
    tops = [50, 170, 290, 410, 530, 650, 830]
    # the maximums narrower than the grades, as printed
    xs = [40, 220, 430, 430 + maximums_width]
    for x in xs:
        cv2.line(img, (x, tops[0]), (x, tops[-1]), 0, 4)
    for y in tops:
        cv2.line(img, (xs[0], y), (xs[-1], y), 0, 4)
    cells = []
    for i, (top, bottom) in enumerate(zip(tops, tops[1:])):
        label = f"Q{i + 1}" if i < 5 else "Total"
        cv2.putText(img, label, (55, (top + bottom) // 2 + 15), FONT, 1.3, 0, 3)
        cv2.putText(img, "/8", (450, (top + bottom) // 2 + 15), FONT, 1.3, 0, 3)
        cells.append((xs[1] + 3, top + 3, xs[2] - xs[1] - 5, bottom - top - 5))
        if grades:
            cv2.putText(img, grades[i], (xs[1] + 60, (top + bottom) // 2 + 20), FONT, 2, 0, 5)
    return img, cells


def row_table(grades=None):
    """The same table laid out in a row: labels above, grade boxes under them."""
    img = np.full((400, 1400), 255, np.uint8)
    xs = [40, 240, 440, 640, 840]
    ys = [60, 150, 330]
    for x in xs:
        cv2.line(img, (x, ys[0]), (x, ys[-1]), 0, 4)
    for y in ys:
        cv2.line(img, (xs[0], y), (xs[-1], y), 0, 4)
    cells = []
    for i, (left, right) in enumerate(zip(xs, xs[1:])):
        label = f"Q{i + 1}" if i < 3 else "Total"
        cv2.putText(img, label, (left + 40, 125), FONT, 1.3, 0, 3)
        cells.append((left + 3, ys[1] + 3, right - left - 5, ys[2] - ys[1] - 5))
        if grades:
            cv2.putText(img, grades[i], (left + 60, 270), FONT, 2, 0, 5)
    # an unrelated, empty pair of small boxes elsewhere in the frame
    cv2.rectangle(img, (1000, 200), (1040, 240), 0, 3)
    cv2.rectangle(img, (1100, 200), (1140, 240), 0, 3)
    return img, cells


@pytest.mark.parametrize("table", [column_table, row_table])
def test_the_empty_aligned_boxes_of_the_template_are_the_grade_boxes(table):
    img, cells = table()

    assert_boxes(find_grade_boxes(img, thick=1), cells)


def test_on_a_copy_the_biggest_aligned_boxes_are_the_grade_boxes():
    img, cells = column_table(["5", "8", "11", "6.5", "0", "30.5"])

    assert_boxes(find_grade_boxes(img, thick=0), cells)


def test_on_a_copy_written_in_a_row_the_grade_boxes_are_found():
    img, cells = row_table(["2", "3", "4", "9"])

    assert_boxes(find_grade_boxes(img, thick=0), cells)


def test_a_known_number_of_boxes_comes_first():
    """Five boxes aligned at the top of the frame, bigger than the grade boxes
    of a copy: told how many boxes there are, the grade boxes win."""
    img, cells = row_table(["2", "3", "4", "9"])
    big = np.full((600, img.shape[1]), 255, np.uint8)
    for i in range(5):
        cv2.rectangle(big, (40 + 260 * i, 40), (280 + 260 * i, 560), 0, 4)
        cv2.putText(big, "x", (120 + 260 * i, 300), FONT, 3, 0, 6)
    frame = np.vstack([big, img])
    shifted = [(x, y + big.shape[0], w, h) for x, y, w, h in cells]

    assert len(find_grade_boxes(frame, thick=0)) == 5
    assert_boxes(find_grade_boxes(frame, thick=0, n=4), shifted)


def test_a_box_whose_sides_are_hidden_is_put_back_between_its_neighbours():
    img, cells = column_table()
    # a grade written over the lines of the third box
    x, y, w, h = cells[2]
    cv2.rectangle(img, (x - 10, y + 10), (x + w + 10, y + h - 10), 0, -1)

    found = [cv2.boundingRect(c) for c in find_grade_boxes(img, thick=0)]

    assert len(found) == len(cells)
    assert abs(found[2][1] - y) <= 10 and abs(found[2][3] - h) <= 15


def test_the_boxes_the_frame_cuts_are_left_out_with_a_border():
    """A frame cutting through the label and maximum columns: the border closes
    them, and they are dropped."""
    img, cells = column_table()
    frame = img[:, 120:520]
    inside = [(x - 120, y, w, h) for x, y, w, h in cells]

    assert_boxes(find_grade_boxes(frame, add_border=True, thick=0), inside)


def test_on_a_copy_the_boxes_of_the_template_tell_the_grades_from_their_neighbours():
    """Maximums as wide as the grades, all filled: the rules cannot tell the
    columns apart, the boxes of the template can."""
    template, cells = column_table(maximums_width=210)
    on_template = find_grade_boxes(template, thick=1)
    assert_boxes(on_template, cells)
    like = [cv2.boundingRect(c) for c in on_template]
    copy, _ = column_table(["5", "8", "11", "6.5", "0", "30.5"], maximums_width=210)
    # a scan a few pixels off the template
    shifted = np.full_like(copy, 255)
    shifted[12:, 15:] = copy[:-12, :-15]

    found = find_grade_boxes(shifted, thick=0, like=like)

    assert_boxes(found, [(x + 15, y + 12, w, h) for x, y, w, h in cells])


def test_template_boxes_far_from_any_run_leave_the_choice_to_the_rules():
    copy, cells = column_table(["5", "8", "11", "6.5", "0", "30.5"])
    far = [(x + 600, y + 600, w, h) for x, y, w, h in cells]

    assert_boxes(find_grade_boxes(copy, thick=0, like=far), cells)


def test_the_cells_of_a_template_land_on_the_same_place_of_any_frame():
    page = np.full((3300, 2550), 255, np.uint8)
    box = (0.82, 0.96, 0.15, 0.55)
    rects = [(30, 40, 200, 110), (30, 160, 200, 110)]
    cells = frame_to_cells(rects, box, page.shape)
    assert cells_in_frame(cells, box, page.shape) == rects

    # the overlay tries wider frames: the cells move with their origin
    wider = (0.81, 0.97, 0.14, 0.56)
    dx = int(box[0] * 2550) - int(wider[0] * 2550)
    dy = int(box[2] * 3300) - int(wider[2] * 3300)
    assert cells_in_frame(cells, wider, page.shape) == [
        (x + dx, y + dy, w, h) for x, y, w, h in rects
    ]
    assert cells_in_frame(None, box, page.shape) is None


def test_a_frame_without_any_box_gives_none():
    img = np.full((300, 300), 255, np.uint8)
    cv2.putText(img, "Total", (40, 150), FONT, 1.5, 0, 3)

    assert find_grade_boxes(img, thick=0) == []
