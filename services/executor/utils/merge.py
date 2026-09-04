import os
from pypdf import PdfReader, PdfWriter
from python.process_copy.database import Database
from utils.storage import Storage
from utils.utils import Document_Status, active_question_keys


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


def merge_parts(job_id, n_pages_per_question):
    """
    Build the ordered list of parts to concatenate for each copy.

    Args:
        job_id (str): The ID of the job.
        n_pages_per_question: The pages per question (dict or [[key, pages], ...]).

    Returns:
        list: (folder, filename suffix) couples: the cover page first, then one
              entry per question that is not ignored, in numeric order.
    """
    parts = [(storage.abs_path(os.path.join('cover_pages', job_id)), "_cover.pdf")]
    for question in active_question_keys(n_pages_per_question):
        folder = storage.abs_path(os.path.join('documents', job_id, question))
        parts.append((folder, f"_{question}.pdf"))
    return parts


def merge_pdfs_by_base_name(base_names, parts, output_folder):
    """
    Merge PDF files based on their base names.

    Args:
        base_names (list): A list of base names of the PDF files to be merged.
        parts (list): (folder, suffix) couples, see merge_parts; the file merged
                      for a copy is folder/<base_name><suffix>.
        output_folder (str): The folder path where the merged PDF files will be saved.

    Returns:
        None
    """
    os.makedirs(output_folder, exist_ok=True)

    print("Merging PDF files...")
    k = 0
    n_docs = len(base_names)
    for base_name in base_names:
        writer = PdfWriter()
        output_path = os.path.join(output_folder, f"{base_name}.pdf")

        for folder, suffix in parts:
            reader = PdfReader(os.path.join(folder, base_name + suffix))
            for page in reader.pages:
                writer.add_page(page)

        with open(output_path, 'wb') as output_file:
            writer.write(output_file)
        k += 1
        print(f"({k}/{n_docs}) Merged PDF for {base_name} saved at {output_path}")


def process_merge(job):
    """
    Merge PDF files for a given job ID.

    Args:
        job (dict): The job.

    Returns:
        output_folder (str): path to the directory with all corrected copies
    """
    job_id = job["job_id"]
    # the question keys (not their position) name the folders and files, and an
    # ignored question (0 page) has neither
    parts = merge_parts(job_id, job["n_pages_per_question"])

    # files to merge
    db = Database()
    documents = db.documents_collection().find({"job_id": job_id})
    base_names = [doc["filename"] for doc in documents if doc['status'] != Document_Status.DELETED.value]

    # output for the merged files
    output_folder = storage.abs_path(os.path.join('corrected_copies', job_id))

    merge_pdfs_by_base_name(base_names, parts, output_folder)

    return output_folder
