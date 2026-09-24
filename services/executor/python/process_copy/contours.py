"""Finding the boxes and the digits drawn on a page, as contours."""

from statistics import median
import cv2
import imutils
import numpy as np
from process_copy.imaging import (
    fetch_box,
    get_image_from_contour,
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
            for l in lines:
                cv2.line(
                    edged,
                    (l[0][0], l[0][1]),
                    (l[0][2], l[0][3]),
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




def find_grade_boxes(cropped, add_border=False, max_diff=50, thick=5):
    """Find boxes on the image."""
    # add border: useful if having only partial boxes
    cropped2 = cropped.copy()
    if add_border:
        cv2.rectangle(
            cropped2,
            (thick, thick),
            (cropped2.shape[1] - thick, cropped2.shape[0] - thick),
            (0, 0, 0),
            thick,
        )
        imwrite_png("cropped", cropped2)

    # find contours in the edge map, then sort them by their
    # size in descending order
    cnts, hierarchy = cv2.findContours(
        find_edges(cropped2, thick=thick), cv2.RETR_TREE, cv2.CHAIN_APPROX_SIMPLE
    )
    cnts = imutils.grab_contours((cnts, hierarchy))
    imwrite_contours("cropped_all_boxes", cropped2, cnts, thick=thick+2)

    # check if any contour
    if not cnts:
        return []

    # keep only the children of the biggest contour
    areas = [cv2.contourArea(cnt) for cnt in cnts]
    areas = []
    for cnt in cnts:
        (x, y, w, h) = cv2.boundingRect(cnt)
        areas.append(w*h)
    pos, c = max(enumerate(cnts), key=lambda cnt: areas[cnt[0]])
    imwrite_png("main_cropped", get_image_from_contour(cropped, c))
    ccnts = biggest_children(cnts, hierarchy, pos)

    # Retrieve
    # loop over the contours to take the ones that are aligned with the biggest one and are big enough
    cropped2 = cropped.copy()
    boxes = []
    ref = None
    horizontal = None
    imwrite_contours("cropped_boxes", cropped2, ccnts, thick=thick + 1)
    # ic=0
    for c in sorted(ccnts, key=cv2.contourArea, reverse=True):
        # imwrite_contours("cropped_boxes_%d" %ic, cropped2, [c], thick=thick + 1)
        # ic+=1
        (x, y, w, h) = cv2.boundingRect(c)
        # set the reference box
        if ref is None:
            ref = (x, y, w, h)
        # box too small
        elif w * h < 0.1 * ref[2] * ref[3]:
            break
        # for horizontal alignment
        elif abs(ref[1] - y) <= max_diff:
            if horizontal is None:
                horizontal = True
            # break the alignment
            elif not horizontal:
                continue
            # break the box size
            if abs(ref[3] - h) >= max_diff:
                continue
        # for vertical alignment
        elif abs(ref[0] - x) <= max_diff:
            if horizontal is None:
                horizontal = False
            # break the alignment
            elif horizontal:
                continue
            # break the box size
            elif abs(ref[2] - w) >= max_diff:
                continue
        # break alignment
        else:
            continue
        boxes.append(c)

    # sort boxes according to alignment
    boxes = sorted(boxes, key=lambda b: cv2.boundingRect(b)[0 if horizontal else 1])
    # remove the extreme boxes close to the border if has added some borders
    if add_border and boxes:
        (x, y, w, h) = cv2.boundingRect(boxes[0])
        if x + y <= 4 * thick + 5:
            boxes = boxes[1:]
        if boxes:
            (x, y, w, h) = cv2.boundingRect(boxes[-1])
            if x + y + h + w >= cropped.shape[0] + cropped.shape[1] - 4 * thick - 5:
                boxes = boxes[:-1]
    # add any missing box
    if boxes:
        prev = None
        m_size = max(4 * thick, 20)
        boxes2 = []
        for b in boxes:
            (x, y, w, h) = cv2.boundingRect(b)
            if prev is not None:
                if horizontal:
                    # add a contour
                    if x - prev > m_size:
                        boxes2.append(
                            np.array(
                                [[prev + thick, y - thick], [x - thick, y + h + thick]]
                            )
                        )
                elif y - prev > m_size:  # add a contour
                    boxes2.append(
                        np.array(
                            [[x - thick, prev + thick], [x + w + thick, y - thick]]
                        )
                    )
            boxes2.append(b)
            prev = x + w if horizontal else y + h
        boxes = boxes2
    imwrite_contours(
        "cropped_boxes2", cropped2, boxes, thick=2 * (thick + 1), padding=-thick - 1
    )
    return boxes




def find_matricule_box_contours(gray, regular_box, callback, biggest_child=False):
    # find the id box
    cropped = fetch_box(gray, regular_box)
    if biggest_child:
        cnts, hierarchy = cv2.findContours(
            find_edges(cropped, thick=0), cv2.RETR_TREE, cv2.CHAIN_APPROX_SIMPLE
        )
        cnts = imutils.grab_contours((cnts, hierarchy))
        imwrite_contours("rgray", cropped, cnts, thick=5)
        # a blank / unreadable matricule box yields no contours: there is
        # nothing to analyse, so report "no box found" instead of crashing on
        # max() over an empty sequence (which used to kill the whole job).
        if len(cnts) == 0:
            return None, False
        # Find the biggest contour for the front box
        pos, biggest_c = max(enumerate(cnts), key=lambda cnt: cv2.contourArea(cnt[1]))
        for cnt in biggest_children(cnts, hierarchy, pos):
            gray_box = get_image_from_contour(cropped, cnt)
            if callback(gray_box, cnt):
                return biggest_c, True
        return biggest_c, False
    else:
        return None, callback(cropped, None)




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
