"""The column names of a French Moodle grades export."""

import re

import pytest

from rmn_common.moodle import MoodleFields as MF


def test_the_columns_are_the_moodle_export_headers():
    # the roster a teacher uploads is Moodle's own export: these are its words
    assert (MF.mat, MF.name, MF.grade, MF.max) == (
        "Matricule",
        "Nom complet",
        "Note",
        "Note maximale",
    )
    assert MF.status_start_filter == "Remis"


# the executor picks the group column with DataFrame.filter(regex=MF.group),
# which keeps the columns the regex is found in (re.search)
@pytest.mark.parametrize("column", ["Groupe", "groupes", "Gr", "Mon groupe", "GR"])
def test_the_group_regex_finds_the_group_column(column):
    assert re.search(MF.group, column)


@pytest.mark.parametrize("column", ["Programme", "Groupe de TP 2", "Note", MF.mat])
def test_the_group_regex_ignores_other_columns(column):
    assert not re.search(MF.group, column)
