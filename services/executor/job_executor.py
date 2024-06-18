from pathlib import Path
from python.process_copy.parser import parse_run_args
from python.process_copy.recognize import get_date
from python.process_copy.config import MoodleFields as MF
from python.process_copy.mcc import group_label
from python.process_copy.database import Database
from utils.utils import Job_Status, Document_Status
from utils.storage import Storage
from utils.stop_handler import StopHandler
from utils.clients import redis_client, socketio_client
from zipfile import ZipFile
from utils.split_and_merge import insert_copies

import os
import re
import shutil
import json
import pandas as pd
import uuid
import time
from datetime import datetime, timedelta


ROOT_DIR = Path(__file__).resolve().parent
MAX_RETRY = int(os.getenv("MAX_RETRY", "5")) # 5
MAX_IDLE_TIME = 120 # 120

storage = Storage()


def save_number_images(job_id, document_index, questions):
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


if __name__ == "__main__":
    # Connect to Mongo
    print("Setting up MongoClient...")
    db = Database()

    # Create SocketIO connection
    sio = socketio_client()

    # create redis connection
    redis = redis_client()

    def process(p_job, TMP_DIR):
        job_id = p_job["job_id"]
        job = db.eval_jobs_collection().find_one({"job_id": job_id})
        if not job:
            raise KeyError(f"Job {job_id} not found in mongodb.")
        user_id = job["user_id"]

        MOODLE_ZIP = TMP_DIR.joinpath("moodle.zip")
        MOODLE_FOLDER = TMP_DIR.joinpath("moodle")
        OUTPUT_FOLDER = TMP_DIR.joinpath("output")
        EXTRACT_FOLDER = TMP_DIR.joinpath("extract")
        VALIDATE_FOLDER = TMP_DIR.joinpath("validate")

        stopH = StopHandler(db.eval_jobs_collection(), job_id)

        if job["job_status"] == Job_Status.VALIDATION.value:
            # Set Job status to VALIDATION
            db.eval_jobs_collection().update_one(
                {"job_id": job_id},
                {"$set": {"job_status": Job_Status.FINALIZING.value}}
            )

            #
            user = db.users_collection().find_one({"username": user_id})
            save_verified_images = user["saveVerifiedImages"]
            moodle_ind = bool(int(user["moodleStructureInd"]))

            #
            output = db.jobs_output_collection().find_one({"job_id": job_id})
            notes_csv_file_id = output["notes_csv_file_id"]
            moodle_zip_id_list = output["moodle_zip_id_list"]

            #
            VALIDATE_FOLDER.mkdir(exist_ok=True)
            tmp_copies_folder_path = VALIDATE_FOLDER.joinpath("copies")
            tmp_copies_folder_path.mkdir(exist_ok=True)
            validated_copies_folder_path = VALIDATE_FOLDER.joinpath(
                "validated_copies"
            )
            validated_copies_folder_path.mkdir(exist_ok=True)

            # Save file to local
            csv_file_path = str(VALIDATE_FOLDER.joinpath('notes.csv'))
            storage.copy_from(notes_csv_file_id, csv_file_path)
            print("notes.csv file created")

            #
            df = pd.read_csv(csv_file_path, index_col=MF.mat, dtype={MF.mat: str})

            # check if group or gr column is present
            l_group = group_label(df)

            #
            docs = db.documents_collection().find({"job_id": job_id})

            #
            print(f"Col: {df.columns}")
            dt = get_date()
            for document_index, doc in enumerate(docs):
                mat = str(doc["matricule"])
                if mat in df.index.values:
                    for key in doc["subquestion_predictions"].keys():
                        df.loc[mat, key] = doc["subquestion_predictions"][key]
                    df.loc[mat, MF.grade] = doc["total"]
                    df.loc[mat, MF.mdate] = dt
            df.to_csv(csv_file_path, mode="w+")

            #
            db.documents_collection().update_many(
                {"job_id": job_id},
                {
                    "$set": {
                        "status": Document_Status.VALIDATED.value,
                    }
                },
            )

            counter = 0
            all_copies_folder_path = validated_copies_folder_path.joinpath("all")
            all_copies_folder_path.mkdir(exist_ok=True)
            print("All folder:", str(all_copies_folder_path))
            for i, id in enumerate(moodle_zip_id_list):
                # moodle_i
                moodle_folder_name = f"moodle_{i}"
                moodle_folder_path = validated_copies_folder_path.joinpath(moodle_folder_name)
                moodle_folder_path.mkdir(exist_ok=True)

                # moodle_i.zip
                moodle_filename = f"{moodle_folder_name}.zip"
                # validated_tmp_folder/<job_id>_moodle_0.zip
                file_p = str(VALIDATE_FOLDER.joinpath(moodle_filename))
                storage.copy_from(id, file_p)
                # validated_tmp_folder/copies/[1.pdf, 2.pdf]
                with ZipFile(file_p, 'r') as zip_ref:
                    zip_ref.extractall(tmp_copies_folder_path)
                curr_moodle_folder_path = tmp_copies_folder_path

                if len(os.listdir(str(curr_moodle_folder_path))) == 0:
                    continue

                for root, dirs, files in os.walk(str(curr_moodle_folder_path)):
                    for f in files:
                        file = os.path.join(root, f)

                        print("file", str(file))

                        if (
                            not os.path.isfile(file)
                            or not f.endswith(".pdf")
                            or f.startswith(".")
                        ):
                            continue

                        doc = db.documents_collection().find_one({"job_id": job_id, "filename": str(f)})

                        if doc is None:
                            continue

                        doc_idx = doc["document_index"]

                        start_time = time.time()

                        if save_verified_images:
                            save_number_images(
                                job_id, doc_idx - 1, doc["subquestion_predictions"]
                            )

                        matricule = str(doc["matricule"])
                        try:
                            nom_complet = df.at[matricule, MF.name]
                        except Exception as e:
                            print(e)
                            print("Matricule", matricule, "not found in csv.")
                            continue

                        try:
                            nom, prenom = nom_complet.split()
                        except Exception as e:
                            print(nom_complet)
                            print(e)
                            nom = nom_complet
                            prenom = ""

                        if moodle_ind:
                            # create folder
                            identifiant = df.at[matricule, MF.id]
                            m_id = re.search('\\d+', identifiant)
                            if not m_id:
                                print("Moodle participant id not found in " + identifiant)
                            else:
                                identifiant = m_id.group()
                                folder_name = f"{nom_complet}_{identifiant}_{matricule}_assignsubmission_file_"
                                print("folder name", folder_name)
                                m_folder = moodle_folder_path.joinpath(folder_name)
                                m_folder.mkdir(exist_ok=True)
                                print("folder path", str(m_folder))

                                m_dest = m_folder.joinpath(f"{nom}_{prenom}_{matricule}.pdf")
                                print("destination", m_dest)

                                # transfert file to folder
                                shutil.copy(str(file), str(m_dest))

                        copies_path = all_copies_folder_path
                        if l_group:
                            group = df.at[matricule, l_group]
                            copies_path = copies_path.joinpath(str(group))
                            copies_path.mkdir(exist_ok=True)
                        dest = copies_path.joinpath(f"{nom}_{prenom}_{matricule}.pdf")
                        shutil.move(str(file), str(dest))

                        exec_time = time.time() - start_time
                        counter += 1

                        db.documents_collection().update_one(
                            {
                                "job_id": job_id,
                                "document_index": doc_idx,
                                "status": Document_Status.VALIDATED.value,
                            },
                            {
                                "$set": {
                                    "document_index": counter,
                                    "execution_time": exec_time,
                                    "status": Document_Status.READY.value,
                                }
                            },
                        )

                #
                if moodle_ind:
                    shutil.make_archive(
                        str(VALIDATE_FOLDER.joinpath(moodle_folder_name)),
                        "zip",
                        str(moodle_folder_path)
                    )

                    try:
                        c_zip = str(VALIDATE_FOLDER.joinpath(moodle_filename))
                        storage.move_to(c_zip, id)
                    except Exception as e:
                        print(e)
                else:
                    storage.remove(id)

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

            # update zip list
            zip_id_list = [zip_file_id]
            if moodle_ind:
                zip_id_list += moodle_zip_id_list

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
                        "moodle_zip_id_list": zip_id_list
                    }})

                #
                db.eval_jobs_collection().update_one(
                    {"job_id": job_id},
                    {
                        "$set": {
                            "job_status": Job_Status.ARCHIVED.value,
                            "notes_file_id": notes_csv_file_id,
                        }
                    },
                )

                sio.emit(
                    "jobs_status",
                    json.dumps(
                        {
                            "job_id": job_id,
                            "status": Job_Status.ARCHIVED.value,
                            "user_id": user_id,
                        }
                    ),
                )
            except Exception as e:
                print("Error while moving file to storage")
                db.eval_jobs_collection().update_one(
                    {"job_id": job_id},
                    {
                        "$set": {
                            "job_status": Job_Status.ERROR.value,
                        }
                    },
                )

            # delete preview image
            print("Clean documents and unverified_numbers")
            docs = db.documents_collection().find({"job_id": job_id})
            for doc in docs:
                # delete unverified numbers for job
                document_index = doc["document_index"] - 1
                for image_index in range(len(doc["subquestion_predictions"].keys())):
                    try:
                        storage.remove(os.path.normpath(
                            f"unverified_numbers{os.sep}{job_id}{os.sep}{document_index}{os.sep}{image_index}.png"))
                    except:
                        continue

            try:
                storage.remove_tree(os.path.normpath(f"documents{os.sep}{job_id}"))
            except:
                pass

            db.documents_collection().delete_many({"job_id": job_id})

        elif job["job_status"] == Job_Status.QUEUED.value or job["job_status"] == Job_Status.CORRECTED.value:
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
                        "alive_time": datetime.utcnow()
                    }
                }
            )
            
            # Save notes.csv file to local
            print("COPYING FROM ", storage.abs_path(job_params["notes_file_id"]), " TO ", str(OUTPUT_FOLDER.joinpath("notes.csv")))
            storage.copy_from(job_params["notes_file_id"], str(OUTPUT_FOLDER.joinpath("notes.csv")))
            # Save zip file to local
            storage.copy_from(job_params["zip_file_id"], str(OUTPUT_FOLDER.joinpath("content.zip")))

            with ZipFile(str(OUTPUT_FOLDER.joinpath("content.zip")), 'r') as zip_ref:
                zip_ref.extractall(EXTRACT_FOLDER)


            args = [
                str(EXTRACT_FOLDER),
                "-m",
                str(MOODLE_FOLDER),
                "-g",
                "exam",
                "--grades",
                str(OUTPUT_FOLDER.joinpath("notes.csv")),
                "-e",
                "--job_id",
                job_id,
                "--user_id",
                user_id,
                "--template_id",
                job_params["template_id"],
                "--export",
                "--batch",
                "500",
            ]
            print("Running module with:", args)
            # process_copy
            try:
                parse_run_args(args)
            except Exception as e:
                print("Error in process-copy:", e)

                if stopH.stop():
                    print("Job has been deleted.")

                    storage.remove(os.path.normpath(f"csv{os.sep}{job_id}.csv"))
                    storage.remove(os.path.normpath(f"zips{os.sep}{job_id}.zip"))
                    return

                # check if should retry
                retry = job_params.get("retry", 0)
                if retry < MAX_RETRY:
                    raise e

                # Error handling
                db.eval_jobs_collection().update_one(
                    {"job_id": job_id},
                    {"$set": {"job_status": Job_Status.ERROR.value}}
                )

                sio.emit(
                    "jobs_status",
                    json.dumps(
                        {
                            "job_id": job_id,
                            "user_id": user_id,
                            "status": Job_Status.ERROR.value,
                        }
                    ),
                )

                storage.remove(os.path.normpath(f"csv{os.sep}{job_id}.csv"))
                storage.remove(os.path.normpath(f"zips{os.sep}{job_id}.zip"))
                return

            print("Module Done")

            # Save output files in storage
            notes_csv_file_id = os.path.normpath(f"output_csv{os.sep}{job_id}.csv")
            storage.move_to(os.path.join(OUTPUT_FOLDER, "notes.csv"), notes_csv_file_id)

            if job["job_status"] == Job_Status.QUEUED.value:
                moodle_zip_file_id = os.path.normpath(f"output_zip{os.sep}{job_id}.zip")
                storage.move_to(MOODLE_ZIP, moodle_zip_file_id)

                moodle_zip_id_list = [moodle_zip_file_id]
                i = 1
                for file_path in TMP_DIR.glob("moodle*.zip"):
                    moodle_zip_file_id = os.path.normpath(f"output_zip{os.sep}{job_id}_{i}.zip")
                    storage.move_to(str(file_path), moodle_zip_file_id)
                    moodle_zip_id_list.append(moodle_zip_file_id)
                    i = i + 1

            n_pages_per_question = {key: value for key, value in job_params["n_pages_per_question"]}

            try:
                insert_copies('output_zip', job_id, n_pages_per_question)
                print("Copies inserted in database")

                if job["job_status"] == Job_Status.QUEUED.value:
                    db.jobs_output_collection().insert_one(
                        {
                            "job_id": job_id,
                            "user_id": user_id,
                            "notes_csv_file_id": notes_csv_file_id,
                            "preview_file_id": "None",
                            "moodle_zip_id_list": moodle_zip_id_list,
                        }
                    )

                # Set Job status to VALIDATION
                db.eval_jobs_collection().update_one(
                    {"job_id": job_id}, {"$set": {"job_status": Job_Status.VALIDATION.value}}
                )

                sio.emit(
                    "jobs_status",
                    json.dumps(
                        {
                            "job_id": job_id,
                            "status": Job_Status.VALIDATION.value,
                            "user_id": user_id,
                        }
                    ),
                )

            except Exception as e:
                error_messages = str(e)
                print(e)
                print("Copies inserted in database")
                db.jobs_output_collection().insert_one(
                    {
                        "job_id": job_id,
                        "user_id": user_id,
                        "notes_csv_file_id": notes_csv_file_id,
                        "preview_file_id": "None",
                        "moodle_zip_id_list": moodle_zip_id_list,
                    }
                )

                # Set Job status to ERROR
                db.eval_jobs_collection().update_one(
                    {"job_id": job_id},
                    {"$set": {"job_status": Job_Status.ERROR.value,
                              "job_infos": error_messages}}
                )

                sio.emit(
                    "jobs_status",
                    json.dumps(
                        {
                            "job_id": job_id,
                            "user_id": user_id,
                            "status": Job_Status.ERROR.value,
                            "job_infos": error_messages
                        }
                    ),
                )

            # storage.remove(os.path.normpath(f"csv{os.sep}{job_id}.csv"))
            # storage.remove(os.path.normpath(f"zips{os.sep}{job_id}.zip"))
        else:
            print("Job status "+job["job_status"]+" not handled.")

    try:
        # retrieve job
        print("Retrieving job from redis")
        job = redis.lpop("job_queue")

        # process job if any
        if job:
            print("Job:", job)
            job = json.loads(job)

            # create tmp work dir
            job_id = job["job_id"]
            WORK_TMP_DIR = ROOT_DIR.joinpath(f"tmp_{job_id}")
            WORK_TMP_DIR.mkdir(exist_ok=True)

            # process job
            try:
                process(job, WORK_TMP_DIR)
            except Exception as e:
                print("Caught an error while processing job:")
                print(e)
                pass

            # clean ENLEVER
            shutil.rmtree(WORK_TMP_DIR)

        # check if any job is idle and dangling
        alive_times = {}
        collection_check = db.get_collection("check")
        try:
            locked = False
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
                    max_alive = datetime.utcnow() - timedelta(seconds=MAX_IDLE_TIME)
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
                        db.eval_jobs_collection().update_one(
                            {"job_id": job_id}, {"$set": {"job_status": Job_Status.VALIDATION.value}}
                        )
                
                        sio.emit(
                            "jobs_status",
                            json.dumps(
                                {
                                    "job_id": job_id,
                                    "status": Job_Status.VALIDATION.value,
                                    "user_id": user_id,
                                }
                            ),
                        )
                        print(f"Ignoring incorrect files and setting job status of job ${job_id} from IGNORED to VALIDATION")

                    job = db.eval_jobs_collection().find_one({
                        "job_status": Job_Status.CORRECTED.value,
                    })
                    if job:
                        job_id = job["job_id"]
                        # restart process
                        WORK_TMP_DIR = ROOT_DIR.joinpath(f"tmp_{job_id}")
                        WORK_TMP_DIR.mkdir(exist_ok=True)
                        print(f"Restarting process...")
                        process(job, WORK_TMP_DIR)

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
                        alive_t = alive_times.get(job_id, datetime.utcnow())
                        # check if alive_time has increased, and thus job is alived
                        if j["alive_time"] > alive_t:
                            all_jobs_idle = False
                            break
                        all_jobs_idle = True
                        alive_times[job_id] = j["alive_time"]
                    # if one job alive -> stop
                    if not all_jobs_idle:
                        print("All jobs are not idle.")
                        break
                    # otherwise, sleep
                    print("Sleep before checking again running jobs.")
                    time.sleep(5)
        finally:
            collection_check.update_one({'locked': True}, {'$set': {'locked': False}})

    except Exception as e:
        print(e)
    finally:
        db.close()
        sio.disconnect()
    print("Job end.")
