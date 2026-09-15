"""Formula neutralisation in the csv files the user downloads."""

import csv

import pytest

from rmn_common.spreadsheet import defuse_cell, defuse_csv


@pytest.mark.parametrize(
    "value",
    [
        '=HYPERLINK("http://x")',
        "+cmd|' /C calc'!A0",
        "-2+3+cmd",
        "@SUM(A1)",
        "\t=1+1",
        "\r=1+1",
        "=",
        "-a",
    ],
)
def test_formula_prefixes_are_neutralised(value):
    assert defuse_cell(value) == "'" + value
    # idempotent: a second pass does not stack apostrophes
    assert defuse_cell(defuse_cell(value)) == "'" + value


@pytest.mark.parametrize(
    "value",
    ["Dupont, Jean", "12.5", "-3", "+1.5", "-", " - ", "", "Remis pour évaluation", "1e3", "-0"],
)
def test_data_is_left_alone(value):
    assert defuse_cell(value) == value


def test_non_strings_pass_through():
    assert defuse_cell(None) is None
    assert defuse_cell(3) == 3


def test_defuse_csv_rewrites_only_the_hostile_cells(tmp_path):
    path = tmp_path / "notes.csv"
    rows = [
        ["Matricule", "Nom complet", "Note", "Dernière modification (note)", "Statut"],
        ["1234567", '=HYPERLINK("http://evil";"Jean")', "12.5", "-", "Remis"],
        ["2345678", "Dupont, Marie", "-3", "", "@cmd"],
    ]
    with open(path, "w", newline="", encoding="utf-8") as f:
        csv.writer(f).writerows(rows)

    assert defuse_csv(path) == 2
    with open(path, newline="", encoding="utf-8") as f:
        result = list(csv.reader(f))
    assert result[0] == rows[0]
    assert result[1] == ["1234567", '\'=HYPERLINK("http://evil";"Jean")', "12.5", "-", "Remis"]
    assert result[2] == ["2345678", "Dupont, Marie", "-3", "", "'@cmd"]
    # nothing left to do on a second pass, and no temp file left behind
    assert defuse_csv(path) == 0
    assert [p.name for p in tmp_path.iterdir()] == ["notes.csv"]
