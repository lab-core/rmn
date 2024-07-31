from fpdf import FPDF
from PIL import Image
import img2pdf
import os
from process_copy.database import Database
from process_copy.recognize import add_grades
from utils.storage import Storage
from process_copy.config import grade_box as def_grade_box
storage = Storage()


def process_writing(job_id, TMP_DIR, dpi=300, shape=(8.5, 11) ):
    """
    Process the writing job by adding grades to the PDF files.

    Args:
        job_id (str): The ID of the job.

    Returns:
        None
    """
    box_grades = def_grade_box["exam"]["grade"]  # default box for grades recognition
    shape = (int(dpi * shape[0]), int(dpi * shape[1]))

    db = Database()
    eval_jobs_collection = db.eval_jobs_collection()
    eval_job = eval_jobs_collection.find_one({"job_id": job_id})

    front_template_id = eval_job["front_template_id"]
    regular_template_id = eval_job["regular_template_id"]
    box_grades_list, _, _ = db.get_templates_info(front_template_id, regular_template_id)
    if box_grades_list is not None:
        box_grades = box_grades_list

    documents = db.documents_collection().find({"job_id": job_id})
    img_path = str(TMP_DIR.joinpath('intermediate_image.png'))
    for doc in documents:
        input_pdf_path = storage.abs_path(doc["rel_filepath"])
        grades = doc["grades"]
        grades.append(sum(grades))

        try:
            add_grades(grades, input_pdf_path, box_grades, img_path,  add_border=False, shape=shape)
        except Exception as e:
            print(f"Error while adding grades to {input_pdf_path}: {e}")

        layout = img2pdf.get_fixed_dpi_layout_fun((dpi, dpi))
        with open(input_pdf_path, "wb") as f:
            f.write(img2pdf.convert(img_path, layout_fun=layout))
        print(f"Modified PDF saved as {input_pdf_path}")
