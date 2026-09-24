"""Build the ink-grade fixtures from real graded copies, matricule removed.

Real pages make far better fixtures than drawn-by-hand ink: they carry the
stroke jitter, the scan noise and the annotation structure the recogniser has
to survive, and they are the only way a test can catch a regression on the
shapes graders actually draw.

What they must not carry is the student. A question page shows no name -- the
header is the course and the exam, names live on the cover page, which is not
used here -- so the matricule handwritten in the printed box at the top right
is the one direct identifier, and this script destroys it:

1. the page is rasterised and the matricule band is painted over **in the
   image**, then the page is rebuilt around that raster. Covering the band
   with a rectangle, or with a redaction annotation, would leave the original
   pixels in the file for anyone who looks;
2. the grader's marks are re-attached as annotations, so they survive
   untouched even where they overlap the band (one corpus writes the grade
   right over the matricule box);
3. metadata is dropped and the file is renamed to an opaque id, because the
   source filenames carry names and matricules;
4. ``recognize.find_matricule`` is run over the result and must come back
   empty -- the redaction is verified, not assumed.

Usage:
    python build_fixtures.py --out . [--check-only]

Review the rendered pages by eye before committing them: this script proves
the matricule is gone, not that nothing else identifies anyone.
"""

import argparse
import json
import os
import shutil
import sys
import tempfile

import numpy as np
import pymupdf

HERE = os.path.dirname(os.path.abspath(__file__))
EXECUTOR = os.path.dirname(os.path.dirname(os.path.dirname(HERE)))
sys.path.insert(0, EXECUTOR)
sys.path.insert(0, os.path.join(EXECUTOR, "python"))
sys.path.insert(0, os.path.join(os.path.dirname(EXECUTOR), "common"))

from process_copy import ink_grades, recognize  # noqa: E402
from process_copy.classifier import load_classifier  # noqa: E402
from process_copy.config import matricule_box  # noqa: E402

DPI = 300
# The page image is only there for review and for the redaction check: the
# reader works off the annotations, so half the resolution costs nothing and
# keeps the fixture set near a megabyte instead of twelve.
RASTER_DPI = 150
# the scans are grey anyway, and jpeg keeps the set small enough to live in a
# repository that CI clones on every run
JPEG_QUALITY = 55
BAND_PAD = 0.015
# how far a rebuilt page may drift from its source render; jpeg and resampling
# cost about 1.5, a background dropped at the wrong rotation costs ten times
# that
MAX_SOURCE_DIFF = 6.0

# Sources live outside the repository; they are only needed to rebuild.
CORPUS_A = os.path.join(os.path.dirname(EXECUTOR), "..", "examples", "copies")
CORPUS_B = os.path.join(
    os.path.dirname(EXECUTOR),
    "..",
    "storage",
    "documents",
    "a9b59d93-5201-4fd7-a0e8-fd15ee8e791f",
)

# (name, source pdf, page index, max points, expected, modal centre, note)
# ``expected`` None means "nothing is written on this page": the reader must
# say so rather than report a zero. A name in KNOWN_MISSES is a page the
# classifier gets wrong today. ``modal`` is the position the reader
# learned for that question from its own upload batch -- a single-page test
# cannot learn one, so the batch's answer is recorded here instead; None means
# that question never had enough pages to learn from.
FIXTURES = [
    (
        "ink_circled_single",
        "A/Antoine_Duong_1957443.pdf",
        1,
        11.0,
        9.0,
        (0.75, 0.33),
        "a circled single digit, the common case",
    ),
    (
        "ink_circled_decimal",
        "A/Antoine_Duong_1957443.pdf",
        22,
        2.0,
        0.25,
        (0.73, 0.36),
        "quarter point on the bonus question; the page carries a second 0.25 "
        "beside the answer, which the circle and the position must beat",
    ),
    (
        "ink_two_digit",
        "A/Zakaria_Mihoubi_2468092.pdf",
        8,
        12.0,
        10.5,
        (0.78, 0.34),
        "two digits and a decimal",
    ),
    (
        "ink_decimal_half",
        "A/Julien_Cazajous-Poulot_2180608.pdf",
        13,
        12.0,
        8.5,
        (0.83, 0.27),
        "a decimal point between two digits written side by side",
    ),
    (
        "ink_two_clusters",
        "A/Yasser_Taha_2476732.pdf",
        13,
        12.0,
        9.0,
        (0.83, 0.27),
        "two circled clusters on one page",
    ),
    (
        "ink_busy_page",
        "B/Q4/wqref_bw_g_Q4.pdf",
        0,
        9.0,
        1.0,
        (0.40, 0.13),
        "58 annotations on the page; the grade is one small mark among them",
    ),
    (
        "ink_left_margin",
        "B/Q4/mffytdhgc_Q4.pdf",
        0,
        9.0,
        8.5,
        (0.40, 0.13),
        "this grader writes in the left margin, not the right",
    ),
    (
        "ink_over_matricule",
        "B/Q3/mdh_xgvc_Q3.pdf",
        0,
        9.0,
        6.0,
        (0.54, 0.13),
        "the grade is drawn across the matricule box it is redacted from",
    ),
    (
        "ink_no_annotation",
        "B/Q1/mtodjhisnjrbifs_Q1.pdf",
        0,
        9.0,
        None,
        None,
        "nothing written: must read not_found, never 0",
    ),
    (
        "freetext_grade",
        "B/Q5/mtodjhisnjrbifs_Q5.pdf",
        0,
        9.0,
        8.5,
        (0.73, 0.28),
        "typed grade, and 'ok' comments on the same page",
    ),
    (
        "freetext_fraction",
        "B/Q5/wvdzcs_Q5.pdf",
        0,
        9.0,
        6.5,
        (0.73, 0.28),
        "typed as a fraction over the question total",
    ),
    (
        "freetext_with_comment",
        "B/Q5/wqref_bw_g_Q5.pdf",
        0,
        9.0,
        9.0,
        (0.73, 0.28),
        "'ok' and the grade share the first page",
    ),
]


# Pages the digit model reads wrong today. They are kept as fixtures, and a
# test xfails them strictly, so that fixing one is recorded here rather than
# silently absorbed.
KNOWN_MISSES = {
    "ink_two_clusters": "the 9 is read as a 7 with high confidence",
}


def source_path(reference: str, roots) -> str:
    """Resolve an ``A/...`` or ``B/...`` reference to a real file."""
    corpus, rest = reference.split("/", 1)
    return os.path.normpath(os.path.join(roots[corpus], rest))


def band_rect(page) -> pymupdf.Rect:
    """The printed matricule band of a regular page, in display coordinates.

    Taken from ``config.matricule_box`` -- the same constant the recogniser
    uses to find a matricule -- so a template that moves the box moves the
    redaction with it.
    """
    x0, x1, y0, y1 = matricule_box["exam"]["regular"]
    width, height = page.rect.width, page.rect.height
    return pymupdf.Rect(
        (x0 - BAND_PAD) * width,
        (y0 - BAND_PAD) * height,
        (x1 + BAND_PAD) * width,
        (y1 + BAND_PAD) * height,
    )


def redacted_page(source, page_index: int):
    """A one-page document holding ``page_index`` with the matricule erased.

    The page is rebuilt from its own raster, so the matricule is gone from the
    pixels rather than hidden behind something. Rotation and page size are
    kept, so the fixtures exercise the ``/Rotate`` handling on real geometry.

    The raster is taken with the rotation removed, in the orientation of the
    mediabox, and the rotation is applied to the rebuilt page afterwards.
    Rasterising the page as displayed and dropping that image onto a rotated
    page leaves the background lying on its side under upright annotations --
    which is what happened, and is why ``matches_source`` exists.
    """
    page = source[page_index]
    band = band_rect(page) * page.derotation_matrix

    upright = pymupdf.open()
    upright.insert_pdf(source, from_page=page_index, to_page=page_index, annots=False)
    upright[0].set_rotation(0)
    pixmap = upright[0].get_pixmap(dpi=RASTER_DPI)
    image = (
        np.frombuffer(pixmap.samples, np.uint8)
        .reshape(pixmap.height, pixmap.width, pixmap.n)
        .copy()
    )
    scale = RASTER_DPI / 72.0
    top, bottom = int(band.y0 * scale), int(band.y1 * scale)
    left, right = int(band.x0 * scale), int(band.x1 * scale)
    image[top:bottom, left:right] = 255
    clean = pymupdf.Pixmap(pixmap.colorspace, pixmap.irect, pixmap.alpha)
    clean.samples_mv[:] = image.tobytes()
    if clean.n > 1:
        clean = pymupdf.Pixmap(pymupdf.csGRAY, clean)

    out = pymupdf.open()
    new = out.new_page(width=page.mediabox.width, height=page.mediabox.height)
    new.insert_image(new.rect, stream=clean.tobytes("jpeg", jpg_quality=JPEG_QUALITY))
    new.set_rotation(page.rotation)

    derotate = new.derotation_matrix
    for annot in page.annots():
        kind = annot.type[0]
        if kind == ink_grades.PDF_ANNOT_INK:
            vertices = annot.vertices or []
            paths = (
                vertices if vertices and isinstance(vertices[0], list) else [vertices]
            )
            display = [
                [pymupdf.Point(p) * page.rotation_matrix for p in path]
                for path in paths
                if len(path) > 1
            ]
            if not display:
                continue
            # add_ink_annot wants plain float pairs, not Point objects
            added = new.add_ink_annot(
                [[tuple(p * derotate) for p in path] for path in display]
            )
            colors = annot.colors or {}
            if colors.get("stroke"):
                added.set_colors(stroke=colors["stroke"])
            added.set_border(width=annot.border.get("width", 1) or 1)
            added.update()
        elif kind == ink_grades.PDF_ANNOT_FREE_TEXT:
            rect = (annot.rect * page.rotation_matrix) * derotate
            added = new.add_freetext_annot(rect, (annot.info or {}).get("content", ""))
            added.update()

    out.set_metadata({})
    out.xref_set_key(-1, "Info", "null")
    return out


def matches_source(fixture_path: str, source, page_index: int) -> float:
    """Mean per-pixel difference between the fixture and the page it came from.

    The redacted band aside, a fixture must look like its source: a background
    placed at the wrong rotation still passes every reading test, because the
    reader works off the annotations and never looks at the page underneath.
    """
    reference = source[page_index].get_pixmap(dpi=60, annots=False)
    with pymupdf.open(fixture_path) as doc:
        rebuilt = doc[0].get_pixmap(dpi=60, annots=False)
    if (reference.height, reference.width) != (rebuilt.height, rebuilt.width):
        return float("inf")

    def as_array(pix):
        samples = np.frombuffer(pix.samples, np.uint8)
        return samples.reshape(pix.height, pix.width, pix.n)[:, :, :3].mean(axis=2)

    return float(np.abs(as_array(reference) - as_array(rebuilt)).mean())


def _classifier(model=None):
    """The shipped LiteRT model, or a Keras file when one is named.

    The executor image has only the ``.tflite``; naming the ``.h5`` keeps this
    script usable in a development environment without the LiteRT wheel, and
    the two agree to 1e-7 by construction.
    """
    if model and model.endswith(".h5"):
        from tensorflow.keras.models import load_model

        return load_model(model)
    return load_classifier(model)


def verify_no_matricule(path: str, classifier) -> bool:
    """True when the recogniser can no longer read a matricule off the page."""
    grays = recognize.gray_images(
        path,
        pages=[0],
        dpi=DPI,
        straighten=False,
        shape=(int(DPI * 8.5), int(DPI * 11)),
    )
    if not grays:
        return True
    # the fixture is a single page, so the "front" box find_matricule starts
    # from is the regular one
    found, _, _ = recognize.find_matricule(
        grays,
        matricule_box["exam"]["regular"],
        matricule_box["exam"]["regular"],
        classifier,
        separate_box=matricule_box["exam"]["separate_box"],
    )
    return not found


def build(out_dir, roots, check_only=False, model=None) -> int:
    classifier = _classifier(model)
    expected = {"raster_dpi": RASTER_DPI, "fixtures": []}
    failures = 0

    for name, reference, page_index, max_points, value, modal, note in FIXTURES:
        source_file = source_path(reference, roots)
        if not os.path.exists(source_file):
            print(f"  SKIP {name}: {source_file} not available")
            continue
        target = os.path.join(out_dir, f"{name}.pdf")
        source = pymupdf.open(source_file)
        doc = redacted_page(source, page_index)

        with tempfile.NamedTemporaryFile(suffix=".pdf", delete=False) as handle:
            temporary = handle.name
        doc.save(temporary, garbage=4, deflate=True)
        doc.close()

        drift = matches_source(temporary, source, page_index)
        if not verify_no_matricule(temporary, classifier):
            os.unlink(temporary)
            failures += 1
            print(f"  FAIL {name}: a matricule is still readable -- not written")
        elif drift > MAX_SOURCE_DIFF:
            os.unlink(temporary)
            failures += 1
            print(f"  FAIL {name}: page differs from its source by {drift:.1f}")
        else:
            if not check_only:
                shutil.move(temporary, target)
            else:
                os.unlink(temporary)
            print(f"  ok   {name}: matricule gone, page matches source ({drift:.1f})")

        source.close()
        expected["fixtures"].append(
            {
                "file": f"{name}.pdf",
                "max_points": max_points,
                "expected": value,
                "modal": list(modal) if modal else None,
                "known_miss": KNOWN_MISSES.get(name, False),
                "note": note,
            }
        )

    if not check_only:
        with open(os.path.join(out_dir, "expected.json"), "w") as handle:
            json.dump(expected, handle, indent=2, ensure_ascii=False)
            handle.write("\n")
    return failures


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", default=HERE)
    parser.add_argument("--check-only", action="store_true")
    parser.add_argument("--model", help="classifier file (.tflite or .h5)")
    parser.add_argument("--corpus-a", default=CORPUS_A, help="whole graded copies")
    parser.add_argument("--corpus-b", default=CORPUS_B, help="per-question tree")
    args = parser.parse_args()
    roots = {"A": args.corpus_a, "B": args.corpus_b}
    failures = build(args.out, roots, args.check_only, args.model)
    if failures:
        print(f"\n{failures} fixture(s) still show a matricule")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
