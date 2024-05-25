import os
import shutil
import zipfile
import glob
from pathlib import Path
from PyPDF2 import PdfReader, PdfWriter

def calculate_pages(pages_per_question):
    results = {}
    current_start_page = 3 # start_page
    for question, num_pages in pages_per_question.items():
        end_page = current_start_page + num_pages - 1
        results[question] = list(range(current_start_page - 1, end_page))
        current_start_page = end_page + 1
    return results

def split_and_merge(n_pages_per_question, input_pdfs, output_folder):
    if not os.path.exists(output_folder):
        os.makedirs(output_folder)

    question_writers = {key: PdfWriter() for key in n_pages_per_question}

    for input_pdf in input_pdfs:
        with open(input_pdf, 'rb') as f:
            reader = PdfReader(f)
            pages_for_questions = calculate_pages(n_pages_per_question)

            for question, pages in pages_for_questions.items():
                for page_index in pages:
                    if page_index < len(reader.pages):
                        question_writers[question].add_page(reader.pages[page_index])
                    else:
                        # flag for missing pages
                        print(f"Page {page_index + 1} missing in '{input_pdf}' for question '{question}'.")

    for question, writer in question_writers.items():
        output_path = os.path.join(output_folder, f"{question}.pdf")
        with open(output_path, 'wb') as output_file:
            writer.write(output_file)

def process_zip(zip_path, temp_folder, output_folder, n_pages_per_question):
    with zipfile.ZipFile(zip_path, 'r') as zip_ref:
        zip_ref.extractall(temp_folder)

        extracted_files = []
        for root, dirs, files in os.walk(temp_folder):
            for file in files:
                if file.lower().endswith('.pdf'):
                    extracted_files.append(os.path.join(root, file))

    split_and_merge(n_pages_per_question, extracted_files, output_folder)
    shutil.rmtree(temp_folder)

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

    process_zip(zip_file_path, temp_path, documents_path, n_pages_per_question)

# example
# n_pages_per_question = {'Q1': 2, 'Q2': 3, 'Q3': 1}
#
# zip_folder_to_extract = os.path.join('storage', 'output_zip')
# process_path(zip_folder_to_extract, '7edc7584-1321-488b-8414-06a2640cee45', n_pages_per_question)




