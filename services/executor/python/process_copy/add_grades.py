from fpdf import FPDF
from PIL import Image
import img2pdf
import os
from process_copy.database import Database
from process_copy.recognize import add_grades
from utils.storage import Storage

storage = Storage()


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


def process_writing(job_id, TMP_DIR, dpi=300, shape=(8.5, 11) ):
    """
    Process the writing job by adding grades to the PDF files.

    Args:
        job_id (str): The ID of the job.

    Returns:
        None
    """
    box_grades = (0.82, .96, 0.15, 0.55)  # default box for grades recognition
    shape = (int(dpi * shape[0]), int(dpi * shape[1]))

    db = Database()
    eval_jobs_collection = db.eval_jobs_collection()
    eval_job = eval_jobs_collection.find_one({"job_id": job_id})

    front_template_id = eval_job["front_template_id"]
    regular_template_id = eval_job["regular_template_id"]
    box_grades_list, _, _ = db.get_templates_info(front_template_id, regular_template_id)
    # if box_grades_list is not None:
    #     box_grades = box_grades_list

    copies_informations = eval_job["copies_informations"]
    copies_info_dict = {item[0]: item[1] for item in copies_informations}

    documents = db.documents_collection().find({"job_id": job_id})
    img_path = str(TMP_DIR.joinpath('intermediate_image.png'))
    for doc in documents:
        copyDict = copies_info_dict.get(doc["filename"])
        input_pdf_path = storage.abs_path(doc["rel_filepath"])
        numbers = [grade[1] for grade in copyDict]
        numbers.append(sum(numbers))

        try:
            add_grades(numbers, input_pdf_path, box_grades, img_path,  add_border=False, shape=shape)
        except Exception as e:
            print(f"Error while adding grades to {input_pdf_path}: {e}")

        layout = img2pdf.get_fixed_dpi_layout_fun((dpi, dpi))
        with open(input_pdf_path, "wb") as f:
            f.write(img2pdf.convert(img_path, layout_fun=layout))
        print(f"Modified PDF saved as {input_pdf_path}")
