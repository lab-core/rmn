"""Running a batch in parallel processes."""

import json
import os
from datetime import datetime
from multiprocessing import Process, SimpleQueue
import numpy as np
import pandas as pd
from colorama import Fore, Style
from process_copy.config import min_documents_for_max_questions
from process_copy.database import Database
from process_copy.mcc import load_csv
from rmn_common.moodle import MoodleFields as MF
from rmn_common.status import Document_Status, Job_Status
from utils.clients import socketio_client
from process_copy.imaging import memory_used_gb







def process_all(
    paths,
    grades_csv,
    box_matricule,
    box,
    job_id,
    user_id,
    process_func,
    dpi=300,
    shape=(8.5, 11),
    detach=True):
    db = Database()
    sio = socketio_client()

    # load csv
    grades_dfs, grades_names = load_csv(grades_csv)

    # Create a list of matricule-name
    all_grades_dfs = pd.concat(grades_dfs)
    names_mat_df = all_grades_dfs.reset_index()[["Matricule", "Nom complet"]]
    names_mat_df = names_mat_df.rename(columns={"Matricule": "matricule"})
    names_mat_json = names_mat_df.to_dict(orient="records")

    # Create list of groups
    groups = None
    group_df = all_grades_dfs.filter(regex=MF.group)  # keep only the right column
    if len(group_df.columns) > 0:
        if len(group_df.columns) > 1:
            print(f"Warning: several columns match the group regex ({MF.group}):", group_df.columns)
        groups = np.unique(all_grades_dfs[group_df.columns[0]]).tolist()  # transform the column to a list with only one appearance

    # Update job status
    job = db.update_job_status_to_run(job_id, names_mat_json, groups)
    new_job = (job["retry"] == 0)
    if new_job:
        print(f"[{datetime.now()}]", "Grade new job:", job_id)
        sio.emit(
            "job_status",
            json.dumps(
                {"job_id": job_id, "user_id": user_id, "status": Job_Status.RUN.value}
            ),
        )
    else:
        print(f"[{datetime.now()}]", "Retry grading old job:", job_id)

    # Create DB entry for each pdf file
    print(f"[{datetime.now()}]", "Retrieving files to grade and initializing entry in Mongo")
    docs = {doc["filename"]: doc for doc in db.documents_collection().find({"job_id": job_id})}
    if len(docs.keys()) > 0:
        g_files = [""] * len(docs.keys())
        for path in paths:
            for root, dirs, files in os.walk(path):
                for f in files:
                    if "__MACOSX" in f or not f.endswith(".pdf") or f.startswith("."):
                        continue
                    filename = f.rsplit(".", 1)[0]
                    doc = docs.get(filename)
                    if doc:
                        g_files[doc["document_index"]] = os.path.join(root, f)
    else:
        doc_index = 0
        g_files = []
        for path in paths:
            for root, dirs, files in os.walk(path):
                for f in files:
                    if "__MACOSX" in f or not f.endswith(".pdf") or f.startswith("."):
                        continue
                    file = os.path.join(root, f)
                    if not os.path.isfile(file):
                        continue
                    g_files.append(file)
                    db.insert_document(job_id, doc_index, [], "",
                                       Document_Status.NOT_READY, "", 0, f)
                    doc_index += 1
    sio.disconnect()

    # set default doc status
    eval_job = db.eval_jobs_collection().find_one({"job_id": job_id})
    default_status = Document_Status.HIGH_ACCURACY if eval_job["validate_matricule"] else Document_Status.VALIDATED

    # get max RAM (see memory_used_gb: the container's usage, not the node's)
    max_RAM_GB = int(os.getenv("MAX_RAM_GB", "1000"))
    doc_index = 0
    batch = 1
    matricules_data = {}
    stalled_at = None
    last_index = len(g_files) - 1
    while doc_index <= last_index:
        batch_start = doc_index
        # grade file in a different process
        g_args = (g_files[doc_index:], doc_index, grades_csv,
                  min_documents_for_max_questions,
                  job_id, user_id,
                  box_matricule, box, matricules_data,
                  dpi, shape, max_RAM_GB, default_status)
        print(f"[{datetime.now()}]", "Run batch", batch, f"from {doc_index} (/{last_index})")

        if detach:
            q_results = SimpleQueue()
            g_args = (*g_args, q_results)
            p = Process(target=process_func, args=g_args)
            p.start()
            # wait for the result but notice a worker that died without
            # reporting (OOM kill, segfault): q_results.get() alone blocked
            # forever while the heartbeat kept the job looking alive
            result = None
            while result is None:
                p.join(timeout=1)
                if not q_results.empty():
                    result = q_results.get()
                elif p.exitcode is not None:
                    break
            if result is None:
                print(
                    Fore.RED
                    + f"Recognition worker died (exit code {p.exitcode}) at document {batch_start}."
                    + Style.RESET_ALL
                )
                stalled_at = batch_start
                break
            doc_index, matricules_data = result
            p.join()
        else:
            doc_index = process_func(*g_args)

        print(f"[{datetime.now()}]", doc_index, "files have been processed.")
        print(f"[{datetime.now()}]", 'RAM Used - end batch', batch, '(GB):', memory_used_gb())
        batch += 1
        last_index = db.documents_collection().count_documents({"job_id": job_id}) - 1

        # Safety net: if a batch made no progress (e.g. the first file crashed
        # the worker before it could be advanced), stop instead of retrying the
        # same file forever and starving the executor.
        if doc_index <= batch_start:
            print(
                Fore.RED
                + f"No progress at document {batch_start}; stopping this job to avoid an infinite loop."
                + Style.RESET_ALL
            )
            stalled_at = batch_start
            break
    db.close()

    # the workers filled their own copy of the csv (in another process) and
    # saved it: reload it, or the frames loaded above, without the grades
    # read, would be written back over it below
    grades_dfs, grades_names = load_csv(grades_csv)

    # check the number of files that have been dropped on moodle if any
    print(f"[{datetime.now()}]", "Store grades in csv")
    n = 0
    for df in grades_dfs:
        for idx, row in df.iterrows():
            try:
                s = row[MF.status]
            except:
                continue
            if pd.isna(s):
                continue
            if s.startswith(MF.status_start_filter):
                n += 1
    if n > 0 and n != doc_index:
        print(
            Fore.RED
            + "%d copies have been uploaded on moodle, but %d have been graded"
            % (n, doc_index)
            + Style.RESET_ALL
        )

    # store grades
    for i, f in enumerate(grades_csv):
        df = grades_dfs[i]
        # sort by status (Remis in first) then matricules (index)
        try:
            status = np.array(
                [not pd.isna(v) and not v.startswith("Remis") for v in df.Statut.values]
            )
            sorted_indexes = np.lexsort((df.index.values, status))
            sdf = df.iloc[sorted_indexes]
            sdf.to_csv(f)
        except:
            df.to_csv(f)

    if stalled_at is not None:
        # a plain return left the job in RUN; the idle sweep requeued it and
        # the same file was retried forever. Raising routes it through the
        # MAX_RETRY handling of process_job instead.
        raise RuntimeError(
            f"No progress at document {stalled_at}: the recognition worker stopped on that file."
        )
