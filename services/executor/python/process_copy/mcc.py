#  MIT License
#
#  Copyright (c) 2021.  Antoine Legrain <antoine.legrain@gmail.com>
#
#  Permission is hereby granted, free of charge, to any person obtaining a copy
#  of this software and associated documentation files (the "Software"), to deal
#  in the Software without restriction, including without limitation the rights
#  to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
#  copies of the Software, and to permit persons to whom the Software is
#  furnished to do so, subject to the following conditions:
#
#  The above copyright notice and this permission notice shall be included in all
#  copies or substantial portions of the Software.
#
#  THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
#  IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
#  FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
#  AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
#  LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
#  OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN THE
#  SOFTWARE.

import os
import shutil
import subprocess
import glob
import zipfile
import re
import pandas as pd
import unidecode
import pymupdf
from colorama import Fore, Style
import traceback

from process_copy.config import re_mat, Latex
from process_copy.config import MoodleFields as MF


MB = 2**20


def load_csv(grades_csv):
    grades_dfs = []
    for g in grades_csv:
        df = pd.read_csv(g)
        dup_index = [i for i, d in enumerate(df.duplicated(subset=[MF.mat])) if d]
        if dup_index:
            print("Remove duplicated:", df.iloc[dup_index])
            df = df.drop(dup_index)
            df.to_csv(g)
        grades_dfs.append(df.set_index(MF.mat))
    grades_names = [g.rsplit(os.sep)[-1].split(".")[0] for g in grades_csv]

    for g in grades_dfs:
        g.index = g.index.map(str)

    return grades_dfs, grades_names


def group_label(df):
    group_df = df.filter(regex=MF.group)
    if group_df.shape[1] >= 1:
        if group_df.shape[1] > 1:
            print(f"Warning: too many columns match the group regex (MF.group):", group_df.columns)
        return group_df.columns[0]
    return None


def copy_file(file, dest):
    # extract folder and name if dest is not a folder
    old_name = None
    folder = dest
    if "." in dest.rsplit(os.sep)[-1]:
        old_name = file.rsplit(os.sep)[-1]
        folder = dest.rsplit(os.sep, 1)[0]
        if not folder:
            folder = "./"

    # copy file
    if not os.path.exists(folder):
        os.makedirs(folder)
    shutil.copy(file, folder)

    # rename it if necessary
    if old_name:
        shutil.move(os.path.join(folder, old_name), dest)


def copy_file_with_front_page(file, dfile, name=None, mat=None, latex_front_page=None):
    # add front page if any
    if latex_front_page:
        f = file.rsplit(os.sep)[-1]
        f_page = None
        try:
            f_page = create_front_page(latex_front_page, name, mat)
            doc = pymupdf.Document(f_page)
            copy = pymupdf.Document(file)
            try:
                doc.insert_pdf(copy)
            except Exception:
                # clean the pdf, and retry
                copy.save("tmp/" + f, garbage=4, deflate=True)
                doc = pymupdf.Document(f_page)
                copy = pymupdf.Document("tmp/" + f)
                doc.insert_pdf(copy)
            doc.save(dfile, garbage=4, deflate=True)
            print("Imported file %s for %s" % (f, name))
        except Exception as e:
            traceback.print_exception(type(e), e, e.__traceback__)
            print(
                Fore.RED + "Error when creating new pdf for %s" % file + Style.RESET_ALL
            )
            if f_page:
                copy_file(f_page, dfile)
            return False
    else:
        # copy file
        copy_file(file, dfile)
    return True


def get_name(mat, grades_dfs):
    for i, g in enumerate(grades_dfs):
        if mat in g.index:
            return i, g.at[mat, MF.name]
    return -1, None


def copy_files_for_moodle(paths, mpath=None, grades_csv=[]):
    grades_dfs, grades_names = load_csv(grades_csv)
    moodle_folders = os.listdir(mpath) if not grades_csv else None
    n = 0
    gpaths = ["%s/" % n for n in grades_names] if len(grades_csv) > 1 else [""]
    print("Copy files for moodle structure")
    for path in paths:
        for root, dirs, files in os.walk(path):
            for f in files:
                file = os.path.join(root, f)
                if os.path.isfile(file) and f.endswith(".pdf") and not f.startswith("."):
                    try:
                        # search matricule
                        m = re.search(re_mat, f)
                        if not m:
                            print("Matricule wasn't found in " + f)
                            if not os.path.exists(mpath):
                                os.makedirs(mpath)
                            shutil.copy(str(file), str(mpath))
                            continue
                        mat = m.group()
                    except IndexError:
                        continue
                    except StopIteration as e:
                        print("Matricule wasn't found in " + f)
                        continue
                    # find moodle folder
                    # rebuild moodle folder name: "Nom complet_Identifiant_Matricule_assignsubmission_file_"
                    folder = None
                    if grades_dfs:
                        for i, g in enumerate(grades_dfs):
                            if mat in g.index:
                                participant = str(g.at[mat, MF.id])
                                m = re.search("\\d+", participant)
                                if not m:
                                    print(
                                        "Moodle participant id not found in "
                                        + participant
                                    )
                                    continue
                                m_id = m.group()
                                folder = "%s%s_%s_%s_assignsubmission_file_" % (
                                    gpaths[i],
                                    g.at[mat, MF.name],
                                    m_id,
                                    mat,
                                )
                                break
                        if folder is None:
                            print(
                                "Matricule %s was not found in %s"
                                % (mat, ", ".join(grades_csv))
                            )
                            continue
                    else:
                        folder = next(fd for fd in moodle_folders if mat in fd)
                    # copy file
                    folder = os.path.join(mpath, folder)
                    folder_files = glob.glob(folder + "/*")
                    for f2 in folder_files:
                        os.remove(f2)
                    copy_file(file, os.path.join(mpath, folder))
                    n += 1
    print("%d files has been copied" % n)
    return grades_names if len(grades_names) > 1 else []


def import_files(dpaths, opath, suffix=None, latex_front_page=None):
    if len(dpaths) != 1:
        raise ValueError("The paths list must contain only one file:", dpaths)
    dpath = dpaths[0]

    if not os.path.exists(dpath):
        os.mkdir(dpath)
    folders = os.listdir(opath)
    n = 0
    for f in folders:
        afolder = os.path.join(opath, f)
        if os.path.isfile(afolder):
            continue

        files = os.listdir(afolder)
        if len(files) != 1:
            raise ValueError(
                "Subfolder %s does not contain only one file, but %d files"
                % (f, len(files))
            )
        file = files[0]

        # rename it
        # use folder name: "Nom complet_Identifiant_Matricule_assignsubmission_file_"
        _split = f.split("_")
        name = "_".join(_split[0].split(" "))
        # extract matricule
        mat = _split[2]
        name = name + "_%s_" % mat
        if suffix:
            name = name + suffix + ".pdf"
        else:
            name = name + file

        file = os.path.join(afolder, files[0])  # origin file
        dfile = os.path.join(dpath, name)  # destination file
        if copy_file_with_front_page(
            file, dfile, name=_split[0], mat=mat, latex_front_page=latex_front_page
        ):
            n += 1
    print("%d files has been copied to %s" % (n, dpath))


def import_files_with_csv(
    dpaths, matricule_csv, grades_csv, suffix=None, latex_front_page=None
):
    if len(dpaths) != 1:
        raise ValueError("The paths list must contain only one file:", dpaths)
    dpath = dpaths[0]

    grades_dfs, grades_names = load_csv(grades_csv)
    matricule_df = pd.read_csv(matricule_csv, dtype={1: "str"})

    # check matricules validity
    matricules = set()
    for idx, row in matricule_df.iterrows():
        m = row[MF.mat]
        if pd.isna(m):
            continue
        if m in matricules:
            raise ValueError("Matricule %s exists more than once" % m)
        matricules.add(m)
        i, n = get_name(m, grades_dfs)
        if i < 0:
            raise ValueError("Matricule %s is not found in any csv file" % m)

    # copy files
    if not os.path.exists(dpath):
        os.mkdir(dpath)
    for gn in grades_names:
        p = os.path.join(dpath, gn)
        if not os.path.exists(p):
            os.mkdir(p)
    n = 0
    for idx, row in matricule_df.iterrows():
        m = row[MF.mat]
        if pd.isna(m):
            continue

        file = row["File"]
        # rename it
        # use folder name: "Nom complet_Matricule_suffix"
        i, name = get_name(m, grades_dfs)
        fname = name + "_%s_" % m
        if suffix:
            fname = fname + suffix + ".pdf"
        else:
            fname = fname + file

        p = os.path.join(dpath, grades_names[i])  # destination folder
        dfile = os.path.join(p, fname)  # destination file
        if copy_file_with_front_page(
            file, dfile, name=name, mat=m, latex_front_page=latex_front_page
        ):
            n += 1
    print("%d files has been copied to %s" % (n, dpath))


def zipdirbatch(path, archive="moodle", batch=None):
    # ziph is zipfile handle
    i = 0
    j = 0
    zip_file_name = archive + ".zip"
    zip_file_names = [zip_file_name]
    ziph = zipfile.ZipFile(zip_file_name, "w", zipfile.ZIP_DEFLATED)
    asize = 0  # archive size
    print(f"batch size {batch}")
    print("Compress", path)
    print("Compressing ", end="", flush=True)
    for root, dirs, files in os.walk(path):
        for file in files:
            i = i + 1
            pfile = os.path.join(root, file)
            ziph.write(pfile, os.path.relpath(pfile, path))  # add the file to the zip
            mbs = os.path.getsize(pfile) / MB  # file size in Mb
            asize += mbs
            if batch and asize >= batch:
                print("\nArchive %s created." % zip_file_name)
                j = j + 1
                zip_file_name = "%s%d.zip" % (archive, j)
                zip_file_names.append(zip_file_name)
                ziph = zipfile.ZipFile(zip_file_name, "w", zipfile.ZIP_DEFLATED)
                asize = 0
                print("Compressing ", end="", flush=True)
            else:
                print(".", end="" if i % 65 else "\nCompressing ", flush=True)
            os.remove(str(os.path.join(root, file)))
    if i:
        print("\nArchive %s created and contains %d files" % (zip_file_name, i))
    else:
        print("\nNo file to compress for %s" % zip_file_name)

    if len(ziph.namelist()) == 0:
        print(ziph.namelist())
        os.remove(ziph.filename)
        zip_file_names.pop()

    return zip_file_names


def create_front_page(
    latex_file, name, matricule, latex_input_file=None, tmp_dir="tmp/"
):
    # define default input file
    if latex_input_file is None:
        latex_input_file = os.path.join(tmp_dir, Latex.input_file)
    # remove ascents
    no_accent_name = unidecode.unidecode(name)
    # write the input file
    input_data = Latex.input_content % (no_accent_name, matricule)
    with open(latex_input_file, "w") as f:
        f.write(input_data)

    # compile latex file
    return create_tex_pdf(latex_file, tmp_dir)


def create_tex_pdf(latex_file, tmp_dir="tmp/"):
    tmp_dir = os.path.abspath(tmp_dir)
    if not os.path.exists(tmp_dir):
        os.makedirs(tmp_dir)

    # compile latex file
    current = os.getcwd()
    os.chdir(tmp_dir)
    flog = "stdout.log"
    with open(flog, "w") as fstdout:
        try:
            print(latex_file)
            subprocess.check_call([Latex.cmd, latex_file], stdout=fstdout, timeout=1)
        except subprocess.TimeoutExpired:
            with open(flog) as f:
                print(f.read())
            raise ChildProcessError("Subprocess latex time out after 1 second.")
    os.chdir(current)

    # return path to pdf
    fname = os.path.basename(latex_file)
    fpdf = fname.rsplit(".", 1)[0] + ".pdf"
    return os.path.join(tmp_dir, fpdf)
