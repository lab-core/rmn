import os
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

        # merging cover page first
        cover_pdf_path = find_files_with_base_name(base_name, folder_paths, suffix='_cover.pdf')
        if cover_pdf_path:
            cover_reader = PdfReader(cover_pdf_path[0])
            for page in cover_reader.pages:
                writer.add_page(page)

        # merging regular PDFs
        pdf_paths = find_files_with_base_name(base_name, folder_paths, suffix='.pdf')
        for pdf_path in pdf_paths:
            if not pdf_path.endswith('_cover.pdf'):
                reader = PdfReader(pdf_path)
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
        None
    """
    db = Database()
    eval_jobs_collection = db.eval_jobs_collection()
    eval_job = eval_jobs_collection.find_one({"job_id": job_id})
    n_max_points_per_question = eval_job["n_max_points_per_question"]
    question_indexes = [item[0] for item in n_max_points_per_question]
    question_indexes.sort()

    folder_paths = [storage.abs_path(os.path.join('cover_pages', job_id))]
    for question_index in question_indexes:
        question_index_path = storage.abs_path(os.path.join('documents', job_id, str(question_index)))
        folder_paths.append(question_index_path)

    base_names = [os.path.splitext(file_name)[0].rsplit('_', 1)[0] for file_name in os.listdir(folder_paths[0]) if file_name.lower().endswith('.pdf')]

    output_folder = storage.abs_path(os.path.join('corrected_copies', job_id))

    merge_pdfs_by_base_name(base_names, folder_paths, output_folder)