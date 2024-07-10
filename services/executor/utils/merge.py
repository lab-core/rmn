import os
from PyPDF2 import PdfReader, PdfWriter

def find_files_with_base_name(base_name, folder_paths, suffix):
    pdf_paths = []
    for folder_path in folder_paths:
        for file_name in os.listdir(folder_path):
            if file_name.startswith(base_name) and file_name.lower().endswith(suffix):
                pdf_paths.append(os.path.join(folder_path, file_name))
    return pdf_paths

def merge_pdfs_by_base_name(base_names, folder_paths, output_folder):
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


# folder_paths = [
#     'storage/cover_pages/3f3c0889-cd70-45e4-9752-8ab26a47a7f5',
#     'storage/documents/3f3c0889-cd70-45e4-9752-8ab26a47a7f5/Q1',
#     'storage/documents/3f3c0889-cd70-45e4-9752-8ab26a47a7f5/Q2',
#     'storage/documents/3f3c0889-cd70-45e4-9752-8ab26a47a7f5/Q3',
#     'storage/documents/3f3c0889-cd70-45e4-9752-8ab26a47a7f5/Q4',
#     'storage/documents/3f3c0889-cd70-45e4-9752-8ab26a47a7f5/Q5'
# ]


base_names = [os.path.splitext(file_name)[0].rsplit('_', 1)[0] for file_name in os.listdir(folder_paths[0]) if file_name.lower().endswith('.pdf')]


# output_folder = 'storage/corrected_copies/3f3c0889-cd70-45e4-9752-8ab26a47a7f5'


# if __name__ == '__main__':
#     merge_pdfs_by_base_name(base_names, folder_paths, output_folder)
