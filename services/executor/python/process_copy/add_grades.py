from fpdf import FPDF
from PIL import Image
import os
from process_copy.database import Database
from process_copy.recognize import add_grades
from utils.storage import Storage

storage = Storage()
INTERMEDIATE_IMAGE_PATH = os.path.join(storage.abs_path(f'temp'), 'intermediate_image.png')


def convert_to_front_box_config(list_matricule_box):
    """
    Converts a list of matricule box values to a front box configuration dictionary.

    Args:
        list_matricule_box (list): A list of matricule box values.

    Returns:
        dict: A dictionary representing the front box configuration with the following keys:
            - "front": A tuple of rounded matricule box values.
            - "separate_box": A boolean indicating whether the box should be separated.
            - "regular": A tuple representing the regular box configuration.

    Example:
        >>> convert_to_front_box_config([1.234, 2.345, 3.456])
        {
            "front": (1.23, 2.35, 3.46),
            "separate_box": True,
            "regular": (0.55, 0.95, 0.05, 0.13)
        }
    """
    rounded_list_matricule_box = [round(x, 2) for x in list_matricule_box]
    return {
        "front": tuple(rounded_list_matricule_box),
        "separate_box": True,
        "regular": (0.55, 0.95, 0.05, 0.13),
    }

def convert_to_regular_box_config(list_matricule_box):
    """
    Converts a list of matricule box values to a regular box configuration.

    Args:
        list_matricule_box (list): A list of matricule box values.

    Returns:
        dict: A dictionary representing the regular box configuration with the following keys:
            - "front" (tuple): A tuple representing the front box dimensions.
            - "separate_box" (bool): A boolean indicating whether the box should be separated.
            - "regular" (tuple): A tuple representing the rounded matricule box values.
    """
    rounded_list_matricule_box = [round(x, 2) for x in list_matricule_box]
    return {
        "front": (0.05, 0.85, 0.15, 0.35),
        "separate_box": True,
        "regular": tuple(rounded_list_matricule_box),
    }

def convert_grade_box_config(list_grade_box):
    """
    Converts a list of grade boxes into a dictionary with a tuple of grades.

    Args:
        list_grade_box (list): A list of grade boxes.

    Returns:
        dict: A dictionary with a tuple of grades.

    """
    return {"grade": tuple(list_grade_box)}

def process_writing(job_id):
    """
    Process the writing job by adding grades to the PDF files.

    Args:
        job_id (str): The ID of the job.

    Returns:
        None
    """
    box_list, box_matricule_list, regular_box_matricule_list = None, None, None
    box_grades=(0.8, 0.95, 0.2, 0.55) # default box for grades recognition
    shape=(8.5, 11) # default shape
    dpi=300 #default dpi
    shape = (int(dpi * shape[0]), int(dpi * shape[1]))

    db = Database()
    documents_collection = db.documents_collection()
    documents = documents_collection.find({"job_id": job_id})

    filenames = []
    for document in documents:
        document_basename = os.path.basename(document["filename"])
        if document_basename.endswith("_cover.pdf"):
            filenames.append(document_basename)

    eval_jobs_collection = db.eval_jobs_collection()
    eval_job = eval_jobs_collection.find_one({"job_id": job_id})

    front_template_id = eval_job["front_template_id"]
    regular_template_id = eval_job["regular_template_id"]
    box_list, box_matricule_list, regular_box_matricule_list = db.get_templates_info(front_template_id, regular_template_id)
    if box_matricule_list is not None:
        front_box_matricule = convert_to_front_box_config(box_matricule_list)
        box_grades = front_box_matricule['front']

    copies_informations = eval_job["copies_informations"]
    copies_info_dict = {item[0]: item[1] for item in copies_informations}

    for filename in filenames:
        base_filename = filename.replace('_cover.pdf', '.pdf')
        copyDict = copies_info_dict.get(base_filename)

        input_pdf_path = os.path.join(storage.abs_path(os.path.join('cover_pages', job_id)), filename)
        numbers = [grade[1] for grade in copyDict]
        total = sum(numbers)
        numbers.append(total)

        try:
            add_grades(numbers, input_pdf_path, box_grades, add_border=False, shape=shape)
        except Exception as e:
            print(f"Error while adding grades to {input_pdf_path}: {e}")

        pdf_width = 8.5 * 72
        pdf_height = 11 * 72

        pdf = FPDF(unit="pt", format=[pdf_width, pdf_height])
        pdf.add_page()

        pdf.image(INTERMEDIATE_IMAGE_PATH, 0, 0, pdf_width, pdf_height)

        pdf.output(input_pdf_path)

        print(f"Modified PDF saved as {input_pdf_path}")

        os.remove(INTERMEDIATE_IMAGE_PATH)
