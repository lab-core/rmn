"""The grades written on a copy where its template has its grade boxes.

End to end through ``annotate.add_grades``, the way finalizing writes them: a
copy moved or turned by the scan gets its grades in its grade boxes, and a
copy whose boxes are not certainly found gets none (it is left for a human)
rather than grades written in a neighbouring column.
"""

import shutil
from pathlib import Path
from typing import Any

import cv2
import numpy as np
import pymupdf
import pytest

from process_copy import add_grades as module
from process_copy.annotate import (
    BOX_FROM_TEMPLATE,
    RULES,
    TEMPLATE_POSITION,
    WRITTEN,
    add_grades,
)
from process_copy.contours import template_grade_layout
from process_copy.database import Database
from tests.test_grade_boxes import AT, BOX, GRADES, column_table, page_with

pytestmark = pytest.mark.skipif(
    shutil.which("pdftoppm") is None, reason="poppler not installed"
)


def pdf_of(page: np.ndarray, path: Path) -> str:
    """A letter page holding ``page`` as its scan, at 300 dpi."""
    png = path.with_suffix(".png")
    cv2.imwrite(str(png), page)
    with pymupdf.open() as document:
        sheet = document.new_page(width=612, height=792)
        sheet.insert_image(sheet.rect, filename=str(png))
        document.save(str(path))
    return str(path)


def red_centres(path: str) -> np.ndarray:
    """The centre of each grade written on the page, in pixels at 300 dpi,
    top to bottom."""
    with pymupdf.open(path) as document:
        pix = document[0].get_pixmap(dpi=300)
    img = np.frombuffer(pix.samples, np.uint8).reshape(pix.height, pix.width, pix.n)
    red = (img[:, :, 0] > 150) & (img[:, :, 1] < 100) & (img[:, :, 2] < 100)
    red = cv2.dilate(red.astype(np.uint8), np.ones((25, 25), np.uint8))
    n, _, stats, found = cv2.connectedComponentsWithStats(red)
    return np.array(sorted(found[1:].tolist(), key=lambda c: c[1]))


def grade_cells(dx: int = 0, dy: int = 0) -> np.ndarray:
    """The centres of the grade boxes of the table moved by (dx, dy)."""
    _, cells = column_table(maximums_width=210)
    return np.array(
        [[AT[0] + dx + x + w / 2, AT[1] + dy + y + h / 2] for x, y, w, h in cells]
    )


@pytest.fixture(scope="module")
def layout() -> dict:
    """The layout of a template whose maximums are as wide as its grades."""
    template, _ = column_table(maximums_width=210)
    found, _ = template_grade_layout(page_with(template)[0], BOX)
    return found


@pytest.mark.parametrize("dx, dy", [(-50, -160), (60, -200), (0, 140), (-80, 0)])
def test_the_grades_are_written_in_the_grade_boxes_of_a_moved_copy(
    tmp_path: Path, layout: dict, dx: int, dy: int
) -> None:
    copy, _ = column_table(GRADES, maximums_width=210)
    pdf = pdf_of(page_with(copy, dx, dy)[0], tmp_path / "copy.pdf")
    out = tmp_path / "graded.pdf"

    numbers = [1, 2, 3, 4, 0, 10]
    placed = add_grades(numbers, pdf, BOX, str(out), shape=(2550, 3300), layout=layout)

    assert placed == WRITTEN
    written = red_centres(str(out))
    assert len(written) == len(numbers)
    # each grade in its box, not in the maximums 210 px to the right
    assert np.abs(written - grade_cells(dx, dy)).max() <= 40


def test_a_copy_whose_boxes_are_not_certain_has_its_grades_where_the_template_has_them(
    tmp_path: Path, layout: dict
) -> None:
    """Four columns as wide as the grades and no narrower label column: the
    grade and maximum columns of the template fit it in three places. The
    grades go where the template has its boxes, and the copy is flagged."""
    copy = np.full((1100, 1000), 255, np.uint8)
    xs = [40, 250, 460, 670, 880]
    for x in xs:
        cv2.line(copy, (x, 50), (x, 830), 0, 4)
    for y in [50, 170, 290, 410, 530, 650, 830]:
        cv2.line(copy, (xs[0], y), (xs[-1], y), 0, 4)
    pdf = pdf_of(page_with(copy, -150)[0], tmp_path / "copy.pdf")
    out = tmp_path / "graded.pdf"

    placed = add_grades([1] * 6, pdf, BOX, str(out), shape=(2550, 3300), layout=layout)

    assert placed == TEMPLATE_POSITION
    # the boxes of the template, not moved with the copy
    assert np.abs(red_centres(str(out)) - grade_cells()).max() <= 40


def test_an_older_template_gets_its_layout_when_its_job_is_finalized(
    storage_root: Path, mongo_db: Any
) -> None:
    template, _ = column_table()
    path = storage_root / "template" / "front.png"
    path.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(path), cv2.cvtColor(page_with(template)[0], cv2.COLOR_GRAY2BGR))
    mongo_db["template"].insert_one(
        {
            "template_id": "front",
            "template_file_id": "template/front.png",
            "grade_box": BOX,
        }
    )
    db = Database()

    layout = module.template_layout(db, "front", BOX)

    assert layout is not None and len(layout["boxes"]) == 6
    assert db.get_template_grade_layout("front") == layout
    # a template without its file has none to give: the rules read its copies
    mongo_db["template"].insert_one({"template_id": "bare", "grade_box": BOX})
    assert module.template_layout(db, "bare", BOX) is None


def test_a_page_drawn_without_the_layout_is_drawn_again(layout: dict) -> None:
    texts = ["1", "2", "3"]
    before = module.cover_signature(texts, BOX)

    assert module.cover_signature(texts, BOX, layout) != before
    assert module.cover_signature(texts, BOX, layout) == module.cover_signature(
        texts, BOX, layout
    )
    assert before["version"] == module.COVER_WRITER_VERSION == 5


@pytest.mark.parametrize("scale", [0.96, 1.03])
def test_a_copy_printed_smaller_or_larger_gets_its_grades_in_its_boxes(
    tmp_path: Path, layout: dict, scale: float
) -> None:
    """16 of the 101 local MTH1007 copies were printed at 96%: boxes 4%
    smaller, rows 4 px closer, 22 px off at the bottom of the table."""
    copy, _ = column_table(GRADES, maximums_width=210)
    copy = cv2.resize(copy, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)
    pdf = pdf_of(page_with(copy, -57, 10)[0], tmp_path / "copy.pdf")
    out = tmp_path / "graded.pdf"

    numbers = [1, 2, 3, 4, 0, 10]
    assert add_grades(numbers, pdf, BOX, str(out), shape=(2550, 3300), layout=layout)

    # the boxes of the scaled table, from its top left corner
    cells = (grade_cells() - np.array(AT)) * scale + np.array(AT) + np.array([-57, 10])
    assert np.abs(red_centres(str(out)) - cells).max() <= 40


def test_a_box_put_back_from_the_template_flags_the_copy(
    tmp_path: Path, layout: dict
) -> None:
    copy, cells = column_table(GRADES, maximums_width=210)
    # a grade written over the lines of the third box
    x, y, w, h = cells[2]
    cv2.rectangle(copy, (x - 10, y + 10), (x + w + 10, y + h - 10), 0, -1)
    pdf = pdf_of(page_with(copy, 20, -30)[0], tmp_path / "copy.pdf")
    out = tmp_path / "graded.pdf"

    placed = add_grades([1] * 6, pdf, BOX, str(out), shape=(2550, 3300), layout=layout)

    assert placed == BOX_FROM_TEMPLATE
    assert np.abs(red_centres(str(out)) - grade_cells(20, -30)).max() <= 40


def test_grades_placed_without_a_layout_flag_the_copy(tmp_path: Path) -> None:
    copy, _ = column_table(GRADES)
    pdf = pdf_of(page_with(copy)[0], tmp_path / "copy.pdf")

    placed = add_grades(
        [1] * 6, pdf, BOX, str(tmp_path / "out.pdf"), shape=(2550, 3300)
    )

    assert placed == RULES
