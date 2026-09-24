import os
import shutil
import datetime as dt
import cv2
from rmn_common.status import Document_Status, Job_Status
from utils.storage import Storage, ROOT_DIR
from utils.clients import mongo_client
from pymongo import ReturnDocument


class Database:
    def __init__(self, db_name="RMN", storage_path=None):
        self.mongo_client = mongo_client()
        self.mongo_database = self.mongo_client[db_name]
        self.storage = Storage(storage_path)

    def close(self):
        self.mongo_client.close()

    def get_collection(self, name):
        return self.mongo_database[name]

    def documents_collection(self):
        return self.get_collection("job_documents")

    def questions_collection(self):
        return self.get_collection("job_questions")

    def eval_jobs_collection(self):
        return self.get_collection("eval_jobs")

    def jobs_output_collection(self):
        return self.get_collection("jobs_output")

    def users_collection(self):
        return self.get_collection("users")

    def insert_question(
        self,
        job_id,
        doc_index,
        rel_filepath,
        status,
        filename,
        question,
        basename,
        question_index=None,
        grade=None
    ):
        if question_index is None:
            question_index = int(question[1:])  # 'Q1' -> index of 1
        return self.questions_collection().insert_one(
            {
                "job_id": job_id,
                "document_index": doc_index,
                "rel_filepath": rel_filepath,
                "status": status.value,
                "filename": filename,
                "question": question,
                "question_index": question_index,
                "basename": basename,
                "grade": grade
            }
        )

    def insert_document(
        self,
        job_id,
        doc_index,
        grades,
        rel_filepath,
        status,
        matricule,
        time,
        filename,
    ):
        return self.documents_collection().insert_one(
            {
                "job_id": job_id,
                "document_index": doc_index,
                "matricule": str(matricule),
                "grades": grades,
                "rel_filepath": rel_filepath,
                "status": status.value,
                "execution_time": time,
                "filename": filename,
            }
        )

    def get_document(self, job_id, doc_index):
        return self.documents_collection().find_one({
            "job_id": job_id, "document_index": doc_index
        })

    def update_document(
        self,
        job_id,
        doc_index,
        grades,
        status,
        matricule,
        time,
        group
    ):
        try:
            # return updated doc
            set = {
                "matricule": str(matricule),
                "status": status.value,
                "execution_time": time,
            }
            if grades is not None:
                set["grades"] = grades
            if group is not None:
                set["group"] = group
            return self.documents_collection().update_one(
                {"job_id": job_id, "document_index": doc_index},
                {"$set": set},
            ).matched_count > 0
        except Exception as e:
            print(f"An error occurred: {e}")
            raise

    def update_document_grades(
        self,
        job_id,
        doc_index,
        grades
    ):
        # return updated doc
        return self.documents_collection().update_one(
            {"job_id": job_id, "document_index": doc_index},
            {
                "$set": {
                    "grades": grades
                }
            },
        ).matched_count > 0

    def get_job_max_questions(self, job_id):
        doc = self.eval_jobs_collection().find_one({"job_id": job_id})
        if doc and "max_questions" in doc:
            return doc["max_questions"]
        return None

    def set_job_max_questions(self, job_id, max_nb_question):
        # update alive time stamp
        self.eval_jobs_collection().update_one(
            {"job_id": job_id},
            {"$set": {
                "alive_time": dt.datetime.now(dt.UTC),
                "max_questions": max_nb_question
            }}
        )

    def update_job_status_to_run(self, job_id, students_list, groups=None):
        # try to change job status if first try
        new_values = {
            "job_status": Job_Status.RUN.value,
            "alive_time": dt.datetime.now(dt.UTC),
            "students_list": students_list
        }
        if groups is not None:
            new_values["groups"] = groups
        self.eval_jobs_collection().update_one(
            {"job_id": job_id},
            {"$set": new_values}
        )
        return self.eval_jobs_collection().find_one({"job_id": job_id})

    # def save_preview_image(self, src, job_id, document_index):
    #     filename = f"documents/{job_id}/Q{document_index+1}.pdf"
    #     # self.storage.move_to(str(src), filename)
    #     return filename

    def save_unverified_number_images(self, job_id, document_index, images):
        for index, img in enumerate(images):
            filename = "unverified_number.png"
            self.imwrite_png(filename, img)
            n_png = f"unverified_numbers/{job_id}/{document_index}/{index}.png"
            self.storage.move_to(str(f"numbers/{filename}"), n_png)

        shutil.rmtree(os.path.join("numbers"))

    def get_templates_info(self, front_template_id, regular_template_id=None):
        front_template = self.mongo_database["template"].find_one(
            {"template_id": front_template_id}
        )
        if front_template is None:
            raise LookupError(f"front template {front_template_id} not found")
        front_template_matricule_box = front_template.get("matricule_box", None)
        front_template_grade_box = front_template.get("grade_box", None)

        regular_template = self.mongo_database["template"].find_one(
            {"template_id": regular_template_id}
        )
        regular_template_matricule_box = regular_template.get("matricule_box", None) if regular_template else None

        return front_template_grade_box, front_template_matricule_box, regular_template_matricule_box


    def imwrite_png(self, name, img):
        if not os.path.exists("numbers"):
            os.mkdir("numbers")
        cv2.imwrite(f"numbers/{name}", img)

    # ---------------------------------------------------------- auto grades --
    # Reading the grade off a re-uploaded page is per question, not per job:
    # questions are uploaded separately and their passes run at the same time.
    # Each question carries a run number that the server bumps on every new
    # upload, and every write is conditional on it, so a pass that has been
    # superseded cannot land a value from the file it was reading.

    def bump_auto_grade_run(self, job_id, question_index):
        """Start a new reading pass for one question and return its run number.

        The documents a human has already validated are left alone: a new
        upload must not discard a grade someone confirmed.
        """
        job = self.eval_jobs_collection().find_one_and_update(
            {"job_id": job_id},
            {"$inc": {f"auto_grade_runs.{question_index}": 1}},
            return_document=ReturnDocument.AFTER,
        )
        run = (job or {}).get("auto_grade_runs", {}).get(str(question_index), 1)
        self.questions_collection().update_many(
            {
                "job_id": job_id,
                "question_index": question_index,
                "status": {"$ne": Document_Status.VALIDATED.value},
                "grade": None,
            },
            {"$set": {"auto_grade_status": "PENDING", "auto_grade_run": run}},
        )
        return run

    def auto_grade_run(self, job_id, question_index):
        """The run number currently in force for a question, or 0."""
        job = self.eval_jobs_collection().find_one(
            {"job_id": job_id}, {"auto_grade_runs": 1}
        )
        return (job or {}).get("auto_grade_runs", {}).get(str(question_index), 0)

    def claim_question_document(self, job_id, question_index, run):
        """Take the next document of the question that still needs reading.

        The claim is a single atomic update, so two executor pods working the
        same question never read the same page twice.
        """
        return self.questions_collection().find_one_and_update(
            {
                "job_id": job_id,
                "question_index": question_index,
                "auto_grade_status": "PENDING",
                "auto_grade_run": run,
            },
            {"$set": {"auto_grade_status": "RUNNING"}},
            return_document=ReturnDocument.AFTER,
        )

    def save_auto_grade(self, job_id, document_index, run, reading):
        """Store a reading, unless it has been superseded or already confirmed.

        ``grade`` is deliberately not written: it stays the human's answer, and
        ``job_documents.grades`` -- the array finalisation sums -- is not
        touched either. The value only becomes a grade when someone validates
        it in the correction screen.
        """
        result = self.questions_collection().update_one(
            {
                "job_id": job_id,
                "document_index": document_index,
                "auto_grade_run": run,
                "status": {"$ne": Document_Status.VALIDATED.value},
            },
            {
                "$set": {
                    "auto_grade": reading.grade,
                    "auto_grade_confidence": round(float(reading.confidence), 4),
                    "auto_grade_reason": reading.reason,
                    "auto_grade_source": reading.source,
                    "auto_grade_bbox": list(reading.bbox) if reading.bbox else None,
                    "auto_grade_status": "DONE",
                }
            },
        )
        return result.modified_count == 1

    def questions_to_read(self, job_id, question_index, run):
        """Documents of a question still waiting for a reading pass."""
        return list(
            self.questions_collection().find(
                {
                    "job_id": job_id,
                    "question_index": question_index,
                    "auto_grade_status": "PENDING",
                    "auto_grade_run": run,
                }
            )
        )
