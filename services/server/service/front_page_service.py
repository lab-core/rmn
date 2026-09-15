"""Cover pages for the copies of a Moodle zip (``/front_page``).

Each student folder ``Nom complet_Identifiant_Matricule_assignsubmission_file_``
holds one PDF; a LaTeX front page with the name and matricule is compiled and
prepended. The folder name is typeset, so it is escaped for TeX, and pdflatex
runs in the request's working directory with shell escape off and file reads
limited to that directory (see ``rmn_common.tex``).
"""

import os
import shutil
import subprocess
import traceback

import pymupdf
import unidecode
from colorama import Fore, Style

from rmn_common.tex import LATEX_ENV, LATEX_FLAGS, tex_escape


class FrontPageHandler:
    CMD = "pdflatex"
    TIMEOUT = 60  # seconds per cover page (1 s used to fail every compile)
    INPUT_CONTENT = "\\renewcommand{\\nom}{%s}\n\\renewcommand{\\matricule}{%s}\n"

    def addFrontPages(
        self, work_directory, input_folder, suffix, latex_front_page, latex_input_file
    ):
        """Prepend a front page to every copy; returns ``(done, failed)`` counts.

        A copy whose front page fails is left in its folder (it used to be
        deleted and the zip returned as if complete).
        """
        done = failed = 0
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
            file = files[0]
            file_path = os.path.join(root, file)
            fullname = split_folder[0]
            matricule = split_folder[2]
            tempname = "_".join(fullname.split(" "))
            name = os.path.join(
                input_folder,
                f"{tempname}_{str(matricule)}{f'_{suffix}.pdf' if suffix else file}",
            )

            if self.copy_file_with_front_page(
                file_path,
                latex_front_page,
                latex_input_file,
                work_directory,
                name,
                name=fullname,
                mat=matricule,
            ):
                done += 1
                shutil.rmtree(root)
            else:
                failed += 1
                print(f"Error while processing {folder}")

        return done, failed

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
            doc = pymupdf.Document(f_page)
            copy = pymupdf.Document(file)
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
        # remove accents, then escape: the values come from a folder name of
        # the uploaded zip
        no_accent_name = tex_escape(unidecode.unidecode(name))
        input_data = self.INPUT_CONTENT % (no_accent_name, tex_escape(matricule))

        with open(latex_input_file, "w") as f:
            f.write(input_data)

        # compile in the request's directory (cwd=, not os.chdir: the process-wide
        # chdir was not restored on error and left the worker in a deleted
        # directory)
        try:
            subprocess.run(
                [self.CMD, *LATEX_FLAGS, latex_file],
                cwd=tmp_dir,
                env={**os.environ, **LATEX_ENV},
                timeout=self.TIMEOUT,
                check=True,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.STDOUT,
            )
        except subprocess.TimeoutExpired:
            raise ChildProcessError(f"Subprocess latex time out after {self.TIMEOUT} seconds.")

        # return path to pdf
        fname = os.path.basename(latex_file)
        fpdf = fname.rsplit(".", 1)[0] + ".pdf"
        return os.path.join(tmp_dir, fpdf)
