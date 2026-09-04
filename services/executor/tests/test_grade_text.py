"""Formatting of the grades written in the boxes of the cover page."""

from process_copy.recognize import format_grade_text


def test_integral_grades_have_no_decimal_part():
    assert format_grade_text(5.0) == "5"
    assert format_grade_text(5) == "5"
    assert format_grade_text("15.0") == "15"


def test_fractional_grades_keep_their_decimals():
    assert format_grade_text(4.5) == "4.5"
    assert format_grade_text("0.25") == "0.25"


def test_missing_grade_is_blank():
    assert format_grade_text(None) == ""
    assert format_grade_text("") == ""
