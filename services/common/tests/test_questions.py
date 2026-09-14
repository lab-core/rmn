"""Question keys: validation, numeric order, ignored questions."""

from rmn_common.questions import (
    active_question_keys,
    ignored_positions,
    question_position,
    question_sort_key,
    validate_questions,
)

PAGES = {"Q1": 2, "Q2": 1, "Q3": 0, "Q4": 3}
PAGES_AS_PAIRS = [["Q1", 2], ["Q2", 1], ["Q3", 0], ["Q4", 3]]


def test_question_sort_key_is_numeric_not_lexicographic():
    assert sorted(["Q10", "Q2", "Q1"], key=question_sort_key) == ["Q1", "Q2", "Q10"]
    assert sorted(["Q10", "Q2", "Q1"]) == ["Q1", "Q10", "Q2"]  # the bug it avoids


def test_question_sort_key_accepts_pairs_and_odd_keys():
    assert question_sort_key(("Q7", 3)) == 7
    assert question_sort_key(["Q12", 0]) == 12
    assert question_sort_key("total") == 0


def test_active_and_ignored_questions():
    assert active_question_keys(PAGES) == ["Q1", "Q2", "Q4"]
    assert active_question_keys(PAGES_AS_PAIRS) == ["Q1", "Q2", "Q4"]
    assert ignored_positions(PAGES) == {2}
    assert ignored_positions(PAGES_AS_PAIRS) == {2}
    assert question_position("Q10") == 9


def test_active_keys_are_sorted_numerically():
    assert active_question_keys({"Q10": 1, "Q2": 1, "Q1": 0}) == ["Q2", "Q10"]


def test_validate_questions_accepts_a_well_formed_task():
    assert (
        validate_questions(
            [["Q1", 2], ["Q2", 0]],
            [["Q1", 10], ["Q2", 0]],
            [["Q1", False], ["Q2", False]],
        )
        is None
    )


def test_validate_questions_rejects_bad_keys_and_inconsistent_lists():
    assert validate_questions([["Q0", 1]], [["Q0", 1]], [["Q0", False]]) is not None
    assert (
        validate_questions([["../x", 1]], [["../x", 1]], [["../x", False]]) is not None
    )
    assert (
        validate_questions([["Q1", 1], ["Q1", 1]], [["Q1", 1]], [["Q1", False]])
        is not None
    )
    assert validate_questions([["Q1", 1]], [["Q2", 1]], [["Q1", False]]) is not None
    assert (
        validate_questions([["Q1", 0]], [["Q1", 5]], [["Q1", False]]) is not None
    )  # ignored but worth points
    assert (
        validate_questions([["Q1", 1]], [["Q1", 0]], [["Q1", False]]) is not None
    )  # graded but worth nothing
    assert validate_questions([["Q1", 1]], [["Q1", 1]], [["Q1", "true"]]) is not None


def test_validate_bonus_map():
    from rmn_common.questions import validate_bonus_map

    assert validate_bonus_map([["Q1", True], ["Q2", False]]) is None
    assert validate_bonus_map([]) is None
    assert validate_bonus_map("garbage") is not None
    assert validate_bonus_map([["Q1"]]) is not None
    assert validate_bonus_map([["Q1", True], ["Q1", False]]) is not None
    assert validate_bonus_map([["bonus", True]]) is not None
    assert validate_bonus_map([["Q1", "yes"]]) is not None
