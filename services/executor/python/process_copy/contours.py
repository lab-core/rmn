"""Finding the boxes and the digits drawn on a page, as contours."""

from statistics import median
import cv2
import imutils
import numpy as np
from process_copy.imaging import (
    cells_in_frame,
    fetch_box,
    frame_to_cells,
    get_image_from_contour,
    hough_segments,
    imwrite_contours,
    imwrite_png,
)







def find_edges(
    cropped,
    thick=5,
    min_lenth=80,
    max_gap=15,
    angle_resolution=np.pi / 2,
    line_on_original=False,
):
    """Find the lines on the image."""
    # Computing the edge map via the Canny edge detector
    edged = cv2.Canny(cropped, 50, 200, 255)
    imwrite_png("canny", edged)
    edged = cv2.dilate(edged, kernel=np.ones((3, 3), dtype="uint8"))
    imwrite_png("dilated", edged)

    if thick:
        lines = cv2.HoughLinesP(
            edged, 1, angle_resolution, 50, minLineLength=min_lenth, maxLineGap=max_gap
        )
        if line_on_original:
            edged = cropped.copy()
        if lines is not None:
            for x1, y1, x2, y2 in hough_segments(lines):
                cv2.line(
                    edged,
                    (int(x1), int(y1)),
                    (int(x2), int(y2)),
                    (255, 255, 255),
                    thick,
                )
            imwrite_png("edged", edged)

        # erode the image to keep only the big lines
        if not line_on_original:
            edged = cv2.erode(edged, kernel=np.ones((thick, thick), dtype="uint8"))
            imwrite_png("eroded", edged)
    return edged




def biggest_children(cnts, hierarchy, parent_positon):
    # Look only to the children (starting with the biggest contours) to try to find a matricule
    n = hierarchy[0][parent_positon][2]  # first child index of the biggest contour
    scnts = []
    while n != -1:
        scnts.append(cnts[n])
        n = hierarchy[0][n][0]  # next index of the current contour
    return sorted(scnts, key=cv2.contourArea, reverse=True)




def biggest_contour(cropped):
    """``(contours, hierarchy, position)`` of the biggest contour of the edges,
    ``position`` None when there is no contour at all."""
    cnts, hierarchy = cv2.findContours(
        find_edges(cropped, thick=0), cv2.RETR_TREE, cv2.CHAIN_APPROX_SIMPLE
    )
    cnts = imutils.grab_contours((cnts, hierarchy))
    imwrite_contours("rgray", cropped, cnts, thick=5)
    if len(cnts) == 0:
        return cnts, hierarchy, None
    pos, _ = max(enumerate(cnts), key=lambda cnt: cv2.contourArea(cnt[1]))
    return cnts, hierarchy, pos




def find_matricule_box_contours(gray, regular_box, callback, biggest_child=False,
                                straighten=False):
    # find the id box, straightened when the scan turned it (see straighten_frame)
    cropped = fetch_box(gray, regular_box)
    if straighten:
        cropped, _ = straighten_frame(cropped)
    if biggest_child:
        cnts, hierarchy, pos = biggest_contour(cropped)
        # a blank / unreadable matricule box yields no contours: there is
        # nothing to analyse, so report "no box found" instead of crashing on
        # max() over an empty sequence (which used to kill the whole job).
        if pos is None:
            return None, False
        # Find the biggest contour for the front box
        biggest_c = cnts[pos]
        for cnt in biggest_children(cnts, hierarchy, pos):
            gray_box = get_image_from_contour(cropped, cnt)
            if callback(gray_box, cnt):
                return biggest_c, True
        return biggest_c, False
    else:
        return None, callback(cropped, None)




def edge_coverage(ink, rect, band=3):
    """Share of the least inked side of ``rect``: 1 when its four sides are lines.

    A side counts as inked where a pixel within ``band`` of it is ink, so a
    slightly skewed or dotted (dithered scan) line still covers its side.
    """
    x, y, w, h = rect
    height, width = ink.shape

    def row(y0):
        return ink[max(0, y0 - band) : min(height, y0 + band + 1), x : x + w].any(axis=0).mean()

    def column(x0):
        return ink[y : y + h, max(0, x0 - band) : min(width, x0 + band + 1)].any(axis=1).mean()

    if w <= 0 or h <= 0:
        return 0.0
    return float(min(row(y), row(y + h - 1), column(x), column(x + w - 1)))




def ink_mask(gray):
    """The ink of a scan: darker than its paper by a share of the contrast.

    A fixed threshold (200) took a paper scanned at grey 200 or darker
    (salmon, goldenrod) for ink, and a thin light-grey printed line (0.5 pt
    at #BFBFBF, lightened further by the blur) for paper.
    """
    blurred = cv2.GaussianBlur(gray, (3, 3), 0)
    paper = float(np.percentile(blurred, 75))
    darkest = float(np.percentile(blurred, 1))
    level = paper - max(30.0, 0.2 * (paper - darkest))
    return cv2.threshold(blurred, level, 255, cv2.THRESH_BINARY_INV)[1]




def find_rectangles(gray, min_size=20, min_coverage=0.85, inner=False, relative=False):
    """The rectangles drawn on ``gray``: ``(x, y, w, h)`` with four ink sides.

    Every contour of the ink is a candidate, outer outlines and holes alike,
    and is kept when the four sides of its bounding rectangle are lines. A box
    is returned once: its hole is dropped (a rectangle inside another one of
    nearly its size), or its outline when ``inner`` (the inside of the box,
    where something is written). The boxes inside a table cell are kept.

    The ink is what is darker than grey 200, or with ``relative`` darker
    than the paper by a share of the contrast (see ``ink_mask``).
    """
    if relative:
        ink = ink_mask(gray)
    else:
        blurred = cv2.GaussianBlur(gray, (3, 3), 0)
        ink = cv2.threshold(blurred, 200, 255, cv2.THRESH_BINARY_INV)[1]
    # join the dots of a dithered scan, so a thin printed line is one stroke
    ink = cv2.morphologyEx(ink, cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
    cnts, _ = cv2.findContours(ink, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
    ink = ink > 0
    rects = []
    for c in cnts:
        rect = cv2.boundingRect(c)
        if min(rect[2:]) >= min_size and edge_coverage(ink, rect) >= min_coverage:
            rects.append(rect)

    def same_box(small, big):
        x, y, w, h = small
        kx, ky, kw, kh = big
        cx, cy = x + w / 2, y + h / 2
        return kx <= cx <= kx + kw and ky <= cy <= ky + kh and w * h >= 0.5 * kw * kh

    kept = []
    for rect in sorted(rects, key=lambda r: r[2] * r[3], reverse=not inner):
        if inner:
            if not any(same_box(k, rect) for k in kept):
                kept.append(rect)
        elif not any(same_box(rect, k) for k in kept):
            kept.append(rect)
    return kept, ink




def _same_row(ref, rect, size_tol=0.25):
    """Whether ``rect`` is a box of the same size as ``ref``, on its row."""
    _, ry, rw, rh = ref
    _, y, w, h = rect
    return (
        abs(w - rw) <= size_tol * rw
        and abs(h - rh) <= size_tol * rh
        and abs((y + h / 2) - (ry + rh / 2)) <= 0.35 * rh
    )




def _regular_run(row, n, ink, min_coverage):
    """The ``n`` evenly spaced boxes of ``row`` (sorted by x), or None.

    A box the detection missed -- a digit written over its side merges with it
    and the outline is no longer a rectangle -- is put back where the spacing
    places it, between two found boxes or at one end of the run, provided its
    sides are still drawn there.
    """
    gaps = [b[0] - a[0] for a, b in zip(row, row[1:])]
    if not gaps:
        return None
    pitch = median(g for g in gaps if g < 1.6 * min(gaps))
    if pitch < 0.8 * median(w for _, _, w, _ in row):
        return None  # overlapping boxes: not a row of boxes

    def inferred(x, like):
        rect = (int(round(x)), like[1], like[2], like[3])
        return rect if edge_coverage(ink, rect, band=6) >= min_coverage else None

    # chains of boxes one pitch apart, a missing box filled where the gap is a
    # whole number of pitches
    chains = [[row[0]]]
    for prev, rect, gap in zip(row, row[1:], gaps):
        steps = round(gap / pitch)
        if steps >= 1 and abs(gap - steps * pitch) <= 0.15 * pitch and steps <= n:
            fill = [inferred(prev[0] + k * gap / steps, prev) for k in range(1, steps)]
            if all(fill):
                chains[-1].extend(fill + [rect])
                continue
        chains.append([rect])

    for chain in sorted(chains, key=len, reverse=True):
        # one box missing at an end of the run: try both ends
        if len(chain) == n - 1:
            ends = [
                inferred(chain[0][0] - pitch, chain[0]),
                inferred(chain[-1][0] + pitch, chain[-1]),
            ]
            if ends[0]:
                chain = [ends[0]] + chain
            elif ends[1]:
                chain = chain + [ends[1]]
        if len(chain) == n:
            return chain
    return None




def find_matricule_digit_boxes(gray, n, min_coverage=0.6):
    """The ``n`` boxes the digits of a matricule are written in, as contours.

    The same reading for any page and any template: the frame the template
    gives (cover page or later page) holds a row of ``n`` rectangles of the
    same size, evenly spaced; the labels, the table lines and the other boxes
    around them (group, page number) do not form such a row. Returns the boxes
    sorted from left to right, or ``[]`` when the frame holds no such row.
    """
    rects, ink = find_rectangles(gray)
    tried = set()
    for ref in sorted(rects, key=lambda r: -r[2] * r[3]):
        row = sorted(r for r in rects if _same_row(ref, r))
        key = tuple(row)
        if len(row) < n - 1 or key in tried:
            continue
        tried.add(key)
        run = _regular_run(row, n, ink, min_coverage)
        if run:
            imwrite_contours("matricule_boxes", gray, [_rect_contour(r) for r in run])
            return [_rect_contour(r) for r in run]
    return []




def _rect_contour(rect):
    """A contour whose bounding rectangle is ``rect``."""
    x, y, w, h = rect
    return np.array([[[x, y]], [[x + w - 1, y]], [[x + w - 1, y + h - 1]], [[x, y + h - 1]]], dtype=np.int32)




def ink_share(ink, rect, margin=0.12):
    """Share of the inside of ``rect`` that is ink, its sides left out."""
    x, y, w, h = rect
    dx, dy = max(4, int(margin * w)), max(4, int(margin * h))
    inside = ink[y + dy : y + h - dy, x + dx : x + w - dx]
    return float(inside.mean()) if inside.size else 0.0




def _aligned_runs(rects, tol=0.15):
    """Every set of boxes of ``rects`` aligned with one of them, with its direction.

    Boxes in a column share their left side, their right side or their
    centre, and their width; boxes in a row their top, their bottom or their
    centre, and their height. The box at either end of a run may be up to
    60% bigger across it: the total. A run is sorted along its direction and
    holds no two overlapping boxes.
    """
    runs = {}
    for ref in rects:
        for horizontal in (False, True):
            lead, size = (1, 3) if horizontal else (0, 2)
            axis = 0 if horizontal else 1

            def aligned(r):
                edges = (r[lead], r[lead] + r[size], r[lead] + r[size] / 2)
                ref_edges = (ref[lead], ref[lead] + ref[size], ref[lead] + ref[size] / 2)
                return (any(abs(e - f) <= tol * ref[size] for e, f in zip(edges, ref_edges))
                        and ref[size] / 1.6 <= r[size] <= 1.6 * ref[size])

            kept = []
            for r in sorted(filter(aligned, rects), key=lambda r: r[axis]):
                if not kept or r[axis] >= kept[-1][axis] + 0.9 * kept[-1][axis + 2]:
                    kept.append(r)
            if not kept:
                continue
            across = median(r[size] for r in kept)
            ends = (kept[0], kept[-1])
            kept = [r for r in kept
                    if abs(r[size] - across) <= tol * across
                    or (r in ends and across < r[size] <= 1.6 * across)]
            if kept:
                runs.setdefault((tuple(kept), horizontal), None)
    return list(runs)




def _segments(run, horizontal, ink, min_coverage=0.6):
    """The run cut where its boxes stop following each other.

    Two boxes follow each other when the gap between them is the gap of the
    run. A wider gap is a box the detection missed (a grade written over its
    sides) only when it holds whole boxes whose sides are drawn there; it is
    then filled. Otherwise the run is cut: a box drawn apart under a column
    of the table, or squares spaced wider than the rest, are another run.
    """
    axis = 0 if horizontal else 1
    size = median(r[axis + 2] for r in run)
    gaps = [b[axis] - a[axis] - a[axis + 2] for a, b in zip(run, run[1:])]
    spacing = max(median(gaps), 0) if gaps else 0
    segments = [[run[0]]]
    for prev, r, gap in zip(run, run[1:], gaps):
        if gap <= spacing + 0.3 * size:
            segments[-1].append(r)
            continue
        steps = (gap - spacing) / (size + spacing)
        k = round(steps)
        if k >= 1 and abs(steps - k) <= 0.25:
            length = (gap - (k + 1) * spacing) / k
            start = prev[axis] + prev[axis + 2] + spacing
            fill = []
            for i in range(k):
                at = int(round(start + i * (length + spacing)))
                if horizontal:
                    fill.append((at, prev[1], int(round(length)), prev[3]))
                else:
                    fill.append((prev[0], at, prev[2], int(round(length))))
            if all(edge_coverage(ink, f, band=6) >= min_coverage for f in fill):
                segments[-1].extend(fill + [r])
                continue
        segments.append([r])
    return segments




def frame_skew(gray, max_angle=10, min_size=20):
    """The angle, in degrees, the boxes of the frame make with the axes.

    Every box of a table is a closed outline, still a rectangle when the scan
    turned the page: the angle of the smallest rectangle around each outline
    that fills it, the median weighted by area, is how far the page turned.
    The sign is the one ``cv2.getRotationMatrix2D`` takes to straighten it.
    0 when the frame holds no box.
    """
    ink = cv2.morphologyEx(ink_mask(gray), cv2.MORPH_CLOSE, np.ones((3, 3), np.uint8))
    cnts, _ = cv2.findContours(ink, cv2.RETR_LIST, cv2.CHAIN_APPROX_SIMPLE)
    angles, areas = [], []
    for c in cnts:
        _, (w, h), angle = cv2.minAreaRect(c)
        if min(w, h) < min_size or cv2.contourArea(c) < 0.85 * w * h:
            continue  # not a box: a digit, a label, a line
        angle -= 90 * round(angle / 90)
        if abs(angle) <= max_angle:
            angles.append(angle)
            areas.append(w * h)
    if not angles:
        return 0.0
    order = np.argsort(angles)
    cumulated = np.cumsum(np.array(areas)[order])
    return float(np.array(angles)[order][np.searchsorted(cumulated, cumulated[-1] / 2)])




def straighten_frame(cropped, min_angle=0.5):
    """The frame turned so that its lines are horizontal and vertical.

    A frame turned by less than ``min_angle`` degrees is read as it is: a
    box is then a pixel off at most, and turning it only blurs the strokes,
    enough to change a doubtful digit of a matricule.

    Returns:
        ``(straight, back)``: the straightened frame, and the affine matrix
        that takes its points back to ``cropped``, None when the frame is
        straight enough to be read as it is.
    """
    angle = frame_skew(cropped)
    if abs(angle) < min_angle:
        return cropped, None
    height, width = cropped.shape[:2]
    turn = cv2.getRotationMatrix2D((width / 2, height / 2), angle, 1.0)
    straight = cv2.warpAffine(cropped, turn, (width, height), flags=cv2.INTER_LINEAR,
                              borderMode=cv2.BORDER_CONSTANT, borderValue=255)
    imwrite_png("straightened", straight)
    return straight, cv2.invertAffineTransform(turn)




def find_grade_boxes(cropped, add_border=False, thick=5):
    """The grade boxes of the frame, as contours sorted along their alignment.

    The grade boxes follow each other, in a column or in a row, and are empty
    on the template: of every run of such rectangles of the frame, the one
    whose boxes are all empty wins, so the labels and the maximums printed
    beside them are left out. On a copy the boxes hold the grades: the run
    covering the most area wins (the most boxes, the biggest ones). A copy is
    better read with the layout of its template (see ``find_layout_boxes``).

    A frame the scan turned is straightened first: the boxes are found on
    it, and returned where they are on ``cropped``, as turned rectangles (a
    caller that cuts the boxes out straightens the frame itself, see
    ``straighten_frame``, so that they come back upright).

    Args:
        cropped: The gray frame the grade box of the template gives.
        add_border: Close the boxes the frame cuts with a border drawn around
            it; the boxes on that border are then dropped from the run.
        thick: The thickness of the lines drawn around the boxes found.

    Returns:
        The contours of the boxes, ``[]`` when the frame holds none.
    """
    cropped, back = straighten_frame(cropped)
    cropped2 = cropped.copy()
    border = max(thick, 2)
    if add_border:
        cv2.rectangle(
            cropped2,
            (border, border),
            (cropped2.shape[1] - border, cropped2.shape[0] - border),
            (0, 0, 0),
            border,
        )
    rects, ink = find_rectangles(cropped2, inner=True, relative=True)
    if add_border:
        # a box closed by the border is a box the frame cuts
        height, width = cropped2.shape[:2]
        edge = 2 * border + 2
        rects = [(x, y, w, h) for x, y, w, h in rects
                 if x > edge and y > edge and x + w < width - edge and y + h < height - edge]
    runs = _runs(rects, ink)

    def area(run):
        return sum(r[2] * r[3] for r in run)

    def narrow(runs, keep):
        """The runs that pass ``keep``, or all of them when none does."""
        return [run for run in runs if keep(run)] or runs

    runs = narrow(runs, lambda run: len(run) >= 2)
    # a few small boxes left empty elsewhere in the frame are not the table
    biggest = max(map(area, runs), default=0)
    runs = narrow(runs, lambda run: area(run) >= 0.25 * biggest)
    runs = narrow(runs, lambda run: all(ink_share(ink, r) < 0.01 for r in run))
    if not runs:
        return []
    return _boxes(max(runs, key=area), cropped, thick, back)




def _runs(rects, ink):
    """The runs of boxes following each other among ``rects`` (see
    ``_aligned_runs`` and ``_segments``), tables left out."""
    # a rectangle filled with other ones is a table, not a box (the hole of a
    # digit written in a box is a small rectangle inside it too)
    rects = [r for r in rects
             if sum(o[2] * o[3] for o in rects if o != r and _inside(o, r)) < 0.5 * r[2] * r[3]]
    return [segment for run, horizontal in _aligned_runs(rects)
            for segment in _segments(run, horizontal, ink)]




def _boxes(run, cropped, thick, back=None):
    """The run as the contours the callers read, taken back to the frame as
    it was scanned when it had to be straightened (``back``)."""
    boxes = [_rect_contour(r) for r in run]
    imwrite_contours("cropped_boxes2", cropped, boxes, thick=2 * (thick + 1))
    if back is not None:
        boxes = [np.round(cv2.transform(b.astype(np.float32), back)).astype(np.int32)
                 for b in boxes]
    return boxes




def _similar(a, b, tol=0.15):
    """Whether rectangles have the same size; ``a`` and ``b`` broadcast as
    arrays of ``(x, y, w, h)``."""
    a, b = np.asarray(a, float), np.asarray(b, float)
    return (np.abs(a[..., 2] - b[..., 2]) <= tol * b[..., 2]) & (
        np.abs(a[..., 3] - b[..., 3]) <= tol * b[..., 3])




def _shift(template, rects, anchors, tol=12):
    """The shift ``(dx, dy)`` that lays the most rectangles of the template on
    rectangles of the same size of the copy, None when it is not known.

    Each anchor (a grade box of the template) laid on a rectangle of its size
    proposes a shift; the right one lays the whole table. It is not known
    when another shift, a box or more away, lays as many (a table of equal
    columns, one of them out of sight), or when fewer rectangles than anchors
    are laid (another page, another template).
    """
    template, rects, anchors = (np.asarray(x, float).reshape(-1, 4)
                                for x in (template, rects, anchors))
    pairs = _similar(rects[None, :], anchors[:, None])
    a, r = np.nonzero(pairs)
    if not len(a):
        return None
    shifts = rects[r, :2] - anchors[a, :2]
    same = _similar(rects[None, :], template[:, None])
    moved = rects[None, None, :, :2] - template[None, :, None, :2] - shifts[:, None, None]
    laid = same[None] & (np.abs(moved) <= tol).all(axis=-1)
    scores = laid.any(axis=2).sum(axis=1)
    best = scores.max()
    if best < len(anchors):
        return None
    tied = shifts[scores == best]
    if np.abs(tied - tied[0]).max() > 2 * tol:
        return None
    dx, dy = np.median(tied, axis=0)
    return float(dx), float(dy)




def _fit(template, rects, shift, tol=12, rounds=3):
    """How the copy's table lies on the template's: ``(scale, offset)``,
    each an ``(x, y)`` pair, so that a point ``p`` of the template is at
    ``p * scale + offset`` on the copy.

    It starts from ``shift`` and is fitted, by least squares, on the centres
    of the rectangles it then lays on one of the same size: a page printed
    at 96% (boxes 4% smaller, rows 4 px closer) is laid box by box, where
    the shift alone was 22 px off at the bottom of the table.
    """
    template, rects = (np.asarray(x, float).reshape(-1, 4) for x in (template, rects))
    t_centre = template[:, :2] + template[:, 2:] / 2
    r_centre = rects[:, :2] + rects[:, 2:] / 2
    scale, offset = np.ones(2), np.asarray(shift, float)
    for _ in range(rounds):
        gap = np.abs(r_centre[None] - (t_centre * scale + offset)[:, None]).max(axis=-1)
        sized = template.copy()
        sized[:, 2:] *= scale
        laid = _similar(rects[None, :], sized[:, None]) & (gap <= tol)
        t, r = np.nonzero(laid)
        if len(t) < 2:
            break
        for axis in (0, 1):
            a, b = t_centre[t, axis], r_centre[r, axis]
            if np.ptp(a) > 4 * tol:  # spread enough to tell a scale
                slope, intercept = np.polyfit(a, b, 1)
                if 0.85 <= slope <= 1.15:
                    scale[axis], offset[axis] = slope, intercept
                    continue
            scale[axis], offset[axis] = 1.0, float(np.median(b - a))
    return scale, offset




def frame_rectangles(cropped):
    """Every rectangle of the frame, the inside of each box: what a copy
    lays on those of its template to find how far the scan moved it."""
    return find_rectangles(cropped, inner=True, relative=True)[0]




def layout_band(box, margin=0.1):
    """Where a copy's grade table is looked for: the grade box of its
    template and ``margin`` of the page around it, in page fractions."""
    return (max(box[0] - margin, 0), min(box[1] + margin, 1),
            max(box[2] - margin, 0), min(box[3] + margin, 1))




def template_grade_layout(gray, grade_box):
    """The layout of a template: its grade boxes, and every rectangle of the
    band around them (see ``layout_band``), for the copies to find theirs.

    Args:
        gray: The page of the template, as uploaded, nothing drawn on it.
        grade_box: The grade box of the template, in page fractions.

    Returns:
        ``(layout, cnts)``: the ``band``, ``boxes`` and ``rects`` in page
        fractions (None when the grade box holds no box), and the grade boxes
        as contours of the grade box.
    """
    shape = gray.shape
    cnts = find_grade_boxes(fetch_box(gray, grade_box), thick=1)
    if not cnts:
        return None, cnts
    band = layout_band(grade_box)
    dx = int(grade_box[0] * shape[1]) - int(band[0] * shape[1])
    dy = int(grade_box[2] * shape[0]) - int(band[2] * shape[0])
    boxes = [(x + dx, y + dy, w, h) for x, y, w, h in map(cv2.boundingRect, cnts)]
    layout = {
        "band": [round(side, 5) for side in band],
        "boxes": frame_to_cells(boxes, band, shape),
        "rects": frame_to_cells(frame_rectangles(fetch_box(gray, band)), band, shape),
    }
    return layout, cnts




def find_layout_boxes(gray, layout, tol=12):
    """The grade boxes of a copy, where the layout of its template has them.

    The band of the page around the grade box (see ``layout_band``) is
    straightened, the shift that lays the rectangles of the template on the
    band's is measured once (see ``_shift``), and each grade box of the
    template, shifted, must then fall on a rectangle of its size, within
    ``tol`` pixels. A box the copy hides (a grade written over its sides) is
    put back where the template has it when its sides are drawn there. Any
    doubt gives no box: the caller then leaves the copy for a human, rather
    than write its grades in a neighbouring column.

    Args:
        gray: The page of the copy.
        layout: ``band``, ``boxes`` and ``rects`` of the template, in page
            fractions (see ``tasks.templates.grade_layout``).
        tol: How far, in pixels, a box may be from where the shift puts it.

    Returns:
        ``(frame, boxes, origin, back)``: the straightened band, the boxes
        as contours of it (``[]`` when not found), where the band starts on
        the page, and the matrix that takes points of ``frame`` back to the
        band as scanned (None when it was not turned).
    """
    band = layout["band"]
    height, width = gray.shape[:2]
    origin = (int(band[0] * width), int(band[2] * height))
    frame, back = straighten_frame(fetch_box(gray, band))
    rects, ink = find_rectangles(frame, inner=True, relative=True)
    template = cells_in_frame(layout["rects"], band, gray.shape)
    boxes = cells_in_frame(layout["boxes"], band, gray.shape)
    shift = _shift(template, rects, boxes, tol) if rects and boxes else None
    if shift is None:
        return frame, [], origin, back
    scale, offset = _fit(template, rects, shift, tol)
    found = []
    for x, y, w, h in boxes:
        cx, cy = np.array([x + w / 2, y + h / 2]) * scale + offset
        w, h = int(round(w * scale[0])), int(round(h * scale[1]))
        like = (int(round(cx - w / 2)), int(round(cy - h / 2)), w, h)
        near = [r for r in rects
                if _similar(r, like) and max(abs(r[0] - like[0]), abs(r[1] - like[1])) <= tol]
        if near:
            found.append(min(near, key=lambda r: abs(r[0] - like[0]) + abs(r[1] - like[1])))
        elif edge_coverage(ink, like, band=6) >= 0.6:
            found.append(like)
        else:
            return frame, [], origin, back
    return frame, _boxes(found, frame, 0), origin, back




def _inside(small, big, slack=2):
    """Whether ``small`` lies within ``big``."""
    x, y, w, h = small
    bx, by, bw, bh = big
    return (bx - slack <= x and by - slack <= y
            and x + w <= bx + bw + slack and y + h <= by + bh + slack)




def ink_rects(thresh, min_size=5):
    """Bounding rectangles of the ink blobs of a thresholded image, tiny specks left out."""
    cnts, _ = cv2.findContours(thresh.copy(), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    rects = [cv2.boundingRect(c) for c in cnts]
    return [(x, y, w, h) for (x, y, w, h) in rects if w >= min_size and h >= min_size]




def get_clean_thresh(gray):
    # threshold the gray image, then apply a series of morphological
    # operations to cleanup the thresholded image
    blurred = cv2.GaussianBlur(gray, (5, 5), 0)
    imwrite_png("blurred", blurred)
    thresh = cv2.threshold(blurred, 200, 255, cv2.THRESH_BINARY_INV)[1]

    # A digit-sized blob wider than tall is a dot or two digits glued together:
    # the fixed threshold takes the gray halo of a degraded print (jpeg overlay,
    # light scan) as ink and bridges the gap. Otsu's threshold thins the strokes
    # and separates them; it is kept only when it splits a blob without losing a
    # digit, so faint handwriting keeps the permissive threshold.
    rects = ink_rects(thresh)
    if rects:
        max_h = max(h for _, _, _, h in rects)

        def n_digit_sized(rs):
            return sum(1 for _, _, _, h in rs if h > 0.5 * max_h)

        if any(w > h > 0.5 * max_h for (_, _, w, h) in rects):
            otsu = cv2.threshold(blurred, 0, 255, cv2.THRESH_BINARY_INV | cv2.THRESH_OTSU)[1]
            orects = ink_rects(otsu)
            if len(orects) > len(rects) and n_digit_sized(orects) >= n_digit_sized(rects):
                print("Glued digits: Otsu threshold used")
                thresh = otsu
    imwrite_png("thresh", thresh)
    return thresh




def clean_and_sort_digit_contours(
    cnts,
    gray=None,
    split_on_semi_column=True,
    min_box_before_split=0,
    max_cnts=None,
    trim=None,
    ctrl_size_variation=True
):
    # remove thin contours
    ccnts = []
    max_h = 0
    middle_y = 0
    for c in cnts:
        (x, y, w, h) = cv2.boundingRect(c)
        # remove thin contours (dot should not been removed)
        if w < 5 or h < 5:
            continue
        if h > max_h:
            max_h = h
            middle_y = y + h / 2
        ccnts.append(c)
    cnts = ccnts

    # remove anything that is too far from middle_y
    ccnts = []
    for c in cnts:
        (x, y, w, h) = cv2.boundingRect(c)
        # remove if too far above or below
        if y + h < middle_y - max_h or y > middle_y + max_h:  # remove above or below
            continue
        ccnts.append(c)
    cnts = ccnts

    # sort contours by x
    scnts = []
    for c in cnts:
        (x, y, w, h) = cv2.boundingRect(c)
        scnts.append((x + w / 2, w, h, c))
    scnts = sorted(scnts, key=lambda t: t[0])

    # trim if needed
    if trim and len(scnts) > trim:
        scnts = scnts[:-trim]

    if gray is not None:
        imwrite_contours("rgray_all", gray, [c[-1] for c in scnts])

    # if split on last semi column: find two boxes that are similar
    if split_on_semi_column:
        prev_mx = -1
        prev_w = -1
        prev_h = -1
        semi_column = -1
        i = 0
        for mx, w, h, c in scnts:
            if abs(mx - prev_mx) < 5 and abs(w - prev_w) < 5 and abs(h - prev_h) < 5:
                semi_column = i
            prev_mx = mx
            prev_w = w
            prev_h = h
            i += 1
        if semi_column + 1 < min_box_before_split:
            return [], 0
        if semi_column > -1:
            scnts = scnts[semi_column + 1 :]
    cnts = [c[-1] for c in scnts]

    if not scnts:
        return [], 0

    # keep centered contours
    # look for the middle line and remove anything above or below
    # and check for a dot
    w_median = median(w for _, w, h, _ in scnts)
    h_median = median(h for _, w, h, _ in scnts)
    dot = len(cnts)
    ccnts = []
    if gray is not None:
        gray = gray.copy()
    for c in cnts:
        (x, y, w, h) = cv2.boundingRect(c)
        if y + h < middle_y:  # remove above
            continue
        if y > middle_y:  # remove below
            if (
                len(ccnts) < dot
            ):  # store position of the first one, as it could be a dot
                dot = len(ccnts)
            continue
        # remove contours that are too different
        if ctrl_size_variation and (abs(w_median - w) > 20 or abs(h_median - h) > 20):
            continue
        ccnts.append(c)
    if gray is not None:
        imwrite_contours("dgray_cnt", gray, ccnts)

    if max_cnts and len(ccnts) > max_cnts:
        return [], 0

    return ccnts, dot




def find_digit_contours(
    gray, split_on_semi_column=True, min_box_before_split=0, max_cnts=None, trim=None, ctrl_size_variation=False
):
    thresh = get_clean_thresh(gray)

    # finding contours in image
    cnts, h = cv2.findContours(
        thresh.copy(), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
    )
    cnts = imutils.grab_contours((cnts, h))
    imwrite_contours("rgray_cnt", gray, cnts)

    # clean cnts
    scnts, dot = clean_and_sort_digit_contours(
        cnts, gray, split_on_semi_column, min_box_before_split, max_cnts,
        trim=trim, ctrl_size_variation=ctrl_size_variation
    )

    return scnts, dot, thresh
