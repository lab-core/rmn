"""Turning an uploaded template into the boxes the recogniser reads."""

import json
import cv2
import numpy as np
from pdf2image import convert_from_path
from PIL import Image
from python.process_copy.contours import frame_rectangles
from python.process_copy.imaging import fetch_box, frame_to_cells
from python.process_copy.recognize import write_box_contours
from runtime import timestamped_print



# the executor timestamps every line it prints (see runtime.timestamped_print)
print = timestamped_print




def process_template(db, storage, sio, temp_id, WORK_TMP_DIR):
    template = db.get_collection("template").find_one({"template_id": temp_id})
    if not template:
        raise KeyError(f"Template {temp_id} not found in mongodb.")

    template_file = str(WORK_TMP_DIR.joinpath(template["template_file_id"]))
    storage.copy_from(template["template_file_id"], template_file)
    if template_file.endswith(".pdf"):
        img = convert_from_path(template_file, dpi=300)[0]
    else:
        img = Image.open(template_file)

    def draw_boxes_on_template(box, np_img, mat):
        box = tuple([round(x, 2) for x in box])
        np_img2 = np.copy(np_img)
        b, r = write_box_contours(np_img2, box, matricule=mat)
        if not r and mat:
            np_img2 = np.copy(np_img)
            write_box_contours(np_img2, box, matricule=mat, biggest_child=True)
        return np_img2, b

    # fetch the user-defined boxes
    np_img = np.array(img)
    # before any frame is drawn on it
    gray = np.array(img.convert("L"))
    matricule_box = template.get("matricule_box", None)
    if matricule_box:
        np_img, _ = draw_boxes_on_template(matricule_box, np_img, True)

    # the grade boxes found and every rectangle around them, kept for the
    # copies to find theirs where they are
    n_questions = 0
    grade_layout = None
    grade_box = template.get("grade_box", None)
    if grade_box:
        page_shape = np_img.shape
        np_img, cnts = draw_boxes_on_template(grade_box, np_img, False)
        n_questions = len(cnts)
        # the frame as the copies cut it (apply_template_boxes rounds it too)
        frame = tuple(round(x, 2) for x in grade_box)
        # the rectangles around the frame too: the labels and the maximums
        # beside the grades are what tells a copy which column it moved to
        around = (max(frame[0] - 0.1, 0), min(frame[1] + 0.1, 1),
                  max(frame[2] - 0.1, 0), min(frame[3] + 0.1, 1))
        grade_layout = {
            "boxes": frame_to_cells([cv2.boundingRect(c) for c in cnts], frame, page_shape),
            "rects": frame_to_cells(frame_rectangles(fetch_box(gray, around)), around, page_shape),
        }

    tmp_img = str(WORK_TMP_DIR.joinpath("rendered.png"))
    cv2.imwrite(tmp_img, np_img)

    # For a png
    rendered_path = template["template_file_id"].rsplit(".", 1)[0] + "-rendered.png"
    storage.move_to(tmp_img, rendered_path)

    # # For a pdf
    # rendered_path = template["template_file_id"].rsplit(".", 1)[0] + "-rendered.pdf"
    # tmp_rendered = str(WORK_TMP_DIR.joinpath(rendered_path))
    # with open(tmp_rendered, "wb") as f:
    #     layout = img2pdf.get_fixed_dpi_layout_fun((100, 100))
    #     f.write(img2pdf.convert(tmp_img, layout_fun=layout))
    # storage.move_to(tmp_rendered, rendered_path)

    try:
        # update doc
        db.get_collection("template").update_one(
            {"template_id": temp_id},
            {"$set": {
                "template_rendered_file_id": rendered_path,
                "n_questions": n_questions - 1,
                "grade_layout": grade_layout,
            }
        })
    except Exception as e:
        print(f"An error occurred: {e}")
        raise

    sio.emit(
        "template_rendered",
        json.dumps(
            {
                "user_id": template["user_id"],
                "template_id": temp_id,
                "n_questions": n_questions - 1
            }
        ),
    )
