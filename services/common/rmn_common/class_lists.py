"""The class lists of a task: one Moodle export per assignment.

A task can be given several Moodle grade exports, one per assignment (two
sections of a course, say). The task keeps a single csv, as before, with a
column saying which export each student came from: reading the matricules
and the grades works on that one file as it always did, and the end of the
task splits it again, a notes file and Moodle zips per export.

A student in two exports would have their copy graded in both assignments;
the teacher is asked which one they belong to (``duplicates``), and is
removed from the others (``combine``).

The cells are copied as text, untouched: a grade export goes back to Moodle.
"""

import csv
import io
import os
from dataclasses import dataclass, field
from typing import Dict, Iterable, List, Optional, Sequence

from rmn_common.moodle import MoodleFields as MF

# the column of the combined csv naming the export of each student; only
# written when there are several (a single export stays as Moodle wrote it)
LIST_COLUMN = "Liste RMN"


@dataclass
class ClassList:
    """One Moodle export: its name, its columns in order and its rows.

    Attributes:
        name: What the teacher sees, the file name without its extension.
        columns: The header, ``Matricule`` included.
        rows: One dict per student, by column.
    """

    name: str
    columns: List[str]
    rows: List[Dict[str, str]] = field(default_factory=list)

    def matricules(self) -> List[str]:
        """The matricules of the rows, in order."""
        return [row[MF.mat] for row in self.rows]


def list_name(filename: str, taken: Iterable[str] = ()) -> str:
    """The name of an export: its file name without the extension, made
    unique among ``taken`` with a number (``notes (2)``)."""
    base = os.path.splitext(os.path.basename(filename))[0].strip() or "liste"
    taken = set(taken)
    name, n = base, 1
    while name in taken:
        n += 1
        name = f"{base} ({n})"
    return name


def read_class_list(text: str, name: str) -> ClassList:
    """Parse a Moodle export.

    Args:
        text: The csv, as decoded text (a byte-order mark is dropped).
        name: The name the list goes by.

    Returns:
        The list; a matricule given twice keeps its first row, as the
        executor always did.

    Raises:
        ValueError: The file has no ``Matricule`` column, or a row has more
            fields than the header.
    """
    text = text.lstrip("\ufeff")
    # Moodle writes commas, a spreadsheet in French semicolons (save_csv)
    header = text.split("\n", 1)[0]
    delimiter = ";" if header.count(";") > header.count(",") else ","
    reader = csv.reader(io.StringIO(text), delimiter=delimiter)
    try:
        columns = [c.strip() for c in next(reader)]
    except StopIteration:
        raise ValueError(f"« {name} » est vide.")
    if MF.mat not in columns:
        raise ValueError(f"« {name} » n'a pas de colonne {MF.mat}.")
    rows, seen = [], set()
    for values in reader:
        if not any(v.strip() for v in values):
            continue
        if len(values) > len(columns):
            raise ValueError(f"« {name} » a une ligne invalide : {','.join(values)}")
        row = dict(zip(columns, values + [""] * (len(columns) - len(values))))
        row[MF.mat] = row[MF.mat].strip()
        if row[MF.mat] in seen:
            continue
        seen.add(row[MF.mat])
        rows.append(row)
    return ClassList(name, columns, rows)


def lists_of_combined(text: str, lists: Sequence[dict]) -> List[ClassList]:
    """Split a combined csv back into its exports.

    Args:
        text: The task's csv.
        lists: The task's ``class_lists`` (``name`` and ``columns``); with
            fewer than two, the whole file is the one list (a task made
            before several were possible has none: it is named ``notes``).

    Returns:
        The lists, in the task's order, each row with every column of the
        file (the ones the processing added included).
    """
    combined = read_class_list(text, "notes")
    if len(lists) < 2 or LIST_COLUMN not in combined.columns:
        name = lists[0]["name"] if lists else "notes"
        return [
            ClassList(
                name, [c for c in combined.columns if c != LIST_COLUMN], combined.rows
            )
        ]
    columns = [c for c in combined.columns if c != LIST_COLUMN]
    out = [ClassList(entry["name"], columns) for entry in lists]
    by_name = {c.name: c for c in out}
    for row in combined.rows:
        target = by_name.get(row.get(LIST_COLUMN))
        if target is not None:
            target.rows.append({c: v for c, v in row.items() if c != LIST_COLUMN})
    return out


def duplicates(lists: Sequence[ClassList]) -> List[dict]:
    """The students found in more than one list.

    Returns:
        ``{"matricule", "name", "lists"}`` per student, the lists in order.
    """
    where: Dict[str, List[str]] = {}
    names: Dict[str, str] = {}
    for class_list in lists:
        for row in class_list.rows:
            where.setdefault(row[MF.mat], []).append(class_list.name)
            names.setdefault(row[MF.mat], row.get(MF.name, ""))
    return [
        {"matricule": mat, "name": names[mat], "lists": found}
        for mat, found in where.items()
        if len(found) > 1
    ]


def unresolved(lists: Sequence[ClassList], assignments: Dict[str, str]) -> List[dict]:
    """The duplicates ``assignments`` does not settle: no list given, or one
    the student is not in."""
    return [
        d
        for d in duplicates(lists)
        if assignments.get(d["matricule"]) not in d["lists"]
    ]


def combine(
    lists: Sequence[ClassList], assignments: Optional[Dict[str, str]] = None
) -> str:
    """The task's csv of the lists.

    Args:
        lists: The exports, in order.
        assignments: The list of each student found in several, by matricule;
            the student is removed from the others.

    Returns:
        The csv text: the union of the columns in order of appearance, plus
        ``LIST_COLUMN`` when there are several lists.

    Raises:
        ValueError: A student is in several lists and ``assignments`` does not
            say which one (``unresolved``).
    """
    assignments = assignments or {}
    if unresolved(lists, assignments):
        raise ValueError("Des étudiants sont dans plusieurs listes.")
    columns: List[str] = []
    for class_list in lists:
        columns += [c for c in class_list.columns if c not in columns]
    several = len(lists) > 1
    if several:
        columns.append(LIST_COLUMN)
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=columns, restval="", lineterminator="\n")
    writer.writeheader()
    for class_list in lists:
        for row in class_list.rows:
            assigned = assignments.get(row[MF.mat], class_list.name)
            if assigned != class_list.name:
                continue
            writer.writerow(
                {**row, **({LIST_COLUMN: class_list.name} if several else {})}
            )
    return out.getvalue()


def metadata(lists: Sequence[ClassList]) -> List[dict]:
    """What the task keeps of each list: its name and columns."""
    return [{"name": c.name, "columns": list(c.columns)} for c in lists]


def output_columns(
    own: Sequence[str], every_list: Sequence[Sequence[str]], present: Sequence[str]
) -> List[str]:
    """The columns of one list's notes file at the end of the task.

    Args:
        own: The columns of the list's export, in order.
        every_list: The columns of each of the task's exports.
        present: The columns of the finished csv.

    Returns:
        The list's own columns still there, in its order, then those the task
        added (the grade of each question...); a column only another export
        had, or ``LIST_COLUMN``, is left out.
    """
    from_exports = {c for columns in every_list for c in columns}
    added = [c for c in present if c not in from_exports and c != LIST_COLUMN]
    return [c for c in own if c in present] + added
