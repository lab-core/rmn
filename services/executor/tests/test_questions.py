"""Ignored questions (0 page, 0 point) in the executor's pure helpers."""

import os

from process_copy.add_grades import grades_to_write
from utils.merge import merge_parts
from utils.split import calculate_pages, calculate_total_expected_pages
from utils.utils import active_question_keys, ignored_positions, question_position

PAGES = {"Q1": 2, "Q2": 1, "Q3": 0, "Q4": 3}
PAGES_AS_PAIRS = [["Q1", 2], ["Q2", 1], ["Q3", 0], ["Q4", 3]]


def test_active_and_ignored_questions():
    assert active_question_keys(PAGES) == ["Q1", "Q2", "Q4"]
    assert active_question_keys(PAGES_AS_PAIRS) == ["Q1", "Q2", "Q4"]
    assert ignored_positions(PAGES) == {2}
    assert ignored_positions(PAGES_AS_PAIRS) == {2}
    assert question_position("Q10") == 9


def test_active_keys_are_sorted_numerically():
    pages = {"Q10": 1, "Q2": 1, "Q1": 0}
    assert active_question_keys(pages) == ["Q2", "Q10"]


def test_calculate_pages_skips_ignored_question():
    assert calculate_pages(PAGES) == {"Q1": [1, 2], "Q2": [3], "Q4": [4, 5, 6]}
    # cover page + 6 question pages
    assert calculate_total_expected_pages(PAGES) == 7


def test_merge_parts_use_question_keys():
    parts = merge_parts("job", PAGES_AS_PAIRS)
    assert [suffix for _, suffix in parts] == [
        "_cover.pdf",
        "_Q1.pdf",
        "_Q2.pdf",
        "_Q4.pdf",
    ]
    assert os.path.basename(parts[0][0]) == "job"
    assert [os.path.basename(folder) for folder, _ in parts[1:]] == ["Q1", "Q2", "Q4"]


def test_grades_to_write_leaves_ignored_box_blank():
    assert grades_to_write([5, 3, 9, 7], 4, {2}) == ["5", "3", "", "7", "15"]


def test_grades_to_write_normalises_length():
    # too short (recognition found fewer boxes) and too long
    assert grades_to_write([5, 3], 4, {2}) == ["5", "3", "", "", "8"]
    assert grades_to_write([5, 3, 9, 7, 1], 4, set()) == ["5", "3", "9", "7", "24"]
    assert grades_to_write([None, 2], 2, set()) == ["", "2", "2"]
