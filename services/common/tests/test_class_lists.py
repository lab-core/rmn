import csv
import io

import pytest

from rmn_common.class_lists import (
    LIST_COLUMN,
    combine,
    duplicates,
    list_name,
    lists_of_combined,
    metadata,
    output_columns,
    read_class_list,
    unresolved,
)

SECTION_A = (
    "\ufeffIdentifiant,Nom complet,Matricule,Note\n"
    "Participant 1,Alice A,0123456,\n"
    "Participant 2,Bob B,2345678,\n"
)
SECTION_B = (
    "Identifiant,Nom complet,Matricule,Groupe,Note\n"
    "Participant 7,Carl C,3456789,02,\n"
    "Participant 8,Bob B,2345678,02,\n"
)


def rows(text):
    return list(csv.DictReader(io.StringIO(text)))


def test_a_list_keeps_its_cells_as_text_and_drops_the_byte_order_mark():
    a = read_class_list(SECTION_A, "A")
    assert a.columns == ["Identifiant", "Nom complet", "Matricule", "Note"]
    assert a.matricules() == ["0123456", "2345678"]  # the leading 0 stays


def test_a_list_separated_by_semicolons_is_read_too():
    a = read_class_list("Nom complet;Matricule;Note\nAlice, A;0123456;12,5\n", "A")
    assert a.rows == [
        {"Nom complet": "Alice, A", "Matricule": "0123456", "Note": "12,5"}
    ]


def test_a_list_without_matricules_or_with_a_long_row_is_refused():
    with pytest.raises(ValueError, match="Matricule"):
        read_class_list("Nom,Note\nAlice,\n", "A")
    with pytest.raises(ValueError, match="ligne invalide"):
        read_class_list("Matricule,Note\n1,2,3\n", "A")
    with pytest.raises(ValueError, match="vide"):
        read_class_list("", "A")


def test_a_matricule_given_twice_in_one_list_keeps_its_first_row():
    a = read_class_list("Matricule,Nom complet\n1,First\n1,Second\n", "A")
    assert [r["Nom complet"] for r in a.rows] == ["First"]


def test_names_come_from_the_files_and_stay_unique():
    assert list_name("/tmp/Section A.csv") == "Section A"
    assert list_name("notes.csv", ["notes"]) == "notes (2)"
    assert list_name("notes.csv", ["notes", "notes (2)"]) == "notes (3)"


def test_a_student_in_two_lists_is_a_duplicate_until_assigned():
    lists = [read_class_list(SECTION_A, "A"), read_class_list(SECTION_B, "B")]
    assert duplicates(lists) == [
        {"matricule": "2345678", "name": "Bob B", "lists": ["A", "B"]}
    ]
    assert unresolved(lists, {}) == duplicates(lists)
    assert unresolved(lists, {"2345678": "C"}) == duplicates(lists)  # not one of his
    assert unresolved(lists, {"2345678": "B"}) == []
    with pytest.raises(ValueError):
        combine(lists)


def test_combining_keeps_each_student_once_in_the_list_chosen():
    lists = [read_class_list(SECTION_A, "A"), read_class_list(SECTION_B, "B")]
    combined = combine(lists, {"2345678": "B"})
    header = combined.splitlines()[0].split(",")
    assert header == [
        "Identifiant",
        "Nom complet",
        "Matricule",
        "Note",
        "Groupe",
        LIST_COLUMN,
    ]
    assert [(r["Matricule"], r[LIST_COLUMN], r["Groupe"]) for r in rows(combined)] == [
        ("0123456", "A", ""),
        ("3456789", "B", "02"),
        ("2345678", "B", "02"),
    ]


def test_a_single_list_is_written_without_the_list_column():
    combined = combine([read_class_list(SECTION_A, "A")])
    assert LIST_COLUMN not in combined
    assert [r["Matricule"] for r in rows(combined)] == ["0123456", "2345678"]


def test_the_combined_csv_splits_back_into_its_lists():
    lists = [read_class_list(SECTION_A, "A"), read_class_list(SECTION_B, "B")]
    combined = combine(lists, {"2345678": "A"})
    back = lists_of_combined(combined, metadata(lists))
    assert [(c.name, c.matricules()) for c in back] == [
        ("A", ["0123456", "2345678"]),
        ("B", ["3456789"]),
    ]
    assert LIST_COLUMN not in back[0].columns
    assert LIST_COLUMN not in back[0].rows[0]


def test_a_task_with_one_list_or_none_recorded_is_one_list():
    back = lists_of_combined(SECTION_A, [])
    assert [(c.name, len(c.rows)) for c in back] == [("notes", 2)]
    back = lists_of_combined(SECTION_A, [{"name": "A", "columns": []}])
    assert back[0].name == "A"


def test_a_notes_file_keeps_its_own_columns_and_those_the_task_added():
    a = ["Identifiant", "Nom complet", "Matricule", "Note"]
    b = ["Identifiant", "Nom complet", "Matricule", "Groupe", "Note"]
    present = [
        "Identifiant",
        "Nom complet",
        "Note",
        "Groupe",
        LIST_COLUMN,
        "Q1",
        "index",
    ]
    # Matricule is the index of the finished frame here: not in present
    assert output_columns(a, [a, b], present) == [
        "Identifiant",
        "Nom complet",
        "Note",
        "Q1",
        "index",
    ]
    assert output_columns(b, [a, b], present) == [
        "Identifiant",
        "Nom complet",
        "Groupe",
        "Note",
        "Q1",
        "index",
    ]
