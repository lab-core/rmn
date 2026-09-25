"""Everything a validated job produces: grades, statistics, the Moodle zip."""

import os
import re
import shutil
import numpy as np
import pandas as pd
from python.process_copy.add_grades import process_writing
from python.process_copy.mcc import group_label, zipdirbatch
from python.process_copy.recognize import get_date
from rmn_common.moodle import MoodleFields as MF
from rmn_common.paths import ensure_within, safe_path_component
from rmn_common.questions import ignored_positions, question_sort_key
from rmn_common.spreadsheet import defuse_csv
from rmn_common.status import Document_Status, Job_Status
from runtime import BATCH_SIZE, timestamped_print
from tasks.cleanup import cleanup_deleted_job
from utils.clients import update_status
from utils.merge import process_merge
from utils.stats import create_all_boxplots, create_stats_latex



# the executor timestamps every line it prints (see runtime.timestamped_print)
print = timestamped_print




def finalize_job(db, storage, sio, job, TMP_DIR, stopH):
    job_id = job["job_id"]
    user_id = job["user_id"]

    # create temp folders
    VALIDATE_FOLDER = TMP_DIR.joinpath("validate")
    TEX_FOLDER = TMP_DIR.joinpath("tex")
    VALIDATE_FOLDER.mkdir(exist_ok=True)
    TEX_FOLDER.mkdir(exist_ok=True)

    # Set Job status to FINALIZING
    if job["job_status"] != Job_Status.FINALIZING.value:
        update_status(db, sio, user_id, job_id, Job_Status.FINALIZING)

    correcting = len(job["n_max_points_per_question"]) > 0

    if not correcting:
        # copy the original files
        input_folder = storage.abs_path(os.path.join('documents', job_id, "all"))
        corrected_copies = storage.abs_path(os.path.join('corrected_copies', job_id))
        os.makedirs(corrected_copies, exist_ok=True)
        print("Copying original files to corrected_copies ...")
        # the folder does not exist when the job was created without any copy
        if os.path.exists(input_folder):
            shutil.copytree(input_folder, corrected_copies, dirs_exist_ok=True)
    elif os.path.exists(storage.abs_path(os.path.join("documents", job_id))):
        # adding grades
        print("Adding grades...")
        process_writing(job, TMP_DIR)

        # merging copies
        print("Merging copies...")
        corrected_copies = process_merge(job)

        # # cleaning storage
        # print("Cleaning storage...")
        # storage.clean_storage(job_id)
    else:
        print("Merging already performed")
        corrected_copies = os.path.join(storage.abs_path('corrected_copies'), job_id)

    #
    # a deleted user keeps the defaults; a job without output cannot finalize
    user = db.users_collection().find_one({"username": user_id}) or {}
    save_verified_images = bool(user.get("saveVerifiedImages", False))
    moodle_ind = bool(int(user.get("moodleStructureInd", True)))

    #
    output = db.jobs_output_collection().find_one({"job_id": job_id})
    if output is None or not output.get("notes_csv_file_id"):
        raise LookupError(f"no output csv recorded for job {job_id}")
    notes_csv_file_id = output["notes_csv_file_id"]

    # Save file to local
    csv_file_path = str(VALIDATE_FOLDER.joinpath('notes.csv'))
    storage.copy_from(notes_csv_file_id, csv_file_path)
    print("notes.csv file created")

    # read csv file for grades
    df = pd.read_csv(csv_file_path, index_col=MF.mat, dtype={MF.mat: str})

    # check if group or gr column is present
    l_group = group_label(df)

    # initialize grade to 0 by default
    df[MF.grade] = df[MF.grade].fillna(0)
    date = get_date()
    df[MF.mdate] = df[MF.mdate].apply(lambda x: x if pd.notna(x) and x != '-' else date)

    # fetch questions information
    eval_job = db.eval_jobs_collection().find_one({"job_id": job_id})
    n_max_points_per_question = eval_job["n_max_points_per_question"]
    statistics_for_students = eval_job["statistics_for_students"]
    # print("statistics_for_students", statistics_for_students)
    # the template defines n_template_questions boxes; the ignored ones
    # (0 page) are skipped everywhere below except in the positions of the
    # grades, which always match the boxes
    n_template_questions = len(n_max_points_per_question)
    ignored = ignored_positions(eval_job["n_pages_per_question"])
    active = [i for i in range(n_template_questions) if i not in ignored]
    question_names = [f"Q{i + 1}" for i in active]
    n_questions = len(active)
    # sort by the numeric question index ("Q2" before "Q10"); a plain sort
    # is lexicographic and mismaps points/bonus once there are >= 10 questions
    n_max_points_per_question = [q[1] for q in sorted(n_max_points_per_question, key=question_sort_key)]
    question_bonus = [q[1] for q in sorted(eval_job["bonus_enabled_map"], key=question_sort_key)]
    question_totals = [n_max_points_per_question[i] for i in active]
    question_totals.append(sum(n_max_points_per_question[i] for i in active if not question_bonus[i]))

    def active_grades(grades):
        """Grades of the non-ignored questions, in order, a missing one as 0."""
        grades = list(grades) + [None] * (n_template_questions - len(grades))
        return [grades[i] if grades[i] is not None else 0 for i in active]

    # store grades
    docs = db.documents_collection().find({"job_id": job_id})
    grades_dict = {}
    for doc in docs:
        if doc['status'] == Document_Status.DELETED.value:
            continue
        mat = str(doc["matricule"])
        # print("mat", mat)
        if mat in df.index.values:
            grades = doc["grades"]
            if grades:
                grades = active_grades(grades)
                grades_dict[doc["filename"]] = grades
                for name, g in zip(question_names, grades):
                    df.loc[mat, name] = g
                total_score = sum(grades)
                # print("TOTAL SCORE FOR ", doc["filename"], ":", total_score)
                df.loc[mat, MF.grade] = total_score
                df.loc[mat, MF.mdate] = date
                df.loc[mat, "index"] = doc["document_index"] + 1

    # save grades; the file is opened in a spreadsheet by the teacher, so a
    # roster value that reads as a formula is neutralised first
    df.to_csv(csv_file_path, mode="w+")
    defuse_csv(csv_file_path)

    # update all document status
    db.documents_collection().update_many(
        {"job_id": job_id},
        {
            "$set": {
                "status": Document_Status.VALIDATED.value,
            }
        },
    )

    # create box plots for statistics
    filenames = []
    if n_questions > 0:
        all_grades = [[] for _ in range(n_questions)]
        for filename, grades in grades_dict.items():
            filenames.append(filename)
            for i in range(n_questions):
                all_grades[i].append(grades[i])
        all_grades = np.array(all_grades)
        # made where pdflatex compiles the stats: it cannot read ../Q1.png
        TEX_FOLDER.mkdir(exist_ok=True)
        f_boxplots = create_all_boxplots(all_grades, str(TEX_FOLDER), question_names=question_names)
    else:
        all_grades = [[]]
        f_boxplots = []

    # create folders for all copies zips
    all_copies_folder_path = VALIDATE_FOLDER.joinpath("all")
    all_copies_folder_path.mkdir(exist_ok=True)
    moodle_folder_path = VALIDATE_FOLDER.joinpath("moodle")
    moodle_folder_path.mkdir(exist_ok=True)

    if stopH.stop():
        cleanup_deleted_job(db, storage, job_id)
        return

    # create zip files for all copies and moodle
    print("Preparing zip files ...")
    i = 0
    n_docs = len(grades_dict)
    for root, dirs, files in os.walk(str(corrected_copies)):
        for f in files:
            file = os.path.join(root, f)
            if not os.path.isfile(file) or not f.endswith(".pdf") or f.startswith("."):
                continue

            filename = str(f).rsplit('.', 1)[0]
            doc = db.documents_collection().find_one({"job_id": job_id, "filename": filename})
            if doc is None or doc['status'] == Document_Status.DELETED.value:
                continue

            # doc_idx = doc["document_index"]
            # start_time = time.time()
            # if save_verified_images:
            #     save_number_images(
            #         storage, job_id, doc_idx - 1, doc["grades"]
            #     )

            # find matricule associated to this file
            matricule = str(doc["matricule"])
            try:
                nom_complet = df.at[matricule, MF.name]
            except Exception as e:
                print(e)
                print("Matricule", matricule, "not found in csv.")
                continue

            # the csv cells become file and folder names below: strip
            # what would leave the job folder (separators, "..")
            safe_name = safe_path_component(nom_complet)
            safe_matricule = safe_path_component(matricule)

            # find nom and prenom associated to this file
            try:
                nom, prenom = safe_name.split()
            except Exception as e:
                nom = safe_name
                prenom = ""

            # store copy for moodle zip if necessary
            if moodle_ind:
                # create participant moodle folder
                identifiant = df.at[matricule, MF.id]
                m_id = re.search('\\d+', identifiant)
                if not m_id:
                    print("Moodle participant id not found in " + identifiant)
                else:
                    identifiant = m_id.group()
                    folder_name = f"{safe_name}_{identifiant}_{safe_matricule}_assignsubmission_file_"
                    m_folder = ensure_within(moodle_folder_path.joinpath(folder_name), moodle_folder_path)
                    m_folder.mkdir(exist_ok=True)
                    m_dest = m_folder.joinpath(f"{nom}_{prenom}_{safe_matricule}.pdf")

                    # transfer file to folder
                    shutil.copy(str(file), str(m_dest))

                    # adding stats file
                    filename = os.path.basename(file).rsplit(".", 1)[0]
                    if statistics_for_students:
                        try:
                            file_index = filenames.index(filename)
                            fpdf = create_stats_latex(nom_complet, file_index, n_questions,
                                                      all_grades, question_totals, f_boxplots, TMP_DIR=TEX_FOLDER,
                                                      question_names=question_names)
                            # print("Stats for", nom_complet, "created:", fpdf)
                            shutil.move(fpdf, m_folder.joinpath(f"{nom}_{prenom}_{safe_matricule}_notes.pdf"))
                        except ValueError:
                            # file not found
                            print(f"File {filename} does not correspond to a valid document.")
                        except Exception as e:
                            # the copy ships without its stats page rather
                            # than failing the whole job
                            print(f"Stats page for {filename} skipped: {e}")

            # store copy in all copies folder
            copies_path = all_copies_folder_path
            if l_group:
                group = df.at[matricule, l_group]
                copies_path = ensure_within(copies_path.joinpath(safe_path_component(group)),
                                            all_copies_folder_path)
                copies_path.mkdir(exist_ok=True)
            dest = copies_path.joinpath(f"{nom}_{prenom}_{safe_matricule}.pdf")
            shutil.move(str(file), str(dest))

            i += 1
            if i % 10 == 0:
                print(f"{i}/{n_docs} copies prepared")

    # create zip with all copies (gathered by group if enabled)
    shutil.make_archive(
        str(VALIDATE_FOLDER.joinpath("all")),
        "zip",
        str(all_copies_folder_path)
    )

    zip_file_id = os.path.normpath(f"output_zip{os.sep}{job_id}_all.zip")
    try:
        all_zip_name = str(VALIDATE_FOLDER.joinpath("all"))
        c_zip = f"{all_zip_name}.zip"
        storage.move_to(c_zip, zip_file_id)
    except Exception as e:
        print(e)

    # create moodle zip files
    zip_id_list = [zip_file_id]
    if moodle_ind:
        try:
            zip_file_ids = zipdirbatch(str(moodle_folder_path), str(moodle_folder_path), BATCH_SIZE)
            for i, zip_file in enumerate(zip_file_ids):
                moodle_zip_file_id = os.path.normpath(f"output_zip{os.sep}{job_id}_{i + 1}.zip")
                storage.move_to(zip_file, moodle_zip_file_id)
                zip_id_list.append(moodle_zip_file_id)
        except Exception as e:
            print(e)

    # adding stats for professors; as for a student's stats page, a failure
    # does not fail the job: the zips are already in storage by now, and
    # nothing needs the stats pdf but its own download, so the job completes
    # with its zips and csv, and the teacher is told the pdf is missing
    stats_file_id = os.path.normpath(f"output_stats{os.sep}{job_id}.pdf")
    stats_infos = None
    try:
        fpdf = create_stats_latex('Statistiques', None, n_questions, all_grades, question_totals,
                                  f_boxplots, TMP_DIR=TEX_FOLDER, question_names=question_names)
        print("General stats created:", fpdf)
        storage.move_to(fpdf, stats_file_id)
    except Exception as e:
        print(f"General stats skipped: {e}")
        # the pdf of an earlier finalization does not match these grades
        storage.remove(stats_file_id)
        stats_file_id = None
        stats_infos = {"job_infos": "Tâche terminée sans le pdf des statistiques générales, "
                                    f"qui n'a pas pu être créé : {e}"}

    if stopH.stop():
        cleanup_deleted_job(db, storage, job_id)
        return

    try:
        #
        n_csv = os.path.normpath(f"output_csv{os.sep}{job_id}.csv")
        storage.move_to(csv_file_path, n_csv)

        #
        outputs = {"$set": {
            "notes_csv_file_id": notes_csv_file_id,
            "zip_id_list": zip_id_list
        }}
        if stats_file_id:
            outputs["$set"]["stats_file_id"] = stats_file_id
        else:
            outputs["$unset"] = {"stats_file_id": ""}
        db.jobs_output_collection().update_one({"job_id": job_id}, outputs)

        #
        update_status(db, sio, user_id, job_id, Job_Status.ARCHIVED, infos=stats_infos,
                      db_infos={"notes_file_id": notes_csv_file_id})

    except Exception as e:
        print("Error while moving file to storage")
        db.eval_jobs_collection().update_one(
            {"job_id": job_id},
            {
                "$set": {
                    "job_status": Job_Status.ERROR.value,
                    "job_infos": str(e)
                }
            },
        )
