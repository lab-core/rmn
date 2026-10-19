"""Writing back onto a copy: its grades, and the boxes that were read."""

import cv2
import pymupdf
from colorama import Fore, Style
from process_copy.config import len_mat
from process_copy.imaging import fetch_box, imwrite_png
from process_copy.pages import gray_images
from process_copy.contours import (
    find_digit_contours,
    find_grade_boxes,
    find_matricule_box_contours,
)







def format_grade_text(number):
    """Text written in a grade box: 5.0 -> "5", 4.5 -> "4.5", None or "" -> "".

    The server stores validated grades as floats, so str() would print "5.0".
    """
    if number is None or number == "":
        return ""
    try:
        value = float(number)
    except (TypeError, ValueError):
        return str(number)
    return str(int(value)) if value.is_integer() else str(value)


# The grades are written in the page, in red, with the font every pdf reader
# has. Helvetica digits are this fraction of the font size tall, which is
# what the size is computed from.
GRADE_FONT = "helv"
GRADE_COLOR = (1, 0, 0)
CAP_HEIGHT = 0.72


def grade_font_size(texts, cells, grade_ratio=0.5):
    """The size every grade of a table is written at.

    The first grade there is sets it, as it did when the grades were drawn on
    a picture of the page: one size for the whole table, large enough to fill
    ``grade_ratio`` of its cell without touching the sides.

    Args:
        texts (list): One text per cell, empty where nothing is written.
        cells (list): The cells, pymupdf.Rect, in page points.
        grade_ratio (float): How much of a cell a grade fills.

    Returns:
        float: The font size, or None when there is nothing to write.
    """
    for text, cell in zip(texts, cells):
        if not text:
            continue
        width = pymupdf.get_text_length(text, fontname=GRADE_FONT, fontsize=1)
        return grade_ratio / max(CAP_HEIGHT / cell.height, width / cell.width)
    return None


def write_grade_texts(page, cells, numbers, grade_ratio=0.5):
    """Write the grades in the cells of a grade table, centred in each.

    Args:
        page (pymupdf.Page): The cover page, written in place.
        cells (list): The cells of the table, pymupdf.Rect, in page points.
        numbers (list): The grades, one per cell; an ignored question or a
            missing grade leaves its cell blank.
        grade_ratio (float): How much of a cell a grade fills.
    """
    texts = [format_grade_text(number) for number in numbers]
    size = grade_font_size(texts, cells, grade_ratio)
    if size is None:
        return
    for text, cell in zip(texts, cells):
        if not text:
            continue
        width = pymupdf.get_text_length(text, fontname=GRADE_FONT, fontsize=size)
        point = pymupdf.Point(cell.x0 + (cell.width - width) / 2,
                              cell.y0 + (cell.height + CAP_HEIGHT * size) / 2)
        # the cells were found on the page as it is displayed; a page that
        # carries a /Rotate is stored turned the other way, and the text has
        # to be turned with it
        page.insert_text(point * page.derotation_matrix, text, fontname=GRADE_FONT,
                         fontsize=size, color=GRADE_COLOR, rotate=page.rotation)


def cells_in_points(boxes, offset, raster, page_rect):
    """Where the cells found on the raster are on the page itself.

    Args:
        boxes (list): The cell contours, in the coordinates of the crop.
        offset (tuple): Where that crop starts in the raster, in pixels.
        raster (tuple): Width and height of the raster, in pixels.
        page_rect (pymupdf.Rect): The page as it is displayed, in points.

    Returns:
        list: One pymupdf.Rect per cell, in page points.
    """
    x0, y0 = offset
    width, height = raster
    sx, sy = page_rect.width / width, page_rect.height / height
    cells = []
    for b in boxes:
        (x, y, w, h) = cv2.boundingRect(b)
        cells.append(pymupdf.Rect((x0 + x) * sx, (y0 + y) * sy,
                                  (x0 + x + w) * sx, (y0 + y + h) * sy))
    return cells


# How the crop is tried when the template box does not give one cell per
# grade: as the template records it, then a little wider on every side (what
# is missing is usually the frame of the table, cut by a box drawn tight
# around it), then further out on one side only. Widening alone never found
# the table of three copies of job d98c2837 whose frame sits left of the
# recorded box, and 472 of its 546 copies needed the first widening.
BOX_ATTEMPTS = (
    (0.00, 0.00, 0.00, 0.00),
    (-0.01, 0.01, -0.01, 0.01),
    (-0.02, 0.02, -0.02, 0.02),
    (-0.03, 0.00, -0.02, 0.02),
    (-0.04, 0.00, -0.02, 0.02),
    (0.00, 0.03, -0.02, 0.02),
    (-0.05, 0.01, -0.03, 0.03),
)


def box_candidates(box, attempts=BOX_ATTEMPTS):
    """Yield the crops to try for a grade table, closest to the template first.

    Args:
        box (tuple): The grade box of the template, (x0, x1, y0, y1) in
            fractions of the page.
        attempts (tuple): What to add to each side, one set of margins per try.

    Yields:
        tuple: The box to crop, in the order the crops are worth trying.
    """
    for dx0, dx1, dy0, dy1 in attempts:
        yield (box[0] + dx0, box[1] + dx1, box[2] + dy0, box[3] + dy1)


def add_grades(numbers: list, pdf_path: str, box: tuple, out_path: str,
               trim: bool = None, add_border: bool = False, shape: tuple = (8.5, 11),
               grade_ratio: float = 0.5):
    """Write the grades of a copy in the boxes of its grade table.

    The table is found on a raster of the page, and the grades are written in
    the page itself: the cover page used to be rasterised at 300 dpi and
    re-encoded as a jpeg, which turned a 94 kB scan into 1.4 MB and lost what
    the scanner had captured.

    Args:
        numbers (list): One text per box of the table, the total last.
        pdf_path (str): The cover page to read the table from.
        box (tuple): The grade box of the template, (x0, x1, y0, y1).
        out_path (str): Where the page carrying the grades is written; it is
            only written when the table was found.
        shape (tuple): The size the raster is expected to have, in pixels.
        grade_ratio (float): How much of a cell a grade fills.

    Returns:
        bool: True when the page was written, False when no crop gave one
              cell per grade -- the caller then keeps the page as it is.
    """
    grays = gray_images(pdf_path, [0], straighten=False, shape=shape)
    if not grays:
        print(Fore.RED + "%s: No valid pdf" % pdf_path + Style.RESET_ALL)
        return False
    gray = grays[0]
    height, width = gray.shape[:2]

    def grade_cells(candidate):
        """The cells of the table in this crop, or None when it is not one."""
        boxes = find_grade_boxes(fetch_box(gray, candidate), add_border, thick=0)
        if len(boxes) != len(numbers):
            print(f'The number of boxes ({len(boxes)}) found is different from '
                  f'the number of grades ({len(numbers)})')
            return None
        for b in boxes:
            (x, y, w, h) = cv2.boundingRect(b)
            if h <= 10 or w <= 10:
                print("An invalid box number has been found (too small or too thin)")
                return None
        return boxes

    for attempt, candidate in enumerate(box_candidates(box)):
        boxes = grade_cells(candidate)
        if boxes is None:
            continue
        if attempt:
            print(f"Grade table found on try {attempt + 1}, at {tuple(round(c, 3) for c in candidate)}")
        # the crop the cells were found in is where they are on the page:
        # every copy that needed a wider crop used to have its grades written
        # the difference away from its boxes
        offset = (int(candidate[0] * width), int(candidate[2] * height))
        with pymupdf.open(pdf_path) as document:
            page = document[0]
            cells = cells_in_points(boxes, offset, (width, height), page.rect)
            write_grade_texts(page, cells, numbers, grade_ratio)
            document.save(out_path, garbage=3, deflate=True)
        return True

    # nothing written when the boxes were not found: the caller keeps the
    # scanned cover page and flags the copy (a page without grades used to be
    # written silently)
    print(Fore.RED + "%s: grade boxes not found, no overlay written" % pdf_path + Style.RESET_ALL)
    return False


def write_box_contours(img, box, color=(0, 0, 255), thick=5, biggest_child=False, matricule=True):
    # create a gray copy of the image
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    # fetch only the part in the box
    b_x = int(box[0] * img.shape[1])
    b_y = int(box[2] * img.shape[0])
    # draw the box
    cv2.rectangle(
        img,
        (b_x, b_y),
        (int(box[1] * img.shape[1]), int(box[3] * img.shape[0])),
        color,
        2*thick
    )

    def draw_contour_on_img(x0, y0, cnt):
        # draw the contour on the whole image
        (x, y, w, h) = cv2.boundingRect(cnt)
        cv2.rectangle(
            img,
            (x0 + x, y0 + y),
            (x0 + x + w, y0 + y + h),
            color,
            thick
        )

    def draw_contour(gray_box, cnt):
        # find contours of the numbers of the matricule is in its separate box
        try:
            cnts, dot, thresh = find_digit_contours(
                gray_box,
                max_cnts=len_mat,
                split_on_semi_column=True,
                min_box_before_split=6,
                ctrl_size_variation=True
            )
            # check length
            if len(cnts) != len_mat:
                return False

            # each number is in a separate box, draw it individually
            x = y = 0
            if cnt is not None:
                (x, y, _, _) = cv2.boundingRect(cnt)
            for c in cnts:
                draw_contour_on_img(b_x + x, b_y + y, c)
                imwrite_png("rendered", img)

        except cv2.error as e:
            print(e)
            print("Got an error while finding digits.")
            return False

        return True

    if matricule:
        return find_matricule_box_contours(gray, box, draw_contour, biggest_child)

    cropped = fetch_box(gray, box)
    cnts = find_grade_boxes(cropped, False, thick=1)
    for c in cnts:
        draw_contour_on_img(b_x, b_y, c)
        imwrite_png("rendered", img)
    return len(cnts), True
