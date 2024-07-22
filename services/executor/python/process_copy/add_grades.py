import img2pdf
import os
from process_copy.database import Database
from process_copy.recognize import add_grades, convert_to_front_box_config

INTERMEDIATE_IMAGE_PATH = 'rmn/services/executor/images/intermediate_image.png'


def process_writing(job_id):
    box_list, box_matricule_list, regular_box_matricule_list = None, None, None
    box_grades = (0.8, .95, 0.2, 0.55)
    shape=(8.5, 11)
    dpi=300
    shape = (int(dpi * shape[0]), int(dpi * shape[1]))

    db = Database()
    documents_collection = db.documents_collection()
    documents = documents_collection.find({"job_id": job_id})

    front_template_id = eval_job["front_template_id"]
    regular_template_id = eval_job["regular_template_id"]
    box_list, box_matricule_list, regular_box_matricule_list = db.get_templates_info(front_template_id, regular_template_id)
    if box_matricule_list is not None:
        front_box_matricule = convert_to_front_box_config(box_matricule_list)
        box_grades = front_box_matricule['front']

    filenames = []
    for document in documents:
        document_basename = os.path.basename(document["filename"])
        if document_basename.endswith("_cover.pdf"):
            filenames.append(document_basename)

    eval_jobs_collection = db.eval_jobs_collection()
    eval_job = eval_jobs_collection.find_one({"job_id": job_id})
    copies_information = eval_job["copies_information"]

    for filename in filenames:
        base_filename = filename.replace('_cover.pdf', '.pdf')
        copyDict = copies_information.get(base_filename)
        input_pdf_path = f'rmn/storage/documents/{job_id}/{filename}'
        numbers = copyDict.values()

        add_grades(numbers, input_pdf_path, box_grades, add_border=False, shape=shape)

        with open(INTERMEDIATE_IMAGE_PATH, "rb") as image_file:
            image_data = image_file.read()
            pdf_bytes = img2pdf.convert(image_data)

        with open(input_pdf_path, "wb") as f:
            f.write(pdf_bytes)

        print(f"Modified PDF saved as {input_pdf_path}")
