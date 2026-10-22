"""How many points a grade is worth, printed.

The cover page, the page a student is given back and anything else showing a
grade print it the same way: a grade is stored as a float, and "5.0 / 3.0" is
not how a teacher writes five out of three. Half and quarter points are kept,
because they are what the grader wrote.
"""


def format_points(value):
    """
    Print points as a teacher writes them.

    Args:
        value: The points, a number or the text of one; None or "" for a
            grade that was never given.

    Returns:
        str: The points without a decimal part when there is none ("5"), with
             it when there is ("4.5"), and empty for a missing grade.
    """
    if value is None or value == "":
        return ""
    try:
        points = float(value)
    except (TypeError, ValueError):
        return str(value)
    return str(int(points)) if points.is_integer() else str(points)
