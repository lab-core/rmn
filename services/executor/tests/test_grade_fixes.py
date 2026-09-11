"""Pure helpers that reconcile the recognised grades with the csv.

They run in the grading worker with no try/except around them, so an
exception here killed the batch and, through the idle sweep, requeued the job
forever.
"""

from process_copy.recognize import (
    get_max_question,
    try_fix_n_questions,
    try_fix_questions,
)


def test_missing_questions_are_padded_even_when_the_median_was_stored_as_a_float():
    assert try_fix_n_questions(3.0, [5]) == [0, 0, 5]
    assert try_fix_n_questions(3, [0, 4, 5, 6]) == [4, 5, 6]
    assert try_fix_n_questions(None, [1]) == [1]


def test_no_max_grade_in_the_csv_disables_the_range_fixes():
    assert get_max_question(None, 4) is None
    assert try_fix_questions(None, [12, 3]) == (False, [12, 3])


def test_out_of_range_grades_are_scaled_down():
    fixed, predictions = try_fix_questions(10, [85, 3])
    assert fixed is True
    assert predictions == [8.5, 3]


def test_decimals_snap_to_the_nearest_quarter_including_three_quarters():
    from process_copy.recognize import correct_decimals

    assert correct_decimals(7.7) == 7.75  # used to come back as 7.5
    assert correct_decimals(7.9) == 7.75
    assert correct_decimals(7.6) == 7.5
    assert correct_decimals(7.3) == 7.25
    assert correct_decimals(7.1) == 7.0
    assert correct_decimals(8.0) == 8.0
