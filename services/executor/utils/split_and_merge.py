import os
import shutil
import zipfile
import glob
from pathlib import Path
from PyPDF2 import PdfReader, PdfWriter, PdfFileMerger
from python.process_copy.database import Database
from utils.utils import Document_Status
from collections import OrderedDict

def calculate_pages(pages_per_question):
    results = {}
    current_start_page = 3 # start_page
    for question, num_pages in pages_per_question.items():
        end_page = current_start_page + num_pages - 1
        results[question] = list(range(current_start_page - 1, end_page))
        current_start_page = end_page + 1
    return results

def split_and_merge(n_pages_per_question, input_pdfs, output_folder):
    generated_pdfs_per_question = {question: [] for question in n_pages_per_question.keys()}

    if not os.path.exists(output_folder):
        os.makedirs(output_folder)

    for input_pdf in input_pdfs:
        with open(input_pdf, 'rb') as f:
            reader = PdfReader(f)
            pages_for_questions = calculate_pages(n_pages_per_question)

            for question, pages in pages_for_questions.items():
                writer = PdfWriter()
                for page_index in pages:
                    if page_index < len(reader.pages):
                        writer.add_page(reader.pages[page_index])
                    else:
                        print(f"Page {page_index + 1} missing in '{input_pdf}' for question '{question}'.") # should re ask for the missing page

                output_path = os.path.join(output_folder, f"{os.path.splitext(os.path.basename(input_pdf))[0]}_{question}.pdf")
                with open(output_path, 'wb') as output_file:
                    writer.write(output_file)
                generated_pdfs_per_question[question].append(output_path)

    merged_pdfs = []
    for question, pdfs in generated_pdfs_per_question.items():
        merger = PdfFileMerger()
        for pdf in pdfs:
            merger.append(pdf)
        merged_output_path = os.path.join(output_folder, f"{question}.pdf")
        with open(merged_output_path, 'wb') as merged_file:
            merger.write(merged_file)
        merged_pdfs.append(merged_output_path)

    return merged_pdfs

def process_zip(zip_path, temp_folder, output_folder, n_pages_per_question):
    with zipfile.ZipFile(zip_path, 'r') as zip_ref:
        zip_ref.extractall(temp_folder)

        extracted_files = []
        for root, dirs, files in os.walk(temp_folder):
            for file in files:
                if file.lower().endswith('.pdf'):
                    extracted_files.append(os.path.join(root, file))

    generated_pdfs = split_and_merge(n_pages_per_question, extracted_files, output_folder)
    shutil.rmtree(temp_folder)
    return generated_pdfs

def process_path(zip_folder, job_id, n_pages_per_question):
    root_path = Path(__file__).resolve().parent.parent
    documents_path = root_path.joinpath('storage', 'documents', job_id)

    zip_path = root_path.joinpath(zip_folder)
    print(zip_path)
    zip_files = glob.glob(str(zip_path / '*.zip'))
    
    if not zip_files:
        raise FileNotFoundError("No ZIP file found in specified folder.")
    
    zip_file_path = os.path.join(zip_path, zip_files[0])
    temp_path = zip_path.joinpath('extracted')
    
    if not n_pages_per_question:
        raise ValueError("Please provide a mapping of questions to page numbers.")

    generated_pdfs = process_zip(zip_file_path, temp_path, documents_path, n_pages_per_question)
    return generated_pdfs

def insert_copies(zip_folder, job_id, n_pages_per_question):
    db = Database()
    generated_pdfs = process_path(zip_folder, job_id, n_pages_per_question)
    unique_generated_pdfs = list(OrderedDict.fromkeys(generated_pdfs))
    generated_pdfs = unique_generated_pdfs
    print("generated_pdfs: ", generated_pdfs)
    document_index = 1
    for pdf_path in generated_pdfs:
        file_name = f"documents{os.sep}{job_id}{os.sep}Q{document_index}.pdf"
        db.insert_document(
            job_id=job_id,
            doc_index=document_index,
            subquestion_pred=[], 
            total=0,
            image_id=file_name,
            status=Document_Status.TO_VALIDATE,  
            matricule="", 
            time=0,
            filename=file_name
        )
        document_index += 1

# example
# n_pages_per_question = {'Q1': 2, 'Q2': 3, 'Q3': 1}
# zip_folder_to_extract = os.path.join('storage', 'output_zip')
# insert_copies(zip_folder_to_extract, '7edc7584-1321-488b-8414-06a2640cee45', n_pages_per_question)




