"""Enums and question-key helpers shared by the executor modules."""

import pytest

from utils.utils import (
    Document_Status,
    Job_Status,
    ensure_within,
    question_position,
    question_sort_key,
    safe_path_component,
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


def test_safe_path_component_keeps_names_readable_but_inside_the_folder():
    assert safe_path_component("Émilie Dupont-Tremblay") == "Émilie Dupont-Tremblay"
    assert safe_path_component("../../mnt/storage/csv") == ".._.._mnt_storage_csv"
    assert safe_path_component("A/B") == "A_B"
    assert safe_path_component("..") == "_"
    assert safe_path_component("   ") == "_"
    assert safe_path_component(3.0) == "3.0"


def test_ensure_within_accepts_children_and_rejects_escapes(tmp_path):
    assert ensure_within(tmp_path / "a" / "b", tmp_path) == (tmp_path / "a" / "b").resolve()
    assert ensure_within(tmp_path, tmp_path) == tmp_path.resolve()
    with pytest.raises(ValueError):
        ensure_within(tmp_path / ".." / "elsewhere", tmp_path)
