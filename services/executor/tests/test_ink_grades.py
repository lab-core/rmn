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
