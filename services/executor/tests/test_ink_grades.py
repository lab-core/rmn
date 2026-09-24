"""Reading the grade a teacher wrote on a graded question page.

The fixtures are real graded pages with the matricule destroyed in the raster
(``fixtures/ink_grades/build_fixtures.py``). Real ink is the point: the shapes
graders actually draw are what this has to survive, and no hand-built stroke
reproduces them.
"""

import json
import os

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


@pytest.mark.parametrize("entry", EXPECTED, ids=lambda e: e["file"][:-4])
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


def test_the_fixtures_carry_no_readable_matricule(classifier):
    """Guards the redaction: a rebuilt fixture must not leak a student id."""
    for entry in EXPECTED:
        path = os.path.join(FIXTURE_DIR, entry["file"])
        grays = recognize.gray_images(
            path, pages=[0], dpi=300, straighten=False, shape=(2550, 3300)
        )
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


def test_a_grade_above_the_maximum_is_refused(classifier):
    """A reading the question cannot yield is dropped, not clamped."""
    entry = next(e for e in EXPECTED if e["file"] == "ink_circled_single.pdf")
    path = os.path.join(FIXTURE_DIR, entry["file"])
    with pymupdf.open(path) as doc:
        page = doc[0]
        candidates = ink_grades.grade_candidates(page, 1.0)
        reading = ink_grades.pick(candidates, tuple(entry["modal"]), 1.0, classifier)
    assert reading.grade is None or reading.grade <= 1.0


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
