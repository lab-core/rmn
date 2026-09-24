"""Reading the student number of a copy, and of a whole batch."""

import json
import os
import re
import time
from datetime import datetime
import cv2
import unidecode
from colorama import Fore, Style
from process_copy.classifier import load_classifier
from process_copy.config import known_mistmatch_matricule, len_mat, re_mat
from process_copy.database import Database
from process_copy.mcc import get_name, group_label, load_csv
from rmn_common.moodle import MoodleFields as MF
from rmn_common.status import Document_Status
from utils.clients import socketio_client
from process_copy.imaging import (
    fetch_box,
    get_image_from_contour,
    memory_used_gb,
)
from process_copy.pages import (
    create_summary,
    create_whole_summary,
    gray_images,
    save_pages,
)
from process_copy.contours import (
    find_digit_contours,
    find_matricule_box_contours,
)
from process_copy.digits import extract_all_digits, extract_digit







def matricule_confidence(possible_digits, mat, roster=None, floor=1e-3):
    """Probability that ``mat`` is the matricule written on the copy.

    ``possible_digits[i]`` maps each candidate digit of position ``i`` to its
    probability summed over every box read (``find_matricule``); normalised,
    each position is a distribution, and a matricule's likelihood is the
    product over its digits (a digit never proposed counts ``floor``, so one
    unread digit does not zero a candidate).

    Without a roster the confidence is that likelihood. With one, the answer
    has to be one of its matricules: ``mat``'s share of the likelihood of all
    of them, times how well its digits fit what was read (geometric mean over
    the positions of the chosen digit's probability relative to the most
    probable one). The share alone is confidently wrong when the student is
    missing from the csv and another one's matricule is made of digits the
    model hesitated on: it is then the best of a bad lot, while its digits fit
    poorly. A matricule outside the roster (the regex fallback) is at most
    half its likelihood.
    """
    if not mat or len(mat) != len(possible_digits):
        return 0.0
    dists = []
    for distri in possible_digits:
        total = sum(distri.values())
        if total <= 0:
            return 0.0
        dists.append({int(d): p / total for d, p in distri.items()})

    def likelihood(m):
        prob = 1.0
        for dist, c in zip(dists, m):
            prob *= max(dist.get(int(c), 0.0), floor)
        return prob

    # float(): the probabilities are numpy float32, which json cannot encode
    p = likelihood(mat)
    if not roster:
        return float(p)
    candidates = {m for m in roster if len(m) == len(mat) and m.isdigit()}
    if mat not in candidates:
        return float(0.5 * p)
    share = p / sum(likelihood(m) for m in candidates)
    fit = 1.0
    for dist, c in zip(dists, mat):
        fit *= max(dist.get(int(c), 0.0), floor) / max(dist.values())
    return float(share * fit ** (1 / len(mat)))




def find_matricule(
    grays, front_box, regular_box, classifier, grades_dfs=[], separate_box=True, min_confidence=0.85, min_img=5,
    return_confidence=False
):
    """Read the matricule of a copy: ``(matricule, id_box, csv index)``.

    With ``return_confidence`` a fourth value is returned, the
    ``matricule_confidence`` of the matricule found (0 when none).
    """
    possible_digits = [{} for i in range(len_mat)]
    id_box = None

    def find_digits(gray_box, cnt, split=True):
        try:
            # find contours of the numbers.
            # If separate_box, each number of the matricule is in its separate box
            # return a sorted list of the relevant digits' contours and the dot position (and the threshold image used)
            # 10 = len("Matricule:")
            cnts, dot, thresh = find_digit_contours(
                gray_box,
                max_cnts=len_mat,
                split_on_semi_column=split,
                min_box_before_split=6,
                ctrl_size_variation=True
            )
            # check length
            if len(cnts) != len_mat:
                return False

            all_digits = []
            # if each number is in a separate box, extract it individually
            if separate_box:
                for c in cnts:
                    digit_box = get_image_from_contour(gray_box, c, border=7)
                    dcnts, dot, dthresh = find_digit_contours(digit_box)
                    # check if only one digit has been found in the box
                    if len(dcnts) == 1:
                        d = extract_digit(dcnts[0], digit_box, dthresh, classifier,
                                          confusions=known_mistmatch_matricule)
                    # if too many contours, just remove some pixels on the border of the image
                    elif len(dcnts) > 1:
                        d = extract_digit(c, gray_box, thresh, classifier, border=-7,
                                          confusions=known_mistmatch_matricule)
                    # if no contour at all, it means that at least one of the box is empty
                    # -> throw this results
                    else:
                        all_digits = []
                        break
                    all_digits.append(d)
            # otherwise, extract all digits at once
            else:
                all_digits = extract_all_digits(
                    cnts, gray_box, thresh, classifier, confusions=known_mistmatch_matricule)
                all_digits = [d for c, d in all_digits]
        except cv2.error as e:
            print(e)
            print("Got an error while finding digits.")
            return False

        # check length
        if len(all_digits) != len_mat:
            return True

        # store values
        for i, digits in enumerate(all_digits):
            distri = possible_digits[i]
            for p, d in digits:
                if d in distri:
                    distri[d] += p
                else:
                    distri[d] = p
        return True

    def best_matricule_match():
        # build matricules and sort them by probabilities
        matricules = [(0, "")]
        for distri in possible_digits:
            matricules = [
                (c + p, "%s%d" % (m, d)) for c, m in matricules for d, p in distri.items()
            ]
        smats = sorted(matricules, reverse=True)

        # find the most probable matricule that exists
        if grades_dfs:
            for p, mat in smats:
                i, name = get_name(mat, grades_dfs)
                if i >= 0:
                    return mat, i
        # find the most valid and probable one if no csv (or not valid) to check the matricule
        for p, mat in smats:
            if re.match(re_mat, mat):
                return mat, None

        return None, None

    def stop_processing():
        # check if enough images processed
        n_img = sum(possible_digits[0].values())
        if n_img < min_img - 0.1:
            return False

        # check if all digits are enough accurate
        min_threshold = n_img * min_confidence
        for distri in possible_digits:
            if len([p for p in distri.values() if p >= min_threshold]) == 0:
                return False

        # check if has a match
        _ , index = best_matricule_match()

        return index is not None

    # find the id box
    biggest_c, ret = find_matricule_box_contours(grays[0], front_box, find_digits, True)

    # try to find a matricule on the next page
    if regular_box != None:
        print("Trying to find matricule on the next page...")
        for gray in grays[1:]:
            find_matricule_box_contours(gray, regular_box, find_digits)
            if stop_processing():
                break

    # build matricules and sort them by probabilities
    mat, index = best_matricule_match()

    cropped = fetch_box(grays[0], front_box)
    # biggest_c is None when the box had no contour (blank / unreadable)
    id_box = get_image_from_contour(cropped, biggest_c) if biggest_c is not None else None

    if return_confidence:
        roster = [str(m) for g in grades_dfs for m in g.index]
        return mat, id_box, index, matricule_confidence(possible_digits, mat, roster)
    return mat, id_box, index




def find_file_matricule(job_id, doc_index, file, db, classifier, shape, grades_dfs, box_matricule, matricules_data, n_questions):
    # check if document has already been processed
    doc = db.get_document(job_id, doc_index)
    if doc and doc['status'] != Document_Status.NOT_READY.value:
        print("Document", doc['filename'], "is ready with status", doc['status'])
        n_questions[doc_index] = list(doc["grades"])
        m = doc["matricule"]
        if m not in matricules_data:
            matricules_data[m] = [file]
        else:
            matricules_data[m].append(file)
        return True, None, None

    # search matricule in filename
    m = re.search(re_mat, doc['filename'])
    is_matricule_valid = True
    # a matricule written in the file or folder name is taken as is
    confidence = 1.0

    # search matricule in forlder name
    # use folder name: "Nom complet_Identifiant_Matricule_assignsubmission_file_"
    if not m:
        par_dir = file.rsplit(os.sep, 2)[-2]
        dir_split = par_dir.split("_")
        if len(dir_split) > 3:
            m = re.search(re_mat, dir_split[2])

    if not m:
        # Find matricule in pdf filename
        for s in file.split("_"):
            m = re.search(re_mat, s)
            if m:
                break

    if not m:
        # Find matricule in pdf file
        print("Matricule wasn't found in " + doc['filename'])
        grays = gray_images(file, shape=shape)
        if box_matricule is None:
            raise Exception
        m, id_box, id_csv, confidence = find_matricule(
            grays,
            box_matricule["front"],
            box_matricule.get("regular"),
            classifier,
            grades_dfs,
            separate_box=box_matricule["separate_box"],
            return_confidence=True,
        )

        m = m if m else "NA"
        if m not in matricules_data:
            matricules_data[m] = []
        # if no valid matricule has been found
        if m == "NA" or (grades_dfs and id_csv is None):
            is_matricule_valid = False
        matricules_data[m].append(file)
    else:
        m = m.group()

    return is_matricule_valid, m, confidence




def find_matricules(
        files,
        doc_index,
        grades_csv,
        min_documents_for_max_questions,
        job_id,
        user_id,
        box_matricule,
        box,
        matricules_data={},
        dpi=300,
        shape=(8.5, 11),
        max_RAM_GB=1000,
        default_status=Document_Status.HIGH_ACCURACY,
        q_results=None
):
    db = Database()
    # load csv
    grades_dfs, grades_names = load_csv(grades_csv)

    # find matricules
    shape = (int(dpi * shape[0]), int(dpi * shape[1]))
    # loading our CNN model
    classifier = load_classifier()

    try:
        # Create SocketIO connection
        sio = socketio_client()

        n_questions = {}
        for file in files:
            # Start timer
            start_time = time.time()
            filename = os.path.basename(file)
            print(f"[{datetime.now()}] Processing file:", filename, f"({job_id}, {doc_index})")

            try:
                is_matricule_valid, m, confidence = find_file_matricule(
                    job_id, doc_index, file, db, classifier, shape, grades_dfs, box_matricule, matricules_data,
                    n_questions)

                # if doc already processed
                if is_matricule_valid and m is None:
                    doc_index += 1
                    continue

                # rel_filepath = db.save_preview_image(src, job_id, doc_index)
                doc_status = (
                    default_status
                    if is_matricule_valid
                    else Document_Status.TO_VALIDATE
                )

                # getting group
                i, name = get_name(m, grades_dfs)
                group = ""
                if i < 0:
                    print(
                        Fore.RED
                        + "%s: Matricule (%s) not found in csv files" % (filename, m)
                        + Style.RESET_ALL
                    )
                else:
                    l_group = group_label(grades_dfs[i])
                    if l_group:
                        group = str(grades_dfs[i].at[m, l_group])
                        print("Group:", group)

                exec_time = time.time() - start_time
                if not db.update_document(
                        job_id,
                        doc_index,
                        None,
                        doc_status,
                        m,
                        exec_time,
                        group,
                        matricule_confidence=confidence,
                ):
                    raise KeyError(f"Document {filename} was not found.")

                sio.emit(
                    "document_ready",
                    json.dumps(
                        {
                            "job_id": job_id,
                            "user_id": user_id,
                            "document_index": doc_index,
                            "execution_time": exec_time,
                            "status": doc_status.value,
                            "n_total_doc": doc_index + 1,
                            "matricule": str(m),
                            "matricule_confidence": confidence,
                        }
                    ),
                )

                print(f"[{datetime.now()}]", 'Processed file:', filename, f"({job_id}, {doc_index})")
            except Exception as e:
                # a single unreadable copy must not crash the job or make the
                # batch loop retry it forever: flag it for manual validation and
                # carry on to the next file.
                print(Fore.RED + f"{filename}: matricule recognition failed: {e}" + Style.RESET_ALL)
                try:
                    db.update_document(job_id, doc_index, None, Document_Status.TO_VALIDATE,
                                       "", time.time() - start_time, "", matricule_confidence=0.0)
                except Exception as e2:
                    print(e2)

            doc_index += 1

            RAM_used = memory_used_gb()
            print(f"[{datetime.now()}]", 'RAM Used once grade found (GB):', RAM_used)

            if RAM_used >= max_RAM_GB:
                print(f"[{datetime.now()}]", 'RAM limit exceeded')
                break
    finally:
        sio.disconnect()
        db.close()

        if q_results is not None:
            print('Store result in queue.')
            q_results.put((doc_index, matricules_data))

    return doc_index




def find_all_matricules(paths, box, grades_csv=[], dpi=300, shape=(8.5, 11)):
    if dpi < 300:
        print(f"Warning: dpi ({dpi}) could be too low for an accurate recognition: you should use 300.")
    shape = (int(dpi * shape[0]), int(dpi * shape[1]))

    # box_list, box_matricule_list = None, None
    # regular_box_matricule = box_matricule_default
    # front_box_matricule = box_matricule_default
    # box_matricule = box_matricule_default
    # box = box_default

    # box_list, box_matricule_list, regular_box_matricule_list = db.get_templates_info(front_template_id, regular_template_id)

    # if regular_box_matricule_list is not None:
    #     regular_box_matricule = convert_to_regular_box_config(regular_box_matricule_list)
    # if box_matricule_list is not None:
    #     front_box_matricule = convert_to_front_box_config(box_matricule_list)
    # if box_list is not None:
    #     box = convert_grade_box_config(box_list)

    # box_matricule['front'] = front_box_matricule['front']
    # box_matricule['regular'] = regular_box_matricule['regular']

    # loading our CNN model
    classifier = load_classifier()

    # load csv
    grades_dfs, grades_names = load_csv(grades_csv)
    root_dir = None

    # list files and directories
    matricules_data = {}
    duplicates = set()
    invalid = []
    for path in paths:
        r = os.path.dirname(path)
        if not root_dir:
            root_dir = r
        elif root_dir.count(os.sep) > r.count(os.sep):
            root_dir = r

        for root, dirs, files in os.walk(path):
            for f in files:
                if not f.endswith(".pdf") or f.startswith("."):
                    continue
                file = os.path.join(root, f)
                if os.path.isfile(file):
                    grays = gray_images(file, shape=shape)
                    if grays is None:
                        print(Fore.RED + "%s: No valid pdf" % f + Style.RESET_ALL)
                        continue
                    mat, id_box, id_group = find_matricule(
                        grays,
                        box["front"],
                        box["regular"],
                        # None,
                        classifier,
                        grades_dfs,
                        separate_box=box["separate_box"],
                    )
                    name = (
                        grades_dfs[id_group].at[mat, MF.name]
                        if id_group is not None
                        else mat
                    )
                    if name:
                        name = unidecode.unidecode(name)
                    if not mat:
                        print(
                            Fore.RED + "No matricule found for %s" % f + Style.RESET_ALL
                        )
                    else:
                        print("Matricule %s found for %s. Name: %s" % (mat, f, name))

                    m = mat if mat else "NA"
                    if m not in matricules_data:
                        matricules_data[m] = []
                        # if no valid matricule has been found
                        if m != "NA" and grades_dfs and id_group is None:
                            invalid.append(m)
                    elif m != "NA":
                        duplicates.add(m)
                    matricules_data[m].append((id_box, name, file))

    sumarries = []
    csvf = "Id,Matricule,NomComplet,File\n"

    def add_summary(mat, id_box, name, file, invalid=False, initial_index=1):
        i = len(sumarries) + initial_index
        l_csv = "%d,%s,%s,%s\n" % (i, mat if mat else "", name if name else "", file)
        sumarry = create_summary(
            id_box,
            name,
            None,
            None,
            "%d: %s" % (i, file.rsplit(os.sep)[-1]),
            dpi,
            align_matricule_left=False,
            name_bottom=False,
            invalid=invalid,
        )
        sumarries.append(sumarry)
        return l_csv

    print(Fore.RED)
    if "NA" in matricules_data:
        for id_box, name, file in matricules_data["NA"]:
            print("No matricule found for %s" % file)
            csvf += add_summary(None, id_box, None, file)
        matricules_data.pop("NA")

    for m in sorted(invalid):
        print("No valid matricule %s for:" % m)
        for id_box, name, file in matricules_data[m]:
            print("    " + file)
            csvf += add_summary(m, id_box, None, file, invalid=True)
        matricules_data.pop(m)

    for m in sorted(duplicates):
        print("Duplicate files found for matricule %s:" % m)
        for id_box, name, file in matricules_data[m]:
            print("    " + file)
            csvf += add_summary(m, id_box, name, file, invalid=True)
        matricules_data.pop(m)
    print(Style.RESET_ALL)

    for m in sorted(matricules_data):
        if len(matricules_data[m]) != 1:
            raise ValueError(
                "The list should contain only one element associated to a given matricule (%s)"
                % m
            )
        id_box, name, file = matricules_data[m][0]
        csvf += add_summary(m, id_box, name, file)

    # save summary pdf and grades
    pages = create_whole_summary(sumarries)
    save_pages(pages, os.path.join(root_dir, "matricule_summary.pdf"))
    with open(os.path.join(root_dir, "matricules.csv"), "w") as wf:
        wf.write(csvf)
