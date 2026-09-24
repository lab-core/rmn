"""A pdf as page images, and the summary pages built from them.

The page geometry is module state that ``refresh`` rebinds, so everything
that reads it lives here: a reader in another module would import the value,
not the name, and keep the one it saw at import time.
"""

import os
import cv2
import numpy as np
from pdf2image import convert_from_path
from PIL import Image
from process_copy.imaging import BLACK, GREEN, ORANGE, RED, imwrite_png






ph = 0


pw = 0


half_dpi = 0


quarter_dpi = 0


one_height_dpi = 0




def refresh(dpi=300):
    global ph, pw, half_dpi, quarter_dpi, one_height_dpi
    ph = int(11 * dpi)
    pw = int(8.5 * dpi)
    half_dpi = int(dpi / 2)
    quarter_dpi = int(dpi / 4)
    one_height_dpi = int(dpi / 8)




def imstraighten(gray):
    ngray = cv2.bitwise_not(gray)
    # threshold the image, setting all foreground pixels to
    # 255 and all background pixels to 0
    thresh = cv2.threshold(ngray, 10, 255, cv2.THRESH_BINARY)[1]
    imwrite_png("thresh", thresh)

    # # grab the (x, y) coordinates of all pixel values that
    # # are greater than zero, then use these coordinates to
    # # compute a rotated bounding box that contains all
    # # coordinates
    # coords = np.column_stack(np.where(thresh > 0))

    # get rid of thinner lines
    dilated = cv2.dilate(thresh, np.ones((5, 5), np.uint8))
    imwrite_png("dilated", dilated)
    # find lines
    lines = cv2.HoughLinesP(dilated, 1, np.pi / 180, 50, minLineLength=half_dpi)
    if lines is None:
        return gray
    # find longuest lines -> should be horizontal or vertical
    max_dist = 0
    max_line = None
    for l in lines:
        d = np.square(l[0][2] - l[0][0]) + np.square(l[0][3] - l[0][1])
        if d > max_dist:
            max_dist = d
            max_line = l[0]
    coords = np.array([max_line[0:2], max_line[2:4]])
    center, dim, angle = cv2.minAreaRect(coords)
    mangle = (180 + angle) % 90
    if mangle > 45:
        mangle = 90 - mangle
    if abs(mangle) > 10:
        raise ValueError("Current page is too skewed (angle found: %.2f)." % angle)
    # rotate the image to deskew it
    (h, w) = gray.shape
    center = (w // 2, h // 2)
    # divide angle by 2 in case of error as we are changing the center and we are just using small angles
    M = cv2.getRotationMatrix2D(center, mangle, 1.0)
    rotated = cv2.warpAffine(
        gray, M, (w, h), flags=cv2.INTER_CUBIC, borderMode=cv2.BORDER_REPLICATE
    )
    imwrite_png("rotated", rotated)
    return rotated




# pages rasterised when the whole document must be searched for a matricule:
# at 300 dpi a page is ~25 MB, and the matricule box is on every page anyway
MAX_RASTERISED_PAGES = int(os.getenv("MAX_RASTERISED_PAGES", "30"))




def gray_images(fpdf, pages=None, dpi=300, straighten=True, shape=None):
    # shape: width, height
    # fpdf: path to pdf file to grade
    images = []
    if pages is None:
        try:
            images = convert_from_path(fpdf, dpi=dpi, first_page=1, last_page=MAX_RASTERISED_PAGES)
        except Image.DecompressionBombError as e:
            print("Decompression issue for %s." % fpdf)
            return None
    else:
        for p in pages:
            try:
                images += convert_from_path(
                    fpdf, dpi=dpi, last_page=p + 1, first_page=p
                )
            except Image.DecompressionBombError as e:
                print("Decompression issue on page %d for %s." % (p, fpdf))
                return None
    gray_images = []
    for i, img in enumerate(images):
        np_img = np.array(img)
        gray = cv2.cvtColor(np_img, cv2.COLOR_BGR2GRAY)
        if straighten:
            try:
                gray = imstraighten(gray)
            except ValueError as e:
                print("For %s, page %d: %s" % (fpdf, i, str(e)))
        if shape:
            if (
                abs(gray.shape[0] - shape[1]) > 0.1 * shape[1]
                or abs(gray.shape[1] - shape[0]) > 0.1 * shape[0]
            ):
                print(
                    "Resizing %s, wrong format: %.1f by %.1f in."
                    % (fpdf, gray.shape[0] / dpi, gray.shape[1] / dpi)
                )
                gray = cv2.resize(gray, shape, interpolation=cv2.INTER_LINEAR)
        imwrite_png("page_%d" % i, gray)
        gray_images.append(gray)
    return gray_images




def get_blank_page(h=ph, w=pw, dim=None):
    if dim:
        return np.full((h, w, dim), 255, np.uint8)
    else:
        return np.full((h, w), 255, np.uint8)




def create_summary(
    grades,
    mat,
    numbers,
    total_matched,
    name,
    dpi,
    align_matricule_left=True,
    name_bottom=True,
    invalid=False,
):
    # put everything in an image
    w = grades.shape[1]
    h = grades.shape[0]

    summary = get_blank_page(h, w)
    # add grades
    summary[0:h, 0:w] = grades
    # write matricule and grade in color
    color_summary = cv2.cvtColor(summary, cv2.COLOR_GRAY2RGB)
    pos = (
        (one_height_dpi, h - half_dpi)
        if align_matricule_left
        else (grades.shape[1] - int(2.5 * dpi), half_dpi)
    )
    cv2.putText(
        color_summary,
        str(mat) if mat else "N/A",
        pos,  # position at which writing has to start
        cv2.FONT_HERSHEY_SIMPLEX,
        2,
        GREEN if mat and not invalid else RED,
        5,
    )
    if total_matched is not None:
        cv2.putText(
            color_summary,
            str(numbers[-1]) if numbers else "N/A",
            (w - dpi, h - half_dpi),  # position at which writing has to start
            cv2.FONT_HERSHEY_SIMPLEX,
            2,
            GREEN if total_matched else RED,
            5,
        )
    pos = h - one_height_dpi if name_bottom else one_height_dpi
    cv2.putText(
        color_summary,
        name,
        (one_height_dpi, pos),  # position at which writing has to start
        cv2.FONT_HERSHEY_SIMPLEX,
        1,
        ORANGE,
        3,
    )
    imwrite_png("summary", color_summary)
    return color_summary




def create_summary2(
    id_box,
    grades,
    mat,
    numbers,
    total_matched,
    name,
    dpi,
    align_matricule_left=True,
    name_bottom=True,
    invalid=False,
):
    w = id_box.shape[1] + grades.shape[1] + dpi
    h = max(id_box.shape[0] + dpi, grades.shape[0])

    summary = get_blank_page(h, w)
    # add id
    summary[0 : id_box.shape[0], 0 : id_box.shape[1]] = id_box
    # add grades
    summary[0 : grades.shape[0], id_box.shape[1] + dpi : w] = grades
    # write matricule and grade in color
    color_summary = cv2.cvtColor(summary, cv2.COLOR_GRAY2RGB)
    pos = int(2.5 * dpi) if align_matricule_left else id_box.shape[1] - int(4 * dpi)
    cv2.putText(
        color_summary,
        mat if mat else "N/A",
        (pos, id_box.shape[0] + half_dpi),  # position at which writing has to start
        cv2.FONT_HERSHEY_SIMPLEX,
        2,
        GREEN if mat or not invalid else RED,
        5,
    )
    if total_matched is not None:
        cv2.putText(
            color_summary,
            str(numbers[-1]) if numbers else "N/A",
            (
                id_box.shape[1] + half_dpi,
                h - half_dpi,
            ),  # position at which writing has to start
            cv2.FONT_HERSHEY_SIMPLEX,
            2,
            GREEN if total_matched else RED,
            5,
        )
    pos = h - one_height_dpi if name_bottom else one_height_dpi
    cv2.putText(
        color_summary,
        name,
        (quarter_dpi, pos),  # position at which writing has to start
        cv2.FONT_HERSHEY_SIMPLEX,
        1,
        ORANGE,
        3,
    )
    imwrite_png("summary", color_summary)
    return color_summary




def create_whole_summary(sumarries):
    # retrieve max width and height
    max_h = 0
    max_w = 0
    for s in sumarries:
        if s.shape[1] > max_w:
            max_w = s.shape[1]
        if s.shape[0] > max_h:
            max_h = s.shape[0]

    # create summary pages
    hmargin = int(pw - max_w) // 2  # horizontal margin
    f = 1
    if hmargin < half_dpi:
        hmargin = half_dpi
        w = pw - 2 * half_dpi
        f = w / max_w
        max_w = w
        max_h = int(max_h * f)

    imgh = max_h + 15
    n_s = ph // imgh  # number of pictures by page
    vmargin = int(ph - n_s * imgh) // 2

    pages = []
    page = get_blank_page(dim=3)
    y = vmargin
    # put summaries on pages
    for s in sumarries:
        if f < 1:
            s = cv2.resize(s, None, fx=f, fy=f)
        # new page if needed
        if y + s.shape[0] > ph - vmargin:
            # store current page
            imwrite_png("page", page)
            pages.append(page)
            # create new one
            page = get_blank_page(dim=3)
            y = vmargin
        # add summarry
        page[y : y + s.shape[0], hmargin : hmargin + s.shape[1]] = s
        y += s.shape[0] + 5  # update cursor
        page[y : y + 2, :] = BLACK
        y += 7
    # store current page
    imwrite_png("page", page)
    pages.append(page)

    return pages




def save_pages(pages, fname):
    images = [Image.fromarray(p) for p in pages]
    images[0].save(fname, save_all=True, append_images=images[1:])
