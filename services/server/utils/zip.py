import os
import shutil
import zipfile


def update_zip(zip_path, pdf_files_to_add, temp_dir):
    with zipfile.ZipFile(zip_path, 'r') as zip_ref:
        zip_ref.extractall(temp_dir)

    for file_path in pdf_files_to_add:
        fn = filename = os.path.basename(file_path)
        i = 0
        while os.path.exists(os.path.join(temp_dir, fn)):
            fn = filename.rsplit('.')[0] + "-%d.pdf" % i
            i += 1
        shutil.move(file_path, os.path.join(temp_dir, fn))

    with zipfile.ZipFile(zip_path, 'w') as new_zip:
        for foldername, subfolders, filenames in os.walk(temp_dir):
            for filename in filenames:
                file_path = os.path.join(foldername, filename)
                new_zip.write(file_path, os.path.relpath(file_path, temp_dir))

    shutil.rmtree(temp_dir)
