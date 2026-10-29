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

FONT = cv2.FONT_HERSHEY_SIMPLEX


def assert_boxes(cnts, rects, tol=6):
    """The boxes found are the ones drawn, give or take the line width."""
    found = [cv2.boundingRect(c) for c in cnts]
    assert len(found) == len(rects), found
    for f, r in zip(found, rects):
        assert max(abs(a - b) for a, b in zip(f, r)) <= tol, (found, rects)


def column_table(grades=None, paper=255, ink=0, line=4):
    """The Réservé table of a cover page: label, grade and maximum columns,
    five questions and a taller total. Returns the frame and the grade cells
    (inside the lines)."""
    img = np.full((1100, 700), paper, np.uint8)
    tops = [50, 170, 290, 410, 530, 650, 830]
    xs = [40, 220, 430, 570]  # the maximums narrower than the grades, as printed
    for x in xs:
        cv2.line(img, (x, tops[0]), (x, tops[-1]), ink, line)
    for y in tops:
        cv2.line(img, (xs[0], y), (xs[-1], y), ink, line)
    cells = []
    for i, (top, bottom) in enumerate(zip(tops, tops[1:])):
        label = f"Q{i + 1}" if i < 5 else "Total"
        cv2.putText(img, label, (55, (top + bottom) // 2 + 15), FONT, 1.3, 0, 3)
        cv2.putText(img, "/8", (450, (top + bottom) // 2 + 15), FONT, 1.3, 0, 3)
        cells.append(
            (
                xs[1] + line // 2 + 1,
                top + line // 2 + 1,
                xs[2] - xs[1] - line - 1,
                bottom - top - line - 1,
            )
        )
        if grades:
            cv2.putText(
                img, grades[i], (xs[1] + 60, (top + bottom) // 2 + 20), FONT, 2, 0, 5
            )
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


def boxes_table(sizes, horizontal, spacing=0, labels=True):
    """One grade box per size, drawn one after the other (sharing their lines
    when ``spacing`` is 0), with their labels in cells before them. The boxes
    share their top (a row) or their left side (a column)."""
    img = np.full((1300, 1500), 255, np.uint8)
    cells, at = [], 60
    for w, h in sizes:
        x, y = (at, 200) if horizontal else (300, at)
        cv2.rectangle(img, (x, y), (x + w, y + h), 0, 4)
        if labels:
            lx, ly = (x, y - 110) if horizontal else (x - 210, y)
            cv2.rectangle(
                img,
                (lx, ly),
                (lx + (w if horizontal else 210), ly + (110 if horizontal else h)),
                0,
                4,
            )
            cv2.putText(img, "Q", (lx + 30, ly + 70), FONT, 1.5, 0, 3)
        cells.append((x + 3, y + 3, w - 5, h - 5))
        at += (w if horizontal else h) + spacing
    return img, cells


@pytest.mark.parametrize("horizontal", [True, False])
def test_a_bigger_total_stays_in_its_run(horizontal):
    """The total box 30% bigger across the run: taller in a row, wider in a column."""
    sizes = [(180, 120)] * 4 + ([(180, 156)] if horizontal else [(234, 120)])

    img, cells = boxes_table(sizes, horizontal)

    assert_boxes(find_grade_boxes(img, thick=1), cells)


def test_a_box_drawn_apart_under_the_column_is_not_one_of_its_boxes():
    """A bonus box under the total, as wide as the grade boxes: no box is made
    up in the gap, and the column keeps its own six boxes."""
    img, cells = column_table()
    x, _, w, _ = cells[0]
    for gap in (40, 90, 150):
        frame = img.copy()
        top = cells[-1][1] + cells[-1][3] + gap
        cv2.rectangle(frame, (x - 3, top), (x + w + 2, top + 100), 0, 4)

        assert_boxes(find_grade_boxes(frame, thick=1), cells)


@pytest.mark.parametrize("spacing", [30, 45, 60])
def test_separate_boxes_spaced_apart_get_no_box_in_between(spacing):
    img, cells = boxes_table([(120, 120)] * 5, True, spacing=spacing, labels=False)

    assert_boxes(find_grade_boxes(img, thick=1), cells)


def test_the_outline_of_a_one_column_table_does_not_hide_its_cells():
    """Six boxes sharing their lines in one bordered column, labels printed
    beside it: the outline holds the boxes, it is not one."""
    img = np.full((1000, 600), 255, np.uint8)
    cells = []
    for i in range(6):
        y = 60 + 120 * i
        cv2.rectangle(img, (250, y), (450, y + 120), 0, 4)
        cv2.putText(img, f"Q{i + 1}", (120, y + 75), FONT, 1.5, 0, 3)
        cells.append((253, y + 3, 195, 115))

    assert_boxes(find_grade_boxes(img, thick=1), cells)


@pytest.mark.parametrize("paper, ink, line", [(192, 0, 4), (175, 0, 4), (255, 191, 2)])
def test_the_boxes_are_found_on_tinted_paper_and_with_light_lines(paper, ink, line):
    """Salmon (192) and goldenrod (175) paper, and thin light-grey printed lines."""
    img, cells = column_table(paper=paper, ink=ink, line=line)

    assert_boxes(find_grade_boxes(img, thick=1), cells, tol=8)


def test_a_grade_box_cut_in_two_does_not_make_the_labels_the_grade_boxes():
    """A stroke across a grade box splits it in two: the grade column has one
    box too many, and the label column, with as many boxes as grades, used to
    be taken for it. It is still the grade column: the overlay then finds one
    box too many and leaves the copy flagged."""
    img, cells = column_table(["5", "8", "11", "6.5", "0", "30.5"])
    x, y, w, h = cells[1]
    cv2.line(img, (x - 4, y + h // 2), (x + w + 4, y + h // 2), 0, 4)

    found = [cv2.boundingRect(c) for c in find_grade_boxes(img, thick=0)]

    assert all(abs(f[0] - x) <= 6 for f in found), found


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


def test_a_frame_without_any_box_gives_none():
    img = np.full((300, 300), 255, np.uint8)
    cv2.putText(img, "Total", (40, 150), FONT, 1.5, 0, 3)

    assert find_grade_boxes(img, thick=0) == []
