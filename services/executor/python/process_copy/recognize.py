"""Reading a scanned copy: its matricule, and the grades written on it.

This module was 2366 lines. It is now the surface the rest of the executor
calls, and the reading itself is split by what it works on:

    imaging     writing debug images, cutting a box out of a page
    pages       a pdf as page images, and the summary pages
    contours    finding the boxes and the digits, as contours
    digits      from a contour to a number
    matricules  the student number of a copy, and of a batch
    grades      the grades written in the cover-page table
    annotate    writing back onto a copy
    batch       running a batch in parallel processes

Everything below is re-exported from those modules, so `from
process_copy.recognize import ...` and `recognize.x` keep meaning what they
did. New code is better off importing the module that owns what it needs.
"""

# noqa: F401 throughout -- re-exported on purpose, see the docstring above
from process_copy.annotate import (  # noqa: F401
    add_grades, format_grade_text, write_box_contours, write_grade_texts)
from process_copy.batch import process_all  # noqa: F401
from process_copy.contours import (  # noqa: F401
    biggest_children, clean_and_sort_digit_contours, find_digit_contours,
    find_edges, find_grade_boxes, find_matricule_box_contours,
    get_clean_thresh, ink_rects)
from process_copy.digits import (  # noqa: F401
    allowed_decimals_with_digits, correct_decimals, extract_all_digits,
    extract_digit, extract_number, process_digits_combinations,
    random_allowed_decimals, split_digits, test)
from process_copy.grades import (  # noqa: F401
    compare_all, get_max_question, grade, grade_files, try_fix_n_questions,
    try_fix_questions)
from process_copy.imaging import (  # noqa: F401
    BLACK, GREEN, ORANGE, RED, fetch_box, get_date, get_image_from_contour,
    ignoreWrite, imwrite_contours, imwrite_png, make_square, memory_used_gb,
    storage)
from process_copy.matricules import (  # noqa: F401
    find_all_matricules, find_file_matricule, find_matricule, find_matricules,
    matricule_confidence)
from process_copy.pages import (  # noqa: F401
    create_summary, create_summary2, create_whole_summary, get_blank_page,
    gray_images, imstraighten, refresh, save_pages)
