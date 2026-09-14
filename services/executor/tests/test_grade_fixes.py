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


def test_an_allowed_decimal_part_is_kept_and_a_lone_digit_becomes_a_half():
    from process_copy.recognize import correct_decimals

    assert correct_decimals(7.75) == 7.75
    assert correct_decimals(7.25) == 7.25
    assert correct_decimals(7.5) == 7.5
    assert correct_decimals(8.0) == 8.0
    # one recognised digit is one written digit: the only one-digit part
    # other than "0" is "5", whatever the digit was read as
    for digit in (1, 2, 3, 4, 6, 7, 8, 9):
        assert correct_decimals(7 + digit / 10) == 7.5, digit


def test_two_unknown_digits_draw_a_random_two_digit_part():
    import random

    from process_copy.recognize import correct_decimals

    drawn = {correct_decimals(7.33, rng=random.Random(seed)) for seed in range(20)}
    assert drawn == {7.25, 7.75}
    # more digits than any allowed part: closest allowed value
    assert correct_decimals(7.875) == 7.75
    assert correct_decimals(7.125, rng=random.Random(0)) in (7.0, 7.25)
    # the allowed parts are configuration (process_copy/config.py)
    assert correct_decimals(7.7, allowed=["0", "3", "5"], rng=random.Random(1)) in (7.3, 7.5)


def test_box_candidates_are_tried_by_probability_then_drawn():
    import random

    from process_copy import recognize

    # "7.7" read with "5" as the second choice of the last digit: 7.5 is the
    # only candidate with an allowed decimal part, whatever its probability
    digits = [(None, [(0.9, 7)]), (None, [(0.6, 7), (0.3, 5)])]
    assert [n for _, n in recognize.process_digits_combinations(digits, dot=1)] == [7.5]
    # no candidate is allowed: the most probable digits with a drawn part
    digits = [(None, [(0.9, 7)]), (None, [(0.9, 3), (0.1, 4)])]
    assert [n for _, n in recognize.process_digits_combinations(digits, dot=1)] == [7.5]
    digits = [(None, [(0.9, 7)]), (None, [(0.9, 3)]), (None, [(0.9, 3)])]
    recognize.random.seed(3)
    assert recognize.process_digits_combinations(digits, dot=1)[0][1] in (7.25, 7.75)
    # no dot: whole numbers pass through, best first
    digits = [(None, [(0.6, 1), (0.4, 7)]), (None, [(0.9, 0)])]
    assert [n for _, n in recognize.process_digits_combinations(digits, dot=2)] == [10.0, 70.0]
