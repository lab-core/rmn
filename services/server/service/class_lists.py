"""The class lists a task is given, as the routes receive them.

The lists themselves (reading, combining, splitting) are in
``rmn_common.class_lists``; this is the request side: uploaded files, the
teacher's choice for a student found in several lists, the answer that asks
for it, and the combined csv written to the share.
"""

import os
from typing import Dict, Iterable, List, Optional, Tuple

from flask import json

from context import storage
from rmn_common.class_lists import (
    ClassList,
    combine,
    list_name,
    read_class_list,
    unresolved,
)
from rmn_common.moodle import MoodleFields as MF
from utils.responses import Response


def _error(message: str, status: int = 400, **extra) -> Response:
    return Response(
        response=json.dumps({"response": f"Error: {message}", **extra}), status=status
    )


def read_uploads(
    files: Iterable, taken: Iterable[str] = ()
) -> Tuple[List[ClassList], Optional[Response]]:
    """The uploaded exports as lists, each named after its file.

    Args:
        files: The uploaded files (werkzeug ``FileStorage``).
        taken: Names already in use (the lists the task keeps).

    Returns:
        The lists, or the 400 answer naming the file that cannot be read.
    """
    names = list(taken)
    lists = []
    for upload in files:
        raw = upload.read()
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            text = raw.decode("latin-1")  # an old Excel export
        name = list_name(upload.filename or "liste", names)
        names.append(name)
        try:
            lists.append(read_class_list(text, name))
        except ValueError as e:
            return [], _error(str(e))
    return lists, None


def read_assignments(form) -> Tuple[Dict[str, str], Optional[Response]]:
    """The teacher's list for each student found in several, by matricule
    (form field ``assignments``, a json object)."""
    try:
        assignments = json.loads(form.get("assignments") or "{}")
    except ValueError:
        assignments = None
    if not isinstance(assignments, dict) or not all(
        isinstance(k, str) and isinstance(v, str) for k, v in assignments.items()
    ):
        return {}, _error("assignments invalide.")
    return assignments, None


def duplicates_answer(
    lists: List[ClassList], assignments: Dict[str, str]
) -> Optional[Response]:
    """The 409 that asks which list each student found in several belongs to,
    or None when there is nothing to ask."""
    pending = unresolved(lists, assignments)
    if not pending:
        return None
    return _error(
        "des étudiants sont dans plusieurs listes de classe.",
        status=409,
        duplicates=pending,
        lists=[c.name for c in lists],
    )


def write_combined(
    lists: List[ClassList], assignments: Dict[str, str], *file_ids: str
) -> None:
    """Write the task's csv of ``lists`` to each of ``file_ids``."""
    text = combine(lists, assignments)
    for file_id in file_ids:
        path = storage.abs_path(file_id)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8", newline="") as f:
            f.write(text)


def students_of(
    lists: List[ClassList], assignments: Dict[str, str]
) -> List[Dict[str, str]]:
    """The task's ``students_list``: each student once, in their list."""
    students = []
    for class_list in lists:
        for row in class_list.rows:
            if assignments.get(row[MF.mat], class_list.name) == class_list.name:
                students.append(
                    {"matricule": row[MF.mat], MF.name: row.get(MF.name, "")}
                )
    return students
