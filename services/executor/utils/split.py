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
    return sum(n_pages_per_question.values()) + CURRENT_START_PAGE - 1

def calculate_pages(pages_per_question):
    current_start_page = CURRENT_START_PAGE
    results = {}
    for question, num_pages in pages_per_question.items():
        end_page = current_start_page + num_pages - 1
        results[question] = list(range(current_start_page - 1, end_page))
        current_start_page = end_page + 1
    return results

def verify_n_pages(n_pages_per_question, input_pdfs, job_id):
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
                    generated_pdfs_per_question[question].append(output_path)
                
                # saving the first page as cover page
                cover_writer = PdfWriter()
                cover_writer.add_page(reader.pages[0])
                cover_output_path = os.path.join(cover_page_folder, f"{base_filename}_cover.pdf")
                with open(cover_output_path, 'wb') as cover_output_file:
                    cover_writer.write(cover_output_file)

    # copying the cover_pages folder to the destination
    cover_page_dest = os.path.join('cover_pages', job_id)
    if not os.path.exists(storage.abs_path(cover_page_dest)):
        os.makedirs(storage.abs_path(cover_page_dest))
    for file in os.listdir(cover_page_folder):
        src_file = os.path.join(cover_page_folder, file)
        dst_file = os.path.join(storage.abs_path(cover_page_dest), file)
        storage.copy_from(src_file, dst_file)

    return generated_pdfs_per_question, is_valid, error_messages


def process_zip(zip_path, temp_folder, output_folder, n_pages_per_question, job_id):
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
    root_path = Path(__file__).resolve().parent.parent
    documents_path = root_path.joinpath('storage', 'documents', job_id)

    zip_path = Path(storage.abs_path(zip_folder))
    zip_files = glob.glob(str(zip_path / '*.zip'))
    
    if not zip_files:
        raise FileNotFoundError("No ZIP file found in specified folder.")
    
    zip_file_path = os.path.join(zip_path, zip_files[0])
    temp_path = zip_path.joinpath('extracted')
    
    if not n_pages_per_question:
        raise ValueError("Please provide a mapping of questions to page numbers.")

    generated_pdfs, is_valid, error_messages = process_zip(zip_file_path, temp_path, documents_path, n_pages_per_question, job_id)
    return generated_pdfs, is_valid, error_messages

def insert_copies(zip_folder, job_id, n_pages_per_question):
    db = Database()

    generated_pdfs, is_valid, error_messages = process_path(zip_folder, job_id, n_pages_per_question)
    
    document_index = 1
    for question, pdf_paths in generated_pdfs.items():
        for pdf_path in pdf_paths:
            file_path = os.path.join('documents', job_id, question, os.path.basename(pdf_path))
            storage.copy_from(pdf_path, storage.abs_path(file_path))
            
            file_name = f"documents/{job_id}/{question}/{os.path.basename(pdf_path)}"
            pdf_name = os.path.basename(pdf_path)
            original_pdf_name = re.sub(r'_Q\d+', '', pdf_name)
            doc  = db.get_document(job_id, original_pdf_name)

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
