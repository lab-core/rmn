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


def test_decimals_follow_the_configured_conversions():
    from process_copy import config
    from process_copy.recognize import correct_decimals

    # one recognised digit cannot be a two-digit quarter: .7 reads as .5
    assert correct_decimals(7.7) == 7.5
    assert correct_decimals(7.6) == 7.5
    assert correct_decimals(7.8) == 7.75
    assert correct_decimals(7.2) == 7.25
    assert correct_decimals(7.1) == 7.0
    assert correct_decimals(8.0) == 8.0
    # two recognised digits that form a quarter are kept (they used to become .5)
    assert correct_decimals(7.75) == 7.75
    assert correct_decimals(7.25) == 7.25
    # anything else snaps to the nearest allowed value
    assert correct_decimals(7.33) == 7.25
    assert correct_decimals(7.9) == 7.75
    # the tables are configuration (process_copy/config.py)
    assert correct_decimals(7.7, conversions={0.7: 0.75}) == 7.75
    assert correct_decimals(7.4, conversions={}, allowed=[0.5]) == 7.5
    assert set(config.decimal_conversions.values()) <= {0, *config.allowed_decimals_part}
