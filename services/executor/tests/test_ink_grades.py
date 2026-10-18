"""Reading the grade a teacher wrote on a graded question page.

The fixtures are real graded pages with the matricule destroyed in the raster
(``fixtures/ink_grades/build_fixtures.py``). Real ink is the point: the shapes
graders actually draw are what this has to survive, and no hand-built stroke
reproduces them.
"""

import json
import os

import cv2
import numpy as np
import pymupdf
import pytest

from process_copy import ink_grades, recognize
from process_copy.classifier import load_classifier
from process_copy.config import matricule_box

FIXTURE_DIR = os.path.join(os.path.dirname(__file__), "fixtures", "ink_grades")


def _load_expected():
    with open(os.path.join(FIXTURE_DIR, "expected.json")) as handle:
        return json.load(handle)["fixtures"]


EXPECTED = _load_expected()
ANNOTATED = [e for e in EXPECTED if e.get("source") != "raster"]


@pytest.fixture(scope="module")
def classifier():
    return load_classifier()


def _read(entry, classifier):
    """Run one fixture through the reader the way the executor will."""
    path = os.path.join(FIXTURE_DIR, entry["file"])
    with pymupdf.open(path) as doc:
        page = doc[0]
        candidates = ink_grades.grade_candidates(page, entry["max_points"])
        modal = tuple(entry["modal"]) if entry["modal"] else None
        return (
            ink_grades.pick(candidates, modal, entry["max_points"], classifier),
            candidates,
        )


@pytest.mark.parametrize("entry", ANNOTATED, ids=lambda e: e["file"][:-4])
def test_fixture_reads_the_written_grade(entry, classifier):
    reading, _ = _read(entry, classifier)
    correct = reading.grade == entry["expected"]
    if entry.get("known_miss"):
        # a known miss that starts passing must be un-flagged, so the
        # improvement is recorded rather than hidden (same rule as the
        # recognition fixtures)
        if correct:
            pytest.fail(
                f"{entry['file']} is read correctly now: clear its "
                "KNOWN_MISSES entry and rebuild the fixtures"
            )
        pytest.xfail(f"{entry['known_miss']}: read {reading.grade}")
    assert correct, entry["note"]


def test_a_page_without_annotations_reports_nothing_not_zero(classifier):
    """The worst failure this feature could have is a silent 0.

    ``process_digits_combinations`` answers ``[(1.0, 0)]`` for an empty image,
    so an unguarded reader would give a confident zero to every ungraded copy.
    """
    entry = next(e for e in EXPECTED if e["file"] == "ink_no_annotation.pdf")
    reading, candidates = _read(entry, classifier)
    assert candidates == []
    assert reading.grade is None
    assert reading.reason == "not_found"
    assert reading.confidence == 0.0


def _gray_page(path, dpi=300, shape=(2550, 3300)):
    """The page as the recogniser wants it, rendered without poppler.

    ``recognize.gray_images`` goes through pdf2image, which needs poppler in
    the PATH; CI has none, and this guard is the one test that must not be
    skipped there.
    """
    with pymupdf.open(path) as doc:
        pixmap = doc[0].get_pixmap(dpi=dpi)
    image = np.frombuffer(pixmap.samples, np.uint8).reshape(
        pixmap.height, pixmap.width, pixmap.n
    )
    gray = cv2.cvtColor(image[:, :, :3], cv2.COLOR_RGB2GRAY)
    if gray.shape != (shape[1], shape[0]):
        gray = cv2.resize(gray, shape)
    return gray


def test_the_fixtures_carry_no_readable_matricule(classifier):
    """Guards the redaction: a rebuilt fixture must not leak a student id."""
    for entry in EXPECTED:
        path = os.path.join(FIXTURE_DIR, entry["file"])
        grays = [_gray_page(path)]
        found, _, _ = recognize.find_matricule(
            grays,
            matricule_box["exam"]["regular"],
            matricule_box["exam"]["regular"],
            classifier,
            separate_box=matricule_box["exam"]["separate_box"],
        )
        assert not found, f"{entry['file']} still shows a matricule"


def test_strokes_land_where_the_page_is_drawn():
    """``/Rotate`` is applied: the strokes must sit on the ink of the render.

    The fixtures keep the landscape mediabox and ``/Rotate 270`` of the real
    copies, so this pins the transform that everything else is measured in.
    """
    path = os.path.join(FIXTURE_DIR, "ink_circled_single.pdf")
    with pymupdf.open(path) as doc:
        page = doc[0]
        assert page.rotation == 270
        assert page.rect.width < page.rect.height  # displayed portrait
        strokes = ink_grades.page_strokes(page)
        assert strokes
        for stroke in strokes:
            x0, y0, x1, y1 = stroke.bbox
            assert 0 <= x0 <= x1 <= page.rect.width
            assert 0 <= y0 <= y1 <= page.rect.height


def test_grades_are_read_from_typed_annotations_without_the_classifier():
    """A typed grade needs no recognition, so no classifier is required."""
    entry = next(e for e in EXPECTED if e["file"] == "freetext_grade.pdf")
    path = os.path.join(FIXTURE_DIR, entry["file"])
    with pymupdf.open(path) as doc:
        candidates = ink_grades.grade_candidates(doc[0], entry["max_points"])
        reading = ink_grades.pick(
            candidates, tuple(entry["modal"]), entry["max_points"], None
        )
    assert reading.source == "freetext"
    assert reading.grade == entry["expected"]


@pytest.mark.parametrize(
    "content, expected",
    [
        ("u:8.5", (8.5, None)),
        ("8.5", (8.5, None)),
        ("u:6.5/9", (6.5, 9.0)),
        ("u:6,5", (6.5, None)),
        ("u:ok", None),
        ("u:bon raisonnement", None),
        ("u:-0.5 calculs", None),
        ("u:orientation -1", None),
        ("u:=? -1", None),
        ("", None),
    ],
)
def test_only_a_bare_number_or_fraction_is_a_grade(content, expected):
    """Comments and adjustments share the page with the grade.

    A grader writes ``ok`` and ``-0.5 calculs`` next to the work; neither is
    the grade, and a signed value is an adjustment to it.
    """
    assert ink_grades.parse_text_grade(content) == expected


def test_a_fraction_over_the_wrong_total_is_not_the_grade(classifier):
    """``0.25/1`` on a question out of 11 is a sub-question mark.

    The denominator is what tells the two apart, so it is checked against the
    question's maximum rather than ignored.
    """
    marks = [ink_grades.TextMark(content="u:6.5/9", bbox=(400, 60, 460, 90))]
    candidate = ink_grades.Candidate(
        bbox=marks[0].bbox, text=marks[0].content, page_size=(612.0, 792.0)
    )
    accepted = ink_grades.pick([candidate], (0.7, 0.1), 9.0, classifier)
    rejected = ink_grades.pick([candidate], (0.7, 0.1), 11.0, classifier)
    assert accepted.grade == 6.5
    assert rejected.grade is None


def test_the_enclosing_circle_is_told_from_the_digits():
    """The circle is the stroke drawn around the others, and is not a digit."""
    path = os.path.join(FIXTURE_DIR, "ink_circled_single.pdf")
    with pymupdf.open(path) as doc:
        page = doc[0]
        strokes = ink_grades.page_strokes(page)
        clusters = ink_grades.cluster_strokes(strokes, page.rect.width)
        circled = [
            (box, members)
            for box, members in clusters
            if ink_grades.enclosing_stroke(members) is not None
        ]
    assert len(circled) == 1
    box, members = circled[0]
    circle = ink_grades.enclosing_stroke(members)
    assert circle.closed
    for stroke in members:
        if stroke is not circle:
            assert ink_grades._contains(circle.bbox, stroke.bbox)


# A "4" is written as a diagonal and an upright, and that upright is a
# hairline sitting in the lower half of the mark with the decimals to its
# right -- the very description the comma rule carried. Taking the first
# stroke that matched ate it: the diagonal alone read as a 6, the real dot
# stayed in as a digit, and 4.75 came back as 6.975 on the autumn 2026 Q5.
def test_the_upright_of_a_four_is_not_taken_for_a_separator():
    """A dot beats a hairline, wherever each sits in the stroke list."""
    def stroke(x0, y0, x1, y1, steps=8):
        xs = np.linspace(x0, x1, steps)
        ys = np.linspace(y0, y1, steps)
        return ink_grades.Stroke(points=np.stack([xs, ys], axis=1))

    diagonal = stroke(0.0, 0.0, 5.0, 11.5)
    upright = stroke(5.0, 4.0, 5.2, 11.6)   # the bar of the 4: a hairline
    point = stroke(7.5, 17.4, 7.9, 17.8)    # the decimal point, low and tiny
    seven = stroke(10.0, 2.0, 13.7, 17.7)
    five = stroke(16.0, 2.0, 22.9, 12.7)
    members = [diagonal, upright, point, seven, five]
    box = ink_grades._union([s.bbox for s in members])

    glyphs, separator = ink_grades._decimal_point(members, box)

    assert separator is point
    assert upright in glyphs
    assert len(glyphs) == 4


def test_a_comma_is_still_the_separator_when_no_dot_was_written():
    """The hairline rule stays: a comma is what a French grader writes."""
    def stroke(x0, y0, x1, y1, steps=8):
        xs = np.linspace(x0, x1, steps)
        ys = np.linspace(y0, y1, steps)
        return ink_grades.Stroke(points=np.stack([xs, ys], axis=1))

    four = stroke(0.0, 0.0, 5.0, 11.5)
    comma = stroke(7.0, 12.0, 7.4, 17.0)
    five = stroke(10.0, 2.0, 16.0, 12.0)
    members = [four, comma, five]
    box = ink_grades._union([s.bbox for s in members])

    glyphs, separator = ink_grades._decimal_point(members, box)

    assert separator is comma
    assert glyphs == [four, five]


# Graders circle the grade in one sweep: the oval overshoots, crosses itself
# and trails off, so its ends sit far apart and it is not closed. Three copies
# of the autumn 2026 Q5 were read 0 because of it -- the oval stayed among the
# glyphs, welded them into one blob, and a ring reads as a confident zero.
def test_a_circle_that_never_closes_is_still_the_circle():
    """An open oval around the digits is an enclosure, a digit is not."""
    angles = np.linspace(0, 2 * np.pi, 120)
    ring = np.stack([30 + 28 * np.cos(angles), 20 + 16 * np.sin(angles)], axis=1)
    # the pen carries on past the start and trails away: the ends are apart
    tail = np.stack([np.linspace(58, 44, 20), np.linspace(20, 52, 20)], axis=1)
    oval = ink_grades.Stroke(points=np.concatenate([ring, tail]))
    assert not oval.closed
    digits = [
        ink_grades.Stroke(points=np.array([[20.0, 12.0], [24.0, 28.0]])),
        ink_grades.Stroke(points=np.array([[34.0, 12.0], [40.0, 28.0]])),
    ]

    assert ink_grades.enclosing_stroke([oval] + digits) is oval
    # the biggest glyph of a bare number holds no turn around the others
    assert ink_grades.enclosing_stroke(digits) is None


def test_a_grade_far_above_the_maximum_is_refused(classifier):
    """A reading the question cannot yield is dropped, not clamped."""
    entry = next(e for e in EXPECTED if e["file"] == "ink_circled_single.pdf")
    path = os.path.join(FIXTURE_DIR, entry["file"])
    with pymupdf.open(path) as doc:
        page = doc[0]
        candidates = ink_grades.grade_candidates(page, 1.0)
        reading = ink_grades.pick(candidates, tuple(entry["modal"]), 1.0, classifier)
    ceiling = ink_grades.grade_ceiling(1.0)
    assert reading.grade is None or reading.grade <= ceiling


@pytest.mark.parametrize(
    "max_points, ceiling",
    [(11.0, 13.75), (12.0, 15.0), (9.0, 11.25), (4.0, 5.0), (2.0, 3.0)],
)
def test_the_bonus_allowance_is_a_fraction_of_the_maximum(max_points, ceiling):
    """A question can carry bonus points without being a bonus question.

    The allowance has to be small: the same bound is what rejects a misread,
    and doubling the maximum would let "85" through on a question out of 12.
    """
    assert ink_grades.grade_ceiling(max_points) == pytest.approx(ceiling)
    assert ink_grades.grade_ceiling(None) is None


def test_a_grade_just_over_the_maximum_is_kept_but_never_confident(classifier):
    """12.5 out of 11 is a bonus; it is offered, and it is sent to review."""
    candidate = ink_grades.Candidate(
        bbox=(400, 60, 460, 90), text="u:12.5", page_size=(612.0, 792.0)
    )
    reading = ink_grades.pick([candidate], (0.7, 0.1), 11.0, classifier)

    assert reading.grade == 12.5
    assert reading.confidence <= ink_grades.UNMEASURED_CEILING


def test_a_grade_beyond_the_allowance_is_still_refused(classifier):
    candidate = ink_grades.Candidate(
        bbox=(400, 60, 460, 90), text="u:85", page_size=(612.0, 792.0)
    )
    reading = ink_grades.pick([candidate], (0.7, 0.1), 12.0, classifier)

    assert reading.grade is None


def test_a_reading_without_a_learned_position_is_never_confident(classifier):
    """No prior means no way to tell the grade from any other margin mark."""
    entry = next(e for e in EXPECTED if e["file"] == "ink_busy_page.pdf")
    path = os.path.join(FIXTURE_DIR, entry["file"])
    with pymupdf.open(path) as doc:
        candidates = ink_grades.grade_candidates(doc[0], entry["max_points"])
        reading = ink_grades.pick(candidates, None, entry["max_points"], classifier)
    assert reading.confidence <= ink_grades.NO_PRIOR_CEILING


def test_the_learned_position_stays_in_the_top_band():
    """Corrections outnumber the grade on a busy page; the band keeps them out."""
    low = [
        ink_grades.Candidate(bbox=(100, 700, 140, 740), page_size=(612.0, 792.0))
        for _ in range(8)
    ]
    modal = ink_grades.learn_modal_positions({"Q1": [[c] for c in low]})
    assert "Q1" not in modal


# Where the two graders of a 2026 question put their marks, as a fraction of
# the page: one writes the grade alone near the top right, the other circles
# it further left and lists the parts under the first grader's spot.
ALONE = (0.75, 0.29)
CIRCLED = (0.40, 0.13)
BREAKDOWN = (0.78, 0.54)


def _mark(centre, i=0, text=None):
    """A 30 x 20 pt mark centred near ``centre``, jittered by page ``i``."""
    width, height = 612.0, 792.0
    cx = (centre[0] + 0.004 * (i % 5 - 2)) * width
    cy = (centre[1] + 0.003 * (i % 3 - 1)) * height
    return ink_grades.Candidate(
        bbox=(cx - 15, cy - 10, cx + 15, cy + 10), page_size=(width, height), text=text
    )


def _near(position, centre):
    return abs(position[0] - centre[0]) < 0.02 and abs(position[1] - centre[1]) < 0.02


def test_a_question_split_between_graders_learns_both_spots():
    """One position for the whole batch landed between the two, on neither."""
    pages = [[_mark(ALONE, i)] for i in range(30)]
    pages += [[_mark(CIRCLED, i), _mark(BREAKDOWN, i)] for i in range(30)]
    positions = ink_grades.learn_modal_positions({"Q5": pages})["Q5"]
    assert len(positions) == 2
    assert any(_near(p, ALONE) for p in positions)
    assert any(_near(p, CIRCLED) for p in positions)


def test_each_page_is_read_at_the_nearest_spot():
    """The grader of a page is unknown: its mark nearest to any spot wins."""
    positions = [ALONE, CIRCLED]
    circled = ink_grades.pick(
        [_mark(CIRCLED, text="6"), _mark(BREAKDOWN, text="0.5")], positions, 7.5, None
    )
    alone = ink_grades.pick([_mark(ALONE, text="4.75")], positions, 7.5, None)
    assert (circled.grade, alone.grade) == (6.0, 4.75)
    assert circled.confidence > ink_grades.NO_PRIOR_CEILING


def test_one_grader_with_a_breakdown_learns_one_spot():
    """The parts are on every page too, but the grade's spot explains them all."""
    pages = [[_mark(CIRCLED, i), _mark(BREAKDOWN, i)] for i in range(30)]
    positions = ink_grades.learn_modal_positions({"Q5": pages})["Q5"]
    assert len(positions) == 1 and _near(positions[0], CIRCLED)


def test_a_few_stray_pages_make_no_spot_of_their_own():
    """A handful of copies graded in the other margin is not another grader."""
    pages = [[_mark(ALONE, i)] for i in range(40)]
    pages += [[_mark((0.06, 0.23), i)] for i in range(3)]
    positions = ink_grades.learn_modal_positions({"Q5": pages})["Q5"]
    assert len(positions) == 1 and _near(positions[0], ALONE)


# ------------------------------------------------- flattened, colour path --
RASTER = [e for e in EXPECTED if e.get("source") == "raster"]


def test_there_are_flattened_fixtures_to_read():
    assert RASTER, "the colour path has no fixtures to exercise it"


@pytest.mark.parametrize("entry", RASTER, ids=lambda e: e["file"][:-4])
def test_a_flattened_page_is_read_from_its_colour(entry, classifier):
    """No annotations left: the grade has to be found among the pixels.

    The page print is black and the grader's marks are not, which is the whole
    of the signal. A typed annotation flattens to black text and is therefore
    invisible here -- that fixture expects nothing, on purpose.
    """
    reading, _ = _read(entry, classifier)
    correct = reading.grade == entry["expected"]
    if entry.get("known_miss"):
        if correct:
            pytest.fail(
                f"{entry['file']} is read correctly now: clear its "
                "KNOWN_MISSES entry and rebuild the fixtures"
            )
        pytest.xfail(f"{entry['known_miss']}: read {reading.grade}")
    assert correct, entry["note"]


def test_a_reading_from_pixels_is_never_confident(classifier):
    """Measurably weaker than the annotation path, so it suggests only.

    On 228 flattened pages it reads 90.8% against the annotation path's 97.8%,
    and it has no stroke to say where a glyph ends or a decimal point sits.
    """
    entry = next(e for e in RASTER if e["expected"] is not None)
    reading, _ = _read(entry, classifier)

    assert reading.source == "raster"
    assert reading.confidence <= ink_grades.RASTER_CEILING


def test_colour_finds_the_marks_and_ignores_the_print(classifier):
    """The mask must hold the grader's ink and almost none of the page."""
    path = os.path.join(FIXTURE_DIR, "raster_circled_single.pdf")
    with pymupdf.open(path) as doc:
        page = doc[0]
        mask, scale = ink_grades.coloured_ink(page)
        marks = ink_grades.raster_marks(mask, scale)
        width, height = page.rect.width, page.rect.height

    assert scale == pytest.approx(ink_grades.DPI / 72.0)
    # the page is a dense scan of printed maths; what is coloured is the
    # grader's handful of marks, a tiny share of the ink on it
    assert 0 < (mask > 0).mean() < 0.02
    assert marks
    for stroke, _ in marks:
        x0, y0, x1, y1 = stroke.bbox
        assert 0 <= x0 <= x1 <= width
        assert 0 <= y0 <= y1 <= height


def test_an_annotated_page_never_takes_the_colour_path(classifier):
    """Vector strokes are better evidence, so they win whenever they exist."""
    entry = next(e for e in EXPECTED if e["file"] == "ink_circled_single.pdf")
    reading, _ = _read(entry, classifier)

    assert reading.source == "ink"


def test_a_flattened_page_without_colour_reports_nothing(classifier):
    """A black-and-white page has nothing to offer, and must not invent one."""
    entry = next(e for e in RASTER if e["file"].startswith("raster_freetext"))
    reading, candidates = _read(entry, classifier)

    assert candidates == []
    assert reading.grade is None
    assert reading.reason == "not_found"


def test_a_mark_inside_the_matricule_box_is_not_a_grade():
    """The box at the top of every page holds the student's own handwriting.

    It is in the same pen as the rest of their work and it sits exactly where
    graders put the grade, so on a real ungraded copy the colour path read the
    matricule 2140874 as a grade of 4. Containment is the test, not overlap:
    the grader who writes the grade across that box draws something far bigger
    than the cells, and that still counts.
    """
    page_size = (612.0, 792.0)
    x0, y0, x1, y1 = ink_grades.matricule_region(page_size)

    in_a_cell = (x0 + 10, y0 + 3, x0 + 50, y1 - 3)
    across_the_box = (x0 + 10, y0 - 30, x0 + 90, y1 + 30)
    well_below = (x0, y1 + 100, x0 + 50, y1 + 160)

    assert ink_grades._inside_matricule(in_a_cell, page_size)
    assert not ink_grades._inside_matricule(across_the_box, page_size)
    assert not ink_grades._inside_matricule(well_below, page_size)


def test_the_circle_is_erased_from_the_pixels(classifier):
    """Left in, the ring reads as a 0 drawn around the grade."""
    path = os.path.join(FIXTURE_DIR, "raster_circled_single.pdf")
    with pymupdf.open(path) as doc:
        candidates = ink_grades.raster_candidates(doc[0], 11.0)

    circled = [c for c in candidates if c.circled]
    assert circled, "the fixture's grade is circled"
    for candidate in circled:
        assert candidate.image is not None
        # what is left is the digits, far less ink than circle plus digits
        assert 0 < (candidate.image > 0).mean() < 0.35


def _vertical_stroke(x, y0=100.0, y1=160.0, n=24):
    """A stroke a grader could have drawn: a straight vertical line."""
    ys = np.linspace(y0, y1, n)
    return ink_grades.Stroke(points=np.stack([np.full(n, x), ys], axis=1))


def test_the_denominator_of_a_fraction_never_reaches_the_digit_bank(
    classifier, storage_root
):
    """``pick`` reads the grade, then the denominator, then keeps what it chose.

    The denominator is read last, so staging it would make it -- and not the
    grade -- the reading ``keep_last`` keeps, and "10" would be banked with
    the label of the grade written above it.
    """
    from process_copy import digit_bank

    grade_strokes = [_vertical_stroke(200.0)]
    denominator_strokes = [_vertical_stroke(300.0), _vertical_stroke(320.0)]

    with digit_bank.recording("job-ink", 0, digit_bank.INK_GRADE, question_index=1):
        ink_grades.read_number(grade_strokes, None, classifier)
        ink_grades.read_number(denominator_strokes, None, classifier, stage=False)
        digit_bank.keep_last(value=1.0)

    staged = sorted((storage_root / digit_bank.STAGED_DIR / "job-ink").rglob("*.npz"))
    assert len(staged) == 1
    with np.load(staged[0], allow_pickle=False) as data:
        crops = data["crops"]
    # the one stroke of the grade, not the two of the denominator
    assert len(crops) == 1


def _stroke(points):
    return ink_grades.Stroke(points=np.array(points, dtype=float))


def test_a_comma_is_a_decimal_separator_not_a_digit():
    """The comma French graders write is a tick, far taller than a dot.

    Measured on a real mark: the "2" and the "5" are 17 and 13 points wide in
    a mark 25 tall, and the comma between them is a hairline 13 points tall.
    Left among the glyphs it became a third digit and the grade read 2.
    """
    two = _stroke([(0, 0), (12, 2), (4, 20), (16, 22)])
    comma = _stroke([(26, 12), (26, 25)])
    five = _stroke([(34, 0), (46, 1), (36, 11), (48, 22)])
    glyphs, denominator, dot = ink_grades.split_separator(
        [two, comma, five], ink_grades._union([s.bbox for s in (two, comma, five)])
    )
    assert denominator == []
    assert dot is comma
    assert glyphs == [two, five]


def test_a_tick_with_nothing_after_it_stays_a_glyph():
    """A separator carries decimals; a lone tick is part of what was written.

    Dropping it would cost a digit rather than save one, so the comma rule
    asks for a glyph to its right.
    """
    two = _stroke([(0, 0), (12, 2), (4, 20), (16, 22)])
    tail = _stroke([(26, 12), (26, 25)])
    glyphs, _, dot = ink_grades.split_separator(
        [two, tail], ink_grades._union([s.bbox for s in (two, tail)])
    )
    assert dot is None
    assert glyphs == [two, tail]


def test_a_digit_is_never_taken_for_a_comma():
    """A "1" drawn as a bare upright is thin, but it is not low and not short."""
    one = _stroke([(0, 0), (0, 24)])
    five = _stroke([(12, 0), (24, 1), (14, 11), (26, 22)])
    glyphs, _, dot = ink_grades.split_separator(
        [one, five], ink_grades._union([s.bbox for s in (one, five)])
    )
    assert dot is None
    assert glyphs == [one, five]


def test_the_rule_drawn_under_a_grade_is_not_a_digit():
    """Some graders underline the number; the rule is not part of it."""
    one = _stroke([(4, 0), (8, 0), (8, 20)])
    underline = _stroke([(0, 23), (24, 23)])
    glyphs, denominator, dot = ink_grades.split_separator(
        [one, underline], ink_grades._union([s.bbox for s in (one, underline)])
    )
    assert denominator == []
    assert dot is None
    assert glyphs == [one]


def test_a_fraction_bar_is_not_mistaken_for_an_underline():
    """A bar with a denominator under it still splits the mark in two."""
    nine = _stroke([(4, 0), (16, 2), (6, 12), (18, 14)])
    bar = _stroke([(0, 20), (24, 20)])
    denominator_digit = _stroke([(4, 26), (16, 28), (6, 38), (18, 40)])
    members = [nine, bar, denominator_digit]
    glyphs, denominator, _ = ink_grades.split_separator(
        members, ink_grades._union([s.bbox for s in members])
    )
    assert glyphs == [nine]
    assert denominator == [denominator_digit]


@pytest.mark.parametrize(
    "name, expected, confident",
    [
        ("ink_comma_decimal.pdf", 2.5, True),
        ("ink_comma_left_margin.pdf", 10.5, True),
        ("ink_wide_circle.pdf", 2.5, True),
        # the grade itself is a "1" drawn with a top flag, which the model
        # reads as a 7; the question maximum rejects that and leaves the 1 of
        # ``known_mistmatch``, which carries no probability of its own. Right
        # answer, and right to send it to the teacher rather than prefill it
        ("ink_underlined_grade.pdf", 1.0, False),
    ],
)
def test_the_2026_corpus_is_read_and_graded_for_trust(
    name, expected, confident, classifier
):
    """The job that motivated these rules, read and scored for confidence.

    A grade the teacher has to correct by hand is a nuisance; one that arrives
    prefilled and wrong is worse, and before these rules every comma grade of
    this batch came back whole and confident.
    """
    entry = next(e for e in EXPECTED if e["file"] == name)
    reading, _ = _read(entry, classifier)
    assert reading.grade == expected
    assert reading.confident is confident
