"""Enums and question-key helpers shared by the executor modules."""

from utils.utils import (
    Document_Status,
    Job_Status,
    question_position,
    question_sort_key,
)


def test_status_values_match_what_the_server_stores():
    assert Job_Status.QUEUED.value == "QUEUED"
    assert Job_Status.FINALIZING.value == "FINALIZING"
    # the two statuses whose value is not their name
    assert Document_Status.TO_VALIDATE.value == "TO VALIDATE"
    assert Document_Status.HIGH_ACCURACY.value == "HIGH ACCURACY"


def test_question_sort_key_is_numeric_not_lexicographic():
    assert sorted(["Q10", "Q2", "Q1"], key=question_sort_key) == ["Q1", "Q2", "Q10"]
    assert sorted(["Q10", "Q2", "Q1"]) == ["Q1", "Q10", "Q2"]  # the bug it avoids


def test_question_sort_key_accepts_pairs_and_odd_keys():
    assert question_sort_key(("Q7", 3)) == 7
    assert question_sort_key(["Q7", 3]) == 7
    assert question_sort_key("cover") == 0
    assert question_position("Q1") == 0
    assert question_position("Q12") == 11
