"""Reading the grades written in the table of a cover page."""

import json
import os
import re
import time
from copy import copy
from statistics import median
import cv2
import pandas as pd
from colorama import Fore, Style
from process_copy.classifier import load_classifier
from process_copy.config import min_documents_for_max_questions
from process_copy.database import Database
from process_copy.mcc import get_name, group_label, load_csv
from rmn_common.moodle import MoodleFields as MF
from rmn_common.status import Document_Status
from utils.clients import socketio_client
from process_copy.imaging import fetch_box, get_date, memory_used_gb
from process_copy.pages import gray_images
from process_copy.contours import find_grade_boxes
from process_copy.digits import correct_decimals, test
from process_copy.matricules import find_file_matricule







def get_max_question(max_grade, max_nb_questions):
    if max_grade is None:
        return None
    if max_nb_questions is None:
        return max_grade
    g = min(2, max_nb_questions) * max_grade / max_nb_questions
    return g




def try_fix_n_questions(max_nb_questions, predictions):
    if max_nb_questions is None:
        return predictions
    # jobs graded before the median was rounded stored a float (3.0) in Mongo
    max_nb_questions = int(max_nb_questions)
    if len(predictions) == max_nb_questions:
        return predictions
    # add zero at the beginning
    print("Try fixing the number of questions for:", predictions)
    if len(predictions) < max_nb_questions:
        diff = max_nb_questions - len(predictions)
        predictions = [0] * diff + predictions
    else:
        # try to remove 0 first
        i = 0
        while len(predictions) > max_nb_questions and i < len(predictions):
            if predictions[i] == 0:
                predictions.pop(i)
            else:
                i += 1
        # remove values at the end
        predictions = predictions[:max_nb_questions]

    return predictions




def try_fix_questions(max_question, predictions):
    # no "Note maximale" column in the csv: nothing to compare against
    if max_question is None:
        return False, copy(predictions)
    fixed = False
    new_predictions = copy(predictions)
    for i, p in enumerate(new_predictions):
        if p > max_question:
            while p > max_question:
                p = p / 10
            new_predictions[i] = correct_decimals(p)
            fixed = True

    # update document
    if fixed:
        print("Try fixing the number of questions for:", predictions, " by ", new_predictions)

    return fixed, new_predictions




def grade(gray, box, classifier=None, add_border=False, trim=None, max_grade=None, max_question=None, retry=0):
    cropped = fetch_box(gray, box)
    boxes = find_grade_boxes(cropped, add_border, thick=0)
    # print(f"Number of boxes : {len(boxes)}")

    number_images = []
    all_numbers = []
    for i, b in enumerate(boxes):
        (x, y, w, h) = cv2.boundingRect(b)
        if h <= 10 or w <= 10:
            print("An invalid box number has been found (too small or too thin)")
            if retry > 0:
                print("Retry grading", retry)
                # a slightly wider box (the old retry box collapsed every
                # coordinate onto box[0], and retry-1 landed in max_question)
                box2 = (box[0]-.01, box[1]+.01, box[2]-.01, box[3]+.01)
                return grade(gray, box2, classifier, add_border, trim, max_grade, max_question, retry-1)
            return False, [], cropped, number_images, boxes
        box_img = cropped[y + 5: y + h - 5, x + 5: x + w - 5]
        # check if need to trim
        n_trim = None
        if trim:
            for (j, n) in trim:
                if i == j or i == len(boxes) + j:
                    n_trim = n
                    break
            # trim everything
            if n_trim < 0:
                continue

        number_images.append(box_img.copy())
        all_numbers.append(test(box_img.copy(), classifier, trim=n_trim))
    print(f"All numbers: {all_numbers}")

    if len(all_numbers) == 0:
        print("No valid number has been found")
        return False, [], cropped, number_images, boxes

    # find all combination that works
    combinations = [(0, [])]
    for i, numbers in enumerate(all_numbers):
        if len(numbers) == 0:
            print("No valid number has been found for at least one of the box. Use 0 as default.")
            numbers = [(1, 0)]
        else:
            for j, p in enumerate(numbers):
                # try to move the dot (as it can be often misplaced)
                max_g = max_question if i < len(all_numbers) - 1 else max_grade
                if max_g is not None and p[1] > max_g:
                    g = p[1]
                    while g > max_g:
                        g = g / 10
                    numbers[j] = (p[0], correct_decimals(g))
        c2 = [(c + p, l + [j]) for p, j in numbers for c, l in combinations]
        combinations = c2

    print(f"Combinations: {combinations}")

    # combinations = [i for i in combinations if len(i[1]) == len(all_numbers[:-1])]

    # Try first the ones with the highest probability and below the max grade if available
    combinations = sorted(combinations, reverse=True)
    for p, numbers in combinations:
        # if only one number, return it
        if len(numbers) <= 1:
            return True, numbers, cropped, number_images, boxes
        # check the sum
        total = sum(numbers[:-1])
        if max_grade is not None and numbers[-1] > max_grade:
            continue
        if total != numbers[-1]:
            continue
        return True, numbers, cropped, number_images, boxes

    # Has not been able to check the total -> give the best prediction
    expected_numbers = [n[0] for n in all_numbers[:-1]]
    print(f"expected_numbers: {expected_numbers}")

    p, total = (
        sum(n[0] for n in expected_numbers) / len(expected_numbers),
        round(sum(n[1] for n in expected_numbers), 2),
    )
    pt, nt = all_numbers[-1][0]
    # keep the first numbers, but choose the most probable feasible total (either the sum or the one read)
    # when nt is 0, always choose the total
    adjusted_total = total
    if pt >= p and nt > 0:
        adjusted_total = nt
    if max_grade is not None:
        if nt > max_grade:
            adjusted_total = total
        if total > max_grade and nt > 0:
            adjusted_total = nt
        # if both are greater than max grade, both are false !
    return (
        False,
        [n for p, n in expected_numbers] + [adjusted_total],
        cropped,
        number_images,
        boxes
    )




def grade_files(
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

    # load max grade if available
    max_grade = None
    for df in grades_dfs:
        for idx, row in df.iterrows():
            try:
                s = row[MF.max]
                if pd.isna(s):
                    continue
                if isinstance(s, str):
                    s = s.replace(",", ".")
                    s = float(s)
            except:
                continue
            if max_grade is None or s < max_grade:
                max_grade = s

    # grade files
    grades_data = []
    dt = get_date()
    trim = box["trim"] if "trim" in box else None
    max_nb_questions = db.get_job_max_questions(job_id)
    n_docs = db.documents_collection().count_documents({"job_id": job_id})
    if n_docs < min_documents_for_max_questions:
        min_documents_for_max_questions = 0
    print("Max number of questions:", max_nb_questions)

    shape = (int(dpi * shape[0]), int(dpi * shape[1]))
    # loading our CNN model
    classifier = load_classifier()

    # handler = PreviewHandler()

    try:
        # Create SocketIO connection
        sio = socketio_client()

        n_questions = {}
        max_question = get_max_question(max_grade, max_nb_questions)
        for file in files:
            # Start timer
            start_time = time.time()

            is_matricule_valid, m, confidence = find_file_matricule(
                job_id, doc_index, file, db, classifier, shape, grades_dfs, box_matricule, matricules_data,
                n_questions)

            # if doc already processed
            if is_matricule_valid and m is None:
                doc_index += 1
                continue

            # getting filename
            filename = file.rsplit(os.sep, 1)[-1]

            # try to recognize each grade and verify the total
            grays = gray_images(file, [0], straighten=False, shape=shape)
            if grays is None:
                print(Fore.RED + "%s: No valid pdf" % filename + Style.RESET_ALL)
                continue
            gray = grays[0]
            total_matched, numbers, grades, number_images, boxes = grade(
                gray,
                box["grade"],
                classifier=classifier,
                trim=trim,
                max_grade=max_grade,
                max_question=max_question
            )

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

            # fill moodle csv file
            if i < 0:
                # grades_dfs[-1] would silently append a row for the misread
                # matricule to the last csv; keep the grades in the database
                # only, the copy is flagged TO VALIDATE below
                print(Fore.RED + "%s: grades not written to the csv (matricule unknown)" % filename + Style.RESET_ALL)
            elif numbers and len(numbers) > 1:
                print("Found numbers:", numbers)

                # db.save_unverified_number_images(
                #     job_id, doc_index, number_images[:-1]
                # )
                number_images.clear()  # delete numbers picture

                # fill csv for all the subquestion
                for index_grade, grade_number in enumerate(numbers[:-1]):
                    col_name = f"{MF.question} {index_grade + 1}"

                    if col_name not in grades_dfs[i].columns:
                        # create new column: Question_{index_grade + 1}
                        # Initialize to 0
                        if MF.grade not in grades_dfs[i].columns:
                            grades_dfs[i][MF.grade] = None
                        total_index = grades_dfs[i].columns.get_loc(MF.grade)
                        grades_dfs[i].insert(total_index, col_name, 0)

                    print("%s - %s: %.2f" % (filename, col_name, grade_number))
                    grades_dfs[i].at[m, col_name] = grade_number

                # Fill total grade in csv
                if pd.isna(grades_dfs[i].at[m, MF.grade]):
                    print("%s - %s: %.2f" % (filename, MF.grade, numbers[-1]))
                    grades_dfs[i].at[m, MF.grade] = numbers[-1]
                    grades_dfs[i].at[m, MF.mdate] = dt
                elif grades_dfs[i].at[m, MF.grade] != numbers[-1]:
                    print(
                        Fore.RED
                        + "%s: there is already a grade (%.2f) different of %.2f"
                        % (filename, grades_dfs[i].at[m, MF.grade], numbers[-1])
                        + Style.RESET_ALL
                    )
                    numbers[-1] = grades_dfs[i].at[m, MF.grade]
                else:
                    print("%s: found same grade %.2f" % (filename, numbers[-1]))
            else:
                print(Fore.GREEN + "%s: No valid grade" % filename + Style.RESET_ALL)
                grades_dfs[i].at[m, MF.mdate] = dt

            # Display in the summary the identity box if provided
            id_img = None
            grades_data.append(
                (m, i, file, grades, numbers, total_matched, id_img)
            )

            results = [(f"Matricule: {m}", is_matricule_valid)]

            # Check there were no grades existing
            if not numbers or len(numbers) < 1:
                if max_nb_questions:
                    numbers = [0] * (int(max_nb_questions) + 1)
                else:
                    # come back later when max_nb_questions found
                    numbers = [0]

            results.extend(
                [
                    (f"Question {i + 1}: {n}", total_matched)
                    for i, n in enumerate(numbers[:-1])
                ]
            )
            results.append((f"Total: {numbers[-1]}", total_matched))

            # DB update
            doc_status = (
                default_status
                if is_matricule_valid
                else Document_Status.TO_VALIDATE
            )
            numbers[:-1] = try_fix_n_questions(max_nb_questions, numbers[:-1])
            n_questions[doc_index] = numbers[:-1]

            exec_time = time.time() - start_time

            if not db.update_document(
                job_id,
                doc_index,
                numbers[:-1],
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

            doc_index += 1

            RAM_used = memory_used_gb()
            print('RAM Used once grade found (GB):', RAM_used)

            if max_nb_questions is None and len(n_questions) > min_documents_for_max_questions:
                print("--n_questions:", n_questions)
                max_nb_questions = int(round(median(len(v) for v in n_questions.values())))
                db.set_job_max_questions(job_id, max_nb_questions)

                # fix previous documents that were not with the right number of questions
                print("--max_nb_questions:", max_nb_questions)
                max_question = get_max_question(max_grade, max_nb_questions)
                for index, doc_questions in n_questions.items():
                    n_doc_q = len(doc_questions)
                    doc_questions = try_fix_n_questions(max_nb_questions, doc_questions)
                    changed2, doc_questions = try_fix_questions(max_question, doc_questions)

                    if len(doc_questions) != n_doc_q or changed2:
                        n_questions[index] = doc_questions
                        # update document
                        db.update_document_grades(job_id, index, doc_questions)

                        doc = db.get_document(job_id, index)
                        sio.emit(
                            "document_ready",
                            json.dumps(
                                {
                                    "job_id": job_id,
                                    "user_id": user_id,
                                    "document_index": index,
                                    "execution_time": doc["execution_time"],
                                    "status": doc["status"],
                                    "n_total_doc": doc_index,
                                }
                            ),
                        )

            if RAM_used >= max_RAM_GB:
                print('RAM limit exceeded')
                break
    finally:
        sio.disconnect()
        db.close()

        # store grades and hand the progress back to the parent process even if
        # the loop above raised — otherwise a crash left the parent blocked
        # forever on q_results.get().
        for i, f in enumerate(grades_csv):
            try:
                grades_dfs[i].to_csv(f)
            except Exception as e:
                print(e)

        if q_results is not None:
            q_results.put((doc_index, matricules_data))

    return doc_index




def compare_all(paths, grades_csv, box, dpi=300, shape=(8.5, 11)):
    shape = (int(dpi * shape[0]), int(dpi * shape[1]))

    # load csv
    grades_df = pd.read_csv(grades_csv, index_col="Matricule")

    # loading our CNN model
    classifier = load_classifier()

    # grade files
    tp = 0
    tpp = 0
    fp = 0
    fpp = 0
    fn = 0
    n = 0
    for path in paths:
        for f in os.listdir(path):
            if not f.endswith(".pdf") or f.startswith("."):
                continue
            # search matricule
            m = re.search("[1-2]\\d{6}(?=\\D)", f)
            if not m:
                print("Matricule wasn't found in " + f)
            m = int(m.group())

            file = os.path.join(path, f)
            if os.path.isfile(file):
                grays = gray_images(file, [0], straighten=False, shape=shape)
                if grays is None:
                    print(Fore.RED + "%s: No valid pdf" % f + Style.RESET_ALL)
                    continue
                gray = grays[0]
                total_matched, numbers = grade(gray, box, classifier)
                if numbers:
                    print("%s: %.2f" % (f, numbers[-1]))
                    if grades_df.at[m, MF.grade] == numbers[-1]:
                        if total_matched:
                            tp += 1
                        else:
                            tpp += 1
                    elif total_matched:
                        fp += 1
                    else:
                        fpp += 1
                    grades_df.at[m, MF.grade] = numbers[-1]
                else:
                    print(Fore.GREEN + "%s: No valid grade" % f + Style.RESET_ALL)
                    fn += 1
                    grades_df.at[m, MF.grade] = -1
                n += 1
    # store grades
    print(
        "Accuracy: %.3f (%.3f, %.3f), Precision: %.3f (%.3f, %.3f)"
        % (
            (tp + tpp) / n,
            tp / n,
            tpp / n,
            (tp + tpp) / (tp + tpp + fp + fpp),
            tp / (tp + fp),
            tpp / (tpp + fpp),
        )
    )
