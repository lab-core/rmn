"""Read the grade a teacher wrote on the first page of a graded question.

Copies are graded offline by annotating the PDF and re-uploaded; the grade is
already on the page, so it does not have to be typed again. Three ways of
writing it are supported, chosen per copy:

* a typed ``/FreeText`` annotation -- read straight from its contents, no
  recognition involved;
* handwritten ``/Ink`` strokes -- vector paths, so the teacher's marks can be
  isolated from the scanned page exactly, rendered on their own and handed to
  the digit classifier the rest of the pipeline already uses;
* a flattened page with no annotation at all -- see ``raster`` below (a later
  stage; ``grade_candidates`` returns nothing for those pages today).

The grade may be circled or bare, a single number (``9``, ``0.25``) or a
fraction over the question total (``6.5/9``), and written in any colour: real
jobs use several reds in the same batch, so nothing here keys on a colour.

Nothing in this module touches Mongo, the socket or the storage tree: it takes
a page and returns numbers, which is what makes it testable.
"""

import math
import re
from dataclasses import dataclass, field
from typing import Any, List, Optional, Sequence, Tuple

import cv2
import numpy as np

from process_copy import recognize
from process_copy.config import matricule_box

DPI = 300
ZOOM = DPI / 72.0

# Clustering: two stroke groups belong together when their boxes are within
# this fraction of the page width of each other.
CLUSTER_TOL = 0.035
# A grade is a small mark: clusters outside this fraction of the page width are
# ticks, crosses and sentences, not numbers.
MIN_CLUSTER_W = 0.04
MAX_CLUSTER_W = 0.16

# Rendering. A vector digit 300 px tall drawn with a hairline almost vanishes
# once make_square resizes it to 28x28, so the thickness follows the size of
# the mark; measured best on the 2026 corpus (95.2% against 92.5% at a fixed
# 7 px), with anti-aliasing OFF (it costs half a point).
STROKE_THICKNESS = 0.08
MIN_THICKNESS = 3
PAD = 14
# two ink blobs belong to the same digit when they share this much of the
# narrower one's columns
MERGE_OVERLAP = 0.5

# A separator stroke: small and low is a decimal point, long and diagonal is a
# fraction slash, long and flat with glyphs above and below is a vinculum.
SEPARATOR_MAX = 0.28
SEPARATOR_MIN_Y = 0.55
SLASH_MIN_HEIGHT = 0.6
SLASH_STRAIGHTNESS = 0.25
# a slash leans; the upright stroke of a handwritten "4" is straight and tall
# too, and splitting a number on it turns "4.5" into a fraction
SLASH_MIN_ASPECT = 0.25
VINCULUM_MAX_HEIGHT = 0.15
VINCULUM_MIN_WIDTH = 0.6

# ``/FreeText`` contents carry an author prefix ("u:8.5"). A grade is a bare
# number or a fraction; "ok", "bon raisonnement" and the signed adjustments
# ("-0.5 calculs") that share the page are comments, not grades.
TEXT_PREFIX = re.compile(r"^\s*[A-Za-z]{1,3}\s*:\s*")
TEXT_GRADE = re.compile(r"^\s*(\d+(?:[.,]\d+)?)\s*(?:/\s*(\d+(?:[.,]\d+)?)\s*)?$")

PDF_ANNOT_FREE_TEXT = 2
PDF_ANNOT_INK = 15

# Flattened pages: the grader's marks are pixels, not annotations. They are
# found by colour, because the page underneath is a black and white scan and
# graders write in anything but. Selection is by saturation rather than hue:
# one real job uses four different reds and there is no reason the next one
# will not use green.
RASTER_MIN_SATURATION = 60
RASTER_MIN_VALUE = 40
RASTER_OPEN_KERNEL = 3
RASTER_MIN_BLOB_PX = 40


@dataclass(eq=False)
class Stroke:
    """One ``/InkList`` polyline, in display coordinates (top-left origin)."""

    points: np.ndarray
    color: Optional[Tuple[float, ...]] = None

    @property
    def bbox(self) -> Tuple[float, float, float, float]:
        """``(x0, y0, x1, y1)`` of the polyline."""
        return (
            float(self.points[:, 0].min()),
            float(self.points[:, 1].min()),
            float(self.points[:, 0].max()),
            float(self.points[:, 1].max()),
        )

    @property
    def closed(self) -> bool:
        """True when the ends meet, i.e. the stroke is a ring (a circle)."""
        x0, y0, x1, y1 = self.bbox
        diagonal = math.hypot(x1 - x0, y1 - y0)
        if diagonal <= 0:
            return False
        gap = math.dist(self.points[0], self.points[-1])
        return gap < 0.45 * diagonal


@dataclass
class TextMark:
    """One ``/FreeText`` annotation."""

    content: str
    bbox: Tuple[float, float, float, float]


@dataclass
class Candidate:
    """A mark on the page that may be the grade."""

    bbox: Tuple[float, float, float, float]
    number_strokes: List[Stroke] = field(default_factory=list)
    dot_x: Optional[float] = None
    denominator_strokes: List[Stroke] = field(default_factory=list)
    denominator_dot_x: Optional[float] = None
    circled: bool = False
    text: Optional[str] = None
    page_size: Tuple[float, float] = (612.0, 792.0)
    source: str = "ink"
    # the raster path carries its ink as pixels: the mark was never a polyline
    # and redrawing its outline would hand the classifier a hollow digit
    image: Optional[np.ndarray] = None

    @property
    def centre(self) -> Tuple[float, float]:
        """Centre of the mark as a fraction of the page."""
        x0, y0, x1, y1 = self.bbox
        return (
            (x0 + x1) / 2 / self.page_size[0],
            (y0 + y1) / 2 / self.page_size[1],
        )


@dataclass
class Reading:
    """What a page yielded, and how much it can be trusted."""

    grade: Optional[float] = None
    confidence: float = 0.0
    reason: str = "not_found"
    source: str = "none"
    bbox: Optional[Tuple[float, float, float, float]] = None
    n_candidates: int = 0


# --------------------------------------------------------------- page input --
def page_strokes(page: Any) -> List[Stroke]:
    """Every ink stroke of ``page``, in display coordinates.

    ``annot.vertices`` are reported in unrotated page space; multiplying by
    ``page.rotation_matrix`` is what lands them on the page as rendered,
    whatever ``/Rotate`` says. Checked against a render of a ``/Rotate 270``
    page: the transformed points match the ink pixels to under a point.

    Args:
        page: A ``pymupdf`` page.

    Returns:
        The strokes, in no particular order. Colour is kept for debugging only
        -- one job legitimately uses four different reds.
    """
    import pymupdf

    matrix = page.rotation_matrix
    strokes: List[Stroke] = []
    for annot in page.annots():
        if annot.type[0] != PDF_ANNOT_INK:
            continue
        vertices = annot.vertices or []
        paths = vertices if vertices and isinstance(vertices[0], list) else [vertices]
        colors = annot.colors or {}
        color = colors.get("stroke") or colors.get("fill") or None
        for path in paths:
            if len(path) < 2:
                continue
            points = np.array(
                [tuple(pymupdf.Point(p) * matrix) for p in path], dtype=float
            )
            strokes.append(Stroke(points=points, color=tuple(color) if color else None))
    return strokes


def page_texts(page: Any) -> List[TextMark]:
    """Every typed ``/FreeText`` annotation of ``page``, in display coordinates."""
    matrix = page.rotation_matrix
    marks: List[TextMark] = []
    for annot in page.annots():
        if annot.type[0] != PDF_ANNOT_FREE_TEXT:
            continue
        content = (annot.info or {}).get("content") or ""
        rect = annot.rect * matrix
        marks.append(
            TextMark(
                content=content,
                bbox=(float(rect.x0), float(rect.y0), float(rect.x1), float(rect.y1)),
            )
        )
    return marks


def parse_text_grade(content: str) -> Optional[Tuple[float, Optional[float]]]:
    """The value a ``/FreeText`` annotation states, if it states one.

    Args:
        content: The raw annotation contents, author prefix included.

    Returns:
        ``(value, denominator)`` -- ``denominator`` is ``None`` unless the mark
        is a fraction -- or ``None`` when the annotation is a comment. Only a
        bare number or fraction counts: a signed value is an adjustment
        ("-0.5 calculs"), and anything with words in it is a remark.
    """
    stripped = TEXT_PREFIX.sub("", content or "")
    match = TEXT_GRADE.match(stripped)
    if not match:
        return None
    value = float(match.group(1).replace(",", "."))
    denominator = match.group(2)
    return value, float(denominator.replace(",", ".")) if denominator else None


# ----------------------------------------------------------------- geometry --
def _union(boxes: Sequence[Tuple[float, float, float, float]]):
    xs0, ys0, xs1, ys1 = zip(*boxes)
    return (min(xs0), min(ys0), max(xs1), max(ys1))


def cluster_strokes(
    strokes: Sequence[Stroke], page_width: float, tol: float = CLUSTER_TOL
) -> List[Tuple[Tuple[float, float, float, float], List[Stroke]]]:
    """Group strokes that sit close enough together to be one mark.

    Args:
        strokes: The page's strokes.
        page_width: Width of the displayed page, the unit ``tol`` is in.
        tol: Gap below which two groups merge, as a fraction of the page width.

    Returns:
        ``(bbox, members)`` per group.
    """
    gap = tol * page_width
    boxes = [s.bbox for s in strokes]
    groups = [[s] for s in strokes]
    merged = True
    while merged:
        merged = False
        for i in range(len(groups)):
            for k in range(i + 1, len(groups)):
                a, b = boxes[i], boxes[k]
                if (
                    a[0] - gap < b[2]
                    and b[0] - gap < a[2]
                    and a[1] - gap < b[3]
                    and b[1] - gap < a[3]
                ):
                    boxes[i] = _union([a, b])
                    groups[i] = groups[i] + groups[k]
                    del groups[k]
                    del boxes[k]
                    merged = True
                    break
            if merged:
                break
    return list(zip(boxes, groups))


def enclosing_stroke(members: Sequence[Stroke]) -> Optional[Stroke]:
    """The stroke drawn around the others, i.e. the circle, if there is one.

    The grade is often circled, which is a strong hint that a mark is the
    grade -- but only a hint: graders do not always circle, so this never
    decides on its own.
    """
    if len(members) < 2:
        return None
    biggest = max(members, key=lambda s: _area(s.bbox))
    box = biggest.bbox
    others = [s for s in members if s is not biggest]
    if all(_contains(box, s.bbox) for s in others) and biggest.closed:
        return biggest
    return None


def _area(box: Tuple[float, float, float, float]) -> float:
    return max(box[2] - box[0], 0.0) * max(box[3] - box[1], 0.0)


def _contains(outer, inner, slack: float = 2.0) -> bool:
    return (
        inner[0] >= outer[0] - slack
        and inner[2] <= outer[2] + slack
        and inner[1] >= outer[1] - slack
        and inner[3] <= outer[3] + slack
    )


def _straightness(stroke: Stroke) -> float:
    """How far the polyline wanders from the line joining its ends, relative
    to its own length. Near 0 for a ruled stroke, large for a digit."""
    start, end = stroke.points[0], stroke.points[-1]
    span = math.dist(start, end)
    if span <= 0:
        return 1.0
    dx, dy = end[0] - start[0], end[1] - start[1]
    dev = np.abs(
        (dy * (stroke.points[:, 0] - start[0]) - dx * (stroke.points[:, 1] - start[1]))
        / span
    )
    return float(dev.max() / span)


def split_separator(members: Sequence[Stroke], box: Tuple[float, float, float, float]):
    """Tell the number's glyphs apart from its separator.

    Three separators occur: the decimal point, the slash of a fraction written
    ``6.5/9``, and the horizontal bar of a stacked fraction. The decimal point
    stays with the number (it only says where the decimals start); a fraction
    bar splits the mark into a numerator and a denominator.

    Args:
        members: Strokes of one cluster, circle already removed.
        box: Bounding box of the cluster.

    Returns:
        ``(numerator_strokes, denominator_strokes, dot_stroke)``. The
        denominator list is empty unless the mark is a fraction.
    """
    height = max(box[3] - box[1], 1e-6)
    width = max(box[2] - box[0], 1e-6)

    for stroke in members:
        sx0, sy0, sx1, sy1 = stroke.bbox
        straight = _straightness(stroke) < SLASH_STRAIGHTNESS
        tall = (sy1 - sy0) >= SLASH_MIN_HEIGHT * height
        leaning = (sx1 - sx0) >= SLASH_MIN_ASPECT * (sy1 - sy0)
        flat = (sy1 - sy0) <= VINCULUM_MAX_HEIGHT * height
        wide = (sx1 - sx0) >= VINCULUM_MIN_WIDTH * width
        rest = [s for s in members if s is not stroke]
        if straight and tall and leaning and (sx1 - sx0) < 0.6 * width and rest:
            left = [s for s in rest if s.bbox[2] <= (sx0 + sx1) / 2]
            right = [s for s in rest if s.bbox[0] >= (sx0 + sx1) / 2]
            if left and right and len(left) + len(right) == len(rest):
                return left, right, None
        if straight and flat and wide and rest:
            above = [s for s in rest if s.bbox[3] <= (sy0 + sy1) / 2]
            below = [s for s in rest if s.bbox[1] >= (sy0 + sy1) / 2]
            if above and below and len(above) + len(below) == len(rest):
                return above, below, None

    dot = None
    for stroke in members:
        sx0, sy0, sx1, sy1 = stroke.bbox
        small = (sx1 - sx0) <= SEPARATOR_MAX * height and (
            sy1 - sy0
        ) <= SEPARATOR_MAX * height
        low = ((sy0 + sy1) / 2 - box[1]) / height >= SEPARATOR_MIN_Y
        if small and low:
            dot = stroke
            break
    glyphs = [s for s in members if s is not dot]
    return glyphs, [], dot


# ---------------------------------------------------------------- rendering --
def _merge_stacked(blobs: List[np.ndarray]) -> List[np.ndarray]:
    """Join the pieces of one digit, keep neighbouring digits apart.

    Connectivity alone cuts a "5" whose bar does not quite touch its curve, and
    those two pieces sit one above the other: they cover the same columns. Two
    digits written side by side barely share any. So pieces merge when they
    overlap in x across most of the narrower one.
    """
    merged = list(blobs)
    joined = True
    while joined:
        joined = False
        for i in range(len(merged)):
            for k in range(i + 1, len(merged)):
                a, b = merged[i], merged[k]
                a0, a1 = a[:, 0].min(), a[:, 0].max()
                b0, b1 = b[:, 0].min(), b[:, 0].max()
                overlap = min(a1, b1) - max(a0, b0)
                narrower = min(a1 - a0, b1 - b0) + 1
                if overlap > MERGE_OVERLAP * narrower:
                    merged[i] = np.concatenate([a, b])
                    del merged[k]
                    joined = True
                    break
            if joined:
                break
    return merged


def render_number(
    strokes: Sequence[Stroke], dot_x: Optional[float] = None
) -> Tuple[np.ndarray, np.ndarray, List[np.ndarray], int]:
    """Draw a number's strokes as the recogniser expects to receive them.

    The image is built, not thresholded: the strokes are already the ink, so
    there is no scan noise to separate and ``get_clean_thresh`` has nothing to
    do here (it earns its place on the flattened-page path instead).

    Digits are separated by the connectivity of what was drawn rather than by
    the gaps between strokes. Grouping on gaps cannot have it both ways: the
    upright of a "4" barely touches its diagonal, while the "8" and the "5" of
    "8.5" are written side by side, so any gap threshold either splits the 4 or
    merges the 8 and the 5 into one blob.

    Args:
        strokes: The number's strokes, decimal point already removed.
        dot_x: Where the decimal point was, in display coordinates.

    Returns:
        ``(gray, thresh, contours, dot)`` -- ``thresh`` is white ink on black,
        ``contours`` are one per digit in cv2's ``(n, 1, 2)`` int32 shape and
        ordered left to right, ``dot`` is how many digits precede the decimal
        point, and ``gray`` is only there for its shape.
    """
    if not strokes:
        return np.zeros((1, 1), np.uint8), np.zeros((1, 1), np.uint8), [], 0

    box = _union([s.bbox for s in strokes])
    height_px = max((box[3] - box[1]) * ZOOM, 1.0)
    thickness = max(MIN_THICKNESS, int(round(STROKE_THICKNESS * height_px)))
    pad = PAD + thickness

    width = int((box[2] - box[0]) * ZOOM) + 2 * pad
    height = int((box[3] - box[1]) * ZOOM) + 2 * pad
    thresh = np.zeros((height, width), np.uint8)

    for stroke in strokes:
        px = (stroke.points - np.array([box[0], box[1]])) * ZOOM + pad
        if len(px) > 1:
            cv2.polylines(
                thresh, [px.astype(np.int32)], False, 255, thickness, cv2.LINE_8
            )
        bx = stroke.bbox
        if (bx[2] - bx[0]) * ZOOM < 12 and (bx[3] - bx[1]) * ZOOM < 12:
            # a stroke that is a dot on the page must survive as a blob
            centre = px.mean(axis=0).astype(int)
            cv2.circle(thresh, tuple(centre), thickness, 255, -1, cv2.LINE_8)

    count, labels = cv2.connectedComponents(thresh, connectivity=8)
    blobs: List[np.ndarray] = []
    for label in range(1, count):
        ys, xs = np.nonzero(labels == label)
        if len(xs) < 4:
            continue
        blobs.append(np.stack([xs, ys], axis=1))
    contours = [
        blob.reshape(-1, 1, 2).astype(np.int32) for blob in _merge_stacked(blobs)
    ]
    contours.sort(key=lambda c: c[:, 0, 0].min())

    if dot_x is None:
        dot = len(contours)
    else:
        dot_px = (dot_x - box[0]) * ZOOM + pad
        dot = sum(1 for c in contours if c[:, 0, 0].mean() < dot_px)

    gray = 255 - thresh
    return gray, thresh, contours, dot


def read_number(
    strokes: Sequence[Stroke], dot_x: Optional[float], classifier: Any
) -> List[Tuple[float, float]]:
    """Ranked ``(probability, value)`` readings of one rendered number.

    The digits go straight to ``extract_all_digits`` rather than through
    ``find_digit_contours``: that function looks for digits inside a printed
    box and drops anything below the middle line, which eats the low digit of a
    handwritten ``10.5``. Here the glyphs and the decimal point are already
    known from the strokes.

    Returns:
        The ranked readings, or ``[]`` when there is nothing to read. An empty
        list is not ``[(1.0, 0)]``: "no mark" must never be reported as a
        confident zero.
    """
    gray, thresh, contours, dot = render_number(strokes, dot_x)
    if not contours:
        return []
    all_digits = recognize.extract_all_digits(contours, gray, thresh, classifier)
    if not all_digits:
        return []
    return recognize.process_digits_combinations(all_digits, dot)


# ------------------------------------------------------------------ raster --
def coloured_ink(page: Any, dpi: int = DPI) -> Tuple[np.ndarray, float]:
    """The grader's marks on a flattened page, as a mask.

    The page underneath is a black and white scan, so the marks are whatever
    on it has colour. The test is saturation, not hue: one job already uses
    four different reds, and nothing says the next grader will not pick green.

    Args:
        page: A ``pymupdf`` page.
        dpi: Rendering resolution; the rest of the pipeline assumes 300.

    Returns:
        ``(mask, scale)`` -- ``mask`` is 255 where ink was found, ``scale`` is
        pixels per point.
    """
    pixmap = page.get_pixmap(dpi=dpi)
    image = np.frombuffer(pixmap.samples, np.uint8).reshape(
        pixmap.height, pixmap.width, pixmap.n
    )[:, :, :3]
    hsv = cv2.cvtColor(image, cv2.COLOR_RGB2HSV)
    mask = (
        (hsv[:, :, 1] >= RASTER_MIN_SATURATION) & (hsv[:, :, 2] >= RASTER_MIN_VALUE)
    ).astype(np.uint8) * 255
    # jpeg leaves coloured fringes along every printed edge; they are one or
    # two pixels wide and would otherwise be read as punctuation
    kernel = np.ones((RASTER_OPEN_KERNEL, RASTER_OPEN_KERNEL), np.uint8)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)
    return mask, dpi / 72.0


def raster_marks(mask: np.ndarray, scale: float) -> List[Tuple[Stroke, int]]:
    """The mask's blobs as strokes, so the ink and raster paths select alike.

    A blob's outline is a closed polyline, which is what ``enclosing_stroke``
    and the clustering already understand; the label is kept so the blob can
    be erased from the mask once it turns out to be the circle.
    """
    count, labels, stats, _ = cv2.connectedComponentsWithStats(mask, connectivity=8)
    marks = []
    for label in range(1, count):
        if stats[label, cv2.CC_STAT_AREA] < RASTER_MIN_BLOB_PX:
            continue
        contours, _ = cv2.findContours(
            (labels == label).astype(np.uint8),
            cv2.RETR_EXTERNAL,
            cv2.CHAIN_APPROX_SIMPLE,
        )
        if not contours:
            continue
        points = max(contours, key=cv2.contourArea).reshape(-1, 2) / scale
        if len(points) < 2:
            continue
        marks.append((Stroke(points=points.astype(float)), label))
    return marks


def raster_candidates(page: Any, max_points: Optional[float] = None) -> List[Candidate]:
    """Marks on a flattened page that could be the grade.

    Everything above the pixels is shared with the annotation path -- the
    clustering, the enclosing test, the size band -- because a blob's outline
    behaves like a stroke. What differs is the recognition: the ink is already
    pixels, so the crop goes to the scan pipeline (``get_clean_thresh`` and
    ``find_digit_contours``), which is what that pipeline was built for.
    """
    page_size = (float(page.rect.width), float(page.rect.height))
    mask, scale = coloured_ink(page)
    marks = raster_marks(mask, scale)
    if not marks:
        return []

    label_of = {id(stroke): label for stroke, label in marks}
    strokes = [stroke for stroke, _ in marks]

    candidates: List[Candidate] = []
    for box, members in cluster_strokes(strokes, page_size[0]):
        width = (box[2] - box[0]) / page_size[0]
        if not MIN_CLUSTER_W <= width <= MAX_CLUSTER_W:
            continue
        circle = enclosing_stroke(members)
        inner = [s for s in members if s is not circle] if circle else list(members)
        if not inner:
            continue
        inner_box = _union([s.bbox for s in inner])
        crop = _crop_mask(mask, inner_box, scale)
        if crop is None:
            continue
        if circle is not None:
            # the ring would be read as a 0 around the digits
            _erase(crop, mask, label_of[id(circle)], inner_box, scale)
        candidates.append(
            Candidate(
                bbox=box,
                circled=circle is not None,
                page_size=page_size,
                source="raster",
                image=crop,
            )
        )
    return candidates


def _crop_mask(mask, box, scale, pad=PAD):
    """The mask around ``box``, in page points, with a margin."""
    x0 = max(int(box[0] * scale) - pad, 0)
    y0 = max(int(box[1] * scale) - pad, 0)
    x1 = min(int(box[2] * scale) + pad, mask.shape[1])
    y1 = min(int(box[3] * scale) + pad, mask.shape[0])
    if x1 - x0 < 4 or y1 - y0 < 4:
        return None
    return mask[y0:y1, x0:x1].copy()


def _erase(crop, mask, label, box, scale, pad=PAD):
    """Blank one blob out of a crop, by its connected-component label."""
    count, labels = cv2.connectedComponents(mask, connectivity=8)
    x0 = max(int(box[0] * scale) - pad, 0)
    y0 = max(int(box[1] * scale) - pad, 0)
    bottom, right = y0 + crop.shape[0], x0 + crop.shape[1]
    crop[labels[y0:bottom, x0:right] == label] = 0


def read_raster(candidate: Candidate, classifier: Any) -> List[Tuple[float, float]]:
    """Ranked readings of a mark that arrived as pixels.

    Here the scan pipeline is the right one: there are no strokes to say where
    the glyphs or the decimal point are, and ``get_clean_thresh``'s Otsu retry
    earns its place on exactly this kind of input.
    """
    if candidate.image is None or not candidate.image.any():
        return []
    gray = 255 - candidate.image
    cnts, dot, thresh = recognize.find_digit_contours(gray)
    if not cnts:
        return []
    all_digits = recognize.extract_all_digits(cnts, gray, thresh, classifier)
    if not all_digits:
        return []
    return recognize.process_digits_combinations(all_digits, dot)


# --------------------------------------------------------------- candidates --
def grade_candidates(page: Any, max_points: Optional[float] = None) -> List[Candidate]:
    """Every mark on ``page`` that could be the grade.

    Typed annotations win when the page has any: they are exact, so there is no
    reason to recognise handwriting as well.

    Args:
        page: A ``pymupdf`` page -- the first page of a question.
        max_points: The question's maximum, used only to size the search.

    Returns:
        Candidates, unranked. ``pick`` chooses between them.
    """
    page_size = (float(page.rect.width), float(page.rect.height))

    texts = [
        Candidate(bbox=mark.bbox, text=mark.content, page_size=page_size)
        for mark in page_texts(page)
        if parse_text_grade(mark.content) is not None
    ]
    if texts:
        return texts

    strokes = page_strokes(page)
    if not strokes:
        # nothing was annotated: either the page was never graded, or it was
        # flattened on export and the marks are pixels now
        return raster_candidates(page, max_points)

    candidates: List[Candidate] = []
    for box, members in cluster_strokes(strokes, page_size[0]):
        width = (box[2] - box[0]) / page_size[0]
        if not MIN_CLUSTER_W <= width <= MAX_CLUSTER_W:
            continue
        circle = enclosing_stroke(members)
        inner = [s for s in members if s is not circle] if circle else list(members)
        if not inner:
            continue
        inner_box = _union([s.bbox for s in inner])
        numerator, denominator, dot_stroke = split_separator(inner, inner_box)
        if not numerator:
            continue
        dot_x = None
        if dot_stroke is not None:
            dot_x = (dot_stroke.bbox[0] + dot_stroke.bbox[2]) / 2
        candidates.append(
            Candidate(
                bbox=box,
                number_strokes=numerator,
                dot_x=dot_x,
                denominator_strokes=denominator,
                circled=circle is not None,
                page_size=page_size,
            )
        )
    return candidates


def matricule_region(page_size: Tuple[float, float]) -> Tuple[float, ...]:
    """The printed matricule band of a regular page, in display points.

    Shares ``config.matricule_box`` with the recogniser so that a job whose
    template moves the box moves this with it.
    """
    x0, x1, y0, y1 = matricule_box["exam"]["regular"]
    return (
        x0 * page_size[0],
        y0 * page_size[1],
        x1 * page_size[0],
        y1 * page_size[1],
    )


# ---------------------------------------------------------------- selection --
# Above this, a reading is good enough to offer as a prefilled value; below,
# it goes to the teacher unfilled. Measured over 257 real graded pages: at 0.90
# the reader fills 95% of them with 98.6% precision on the batch it was tuned
# on and 100% on the other one, while 0.95 buys 0.3 points of precision for 18
# points of coverage.
AUTO_GRADE_MIN_CONFIDENCE = 0.90
MIN_UNAMBIGUOUS = 5
# grades live in the margin at the top or the right of the page
TOP_BAND = 0.6
CIRCLE_BONUS = 0.06
DENOMINATOR_BONUS = 0.10
UNMEASURED_CEILING = 0.90
# Without a learned position there is nothing to tell the grade apart from any
# other mark in the margin, so such a reading is a suggestion at best: on a
# question nobody graded it is how a correction becomes a phantom grade.
NO_PRIOR_CEILING = 0.50
# The flattened path recovers the mark from pixels instead of strokes; it is
# measurably weaker, so it suggests and never prefills.
RASTER_CEILING = 0.50
LOW_MAX_POINTS = 3.0
# A question that is not itself a bonus can still carry a few bonus points
# inside it, so a grade may sit a little above the maximum -- the correction
# screen already accepts that and warns about it. The allowance stays small:
# its job is to keep rejecting a misread, and doubling the maximum would let
# "85" through on a question out of 12.
BONUS_HEADROOM_RATIO = 0.25
BONUS_HEADROOM_MIN = 1.0
BONUS_HEADROOM_MAX = 3.0


def _median_centre(centres):
    xs = sorted(c[0] for c in centres)
    ys = sorted(c[1] for c in centres)
    return (xs[len(xs) // 2], ys[len(ys) // 2])


def learn_modal_positions(candidates_by_question, rounds: int = 3):
    """Where this grader puts the grade, per question, learned from the batch.

    Graders repeat themselves within a batch but not between jobs: one exam has
    its grades two thirds down the right margin, another jams them into the top
    right corner over the matricule box. So this is measured per (job,
    question) from the batch itself, and never carried over.

    Only marks in the top band of the page are considered. Graders write the
    grade in the margin at the top or the right; the rest of the page is the
    student's work and the corrections on it, which on a busy question
    outnumber the grade and would otherwise drag the estimate down into the
    middle of the page -- measured on a six-copy job, where the unconstrained
    median landed at 94% of the page height.

    Args:
        candidates_by_question: ``{question: [candidates of one page, ...]}``.
        rounds: Refinement passes.

    Returns:
        ``{question: (cx, cy)}``; a question with too little to go on is left
        out, and ``pick`` then falls back to the top-most, right-most mark.
    """
    modal = {}
    for question, pages in candidates_by_question.items():
        in_band = [
            [c for c in page if c.centre[1] <= TOP_BAND]
            for page in candidates_by_question[question]
        ]
        in_band = [page for page in in_band if page]
        if len(in_band) < MIN_UNAMBIGUOUS:
            continue
        singles = [page[0].centre for page in in_band if len(page) == 1]
        if singles:
            centre = _median_centre(singles)
        else:
            centre = _median_centre(
                [
                    max(page, key=lambda c: c.centre[0] - c.centre[1]).centre
                    for page in in_band
                ]
            )
        for _ in range(rounds):
            nearest = [
                min(
                    page,
                    key=lambda c: math.hypot(
                        c.centre[0] - centre[0], c.centre[1] - centre[1]
                    ),
                ).centre
                for page in in_band
            ]
            moved = _median_centre(nearest)
            if moved == centre:
                break
            centre = moved
        if centre[1] <= TOP_BAND:
            modal[question] = centre
    return modal


def grade_ceiling(max_points: Optional[float]) -> Optional[float]:
    """The highest grade a question can plausibly carry.

    Bonus points inside an ordinary question mean the maximum is not a hard
    ceiling; the allowance is deliberately a fraction of it rather than a
    multiple, because the same bound is what rejects a misread.
    """
    if max_points is None:
        return None
    headroom = min(
        max(BONUS_HEADROOM_MIN, BONUS_HEADROOM_RATIO * max_points),
        BONUS_HEADROOM_MAX,
    )
    return max_points + headroom


def _bounded(readings, max_points):
    """The best reading that fits the question, repairing a misplaced dot.

    A value above the maximum but within the bonus allowance is kept and
    reported, so that a genuine bonus is not thrown away; ``over`` says so, and
    the caller lowers its confidence because the same shape of value is what a
    misread produces.

    Beyond that, the number usually means the decimal point was missed, so it
    is divided down and its decimals re-fitted before being given up on --
    what ``recognize.grade`` does for the cover-page table.

    Returns:
        ``(probability, value, over)`` or ``None``.
    """
    if max_points is None:
        return (readings[0][0], readings[0][1], False) if readings else None

    ceiling = grade_ceiling(max_points)
    for probability, value in readings:
        if value <= max_points + 1e-6:
            return probability, value, False
    for probability, value in readings:
        if value <= ceiling + 1e-6:
            return probability, value, True
    for probability, value in readings:
        repaired = value
        while repaired > ceiling + 1e-6:
            repaired = repaired / 10
        repaired = recognize.correct_decimals(repaired)
        if 0 <= repaired <= ceiling + 1e-6:
            return probability * 0.5, repaired, repaired > max_points + 1e-6
    return None


def pick(candidates, modal_centre, max_points, classifier, bonus=False):
    """Choose between the marks of one page and read the grade off it.

    The signals are combined rather than used as filters, because a grader who
    does not circle would otherwise be invisible: position carries the
    decision, a circle and a matching fraction denominator add to it, and the
    question's maximum is the one hard constraint.

    Args:
        candidates: What ``grade_candidates`` returned for the page.
        modal_centre: Where this question's grades usually sit, or ``None``.
        max_points: The question's maximum, or ``None``.
        classifier: The digit classifier, unused for typed annotations.
        bonus: True for a bonus question, which is always sent to review.

    Returns:
        A ``Reading``. ``grade is None`` means nothing was written here -- it
        is never reported as a zero.
    """
    if not candidates:
        return Reading(reason="not_found", n_candidates=0)

    # The grade lives in the margin at the top or the right. Marks below that
    # band are corrections on the student's work: reading one as the grade
    # invents a value for a question nobody graded, which is worse than
    # reporting nothing.
    candidates = [c for c in candidates if c.centre[1] <= TOP_BAND]
    if not candidates:
        return Reading(reason="not_found", n_candidates=0)

    def distance(candidate):
        if modal_centre is None:
            cx, cy = candidate.centre
            return (1 - cx) + cy  # fall back to top-most, right-most
        cx, cy = candidate.centre
        return math.hypot(cx - modal_centre[0], cy - modal_centre[1])

    ordered = sorted(candidates, key=distance)
    ambiguous = (
        len(ordered) > 1 and abs(distance(ordered[0]) - distance(ordered[1])) < 0.03
    )

    for candidate in ordered:
        if candidate.text is not None:
            parsed = parse_text_grade(candidate.text)
            if parsed is None:
                continue
            value, denominator = parsed
            ceiling = grade_ceiling(max_points)
            if ceiling is not None and value > ceiling + 1e-6:
                continue
            over_max = max_points is not None and value > max_points + 1e-6
            if denominator is not None and max_points is not None:
                if abs(denominator - max_points) > 1e-6:
                    continue  # a sub-question mark, not the grade
            confidence = 1.0
            reason = "ok"
            if over_max:
                # a bonus inside the question, or a misread that looks like one
                confidence = min(confidence, UNMEASURED_CEILING)
            if ambiguous or bonus:
                confidence = min(confidence, UNMEASURED_CEILING)
                reason = "ambiguous" if ambiguous else "ok"
            if modal_centre is None:
                confidence = min(confidence, NO_PRIOR_CEILING)
            return Reading(
                grade=value,
                confidence=confidence,
                reason=reason,
                source="freetext",
                bbox=candidate.bbox,
                n_candidates=len(candidates),
            )

        if candidate.source == "raster":
            readings = read_raster(candidate, classifier)
        else:
            readings = read_number(
                candidate.number_strokes, candidate.dot_x, classifier
            )
        if not readings:
            continue
        best = _bounded(readings, max_points)
        if best is None:
            continue
        probability, value, over_max = best
        # the truncated-fraction bonus of process_digits_combinations can push
        # the sum above 1; a confidence gate needs a real probability
        probability = min(1.0, max(0.0, probability))
        if over_max:
            probability = min(probability, UNMEASURED_CEILING)

        if candidate.denominator_strokes:
            den = read_number(
                candidate.denominator_strokes, candidate.denominator_dot_x, classifier
            )
            if den and max_points is not None:
                if abs(den[0][1] - max_points) > 1e-6:
                    continue  # denominator disagrees: a sub-question mark
                probability = min(1.0, probability + DENOMINATOR_BONUS)

        if candidate.circled:
            probability = min(1.0, probability + CIRCLE_BONUS)
        if candidate.source == "raster":
            # measured well below the annotation path, and on a flattened page
            # there is no stroke to say where a glyph ends or a decimal point
            # sits, so these always go to a human
            probability = min(probability, RASTER_CEILING)
        if ambiguous:
            probability *= 0.5
        if modal_centre is None:
            probability = min(probability, NO_PRIOR_CEILING)
        if bonus or (max_points is not None and max_points < LOW_MAX_POINTS):
            probability = min(probability, UNMEASURED_CEILING)

        return Reading(
            grade=value,
            confidence=probability,
            reason="ambiguous" if ambiguous else "ok",
            source=candidate.source,
            bbox=candidate.bbox,
            n_candidates=len(candidates),
        )

    return Reading(reason="above_max", n_candidates=len(candidates))
