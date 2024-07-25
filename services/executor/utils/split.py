import os
import re
import shutil
import zipfile
import glob
from pathlib import Path
from PyPDF2 import PdfReader, PdfWriter
from python.process_copy.database import Database
from utils.storage import Storage
from utils.utils import Document_Status
from collections import OrderedDict

storage = Storage()
CURRENT_START_PAGE = 2 # start_page

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
    """
    current_start_page = CURRENT_START_PAGE
    results = {}
    for question, num_pages in pages_per_question.items():
        end_page = current_start_page + num_pages - 1
        results[question] = list(range(current_start_page - 1, end_page))
        current_start_page = end_page + 1
    return results

def verify_n_pages(n_pages_per_question, input_pdfs, job_id):
    """
    Verifies the number of pages in each input PDF file.

    Args:
        n_pages_per_question (int): The expected number of pages per question.
        input_pdfs (list): A list of input PDF file paths.
        job_id (str): The ID of the job.

    Returns:
        tuple: A tuple containing a boolean value indicating whether the verification is valid,
               and a list of error messages if any.

    """
    is_valid = True
    error_messages = []
    total_expected_pages = calculate_total_expected_pages(n_pages_per_question)

    for input_pdf in input_pdfs:
        with open(input_pdf, 'rb') as f:
            reader = PdfReader(f)
            total_pages = len(reader.pages)

            if total_pages != total_expected_pages:
                is_valid = False
                file_name = os.path.basename(input_pdf)
                error_messages.append(f"Erreur : {file_name} a {total_pages} page(s).")
                file_path = os.path.join('incorrect_files', job_id, file_name)
                storage.copy_from(input_pdf, storage.abs_path(file_path))
    
    return is_valid, error_messages

def split_and_save(n_pages_per_question, input_pdfs, output_folder, job_id):
    """
    Splits the input PDFs into separate question PDFs and saves them in the output folder.
    Also saves the first page of each input PDF as a cover page.

    Args:
        n_pages_per_question (dict): A dictionary mapping question names to the number of pages per question.
        input_pdfs (list): A list of input PDF file paths.
        output_folder (str): The path to the output folder where the split PDFs will be saved.
        job_id (str): The ID of the job.

    Returns:
        tuple: A tuple containing the following:
            - generated_pdfs_per_question (dict): A dictionary mapping question names to the generated PDF file paths.
            - is_valid (bool): A flag indicating whether the input PDFs are valid.
            - error_messages (list): A list of error messages if the input PDFs are invalid.
    """
    is_valid, error_messages = verify_n_pages(n_pages_per_question, input_pdfs, job_id)
    total_expected_pages = calculate_total_expected_pages(n_pages_per_question)
    generated_pdfs_per_question = {question: [] for question in n_pages_per_question.keys()}

    if not os.path.exists(output_folder):
        os.makedirs(output_folder)

    base_cover_page_path = os.path.dirname(os.path.dirname(output_folder))
    cover_page_folder = os.path.join(base_cover_page_path, "cover_pages", job_id)
    if not os.path.exists(cover_page_folder):
        os.makedirs(cover_page_folder)

    for input_pdf in input_pdfs:
        with open(input_pdf, 'rb') as f:
            reader = PdfReader(f)
            pages_for_questions = calculate_pages(n_pages_per_question)

            if len(reader.pages) == total_expected_pages:
                base_filename = os.path.splitext(os.path.basename(input_pdf))[0]
                for question, pages in pages_for_questions.items():
                    writer = PdfWriter()
                    for page_index in pages:
                        if page_index < len(reader.pages):
                            writer.add_page(reader.pages[page_index])

                    question_folder = os.path.join(output_folder, question)
                    if not os.path.exists(question_folder):
                        os.makedirs(question_folder)
                    output_path = os.path.join(question_folder, f"{base_filename}_{question}.pdf")
                    with open(output_path, 'wb') as output_file:
                        writer.write(output_file)
                    # save first backup
                    backup_dir = os.path.join(os.path.dirname(output_path), "versions")
                    os.makedirs(backup_dir, exist_ok=True)
                    backup_name = os.path.basename(output_path).rsplit(".", 1)[0] + "-0.pdf"
                    shutil.copy(output_path, os.path.join(backup_dir, backup_name))
                    generated_pdfs_per_question[question].append(output_path)
                
                # saving the first page as cover page
                cover_writer = PdfWriter()
                cover_writer.add_page(reader.pages[0])
                cover_output_path = os.path.join(cover_page_folder, f"{base_filename}_cover.pdf")
                with open(cover_output_path, 'wb') as cover_output_file:
                    cover_writer.write(cover_output_file)

    # inserting the cover_pages into the database
    db = Database()
    cover_page_dest = os.path.join('cover_pages', job_id)
    if not os.path.exists(storage.abs_path(cover_page_dest)):
        os.makedirs(storage.abs_path(cover_page_dest))
    for file in os.listdir(cover_page_folder):
        original_pdf_name = re.sub(r'_cover\.pdf$', '.pdf', file)
        doc = db.get_document(job_id, original_pdf_name)
        db.insert_document(
            job_id=job_id,
            doc_index=file,
            subquestion_pred=[], 
            total=0,
            image_id=file,
            status=Document_Status.TO_VALIDATE,  
            matricule=doc["matricule"],
            time=0,
            filename=file
        )

    return generated_pdfs_per_question, is_valid, error_messages


def process_zip(zip_path, temp_folder, output_folder, n_pages_per_question, job_id):
    """
    Extracts the contents of a zip file, processes the extracted PDF files, and saves the generated PDFs.

    Args:
        zip_path (str): The path to the zip file.
        temp_folder (str): The temporary folder to extract the zip contents.
        output_folder (str): The folder to save the generated PDFs.
        n_pages_per_question (int): The number of pages per question.
        job_id (str): The ID of the job.

    Returns:
        tuple: A tuple containing the generated PDFs, a flag indicating if the processing is valid, and any error messages.
    """
    with zipfile.ZipFile(zip_path, 'r') as zip_ref:
        zip_ref.extractall(temp_folder)

        extracted_files = []
        for root, dirs, files in os.walk(temp_folder):
            for file in files:
                if file.lower().endswith('.pdf'):
                    extracted_files.append(os.path.join(root, file))

    generated_pdfs, is_valid, error_messages = split_and_save(n_pages_per_question, extracted_files, output_folder, job_id)
    shutil.rmtree(temp_folder)
    return generated_pdfs, is_valid, error_messages


def process_path(zip_folder, job_id, n_pages_per_question):
    """
    Process the path for a given job.

    Args:
        zip_folder (str): The folder containing the ZIP file.
        job_id (str): The ID of the job.
        n_pages_per_question (dict): A mapping of questions to page numbers.

    Returns:
        tuple: A tuple containing the generated PDFs, a flag indicating if the process is valid, and any error messages.

    Raises:
        FileNotFoundError: If no ZIP file is found in the specified folder.
        ValueError: If no mapping of questions to page numbers is provided.
    """
    documents_path = Path(storage.abs_path('documents')).resolve().joinpath(job_id)

    zip_path = Path(storage.abs_path(zip_folder))
    zip_files = glob.glob(os.path.join(zip_path, '%s.zip' % job_id))
    
    if not zip_files:
        raise FileNotFoundError("No ZIP file found in specified folder.")
    
    zip_file_path = os.path.join(zip_path, zip_files[0])
    temp_path = zip_path.joinpath('extracted')
    
    if not n_pages_per_question:
        raise ValueError("Please provide a mapping of questions to page numbers.")

    generated_pdfs, is_valid, error_messages = process_zip(zip_file_path, temp_path, documents_path, n_pages_per_question, job_id)
    return generated_pdfs, is_valid, error_messages


def insert_copies(zip_folder, job_id, n_pages_per_question):
    """
    Inserts copies of PDF documents into the database.

    Args:
        zip_folder (str): The path to the folder containing the ZIP file.
        job_id (str): The ID of the job.
        n_pages_per_question (int): The number of pages per question.

    Raises:
        ValueError: If the generated PDFs are not valid.

    Returns:
        None
    """
    db = Database()

    generated_pdfs, is_valid, error_messages = process_path(zip_folder, job_id, n_pages_per_question)
    
    document_index = 1
    for question, pdf_paths in generated_pdfs.items():
        for pdf_path in pdf_paths:
            # code used to develop in local
            # file_path = os.path.join('documents', job_id, question, os.path.basename(pdf_path))
            # storage.copy_from(pdf_path, storage.abs_path(file_path))
            
            file_name = f"documents/{job_id}/{question}/{os.path.basename(pdf_path)}"
            pdf_name = os.path.basename(pdf_path)
            original_pdf_name = re.sub(r'_Q\d+', '', pdf_name)
            doc = db.get_document(job_id, original_pdf_name)

            db.insert_document(
                job_id=job_id,
                doc_index=document_index,
                subquestion_pred=[], 
                total=0,
                image_id=file_name,
                status=Document_Status.TO_VALIDATE,  
                matricule=doc["matricule"], 
                time=0,
                filename=file_name
            )
            document_index += 1
    
    if not is_valid:
        raise ValueError(error_messages)

# example
# n_pages_per_question = {'Q1': 2, 'Q2': 3, 'Q3': 1}
# zip_folder_to_extract = os.path.join('storage', 'output_zip')
# insert_copies(zip_folder_to_extract, '7edc7584-1321-488b-8414-06a2640cee45', n_pages_per_question)
