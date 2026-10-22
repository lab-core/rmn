"""How points are printed, wherever they are shown (rmn_common.grades)."""

from rmn_common.grades import format_points


def test_whole_points_have_no_decimal_part():
    assert format_points(5.0) == "5"
    assert format_points(5) == "5"
    assert format_points("15.0") == "15"


def test_half_and_quarter_points_are_kept():
    # a question out of 3.5 printed with "%d" told the student it was out of 3
    assert format_points(3.5) == "3.5"
    assert format_points(42.5) == "42.5"
    assert format_points("0.25") == "0.25"


def test_points_that_were_never_given_are_blank():
    assert format_points(None) == ""
    assert format_points("") == ""


def test_what_is_not_a_number_is_left_as_it_is():
    assert format_points("absent") == "absent"
