from fpdf import FPDF
from PIL import Image
import img2pdf
import os
import shutil
from process_copy.database import Database
from process_copy.recognize import add_grades
from utils.storage import Storage
from utils.utils import Document_Status
from process_copy.config import grade_box as def_grade_box
storage = Storage()


def process_writing(job, TMP_DIR, dpi=300, shape=(8.5, 11) ):
    """
    Process the writing job by adding grades to the PDF files.

    Args:
        job (dict): The job.

    Returns:
        None
    """
    job_id = job["job_id"]
    box_grades = def_grade_box["exam"]["grade"]  # default box for grades recognition
    shape = (int(dpi * shape[0]), int(dpi * shape[1]))

    db = Database()
    front_template_id = job["front_template_id"]
    regular_template_id = job["regular_template_id"]
    box_grades_list, _, _ = db.get_templates_info(front_template_id, regular_template_id)
    if box_grades_list is not None:
        box_grades = box_grades_list

    n_docs = db.documents_collection().count_documents({"job_id": job_id})
    documents = db.documents_collection().find({"job_id": job_id})
    img_path = str(TMP_DIR.joinpath('intermediate_image.jpg'))
    print("Adding grades to copies ...")
    i = 0
    for doc in documents:
        input_pdf_path = storage.abs_path(doc["rel_filepath"])

        if doc['status'] == Document_Status.DELETED.value:
            i += 1
            print(f"({i}/{n_docs}) PDF is deleted {input_pdf_path}")

        grades = doc["grades"]
        grades.append(sum(grades))

        # copy a backup of the original cover page
        input_pdf_path_backup = input_pdf_path.replace(".pdf", "_nograde.pdf")
        if not os.path.exists(input_pdf_path_backup):
            shutil.copy(input_pdf_path, input_pdf_path_backup)

        try:
            # use backup to add grades (not to overwrite grades if re-processing)
            add_grades(grades, input_pdf_path_backup, box_grades, img_path,  add_border=False, shape=shape)
        except Exception as e:
            print(f"Error while adding grades to {input_pdf_path}: {e}")

        layout = img2pdf.get_fixed_dpi_layout_fun((dpi, dpi))
        with open(input_pdf_path, "wb") as f:
            f.write(img2pdf.convert(img_path, layout_fun=layout))
        i += 1
        print(f"({i}/{n_docs}) Modified PDF saved as {input_pdf_path}")
