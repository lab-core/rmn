import fitz
import traceback
import unidecode
import os
import subprocess
import shutil

from colorama import Fore, Style
from pathlib import Path


class FrontPageHandler:
    CMD = "pdflatex"
    INPUT_CONTENT = "\\renewcommand{\\nom}{%s}\n\\renewcommand{\\matricule}{%s}\n"

    def addFrontPages(
        self, work_directory, input_folder, suffix, latex_front_page, latex_input_file
    ):
        for root, dirs, files in os.walk(input_folder):
            # try to split name based on: "Nom complet_Identifiant_Matricule_assignsubmission_file_"
            folder = root.rsplit(os.sep, 1)[-1]
            split_folder = folder.split("_")
            # if folder start by _, ignore whole directory
            ignore_folder = split_folder[0] == ""
            if len(split_folder) < 4 or ignore_folder:
                # if no directory or ignore this folder, remove root
                if len(dirs) == 0 or ignore_folder:
                    # remove folder
                    shutil.rmtree(root)
                else:
                    # remove just all files
                    for f in files:
                        os.remove(os.path.join(root, f))
                continue

            if len(files) != 1:
                print(
                    "Subfolder %s does not contain only one file, but %d files"
                    % (root, len(files))
                )

                if not files:
                    # remove folder and continue
                    shutil.rmtree(root)
                    continue

            # rename it
            # use folder name: "Nom complet_Identifiant_Matricule_assignsubmission_file_"
            try:
                # pdf file
                file = files[0]
                file_path = os.path.join(root, file)
                fullname = split_folder[0]
                matricule = split_folder[2]
                tempname = "_".join(fullname.split(" "))
                name = os.path.join(
                    input_folder,
                    f"{tempname}_{str(matricule)}{f'_{suffix}.pdf' if suffix else file}",
                )

                self.copy_file_with_front_page(
                    file_path,
                    latex_front_page,
                    latex_input_file,
                    work_directory,
                    name,
                    name=fullname,
                    mat=matricule,
                )
            except:
                print(f"Error while processing {folder}")
                pass

            # remove folder
            shutil.rmtree(root)

        root, dirs, files = next(os.walk(input_folder))
        for d in dirs:
            # remove any remaining folders
            folder_path = os.path.join(root, d)
            shutil.rmtree(folder_path)

    def copy_file_with_front_page(
        self,
        file,
        latex_front_page,
        latex_input_file,
        work_directory,
        output_filename,
        name=None,
        mat=None,
    ):
        # add front page if any
        try:
            f_page = self.create_front_page(
                latex_front_page, latex_input_file, name, mat, work_directory
            )
            doc = fitz.Document(f_page)
            copy = fitz.Document(file)
            doc.insert_pdf(copy)
            doc.save(file, garbage=4, deflate=True)
            shutil.move(file, output_filename)
            return True
        except Exception as e:
            traceback.print_exception(type(e), e, e.__traceback__)
            print(
                Fore.RED + "Error when creating new pdf for %s" % file + Style.RESET_ALL
            )
            return False

    def create_front_page(
        self,
        latex_file,
        latex_input_file,
        name,
        matricule,
        tmp_dir,
    ):
        # remove ascents
        no_accent_name = unidecode.unidecode(name)
        # write the input file
        input_data = self.INPUT_CONTENT % (no_accent_name, matricule)

        with open(latex_input_file, "w") as f:
            f.write(input_data)

        current_dir = os.path.dirname(__file__)
        os.chdir(tmp_dir)

        # compile latex file
        try:
            subprocess.check_call([self.CMD, latex_file], timeout=1)
        except subprocess.TimeoutExpired:
            raise ChildProcessError("Subprocess latex time out after 1 second.")

        os.chdir(current_dir)

        # return path to pdf
        fname = os.path.basename(latex_file)
        fpdf = fname.rsplit(".", 1)[0] + ".pdf"
        return os.path.join(tmp_dir, fpdf)
