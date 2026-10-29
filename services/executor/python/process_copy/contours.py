"""Finding the boxes and the digits drawn on a page, as contours."""

from statistics import median
import cv2
import imutils
import numpy as np
from process_copy.imaging import (
    fetch_box,
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




def find_matricule_box_contours(gray, regular_box, callback, biggest_child=False):
    # find the id box
    cropped = fetch_box(gray, regular_box)
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




def find_grade_boxes(cropped, add_border=False, thick=5):
    """The grade boxes of the frame, as contours sorted along their alignment.

    The grade boxes follow each other, in a column or in a row, and are empty
    on the template: of every run of such rectangles of the frame, the one
    whose boxes are all empty wins, so the labels and the maximums printed
    beside them are left out. On a copy the boxes hold the grades: the run
    covering the most area wins (the most boxes, the biggest ones). A copy is
    better read with the layout of its template (see ``find_layout_boxes``).

    Args:
        cropped: The gray frame the grade box of the template gives.
        add_border: Close the boxes the frame cuts with a border drawn around
            it; the boxes on that border are then dropped from the run.
        thick: The thickness of the lines drawn around the boxes found.

    Returns:
        The contours of the boxes, ``[]`` when the frame holds none.
    """
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
    # a rectangle filled with other ones is a table, not a box (the hole of a
    # digit written in a box is a small rectangle inside it too)
    rects = [r for r in rects
             if sum(o[2] * o[3] for o in rects if o != r and _inside(o, r)) < 0.5 * r[2] * r[3]]

    runs = [segment for run, horizontal in _aligned_runs(rects)
            for segment in _segments(run, horizontal, ink)]

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
    boxes = [_rect_contour(r) for r in max(runs, key=area)]
    imwrite_contours("cropped_boxes2", cropped, boxes, thick=2 * (thick + 1))
    return boxes




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
