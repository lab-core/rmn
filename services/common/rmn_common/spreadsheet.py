"""Neutralise spreadsheet formulas in the csv files handed to the user.

Excel and LibreOffice evaluate a cell that starts with ``=``, ``+``, ``-``,
``@`` (and, after a tab or carriage return, the rest of the cell) as a
formula when a csv is opened, which lets a value from the class list
(a name, a status, a comment column) run ``=HYPERLINK`` or a DDE command
on the teacher's machine. The grades csv is written by pandas from the
uploaded roster, so every text cell is passed through here before the file
is stored.
"""

import csv
import os
import tempfile

FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")


def _is_number(value):
    try:
        float(value)
    except ValueError:
        return False
    return True


def defuse_cell(value):
    """Prefix a cell that a spreadsheet would evaluate with an apostrophe.

    Numbers (``-3``, ``+1.5``) and the bare ``-`` placeholder of the Moodle
    date column are left alone: they are data, not formulas, and the
    executor compares the placeholder literally. Applying the function
    twice changes nothing.
    """
    if not isinstance(value, str) or not value:
        return value
    if not value.startswith(FORMULA_PREFIXES):
        return value
    stripped = value.strip()
    if stripped == "-" or _is_number(stripped):
        return value
    return "'" + value


def defuse_csv(path):
    """Rewrite the csv at ``path`` with every formula-looking cell defused.

    The file is read and written as text (header included) so that
    numeric columns, empty cells and quoting survive the round trip; the
    result replaces the original atomically.

    Returns:
        The number of cells that were changed.
    """
    changed = 0
    directory = os.path.dirname(os.path.abspath(path))
    with open(path, newline="", encoding="utf-8") as src:
        reader = csv.reader(src)
        fd, tmp = tempfile.mkstemp(dir=directory, suffix=".csv")
        try:
            with os.fdopen(fd, "w", newline="", encoding="utf-8") as dst:
                writer = csv.writer(dst)
                for row in reader:
                    defused = [defuse_cell(cell) for cell in row]
                    changed += sum(1 for a, b in zip(row, defused) if a != b)
                    writer.writerow(defused)
            os.replace(tmp, path)
        except BaseException:
            os.unlink(tmp)
            raise
    return changed
