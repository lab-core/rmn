import os
import re
import shutil
import zipfile
import glob
from pathlib import Path
from pypdf import PdfReader, PdfWriter
from python.process_copy.database import Database
from utils.storage import Storage
from utils.utils import Document_Status, active_question_keys
from collections import OrderedDict
from werkzeug.utils import secure_filename


storage = Storage()
CURRENT_START_PAGE = 2  # start_page


def calculate_total_expected_pages(n_pages_per_question):
    """
    Calculate the total expected number of pages based on the number of pages per question.

    Args:
        n_pages_per_question (dict): A dictionary mapping question IDs to the number of pages for each question.

    Returns:
        int: The total expected number of pages.

    """
    return sum(n_pages_per_question.values()) + CURRENT_START_PAGE - 1


def calculate_pages(pages_per_question):
    """
    Calculate the range of pages for each question based on the number of pages per question.

    Args:
        pages_per_question (dict): A dictionary mapping each question to the number of pages.

    Returns:
        dict: A dictionary mapping each question to a list of page numbers.

    Example:
        >>> pages_per_question = {'Q1': 3, 'Q2': 2, 'Q3': 4}
        >>> calculate_pages(pages_per_question)
        {'Q1': [0, 1, 2], 'Q2': [3, 4], 'Q3': [5, 6, 7, 8]}

    An ignored question (0 page) is left out of the result: no folder and no
    empty pdf are created for it. The questions are taken in numeric order
    ("Q2" before "Q10"), whatever the order of the input.
    """
    current_start_page = CURRENT_START_PAGE
    results = {}
    for question in active_question_keys(pages_per_question):
        num_pages = pages_per_question[question]
        end_page = current_start_page + num_pages - 1
        results[question] = list(range(current_start_page - 1, end_page))
        current_start_page = end_page + 1
    return results


def save_initial_version(db, job_id, rel_filepath):
    # save initial version document
    rel_dir = os.path.dirname(rel_filepath)
    base_filename = os.path.basename(rel_filepath).rsplit('.', 1)[0]
    version_filepath = os.path.join(rel_dir, "versions", f"{base_filename}-0.pdf")
    storage.copy_from(rel_filepath, storage.abs_path(version_filepath))
    # save version in db
    db.mongo_database["versions"].insert_one(
        {"job_id": job_id, "rel_filepath": rel_filepath, "version": 0,
         "version_filepath": version_filepath, "annotations": []}
    )


def verify_names_and_n_pages(n_pages_per_question, input_pdfs, job_id):
    """
    Verifies the number of pages in each input PDF file.

    Args:
        n_pages_per_question (dict): The expected number of pages per question.
        input_pdfs (list): A list of input PDF file paths.
        job_id (str): The ID of the job.

    Returns:
        couple: A couple containing the list of the new pdfs renamed,
               and a list of error messages if any.

    """
    error_messages = []
    total_expected_pages = calculate_total_expected_pages(n_pages_per_question)
    copies_pattern = storage.abs_path(os.path.join("documents", job_id, "all", "*.pdf"))
    names = set(os.path.basename(cpdf) for cpdf in glob.glob(copies_pattern))
    new_input_pdfs = []

    for input_pdf in input_pdfs:
        # check if name exists, and find a new one in this case
        file_name = os.path.basename(input_pdf)
        fname = sfile_name = secure_filename(file_name)
        i = 0
        while fname in names:
            fname = sfile_name.rsplit('.', 1)[0] + "-%d.pdf" % i
            i += 1

        # add the name, and update the name if needed
        names.add(fname)
        if fname == file_name:
            new_input = input_pdf
        else:
            new_input = os.path.join(os.path.dirname(input_pdf), fname)
            shutil.move(input_pdf, new_input)

        with open(new_input, 'rb') as f:
            reader = PdfReader(f)
            total_pages = len(reader.pages)

            if n_pages_per_question and total_pages != total_expected_pages:
                diff = total_expected_pages - total_pages
                s_str = "s" if abs(diff) > 1 else ""
                if diff > 0:
                    error_messages.append(f"Erreur: {fname} a {diff} page{s_str} manquante{s_str}.")
                else:
                    error_messages.append(f"Erreur: {fname} a {abs(diff)} page{s_str} de trop.")
                file_path = os.path.join('incorrect_files', job_id, fname)
                storage.move_to(new_input, file_path)
            else:
                new_input_pdfs.append(new_input)

    return new_input_pdfs, error_messages


def split_and_save(n_pages_per_question, input_pdfs, job_id):
    """
    Splits the input PDFs into separate question PDFs and saves them in the output folder.
    Also saves the first page of each input PDF as a cover page.

    Args:
        n_pages_per_question (dict): A dictionary mapping question names to the number of pages per question.
        input_pdfs (list): A list of input PDF file paths.
        job_id (str): The ID of the job.

    Returns:
        couple: A couple containing the following:
            - generated_pdfs_per_question (dict): A dictionary mapping question names to the generated PDF file paths.
            - error_messages (list): A list of error messages if the input PDFs are invalid.
    """
    input_pdfs, error_messages = verify_names_and_n_pages(n_pages_per_question, input_pdfs, job_id)
    total_expected_pages = calculate_total_expected_pages(n_pages_per_question)
    generated_pdfs_per_question = {question: [] for question in active_question_keys(n_pages_per_question)}

    output_folder = os.path.join("documents", job_id)
    cover_page_folder = storage.abs_path(os.path.join("cover_pages", job_id))
    os.makedirs(cover_page_folder, exist_ok=True)

    db = Database()
    document_index = db.documents_collection().count_documents({"job_id": job_id})
    # one slot per question of the template, ignored ones included, so that the
    # position of a grade always matches its box on the cover page
    def_grades = [None] * len(n_pages_per_question)
    for input_pdf in input_pdfs:
        with open(input_pdf, 'rb') as f:
            reader = PdfReader(f)
            pages_for_questions = calculate_pages(n_pages_per_question)

            # if no question, store all copies in the "all" folder
            if not n_pages_per_question or len(reader.pages) == total_expected_pages:
                base_filename = os.path.splitext(os.path.basename(input_pdf))[0]
                # won't iterate if no question
                for question, pages in pages_for_questions.items():
                    writer = PdfWriter()
                    for page_index in pages:
                        if page_index < len(reader.pages):
                            writer.add_page(reader.pages[page_index])

                    # save file
                    question_folder = os.path.join(output_folder, question)
                    os.makedirs(storage.abs_path(question_folder), exist_ok=True)
                    output_path = os.path.join(question_folder, f"{base_filename}_{question}.pdf")
                    with open(storage.abs_path(output_path), 'wb') as output_file:
                        writer.write(output_file)
                    # save first version
                    save_initial_version(db, job_id, output_path)
                    # store pdf
                    generated_pdfs_per_question[question].append(output_path)
                
                # saving the first page as cover page
                cover_writer = PdfWriter()
                cover_writer.add_page(reader.pages[0])
                cover_basename = f"{base_filename}_cover.pdf"
                cover_output_path = os.path.join(cover_page_folder, cover_basename)
                with open(cover_output_path, 'wb') as cover_output_file:
                    cover_writer.write(cover_output_file)

                # inserting the cover_pages into the database
                db.insert_document(
                    job_id=job_id,
                    doc_index=document_index,
                    grades=def_grades,
                    rel_filepath=os.path.join("cover_pages", job_id, cover_basename),
                    status=Document_Status.NOT_READY,
                    matricule="",
                    time=0,
                    filename=base_filename
                )

                # save whole pdf
                storage.move_to(input_pdf, os.path.join(output_folder, "all", f"{base_filename}.pdf"))

                document_index += 1

    return generated_pdfs_per_question, error_messages


def process_folder(zip_folder, job_id, n_pages_per_question, TMP_DIR):
    """
    Process the path for a given job.

    Args:
        zip_folder (str): The path to the folder containing the ZIP files.
        job_id (str): The ID of the job.
        n_pages_per_question (dict): A mapping of questions to page numbers.
        TMP_DIR (Path): temporary folder to put temporary files

    Returns:
        couple: A couple containing the generated PDFs, any error messages, and all processed zip files.

    Raises:
        FileNotFoundError: If no ZIP file is found in the specified folder.
        ValueError: If no mapping of questions to page numbers is provided.
    """
    all_zips = []
    extracted_files = []
    zip_path = Path(storage.abs_path(zip_folder))
    temp_path = str(TMP_DIR.joinpath('extracted'))
    # an empty zip extracts nothing, so make sure the folder exists anyway
    os.makedirs(temp_path, exist_ok=True)
    for zip_file in zip_path.glob('*.zip'):
        with zipfile.ZipFile(zip_file, 'r') as zip_ref:
            zip_ref.extractall(temp_path)
            extracted_files = []
            for root, dirs, files in os.walk(temp_path):
                for file in files:
                    if "__MACOSX" in file or not file.endswith(".pdf") or file.startswith("."):
                        os.remove(os.path.join(root, file))
                    elif file.lower().endswith('.pdf'):
                        extracted_files.append(os.path.join(root, file))

        all_zips.append(zip_file)

    generated_pdfs, error_messages = \
        split_and_save(n_pages_per_question, extracted_files, job_id)

    # remove zip tmp directory
    shutil.rmtree(temp_path)

    return generated_pdfs, error_messages, all_zips


def insert_copies(zip_folder, job_id, n_pages_per_question, TMP_DIR):
    """
    Inserts copies of PDF documents into the database.

    Args:
        zip_folder (str): The path to the folder containing the ZIP files.
        job_id (str): The ID of the job.
        n_pages_per_question (dict): The number of pages per question.

    Raises:
        ValueError: If the generated PDFs are not valid.

    Returns:
        None
    """
    generated_pdfs, error_messages, zips = process_folder(zip_folder, job_id, n_pages_per_question, TMP_DIR)

    db = Database()
    document_index = db.questions_collection().count_documents({"job_id": job_id})
    for question, pdf_paths in generated_pdfs.items():
        for pdf_path in pdf_paths:
            filename = os.path.basename(pdf_path).rsplit(".", 1)[0]
            basename = filename.rsplit("_", 1)[0]
            rel_filepath = os.path.join('documents', job_id, question, filename) + ".pdf"
            db.insert_question(
                job_id=job_id,
                doc_index=document_index,
                rel_filepath=rel_filepath,
                status=Document_Status.TO_VALIDATE,
                filename=filename,
                question=question,
                basename=basename
            )
            document_index += 1

    for zip_file in zips:
        os.remove(zip_file)

    if error_messages:
        raise ValueError(error_messages)

# example
# n_pages_per_question = {'Q1': 2, 'Q2': 3, 'Q3': 1}
# zip_folder_to_extract = os.path.join('storage', 'output_zip')
# insert_copies(zip_folder_to_extract, '7edc7584-1321-488b-8414-06a2640cee45', n_pages_per_question)
