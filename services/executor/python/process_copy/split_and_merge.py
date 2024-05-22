import os
from PyPDF2 import PdfReader, PdfWriter

def calculate_pages(pages_per_question):
    results = {}
    current_start_page = 2
    for question, num_pages in pages_per_question.items():
        end_page = current_start_page + num_pages - 1
        results[question] = list(range(current_start_page - 1, end_page))
        current_start_page = end_page + 1
    return results

def split_and_merge(nPagesPerQuestion, input_pdfs, output_folder):
    if not os.path.exists(output_folder):
        os.makedirs(output_folder)

    question_writers = {key: PdfWriter() for key in nPagesPerQuestion}

    for input_pdf in input_pdfs:
        with open(input_pdf, 'rb') as f:
            reader = PdfReader(f)
            pages_for_questions = calculate_pages(nPagesPerQuestion)

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

# hard-coded part 
nPagesPerQuestion = {
    "Q1": 2,
    "Q2": 3,
    "Q3": 1,
}
input_pdfs = ["copie1.pdf", "copie2.pdf", "copie3.pdf"]
output_folder = "output"
# split_and_merge(nPagesPerQuestion, input_pdfs, output_folder)


