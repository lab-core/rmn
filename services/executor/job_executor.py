import os
import re
import shutil
import json
import pandas as pd
import uuid
import time
import datetime as dt
import numpy as np, cv2
from pdf2image import convert_from_path
from PIL import Image
from pathlib import Path
import copy

from python.process_copy.parser import parse_run_args, grade_box, matricule_box
from python.process_copy.recognize import get_date, write_box_contours, imwrite_png
from python.process_copy.config import MoodleFields as MF
from python.process_copy.mcc import group_label, zipdirbatch
from python.process_copy.database import Database
from python.process_copy.add_grades import process_writing
from utils.stats import create_all_boxplots, create_stats_latex, remove_non_pdfs
from utils.merge import process_merge
from utils.utils import Job_Status, Document_Status
from utils.storage import Storage
from utils.stop_handler import StopHandler
from utils.clients import redis_client, socketio_client, update_status
from zipfile import ZipFile
from utils.split import insert_copies


ROOT_DIR = Path(__file__).resolve().parent
MAX_RETRY = int(os.getenv("MAX_RETRY", "5"))
MAX_IDLE_TIME = 120
BATCH_SIZE = 500


# override print
old_print = print
def timestamped_print(*args, **kwargs):
  old_print(dt.datetime.now(), *args, **kwargs)
print = timestamped_print


def save_number_images(storage, job_id, document_index, questions):
    try:
        numbers = [n for n in questions.values()]

        for index, number in enumerate(numbers):
            number = float(number)
            if number.is_integer() and 0 <= int(number) <= 9:
                try:
                    unverified_filename = os.path.join("unverified_numbers", job_id, str(document_index),f"{index}.png")
                    new_filename = os.path.join("numbers", str(int(number)), f"{uuid.uuid4()}.png")
                    storage.move_to(storage.abs_path(unverified_filename), new_filename)
                except Exception as e:
                    print(e)
    except Exception as e:
        print(e)


def check_for_idle_jobs_to_requeue(db, sleep):
    alive_times = {}
    collection_check = db.get_collection("check")
    try:
        if collection_check.count_documents({}) == 0:
            collection_check.insert_one({'locked': True})
            locked = True
        else:
            res = collection_check.update_one({'locked': False}, {'$set': {'locked': True}})
            locked = res.matched_count > 0

        if locked:
            while True:
                print("Check idle running jobs")
                # search idle jobs
                max_alive = dt.datetime.now(dt.UTC) - dt.timedelta(seconds=MAX_IDLE_TIME)
                jobs = db.eval_jobs_collection().find({
                    "job_status": Job_Status.RUN.value,
                    "alive_time": {"$lt": max_alive}
                })

                job = db.eval_jobs_collection().find_one({
                    "job_status": Job_Status.IGNORED.value,
                })
                if job:
                    # Set Job status from IGNORED to VALIDATION
                    job_id = job["job_id"]
                    user_id = job["user_id"]

                    update_status(db, sio, user_id, job_id, Job_Status.VALIDATION)

                # requeue old idle jobs
                old_idle_jobs = False
                for j in jobs:
                    def requeue(c_status, n_status):
                        print("Resubmit job", j["job_id"])
                        # change status to ensure that a job is not resubmitted several times
                        res = db.eval_jobs_collection().update_one(
                            {"job_id": j["job_id"], "job_status": c_status},
                            {"$inc": {"retry": 1}, "$set": {"job_status": n_status}}
                        )
                        if res.matched_count > 0:
                            redis.lpush("job_queue", json.dumps({"job_id": j["job_id"]}))

                    if j["job_status"] == Job_Status.RUN.value:
                        requeue(Job_Status.RUN.value, Job_Status.QUEUED.value)
                    else:
                        requeue(Job_Status.FINALIZING.value, Job_Status.VALIDATION.value)

                    old_idle_jobs = True

                # continue if idle jobs
                if old_idle_jobs:
                    break

                # check if all running jobs are idle. If yes, sleep, otherwise break
                print("Check alive running jobs")

                jobs = db.eval_jobs_collection().find({
                    "job_status": Job_Status.RUN.value
                })
                all_jobs_idle = False
                for j in jobs:
                    job_id = j["job_id"]
                    alive_t = alive_times.get(job_id, dt.datetime.now(dt.UTC))
                    # check if alive_time has increased, and thus job is alived
                    j["alive_time"] = j["alive_time"].replace(tzinfo=dt.UTC)
                    if j["alive_time"] > alive_t:
                        all_jobs_idle = False
                        break
                    all_jobs_idle = True
                    alive_times[job_id] = j["alive_time"]
                # if one job alive -> stop
                if not all_jobs_idle or not sleep:
                    print("All jobs are not idle.")
                    break
                # otherwise, sleep
                print("Sleep before checking again running jobs.")
                time.sleep(5)
    finally:
        collection_check.update_one({'locked': True}, {'$set': {'locked': False}})


if __name__ == "__main__":
    # Connect to Mongo
    print("Setting up MongoClient...")
    db = Database()

    # create redis connection
    redis = redis_client()

    # create storage connection (local or NFS)
    storage = Storage()

    # create socketio connection
    sio = socketio_client()

    def process_template(temp_id, WORK_TMP_DIR):
        template = db.get_collection("template").find_one({"template_id": temp_id})
        if not template:
            raise KeyError(f"Template {temp_id} not found in mongodb.")

        template_file = str(WORK_TMP_DIR.joinpath(template["template_file_id"]))
        storage.copy_from(template["template_file_id"], template_file)
        if template_file.endswith(".pdf"):
            img = convert_from_path(template_file, dpi=100)[0]
        else:
            img = Image.open(template_file)

        def draw_boxes_on_template(box, np_img, mat):
            box = tuple([round(x, 2) for x in box])
            np_img2 = np.copy(np_img)
            b, r = write_box_contours(np_img2, box, matricule=mat)
            if not r and mat:
                np_img2 = np.copy(np_img)
                write_box_contours(np_img2, box, matricule=mat, biggest_child=True)
            return np_img2, b

        # fetch the user-defined boxes
        np_img = np.array(img)
        matricule_box = template.get("matricule_box", None)
        if matricule_box:
            np_img, _ = draw_boxes_on_template(matricule_box, np_img, True)

        # number of grade boxes found
        n_questions = 0
        grade_box = template.get("grade_box", None)
        if grade_box:
            np_img, n_questions = draw_boxes_on_template(grade_box, np_img, False)

        tmp_img = str(WORK_TMP_DIR.joinpath("rendered.png"))
        cv2.imwrite(tmp_img, np_img)

        # For a png
        rendered_path = template["template_file_id"].rsplit(".", 1)[0] + "-rendered.png"
        storage.move_to(tmp_img, rendered_path)

        # # For a pdf
        # rendered_path = template["template_file_id"].rsplit(".", 1)[0] + "-rendered.pdf"
        # tmp_rendered = str(WORK_TMP_DIR.joinpath(rendered_path))
        # with open(tmp_rendered, "wb") as f:
        #     layout = img2pdf.get_fixed_dpi_layout_fun((100, 100))
        #     f.write(img2pdf.convert(tmp_img, layout_fun=layout))
        # storage.move_to(tmp_rendered, rendered_path)

        try:
            # update doc
            db.get_collection("template").update_one(
                {"template_id": temp_id},
                {"$set": {
                    "template_rendered_file_id": rendered_path,
                    "n_questions": n_questions - 1
                }
            })
        except Exception as e:
            print(f"An error occurred: {e}")
            raise

        sio.emit(
            "template_rendered",
            json.dumps(
                {
                    "user_id": template["user_id"],
                    "template_id": temp_id,
                    "n_questions": n_questions - 1
                }
            ),
        )

    def process(p_job, TMP_DIR):
        job_id = p_job["job_id"]
        job = db.eval_jobs_collection().find_one({"job_id": job_id})
        if not job:
            raise KeyError(f"Job {job_id} not found in mongodb.")
        user_id = job["user_id"]

        MOODLE_FOLDER = TMP_DIR.joinpath("moodle")
        OUTPUT_FOLDER = TMP_DIR.joinpath("output")
        EXTRACT_FOLDER = TMP_DIR.joinpath("extract")
        VALIDATE_FOLDER = TMP_DIR.joinpath("validate")
        TEX_FOLDER = TMP_DIR.joinpath("tex")

        stopH = StopHandler(db.eval_jobs_collection(), job_id)

        if job["job_status"] == Job_Status.VALIDATED.value or job["job_status"] == Job_Status.FINALIZING.value:
            # Set Job status to FINALIZING
            if job["job_status"] != Job_Status.FINALIZING.value:
                update_status(db, sio, user_id, job_id, Job_Status.FINALIZING)

            if os.path.exists(storage.abs_path(os.path.join("documents", job_id))):
                # adding grades
                print("Adding grades...")
                process_writing(job_id, TMP_DIR)

                # merging copies
                print("Merging copies...")
                corrected_copies = process_merge(job_id)

                # # cleaning storage
                # print("Cleaning storage...")
                # storage.clean_storage(job_id)
            else:
                print("Merging already performed")
                corrected_copies = os.path.join(storage.abs_path('corrected_copies'), job_id)

            #
            user = db.users_collection().find_one({"username": user_id})
            save_verified_images = user["saveVerifiedImages"]
            moodle_ind = bool(int(user["moodleStructureInd"]))

            #
            output = db.jobs_output_collection().find_one({"job_id": job_id})
            notes_csv_file_id = output["notes_csv_file_id"]

            # Save file to local
            csv_file_path = str(VALIDATE_FOLDER.joinpath('notes.csv'))
            storage.copy_from(notes_csv_file_id, csv_file_path)
            print("notes.csv file created")

            # read csv file for grades
            df = pd.read_csv(csv_file_path, index_col=MF.mat, dtype={MF.mat: str})

            # check if group or gr column is present
            l_group = group_label(df)

            # fetch questions information
            eval_job = db.eval_jobs_collection().find_one({"job_id": job_id})
            n_max_points_per_question = eval_job["n_max_points_per_question"]
            statistics_for_students = eval_job["statistics_for_students"]
            # print("statistics_for_students", statistics_for_students)
            n_questions = len(n_max_points_per_question)
            n_max_points_per_question = [q[1] for q in sorted(n_max_points_per_question)]
            question_bonus = [q[1] for q in sorted(eval_job["bonus_enabled_map"])]
            question_totals = copy.copy(n_max_points_per_question)
            question_totals.append(sum(s for i, s in enumerate(n_max_points_per_question) if not question_bonus[i]))


            # store grades
            docs = db.documents_collection().find({"job_id": job_id})
            date = get_date()
            grades_dict = {}
            for doc in docs:
                if doc['status'] == Document_Status.DELETED.value:
                    continue
                mat = str(doc["matricule"])
                # print("mat", mat)
                if mat in df.index.values:
                    grades = doc["grades"]
                    if grades:
                        grades_dict[doc["filename"]] = grades
                        for i, g in enumerate(grades):
                            df.loc[mat, f"Q{i+1}"] = g
                        total_score = sum(grades)
                        # print("TOTAL SCORE FOR ", doc["filename"], ":", total_score)
                        df.loc[mat, MF.grade] = total_score
                        df.loc[mat, MF.mdate] = date

            # save grades
            df.to_csv(csv_file_path, mode="w+")

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
            all_grades = [[] for _ in range(n_questions)]
            for filename, grades in grades_dict.items():
                filenames.append(filename)
                for i in range(n_questions):
                    all_grades[i].append(grades[i])
            all_grades = np.array(all_grades)
            f_boxplots = create_all_boxplots(all_grades, str(TMP_DIR))
            TEX_FOLDER.mkdir(exist_ok=True)

            # create folders for all copies zips
            all_copies_folder_path = VALIDATE_FOLDER.joinpath("all")
            all_copies_folder_path.mkdir(exist_ok=True)
            moodle_folder_path = VALIDATE_FOLDER.joinpath("moodle")
            moodle_folder_path.mkdir(exist_ok=True)

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

                    # find nom and prenom associated to this file
                    try:
                        nom, prenom = nom_complet.split()
                    except Exception as e:
                        # print(nom_complet)
                        # print(e)
                        nom = nom_complet
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
                            folder_name = f"{nom_complet}_{identifiant}_{matricule}_assignsubmission_file_"
                            m_folder = moodle_folder_path.joinpath(folder_name)
                            m_folder.mkdir(exist_ok=True)
                            m_dest = m_folder.joinpath(f"{nom}_{prenom}_{matricule}.pdf")

                            # transfer file to folder
                            shutil.copy(str(file), str(m_dest))

                            # adding stats file
                            filename = os.path.basename(file).rsplit(".", 1)[0]
                            if statistics_for_students:
                                try:
                                    file_index = filenames.index(filename)
                                    fpdf = create_stats_latex(nom_complet, file_index, n_questions,
                                                              all_grades, question_totals, f_boxplots, TMP_DIR=TEX_FOLDER)
                                    # print("Stats for", nom_complet, "created:", fpdf)
                                    shutil.move(fpdf, m_folder.joinpath(f"{nom}_{prenom}_{matricule}_notes.pdf"))
                                except ValueError:
                                    # file not found
                                    print(f"File {filename} does not correspond to a valid document.")
                                    pass

                    # store copy in all copies folder
                    copies_path = all_copies_folder_path
                    if l_group:
                        group = df.at[matricule, l_group]
                        copies_path = copies_path.joinpath(str(group))
                        copies_path.mkdir(exist_ok=True)
                    dest = copies_path.joinpath(f"{nom}_{prenom}_{matricule}.pdf")
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
                        moodle_zip_file_id = os.path.normpath(f"output_zip{os.sep}{job_id}_{i+1}.zip")
                        storage.move_to(zip_file, moodle_zip_file_id)
                        zip_id_list.append(moodle_zip_file_id)
                except Exception as e:
                    print(e)

            # adding stats for professors
            fpdf = create_stats_latex('Statistiques', None, n_questions, all_grades, question_totals,
                                      f_boxplots, TMP_DIR=TEX_FOLDER)
            print("General stats created:", fpdf)
            stats_file_id = os.path.normpath(f"output_stats{os.sep}{job_id}.pdf")
            storage.move_to(fpdf, stats_file_id)

            if stopH.stop():
                print("Job has been deleted.")
                return

            try:
                #
                n_csv = os.path.normpath(f"output_csv{os.sep}{job_id}.csv")
                storage.move_to(csv_file_path, n_csv)

                #
                db.jobs_output_collection().update_one(
                    {"job_id": job_id},
                    {"$set": {
                        "notes_csv_file_id": notes_csv_file_id,
                        "stats_file_id": stats_file_id,
                        "zip_id_list": zip_id_list
                    }})

                #
                update_status(db, sio, user_id, job_id, Job_Status.ARCHIVED, db_infos={"notes_file_id": notes_csv_file_id})

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

            # delete preview image
            # print("Clean documents and unverified_numbers")
            # docs = db.documents_collection().find({"job_id": job_id})
            # for doc in docs:
            #     # delete unverified numbers for job
            #     document_index = doc["document_index"] - 1
            #     for image_index in range(len(doc["grades"].keys())):
            #         try:
            #             storage.remove(os.path.normpath(
            #                 f"unverified_numbers{os.sep}{job_id}{os.sep}{document_index}{os.sep}{image_index}.png"))
            #         except:
            #             continue

            try:
                storage.remove_tree(os.path.normpath(f"documents{os.sep}{job_id}"))
                storage.remove_tree(os.path.normpath(f"corrected_copies{os.sep}{job_id}"))
            except:
                pass

            db.questions_collection().delete_many({"job_id": job_id})
            db.documents_collection().delete_many({"job_id": job_id})

        elif job["job_status"] == Job_Status.QUEUED.value or job["job_status"] == Job_Status.IGNORED.value:
            # make directories
            MOODLE_FOLDER.mkdir(exist_ok=True)
            OUTPUT_FOLDER.mkdir(exist_ok=True)
            EXTRACT_FOLDER.mkdir(exist_ok=True)

            # Query job params
            print("Querying job details from Database...")
            job_params = db.eval_jobs_collection().find_one({"job_id": job_id})

            if job_params is None:
                print("No params found!")
                return

            print(job_params)
            db.eval_jobs_collection().update_one(
                {"job_id": job_id},
                {
                    "$set": {
                        "job_status": Job_Status.RUN.value,
                        "alive_time": dt.datetime.now(dt.UTC)
                    }
                }
            )

            # Save notes.csv file to local
            storage.copy_from(job_params["notes_file_id"], str(OUTPUT_FOLDER.joinpath("notes.csv")))
            # Save zip file to local
            storage.copy_from(job_params["zip_file_id"], str(OUTPUT_FOLDER.joinpath("content.zip")))

            with ZipFile(str(OUTPUT_FOLDER.joinpath("content.zip")), 'r') as zip_ref:
                zip_ref.extractall(EXTRACT_FOLDER)

            # fetch the user-defined boxes
            box_grade_list, box_matricule_list, regular_box_matricule_list = \
                db.get_templates_info(job_params["front_template_id"],
                                      job_params["regular_template_id"])
            if regular_box_matricule_list is not None:
                matricule_box['exam']['regular'] = tuple([round(x, 2) for x in regular_box_matricule_list])
            if box_matricule_list is not None:
                matricule_box['exam']['front'] = tuple([round(x, 2) for x in box_matricule_list])
            if box_grade_list is not None:
                grade_box['exam']['grade'] = tuple([round(x, 2) for x in box_grade_list])

            args = [
                str(EXTRACT_FOLDER),
                "-m",
                str(MOODLE_FOLDER),
                "-f",
                "exam",
                "--grades",
                str(OUTPUT_FOLDER.joinpath("notes.csv")),
                "--job_id",
                job_id,
                "--user_id",
                user_id,
            ]
            print("Running module with:", args)
            # process_copy
            try:
                parse_run_args(args)
            except Exception as e:
                print("Error in process-copy:", e)

                if stopH.stop():
                    print("Job has been deleted.")
                    # storage.remove(os.path.normpath(f"csv{os.sep}{job_id}.csv"))
                    # storage.remove(os.path.normpath(f"zips{os.sep}{job_id}.zip"))
                    return

                # check if should retry
                retry = job_params.get("retry", 0)
                db.eval_jobs_collection().update_one(
                    {"job_id": job_id},
                    {"$set": {"job_infos": str(e)} })
                if retry < MAX_RETRY:
                    raise e

                # Error handling
                update_status(db, sio, user_id, job_id, Job_Status.ERROR, infos={"job_infos": str(e)})
                return

            print("Module Done")

            # Save csv files in storage
            notes_csv_file_id = os.path.normpath(f"output_csv{os.sep}{job_id}.csv")
            storage.move_to(os.path.join(OUTPUT_FOLDER, "notes.csv"), notes_csv_file_id)

            # finalize job
            db.jobs_output_collection().insert_one(
                {
                    "job_id": job_id,
                    "user_id": user_id,
                    "notes_csv_file_id": notes_csv_file_id,
                    "preview_file_id": "None",
                    "zip_id_list": [],
                }
            )

            # Set Job status to VALIDATION
            update_status(db, sio, user_id, job_id, Job_Status.VALIDATION, sio_infos={"job_infos": "Validation matricule prête"})

        elif job["job_status"] == Job_Status.SPLIT.value or job["job_status"] == Job_Status.CORRECTED.value:
            job_params = db.eval_jobs_collection().find_one({"job_id": job_id})
            n_pages_per_question = {key: value for key, value in job_params["n_pages_per_question"]}

            try:
                insert_copies('zips', job_id, n_pages_per_question, TMP_DIR)
                print("Copies inserted in database")

                # Set Job status to QUEUED as no error have been raised. Process can continue
                update_status(db, sio, user_id, job_id, Job_Status.QUEUED)

                # push the job to the queue to be continued
                redis.rpush("job_queue", json.dumps({"job_id": job_id}))
            except ValueError as e:
                error_messages = str(e)
                print(e)
                # Set Job status to RETRY
                update_status(db, sio, user_id, job_id, Job_Status.RETRY, infos={"job_infos": error_messages})

            except Exception as e:
                print(e)
                # Set Job status to ERROR
                update_status(db, sio, user_id, job_id, Job_Status.ERROR, infos={"job_infos": str(e)})

        else:
            print("Job status "+job["job_status"]+" not handled.")

    try:
        # retrieve job
        blocking = os.getenv("REDIS_POP") == "block" or os.getenv("ENVIRONMENT") != "production"
        while True:
            print("Retrieving job from redis")
            if blocking:
                job = redis.blpop("job_queue", timeout=MAX_IDLE_TIME)
                # output of blocking is a tuple (job_queue, job)
                if job:
                    job = job[1]
            else:
                job = redis.lpop("job_queue")

            # process job if any
            if job:
                print("Job:", job)
                # check if job if of form (job_queue, job)
                if type(job) is tuple:
                    job = job[1]
                job = json.loads(job)

                # create tmp work dir
                jid = job["template_id"] if "template_id" in job else job["job_id"]
                WORK_TMP_DIR = ROOT_DIR.joinpath(f"tmp_{jid}")
                WORK_TMP_DIR.mkdir(exist_ok=True)

                # process job
                try:
                    if "template_id" in job:
                        process_template(jid, WORK_TMP_DIR)
                    else:
                        process(job, WORK_TMP_DIR)
                except Exception as e:
                    print("Caught an error while processing job:")
                    print(e)
                    pass

                # clean ENLEVER
                shutil.rmtree(WORK_TMP_DIR)

            # check if any job is idle and dangling
            check_for_idle_jobs_to_requeue(db, not blocking)

            if not blocking:
                break

    except Exception as e:
        print(e)
    finally:
        db.close()
        sio.disconnect()
    print("Job end.")
