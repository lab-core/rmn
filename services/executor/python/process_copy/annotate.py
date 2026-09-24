"""Writing back onto a copy: its grades, and the boxes that were read."""

import cv2
import numpy as np
from colorama import Fore, Style
from pdf2image import convert_from_path
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




def write_grade_texts(img, boxes, numbers, offset=(0, 0), grade_ratio=0.5, color=0, thickness=2):
    """Print the grades in the boxes of a grade table (the overlay of a finalised copy).

    ``boxes`` are the contours found by ``find_grade_boxes`` on the table cropped
    at ``offset`` in ``img``. The font scale is set once from the first printed
    grade so every box uses the same size; an empty text (ignored question or
    missing grade) leaves its box blank and does not set the scale.
    """
    x0, y0 = offset
    font_scale = None
    for b, number in zip(boxes, numbers):
        (x, y, w, h) = cv2.boundingRect(b)
        number_text = format_grade_text(number)
        if number_text == "":
            continue
        (nw, nh), _ = cv2.getTextSize(number_text, cv2.FONT_HERSHEY_SIMPLEX, 1, thickness)
        if font_scale is None:
            font_scale = grade_ratio / max(nh / h, nw / w)
        x_anchor = int(x + (w - nw * font_scale) / 2)
        y_anchor = int(y + (h + nh * font_scale) / 2)
        cv2.putText(img, number_text, (x0 + x_anchor, y0 + y_anchor),
                    cv2.FONT_HERSHEY_SIMPLEX, font_scale, color, thickness)




def add_grades(numbers: list, pdf_path: str, box: tuple, img_path: str = 'intermediate_image.jpg',
               trim: bool = None, add_border: bool = False, shape: tuple = (8.5, 11),
               jpg_quality: int = 5, grade_ratio: float = 0.5):
    grays = gray_images(pdf_path, [0], straighten=False, shape=shape)
    img = convert_from_path(pdf_path, dpi=300, first_page=0, last_page=1)[0]
    np_img = np.array(img)
    x0 = int(box[0] * np_img.shape[1])
    y0 = int(box[2] * np_img.shape[0])
    if grays is None:
        print(Fore.RED + "%s: No valid pdf" % pdf_path + Style.RESET_ALL)
        return False
    gray = grays[0]

    def find_right_boxes(box, retry=5):
        cropped = fetch_box(gray, box)
        boxes = find_grade_boxes(cropped, add_border, thick=0)
        # print(f"Number of boxes : {len(boxes)}")

        if len(boxes) != len(numbers):
            print(f'The number of boxes ({len(boxes)}) found is different from the number of grades ({len(numbers)})')
            if retry > 0:
                print("Retry grading", retry)
                box2 = (box[0]-.01, box[1]+.01, box[2]-.01, box[3]+.01)
                return find_right_boxes(box2, retry-1)
            return False, cropped, [], boxes

        number_images = []
        for b in boxes:
            (x, y, w, h) = cv2.boundingRect(b)
            if h <= 10 or w <= 10:
                print("An invalid box number has been found (too small or too thin)")
                if retry > 0:
                    print("Retry grading", retry)
                    box2 = (box[0]-.01, box[1]+.01, box[2]-.01, box[3]+.01)
                    return find_right_boxes(box2, retry-1)
                return False, cropped, number_images, boxes

        write_grade_texts(np_img, boxes, numbers, (x0, y0), grade_ratio, color=(0, 0, 255))
        return True, cropped, number_images, boxes

    # no image when the boxes were not found: the caller keeps the original
    # cover page and flags the copy (a page without grades used to be written
    # silently)
    found, *_ = find_right_boxes(box)
    if not found:
        print(Fore.RED + "%s: grade boxes not found, no overlay written" % pdf_path + Style.RESET_ALL)
        return False
    cv2.imwrite(img_path, np_img, [cv2.IMWRITE_JPEG_QUALITY, jpg_quality])
    return True




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
