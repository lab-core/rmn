import os
import re
from PyPDF2 import PdfReader, PdfWriter
from python.process_copy.database import Database
from utils.storage import Storage

storage = Storage()


def find_files_with_base_name(base_name, folder_paths, suffix):
    """
    Find files with a given base name and suffix in the specified folder paths.

    Args:
        base_name (str): The base name of the files to search for.
        folder_paths (list): A list of folder paths to search in.
        suffix (str): The suffix of the files to search for.

    Returns:
        list: A list of file paths that match the given base name and suffix.
    """
    pdf_paths = []
    for folder_path in folder_paths:
        for file_name in os.listdir(folder_path):
            if file_name.startswith(base_name) and file_name.lower().endswith(suffix):
                pdf_paths.append(os.path.join(folder_path, file_name))
    return pdf_paths


def merge_pdfs_by_base_name(base_names, folder_paths, output_folder):
    """
    Merge PDF files based on their base names.

    Args:
        base_names (list): A list of base names of the PDF files to be merged.
        folder_paths (list): A list of folder paths where the PDF files are located.
        output_folder (str): The folder path where the merged PDF files will be saved.

    Returns:
        None
    """
    if not os.path.exists(output_folder):
        os.makedirs(output_folder)

    for base_name in base_names:
        writer = PdfWriter()
        output_path = os.path.join(output_folder, f"{base_name}.pdf")

        for i, path in enumerate(folder_paths):
            filename = base_name
            # if cover
            if i == 0:
                filename += "_cover.pdf"
            # otherwise, it's a question
            else:
                filename += f"_Q{i}.pdf"

            reader = PdfReader(os.path.join(path, filename))
            for page in reader.pages:
                writer.add_page(page)

        with open(output_path, 'wb') as output_file:
            writer.write(output_file)
        print(f"Merged PDF for {base_name} saved at {output_path}")


def process_merge(job_id):
    """
    Merge PDF files for a given job ID.

    Args:
        job_id (str): The ID of the job.

    Returns:
        output_folder (str): path to the directory with all corrected copies
    """
    db = Database()
    eval_jobs_collection = db.eval_jobs_collection()
    eval_job = eval_jobs_collection.find_one({"job_id": job_id})
    n_max_points_per_question = eval_job["n_max_points_per_question"]
    question_indexes = [item[0] for item in n_max_points_per_question]
    question_indexes.sort()

    # folders where to fetch the different parts to merge
    folder_paths = [storage.abs_path(os.path.join('cover_pages', job_id))]
    for question_index in question_indexes:
        question_index_path = storage.abs_path(os.path.join('documents', job_id, str(question_index)))
        folder_paths.append(question_index_path)

    # files to merge
    documents = db.documents_collection().find({"job_id": job_id})
    base_names = [doc["filename"] for doc in documents]

    # output for the merged files
    output_folder = storage.abs_path(os.path.join('corrected_copies', job_id))

    merge_pdfs_by_base_name(base_names, folder_paths, output_folder)

    return output_folder
